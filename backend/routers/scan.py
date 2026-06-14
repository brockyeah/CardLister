"""Image / PDF upload + Claude vision extraction."""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException

from ..auth import require_auth
from ..schemas import ScanResponse
from ..services.claude_vision import extract_card_from_image

router = APIRouter(dependencies=[Depends(require_auth)])


def _uploads_dir() -> Path:
    db_path = Path(os.getenv("DB_PATH", "./cardlister.db")).resolve()
    return db_path.parent / "uploads"


# PDFs are useful for scanned card pages from a flatbed scanner.
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


@router.post("", response_model=ScanResponse)
async def scan_card(image: UploadFile = File(...)):
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        # Unknown extension — coerce to .jpg so downstream stays predictable.
        # (PDFs without a .pdf extension would be wrong here, so we don't auto-PDF.)
        suffix = ".jpg"

    uploads = _uploads_dir()
    uploads.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = uploads / filename

    try:
        contents = await image.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    extracted, is_mock = extract_card_from_image(str(file_path))

    # The frontend uses this URL path to render the thumbnail.
    public_path = f"/uploads/{filename}"

    return ScanResponse(image_path=public_path, extracted=extracted, mock=is_mock)
