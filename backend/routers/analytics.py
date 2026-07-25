"""Analytics: usage + cost across the recorded Anthropic calls.

Aggregates usage_events with filters (time range, user, model) and returns
totals plus breakdowns by user, model, and day. Costs are estimated from
per-model token prices; settlement happens offline.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import require_auth, get_users
from ..database import get_db
from ..models import Correction, Scan, UsageEvent
from ..services.billing_alerts import send_test_alert
from ..schemas import (
    AnalyticsReport, AnalyticsTotals, UsageRow, ModelRow, DayRow, ReassignRequest,
)

router = APIRouter(dependencies=[Depends(require_auth)])

# USD per 1M tokens, (input, output). Output includes thinking tokens.
MODEL_PRICES = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Unknown/overridden models price at Opus rates so estimates never undercount.
_DEFAULT_PRICE = (5.0, 25.0)


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    # Scans billed to the owner's Claude subscription (vision fallback) cost no
    # API dollars — tokens are recorded for visibility but priced at zero.
    if model.endswith("(subscription)"):
        return 0.0
    in_price, out_price = MODEL_PRICES.get(model, _DEFAULT_PRICE)
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


def _range_start(range_key: str, now: datetime) -> Optional[datetime]:
    """Inclusive start of the reporting window, or None for all-time."""
    if range_key == "all":
        return None
    if range_key == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if range_key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = {"7d": 7, "30d": 30}.get(range_key, 30)
    return now - timedelta(days=days)


@router.get("", response_model=AnalyticsReport)
def analytics(
    range: str = Query("month", pattern="^(today|7d|30d|month|all)$"),
    user: Optional[str] = None,
    model: Optional[str] = None,
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    since = _range_start(range, now)

    # Base query with the active filters applied.
    base = db.query(UsageEvent)
    if since is not None:
        base = base.filter(UsageEvent.created_at >= since)
    if user:
        base = base.filter(UsageEvent.username == user)
    if model:
        base = base.filter(UsageEvent.model == model)

    # Pull the filtered rows once and aggregate in Python — volumes are small
    # (a couple users scanning cards), so this keeps the cost math in one place.
    events = base.all()

    by_user = defaultdict(lambda: {"scans": 0, "input": 0, "output": 0, "cost": 0.0})
    by_model = defaultdict(lambda: {"scans": 0, "input": 0, "output": 0, "cost": 0.0})
    by_day = defaultdict(lambda: {"scans": 0, "cost": 0.0})
    tot = {"scans": 0, "input": 0, "output": 0, "cost": 0.0}

    for ev in events:
        c = _cost(ev.model, ev.input_tokens, ev.output_tokens)
        for bucket, key in ((by_user, ev.username), (by_model, ev.model)):
            b = bucket[key]
            b["scans"] += 1
            b["input"] += ev.input_tokens
            b["output"] += ev.output_tokens
            b["cost"] += c
        day = by_day[ev.created_at.strftime("%Y-%m-%d")]
        day["scans"] += 1
        day["cost"] += c
        tot["scans"] += 1
        tot["input"] += ev.input_tokens
        tot["output"] += ev.output_tokens
        tot["cost"] += c

    user_rows = [
        UsageRow(username=u, scans=v["scans"], input_tokens=v["input"],
                 output_tokens=v["output"], est_cost_usd=round(v["cost"], 2))
        for u, v in sorted(by_user.items(), key=lambda kv: kv[1]["cost"], reverse=True)
    ]
    model_rows = [
        ModelRow(model=m or "(unknown)", scans=v["scans"], input_tokens=v["input"],
                 output_tokens=v["output"], est_cost_usd=round(v["cost"], 2))
        for m, v in sorted(by_model.items(), key=lambda kv: kv[1]["cost"], reverse=True)
    ]
    day_rows = [
        DayRow(date=d, scans=v["scans"], est_cost_usd=round(v["cost"], 2))
        for d, v in sorted(by_day.items())
    ]

    # Distinct users/models across ALL events so the filter dropdowns stay stable
    # regardless of the active filter.
    all_users = [r[0] for r in db.query(UsageEvent.username).distinct().all() if r[0]]
    all_models = [r[0] for r in db.query(UsageEvent.model).distinct().all() if r[0]]

    corr_q = db.query(Correction)
    if since is not None:
        corr_q = corr_q.filter(Correction.created_at >= since)
    if user:
        corr_q = corr_q.filter(Correction.username == user)
    corrections_count = corr_q.count()

    return AnalyticsReport(
        range=range,
        since=since,
        until=now,
        totals=AnalyticsTotals(
            scans=tot["scans"], input_tokens=tot["input"],
            output_tokens=tot["output"], est_cost_usd=round(tot["cost"], 2),
            corrections=corrections_count,
        ),
        by_user=user_rows,
        by_model=model_rows,
        by_day=day_rows,
        users=sorted(all_users),
        models=sorted(all_models),
    )


_USER_TABLES = (UsageEvent, Scan, Correction)


@router.post("/users/reassign")
def reassign_user(payload: ReassignRequest, db: Session = Depends(get_db)):
    if payload.to_user not in get_users():
        raise HTTPException(status_code=400, detail="Target user is not configured")
    if payload.from_user == payload.to_user:
        raise HTTPException(status_code=400, detail="from_user and to_user are the same")
    moved = {}
    for model in _USER_TABLES:
        n = (db.query(model).filter(model.username == payload.from_user)
             .update({model.username: payload.to_user}))
        moved[model.__tablename__] = n
    db.commit()
    return {"moved": moved}


@router.delete("/users/{username}/data")
def delete_user_data(username: str, db: Session = Depends(get_db)):
    deleted = {}
    for model in _USER_TABLES:
        n = db.query(model).filter(model.username == username).delete()
        deleted[model.__tablename__] = n
    db.commit()
    return {"deleted": deleted}


@router.get("/users/configured")
def configured_users():
    """Usernames from CARDLISTER_USERS — valid merge targets for Manage data."""
    return {"users": sorted(get_users())}


@router.post("/alerts/test")
def test_alerts():
    """Fire the credits-exhausted alert channels (email + ntfy push) right now,
    bypassing the throttle, so the owner can verify the wiring end to end."""
    return send_test_alert()
