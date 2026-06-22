"""Image / PDF upload + Claude vision extraction."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db, uploads_dir
from ..models import UsageEvent
from ..schemas import ScanResponse
from ..services.claude_vision import DEFAULT_PRESET, extract_card_from_image, resolve_preset

router = APIRouter(dependencies=[Depends(require_auth)])


# PDFs are useful for scanned card pages from a flatbed scanner.
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


@router.post("", response_model=ScanResponse)
async def scan_card(
    image: UploadFile = File(...),
    preset: str = Form(DEFAULT_PRESET),
    username: str = Depends(require_auth),
    db: Session = Depends(get_db),
):
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        # Unknown extension — coerce to .jpg so downstream stays predictable.
        # (PDFs without a .pdf extension would be wrong here, so we don't auto-PDF.)
        suffix = ".jpg"

    uploads = uploads_dir()
    uploads.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = uploads / filename

    try:
        contents = await image.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # The user's chosen scan mode (cost / balance / accuracy) → model + effort.
    model, effort = resolve_preset(preset)

    # The Anthropic call is synchronous and can take 15-30s. Run it in a worker
    # thread so it doesn't block the event loop (and every other request) while
    # this async endpoint waits on it.
    extracted, is_mock, error, usage = await run_in_threadpool(
        extract_card_from_image, str(file_path), model, effort
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

    # The frontend uses this URL path to render the thumbnail.
    public_path = f"/uploads/{filename}"

    return ScanResponse(image_path=public_path, extracted=extracted, mock=is_mock, error=error)
