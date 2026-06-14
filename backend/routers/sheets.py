"""Manual Google Sheets sync trigger (in case automatic sync gets out of step)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Card
from ..services.google_sheets import sync_card

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/resync")
def resync_all(db: Session = Depends(get_db)):
    """Push every card to the Sheet. Useful after first connecting Sheets, or after a wipe."""
    cards = db.query(Card).order_by(Card.created_at.asc()).all()
    synced = 0
    skipped = 0
    for card in cards:
        # Force re-append by clearing the cached row index
        card.sheets_row = None
        row = sync_card(card)
        if row:
            card.sheets_row = row
            synced += 1
        else:
            skipped += 1
    db.commit()
    return {"synced": synced, "skipped": skipped, "total": len(cards)}


@router.post("/sync/{card_id}")
def resync_one(card_id: int, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    row = sync_card(card)
    if row:
        card.sheets_row = row
        db.commit()
    return {"ok": row is not None, "row": row}
