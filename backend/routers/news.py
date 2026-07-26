"""Prospect news + call-up ticker for the scan page."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import CallupEvent
from ..services import prospect_news   # import the module so tests can patch fetch_articles

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("")
def news(db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=7)
    events = (db.query(CallupEvent)
              .filter(CallupEvent.created_at >= since)
              .order_by(CallupEvent.created_at.desc()).all())
    callups = [{
        "date": e.date, "player_name": e.player_name, "to_team": e.to_team,
        "type_desc": e.type_desc, "inventory_match": e.inventory_match,
        "matched_card_count": e.matched_card_count,
        "first_bowman_count": e.first_bowman_count,
    } for e in events]
    # Attribute access (not a bound import) so patch.object(prospect_news, "fetch_articles") works.
    return {"callups": callups, "articles": prospect_news.fetch_articles()}


@router.post("/poll-now")
def poll_now(db: Session = Depends(get_db)):
    """Run one call-up poll cycle immediately. Returns {"new": int, "emailed": int}."""
    from ..services.callups import run_poll_cycle
    return run_poll_cycle(db)
