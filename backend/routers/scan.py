"""Image / PDF upload + Claude vision extraction."""
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db, uploads_dir
from ..models import Scan, UsageEvent
from ..schemas import ScanResponse
from ..services.claude_vision import DEFAULT_PRESET, extract_card_from_image, resolve_preset
from ..services.learning import apply_exact_match, build_cheatsheet

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


# PDFs are useful for scanned card pages from a flatbed scanner.
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

# Per-file cap so one request can't exhaust memory or fill the Railway volume.
# Generous for flatbed PDF scans; phone photos arrive far smaller (and the
# client downscales before upload).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_READ_CHUNK = 1024 * 1024


async def _save_upload(upload: UploadFile, uploads: Path) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        # Unknown extension — coerce to .jpg so downstream stays predictable.
        suffix = ".jpg"
    filename = f"{uuid.uuid4().hex}{suffix}"
    dest = uploads / filename
    size = 0
    try:
        with open(dest, "wb") as f:
            while chunk := await upload.read(_READ_CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                f.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return filename


@router.post("", response_model=ScanResponse)
async def scan_card(
    image: UploadFile = File(...),
    back: Optional[UploadFile] = File(None),
    preset: str = Form(DEFAULT_PRESET),
    username: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    uploads = uploads_dir()
    uploads.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    try:
        front_name = await _save_upload(image, uploads)
        saved.append(front_name)
        back_name = await _save_upload(back, uploads) if back and back.filename else None
    except Exception as exc:
        # A failed back save must not orphan the already-written front file.
        for name in saved:
            (uploads / name).unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            # Already client-safe (e.g. 413 over the size cap).
            raise
        # Full detail goes to the server log only — raw exception text can leak
        # filesystem paths and internals to the client.
        logger.exception("Failed to save upload")
        raise HTTPException(status_code=500, detail="Failed to save upload.")

    model, effort, max_px = resolve_preset(preset)
    back_path = str(uploads / back_name) if back_name else None
    cheatsheet = build_cheatsheet(db)
    # The Anthropic call is synchronous and can take 15-30s. Run it in a worker
    # thread so it doesn't block the event loop (and every other request) while
    # this async endpoint waits on it.
    extracted, is_mock, error, usage = await run_in_threadpool(
        extract_card_from_image, str(uploads / front_name), model, effort, back_path, max_px, cheatsheet or None
    )

    # Attribute the API cost to the logged-in user (only real, billed calls have
    # usage — mock mode and failures don't).
    if usage:
        db.add(UsageEvent(
            username=username,
            kind="scan",
            model=usage.get("model", ""),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        ))
        db.commit()

    public_front = f"/uploads/{front_name}"
    public_back = f"/uploads/{back_name}" if back_name else None

    # Learning: overlay identity fields from past corrections of this exact card,
    # then persist the extraction (as shown to the user) so the save can be diffed.
    scan_id = None
    if not is_mock and not error:
        extracted = apply_exact_match(db, extracted)
        scan_row = Scan(
            username=username,
            image_path=public_front,
            back_image_path=public_back,
            model=(usage or {}).get("model", ""),
            extracted_json=json.dumps(extracted, default=str),
        )
        db.add(scan_row)
        db.commit()
        db.refresh(scan_row)
        scan_id = scan_row.id

    return ScanResponse(image_path=public_front, back_image_path=public_back,
                        extracted=extracted, mock=is_mock, error=error, scan_id=scan_id)
