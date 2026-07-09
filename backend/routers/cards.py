"""Card CRUD endpoints. All routes require auth."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth import require_auth
from ..models import Card, Scan
from ..schemas import (
    CardCreate, CardUpdate, CardOut,
    EbayListingUpdate, MarkSoldRequest,
)
from ..services.google_sheets import sync_card
from ..services.learning import record_correction

router = APIRouter(dependencies=[Depends(require_auth)])


def _sync_card_to_sheets(card_id: int) -> None:
    """Background task: mirror a card to Google Sheets and persist its row index.

    Runs after the response is sent, on its own DB session — the request-scoped
    session is already closed by then. Sheets failures are swallowed inside
    sync_card, so a slow or failing Google API call never delays or breaks the
    user's save.
    """
    db = SessionLocal()
    try:
        card = db.query(Card).filter(Card.id == card_id).first()
        if card is None:
            return
        row = sync_card(card)
        if row and card.sheets_row != row:
            card.sheets_row = row
            db.commit()
    finally:
        db.close()


@router.get("", response_model=List[CardOut])
def list_cards(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    team: Optional[str] = None,
    year: Optional[int] = None,
    player_name: Optional[str] = None,
):
    q = db.query(Card)
    if status:
        q = q.filter(Card.status == status)
    if team:
        q = q.filter(Card.team.ilike(f"%{team}%"))
    if year:
        q = q.filter(Card.year == year)
    if player_name:
        q = q.filter(Card.player_name.ilike(f"%{player_name}%"))
    return q.order_by(Card.created_at.desc()).all()


@router.get("/{card_id}", response_model=CardOut)
def get_card(card_id: int, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.post("", response_model=CardOut)
def create_card(payload: CardCreate, background_tasks: BackgroundTasks,
                username: str = Depends(require_auth), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"scan_id"})
    card = Card(**data)
    # Anything saved here is going on eBay next, so always mark it "active".
    card.status = "active"
    db.add(card)
    db.commit()
    db.refresh(card)
    # Learning: diff what the model extracted vs. what the user actually saved.
    if payload.scan_id:
        scan = db.query(Scan).filter(Scan.id == payload.scan_id).first()
        if scan is not None:
            record_correction(db, scan, data, card.id, username)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card


@router.patch("/{card_id}", response_model=CardOut)
def update_card(card_id: int, payload: CardUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(card, k, v)
    db.commit()
    db.refresh(card)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card


@router.delete("/{card_id}")
def delete_card(card_id: int, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(card)
    db.commit()
    return {"ok": True}


@router.post("/{card_id}/ebay-id", response_model=CardOut)
def attach_ebay_listing(card_id: int, payload: EbayListingUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """User pastes back the eBay listing ID + URL after publishing."""
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.ebay_listing_id = payload.ebay_listing_id
    card.ebay_listing_url = payload.ebay_listing_url
    db.commit()
    db.refresh(card)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card


@router.post("/{card_id}/mark-sold", response_model=CardOut)
def mark_sold(card_id: int, payload: MarkSoldRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.status = "sold"
    card.sold_price = payload.sold_price
    card.sold_at = payload.sold_at or datetime.utcnow()
    db.commit()
    db.refresh(card)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card
