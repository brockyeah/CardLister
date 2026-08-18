"""Manual Google Sheets sync trigger (in case automatic sync gets out of step)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Card
from ..services.google_sheets import rewrite_all_rows, sync_card

router = APIRouter(dependencies=[Depends(require_auth)])

_FAILURE_DETAIL = {
    "unconfigured": "Google Sheets is not configured (set GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID).",
    "setup": "Could not reach the Sheet — nothing was changed. Check the credentials and that the sheet is shared with the service account.",
    "cleared": "The Inventory tab was cleared but the rewrite failed, so the sheet is now empty. Every card will re-mirror on its next save; run this again to restore the sheet.",
    "commit": "The Sheet was rewritten correctly, but recording the new row numbers failed. The sheet is right; run this again to re-record them.",
}


@router.post("/resync")
def resync_all(db: Session = Depends(get_db)):
    """Rewrite the whole Inventory tab from the database.

    Clear-then-rewrite, so running it twice is a no-op. The old implementation
    nulled every sheets_row and re-synced, which took sync_card's append branch
    and added a complete second copy of the inventory on every press — while
    being the button the UI offers precisely when the sheet looks wrong.

    Ordered by created_at then id: created_at alone is not a total order (a CSV
    import stamps many rows in the same instant), and without the tiebreaker two
    runs could assign different rows, defeating the idempotence this exists for.
    """
    cards = db.query(Card).order_by(Card.created_at.asc(), Card.id.asc()).all()
    rows, error = rewrite_all_rows(cards)

    if error == "cleared":
        # The tab is empty. Null every index so each card re-appends rather than
        # writing into a position nothing occupies any more.
        for card in cards:
            card.sheets_row = None
        db.commit()
        return {"synced": 0, "skipped": len(cards), "total": len(cards),
                "ok": False, "reason": error, "detail": _FAILURE_DETAIL[error]}

    if error:
        # Nothing was cleared — leave every index alone.
        return {"synced": 0, "skipped": len(cards), "total": len(cards),
                "ok": False, "reason": error, "detail": _FAILURE_DETAIL[error]}

    for card, row in zip(cards, rows):
        card.sheets_row = row
    try:
        db.commit()
    except Exception:
        # The sheet is full and correct. Do NOT null the indices: positions are
        # deterministic (index + 2), so a retry re-records them, whereas nulling
        # would make every card append a second copy — recreating the exact
        # duplication this change removes. Stale indices are repaired by the
        # next resync; duplicate rows have to be deleted by hand.
        db.rollback()
        return {"synced": 0, "skipped": len(cards), "total": len(cards),
                "ok": False, "reason": "commit", "detail": _FAILURE_DETAIL["commit"]}

    return {"synced": len(rows), "skipped": 0, "total": len(cards), "ok": True}


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
