"""Card CRUD endpoints. All routes require auth."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import require_auth
from ..models import Card
from ..schemas import (
    CardCreate, CardUpdate, CardOut,
    EbayListingUpdate, MarkSoldRequest,
)
from ..services.google_sheets import sync_card

router = APIRouter(dependencies=[Depends(require_auth)])


def _sync_safely(card: Card, db: Session) -> None:
    """Sync to Sheets, persist the returned row index. Errors are swallowed by sync_card."""
    row = sync_card(card)
    if row and card.sheets_row != row:
        card.sheets_row = row
        db.commit()


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
def create_card(payload: CardCreate, db: Session = Depends(get_db)):
    card = Card(**payload.model_dump())
    # Anything saved here is going on eBay next, so default to "active".
    if not card.status:
        card.status = "active"
    else:
        card.status = "active"
    db.add(card)
    db.commit()
    db.refresh(card)
    _sync_safely(card, db)
    return card


@router.patch("/{card_id}", response_model=CardOut)
def update_card(card_id: int, payload: CardUpdate, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(card, k, v)
    db.commit()
    db.refresh(card)
    _sync_safely(card, db)
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
def attach_ebay_listing(card_id: int, payload: EbayListingUpdate, db: Session = Depends(get_db)):
    """User pastes back the eBay listing ID + URL after publishing."""
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.ebay_listing_id = payload.ebay_listing_id
    card.ebay_listing_url = payload.ebay_listing_url
    db.commit()
    db.refresh(card)
    _sync_safely(card, db)
    return card


@router.post("/{card_id}/mark-sold", response_model=CardOut)
def mark_sold(card_id: int, payload: MarkSoldRequest, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.status = "sold"
    card.sold_price = payload.sold_price
    card.sold_at = payload.sold_at or datetime.utcnow()
    db.commit()
    db.refresh(card)
    _sync_safely(card, db)
    return card
