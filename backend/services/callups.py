"""MLB call-up detection via the free MLB Stats API transactions endpoint.

Pure helpers only — the scheduler/email glue lives in the poller (Task 3).
Every network call degrades to [] on failure so the poller never crashes.
"""
import logging
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ..models import Card, CallupEvent
from . import mailer

logger = logging.getLogger(__name__)

STATS_API = "https://statsapi.mlb.com/api/v1/transactions"
CALLUP_TYPES = {"Selected", "Recalled"}  # Selected = first call-up; Recalled = return from AAA


def normalize_name(s: Optional[str]) -> str:
    """Casefold, strip accents, collapse non-alphanumerics to single spaces."""
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    out = []
    for ch in ascii_only.casefold():
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


def _get_json(url: str, params: dict) -> dict:
    """Isolated so tests can patch the network boundary."""
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def fetch_callup_transactions(start_date: str, end_date: str) -> list[dict]:
    """Return normalized call-up transactions in [start_date, end_date]."""
    try:
        data = _get_json(STATS_API, {"startDate": start_date, "endDate": end_date})
    except Exception as e:
        logger.warning("MLB transactions fetch failed: %s", e)
        return []

    rows = []
    for t in data.get("transactions", []):
        if t.get("typeDesc") not in CALLUP_TYPES:
            continue
        person = t.get("person") or {}
        to_team = t.get("toTeam") or {}
        try:
            tx_id = int(t["id"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({
            "tx_id": tx_id,
            "date": t.get("date", ""),
            "type_desc": t.get("typeDesc", ""),
            "player_name": person.get("fullName", ""),
            "person_id": person.get("id"),
            "to_team": to_team.get("name", ""),
            "description": t.get("description", ""),
        })
    return rows


def count_inventory_matches(db: Session, player_name: str) -> int:
    """Sum of Card.quantity for cards whose normalized name matches. Normalizes
    in Python (SQLite lacks accent folding), so scans all cards — fine at this
    scale (hundreds of rows)."""
    target = normalize_name(player_name)
    if not target:
        return 0
    total = 0
    for name, qty in db.query(Card.player_name, Card.quantity).all():
        if normalize_name(name) == target:
            total += qty or 0
    return total


def is_alertable(type_desc: str, inventory_match: bool) -> bool:
    """Email-worthy = a first call-up (Selected), or any call-up of an owned player."""
    return type_desc == "Selected" or inventory_match


ALERT_MAX_AGE_HOURS = 48  # don't email events older than this (bounds retry)


def _compose_digest(events: list) -> tuple[str, str]:
    """(subject, plaintext body) for a batch of alertable CallupEvents.
    First call-ups (Selected) lead as the bigger headline; inventory matches
    are the tiebreaker within each group."""
    ordered = sorted(
        events,
        key=lambda e: (e.type_desc != "Selected", not e.inventory_match, e.player_name),
    )
    lead = ordered[0].player_name
    extra = len(ordered) - 1
    subject = f"🚨 Call-up alert: {lead}" + (f" (+{extra} more)" if extra else "")

    lines = ["Prospect call-ups just posted:\n"]
    for e in ordered:
        kind = "FIRST CALL-UP" if e.type_desc == "Selected" else "recalled"
        lines.append(f"• {e.player_name} — {e.to_team} ({kind})")
        if e.inventory_match:
            lines.append(f"    ⭐ You own {e.matched_card_count} card(s) of this player.")
        if e.description:
            lines.append(f"    {e.description}")
        lines.append("")
    lines.append("— CardLister")
    return subject, "\n".join(lines)


def run_poll_cycle(db: Session) -> dict:
    """One poll: fetch trailing 2-day window, record new call-ups, email the
    alertable un-emailed ones as a single digest. Returns {new, emailed}."""
    today = datetime.utcnow().date()
    start = (today - timedelta(days=2)).isoformat()
    end = today.isoformat()

    txs = fetch_callup_transactions(start, end)
    existing = {tx for (tx,) in db.query(CallupEvent.tx_id).all()}
    new_count = 0
    for tx in txs:
        if tx["tx_id"] in existing:
            continue
        matches = count_inventory_matches(db, tx["player_name"])
        db.add(CallupEvent(
            tx_id=tx["tx_id"], date=tx["date"], type_desc=tx["type_desc"],
            player_name=tx["player_name"], person_id=tx["person_id"],
            to_team=tx["to_team"], description=tx["description"],
            inventory_match=matches > 0, matched_card_count=matches,
        ))
        new_count += 1
    if new_count:
        db.commit()

    # Collect alertable, un-emailed, recent events.
    cutoff = datetime.utcnow() - timedelta(hours=ALERT_MAX_AGE_HOURS)
    pending = [
        e for e in db.query(CallupEvent).filter(
            CallupEvent.emailed_at.is_(None), CallupEvent.created_at >= cutoff
        ).all()
        if is_alertable(e.type_desc, e.inventory_match)
    ]
    emailed = 0
    if pending:
        subject, body = _compose_digest(pending)
        if mailer.send_email(subject, body):
            now = datetime.utcnow()
            for e in pending:
                e.emailed_at = now
            db.commit()
            emailed = len(pending)
    return {"new": new_count, "emailed": emailed}
