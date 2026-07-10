"""MLB call-up detection via the free MLB Stats API transactions endpoint.

Pure helpers only — the scheduler/email glue lives in the poller (Task 3).
Every network call degrades to [] on failure so the poller never crashes.
"""
import logging
import unicodedata
from typing import Optional

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Card

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
