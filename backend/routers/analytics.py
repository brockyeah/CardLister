"""Analytics: usage + cost across the recorded Anthropic calls.

Aggregates usage_events with filters (time range, user, model) and returns
totals plus breakdowns by user, model, and day. Costs are estimated from
per-model token prices; settlement happens offline.
"""
import os
import sqlite3
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..auth import require_auth, get_users
from ..database import DB_PATH, get_db, uploads_dir
from ..models import Card, Correction, Scan, UsageEvent
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


@router.get("/backup.db")
def download_backup():
    """Consistent point-in-time snapshot of the SQLite DB, streamed as a download.

    VACUUM INTO takes a transactional copy, so it's safe against concurrent
    writes — unlike copying the file, which can capture a torn state mid-write.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="cardlister-backup-")
    os.close(fd)
    os.unlink(tmp_path)  # VACUUM INTO refuses to overwrite an existing file
    try:
        # timeout=5.0 is Python's default; explicit so it's clear a snapshot
        # landing in a writer's brief EXCLUSIVE window waits instead of 500ing.
        src = sqlite3.connect(DB_PATH, timeout=5.0)
        try:
            src.execute("VACUUM INTO ?", (tmp_path,))
        finally:
            src.close()
    except sqlite3.Error:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail="Backup snapshot failed")
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        tmp_path,
        media_type="application/octet-stream",
        filename=f"cardlister-backup-{stamp}.db",
        background=BackgroundTask(os.unlink, tmp_path),
    )


# Files younger than this are never treated as orphans — they may belong to a
# scan that's still sitting unsaved in the Scanner (e.g. an overnight batch queue).
ORPHAN_GRACE_HOURS = 48


def _orphaned_uploads(db: Session) -> list:
    """Upload files not referenced by any card and older than the grace window.

    Scan rows deliberately do NOT protect files: a scan whose card was never
    saved (or was deleted) is exactly the disk growth this exists to reclaim.
    Only the cards table represents data the user chose to keep.
    """
    referenced = set()
    for front, back in db.query(Card.image_path, Card.back_image_path).all():
        for p in (front, back):
            if p:
                referenced.add(os.path.basename(p))
    # time.time(), not utcnow().timestamp(): .timestamp() on a naive datetime
    # assumes local time, which silently shrinks the grace window off-UTC.
    cutoff = time.time() - ORPHAN_GRACE_HOURS * 3600
    orphans = []
    root = uploads_dir()
    if not root.is_dir():
        return orphans
    for path in root.iterdir():
        if not path.is_file() or path.name in referenced:
            continue
        stat = path.stat()
        if stat.st_mtime < cutoff:
            orphans.append((path, stat.st_size))
    return orphans


@router.get("/uploads/orphans")
def upload_orphans(db: Session = Depends(get_db)):
    """Count + size of reclaimable upload files, without deleting anything."""
    orphans = _orphaned_uploads(db)
    root = uploads_dir()
    total_files = sum(1 for p in root.iterdir() if p.is_file()) if root.is_dir() else 0
    return {
        "count": len(orphans),
        "bytes": sum(size for _, size in orphans),
        "grace_hours": ORPHAN_GRACE_HOURS,
        # Lets the UI warn when the orphan set is most of the uploads dir —
        # e.g. after a CSV restore, where no card references any photo.
        "total_files": total_files,
    }


@router.post("/uploads/cleanup")
def cleanup_uploads(db: Session = Depends(get_db)):
    """Delete orphaned upload files. Recomputes the orphan set at call time."""
    deleted = 0
    freed = 0
    for path, size in _orphaned_uploads(db):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        deleted += 1
        freed += size
    return {"deleted": deleted, "freed_bytes": freed}


@router.get("/storage")
def storage_usage():
    """DB file + uploads footprint, so Railway volume pressure is visible
    next to the cleanup tools that relieve it."""
    db_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    uploads_count = 0
    uploads_bytes = 0
    root = uploads_dir()
    if root.is_dir():
        for path in root.iterdir():
            if path.is_file():
                uploads_count += 1
                uploads_bytes += path.stat().st_size
    return {
        "db_bytes": db_bytes,
        "uploads_count": uploads_count,
        "uploads_bytes": uploads_bytes,
    }


@router.post("/alerts/test")
def test_alerts():
    """Fire the credits-exhausted alert channels (email + ntfy push) right now,
    bypassing the throttle, so the owner can verify the wiring end to end."""
    return send_test_alert()
