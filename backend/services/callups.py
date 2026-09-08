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
# Modules, not the functions inside them, so tests can patch the attribute
# (see the testing notes in CLAUDE.md).
from . import billing_alerts, mailer

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


class CallupFetchError(Exception):
    """The MLB transactions fetch failed. Raised only when a caller asks to be
    told (`strict=True`); the default still degrades to []."""


def fetch_callup_transactions(start_date: str, end_date: str, *, strict: bool = False) -> list[dict]:
    """Return normalized call-up transactions in [start_date, end_date].

    `strict` decides what a *network* failure looks like to the caller, and the
    distinction matters because an empty list is otherwise ambiguous in the one
    direction that hurts: "MLB reported no call-ups today" and "we never
    reached MLB" are the same value, and the second is indistinguishable from
    a perfectly healthy quiet day. The poller passes `strict=True` so it can
    report a degraded cycle rather than a successful one; everything else keeps
    the module's stated guarantee that a network call degrades to [] and never
    crashes its caller.
    """
    try:
        data = _get_json(STATS_API, {"startDate": start_date, "endDate": end_date})
    except Exception as e:
        logger.warning("MLB transactions fetch failed: %s", e)
        if strict:
            raise CallupFetchError(str(e)) from e
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


def count_inventory_matches(db: Session, player_name: str) -> tuple[int, int]:
    """(total_qty, first_bowman_qty) of cards whose normalized name matches.
    Normalizes in Python (SQLite lacks accent folding), so scans all cards —
    fine at this scale (hundreds of rows)."""
    target = normalize_name(player_name)
    if not target:
        return 0, 0
    total = first_bowman = 0
    rows = (db.query(Card.player_name, Card.quantity, Card.is_first_bowman)
            .filter(Card.status != "sold").all())
    for name, qty, is_fb in rows:
        if normalize_name(name) == target:
            total += qty or 0
            if is_fb:
                first_bowman += qty or 0
    return total, first_bowman


def is_alertable(type_desc: str, inventory_match: bool) -> bool:
    """Email-worthy = a first call-up (Selected), or any call-up of an owned player."""
    return type_desc == "Selected" or inventory_match


ALERT_MAX_AGE_HOURS = 48  # don't email events older than this (bounds retry)


def _recently_abandoned(db: Session, now: datetime) -> list:
    """Alertable events that left the retry window unemailed in the last
    ALERT_MAX_AGE_HOURS.

    The window itself is right — it bounds retries, so one broken send cannot
    keep the poller emailing stale news forever. What was missing is the
    record: an event crossing the cutoff simply stopped appearing in `pending`
    and nothing anywhere said an alert had been dropped.

    This is a rolling count over a band, not a per-event notification. There
    is no column marking a row as abandoned (adding one would be a schema
    change for a number that is only ever reported), so the band bounds the
    query instead: without a lower bound the count would grow forever and
    include every non-alertable row the app has ever recorded. An event is
    therefore counted on every cycle for the two days it sits in the band —
    which is why the alert says "in the last two days" rather than "just now".
    """
    cutoff = now - timedelta(hours=ALERT_MAX_AGE_HOURS)
    floor = cutoff - timedelta(hours=ALERT_MAX_AGE_HOURS)
    rows = db.query(CallupEvent).filter(
        CallupEvent.emailed_at.is_(None),
        CallupEvent.created_at < cutoff,
        CallupEvent.created_at >= floor,
    ).all()
    # Most un-emailed events are un-emailed on purpose (a Recalled for a player
    # the owner does not own is never alertable), so the same filter the
    # pending query uses has to run here or the count is meaningless.
    return [e for e in rows if is_alertable(e.type_desc, e.inventory_match)]


def _compose_digest(events: list) -> tuple[str, str]:
    """(subject, plaintext body) for a batch of alertable CallupEvents.
    Inventory matches lead per spec — the owner's sell signal leads the
    subject line and body. Sort order is four tiers: inventory matches
    before non-matches; within matches, those including a 1st Bowman card
    lead ahead of plain matches; then first call-ups (Selected) come before
    Recalled; then alphabetical by player name.
    Requires a non-empty events list (the caller guards with `if pending:`)."""
    ordered = sorted(
        events,
        key=lambda e: (
            not e.inventory_match,
            not (e.first_bowman_count or 0),
            e.type_desc != "Selected",
            e.player_name,
        ),
    )
    lead = ordered[0].player_name
    extra = len(ordered) - 1
    subject = f"🚨 Call-up alert: {lead}" + (f" (+{extra} more)" if extra else "")

    lines = ["Prospect call-ups just posted:\n"]
    for e in ordered:
        kind = "FIRST CALL-UP" if e.type_desc == "Selected" else "recalled"
        lines.append(f"• {e.player_name} — {e.to_team} ({kind})")
        if e.inventory_match:
            note = f"    ⭐ You own {e.matched_card_count} card(s) of this player"
            if e.first_bowman_count:
                note += f" — including his 1st Bowman ({e.first_bowman_count})!"
            else:
                note += "."
            lines.append(note)
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

    # strict=True so a swallowed upstream failure cannot be reported as a
    # healthy cycle. `fetch_callup_transactions` returns [] on a network error,
    # which is byte-for-byte what a quiet day returns, so without this the
    # poller stamps a successful cycle through a total MLB Stats API outage and
    # `/api/health` stays green while no call-up is being seen at all (Codex,
    # PR #74). The rest of the cycle still runs on the empty list — pending
    # alerts from earlier cycles must keep being retried while MLB is down —
    # so the only thing that changes is that we say so.
    fetch_ok = True
    try:
        txs = fetch_callup_transactions(start, end, strict=True)
    except CallupFetchError:
        fetch_ok = False
        txs = []
    existing = {tx for (tx,) in db.query(CallupEvent.tx_id).all()}
    new_count = 0
    for tx in txs:
        if tx["tx_id"] in existing:
            continue
        matches, first_bowman = count_inventory_matches(db, tx["player_name"])
        db.add(CallupEvent(
            tx_id=tx["tx_id"], date=tx["date"], type_desc=tx["type_desc"],
            player_name=tx["player_name"], person_id=tx["person_id"],
            to_team=tx["to_team"], description=tx["description"],
            inventory_match=matches > 0, matched_card_count=matches,
            first_bowman_count=first_bowman,
        ))
        new_count += 1
    if new_count:
        db.commit()

    # Collect alertable, un-emailed, recent events. One clock for the whole
    # step, so `pending` and `abandoned` are split on exactly the same cutoff
    # and an event cannot fall in both or neither.
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=ALERT_MAX_AGE_HOURS)
    pending = [
        e for e in db.query(CallupEvent).filter(
            CallupEvent.emailed_at.is_(None), CallupEvent.created_at >= cutoff
        ).all()
        if is_alertable(e.type_desc, e.inventory_match)
    ]
    abandoned = _recently_abandoned(db, now)
    emailed = 0
    send_failed = False
    if pending:
        subject, body = _compose_digest(pending)
        if mailer.send_email(subject, body):
            for e in pending:
                e.emailed_at = now
            db.commit()
            emailed = len(pending)
        else:
            send_failed = True
            logger.error(
                "Call-up digest could not be emailed; %s alert(s) held for retry "
                "until they are %sh old", len(pending), ALERT_MAX_AGE_HOURS,
            )
    if abandoned:
        logger.error(
            "%s call-up alert(s) passed %sh unsent and will never be retried: %s",
            len(abandoned), ALERT_MAX_AGE_HOURS,
            ", ".join(sorted(e.player_name for e in abandoned)),
        )
    # What is *still* waiting on a retry, which is what "pending" has to mean
    # to be worth reporting. A successful send stamps every candidate, so the
    # pre-send count would say alerts are awaiting delivery when none are —
    # and a healthy cycle would read as {"emailed": 3, "pending": 3}
    # (CodeRabbit, PR #64).
    still_pending = len(pending) if send_failed else 0
    if send_failed or abandoned:
        # Out-of-band on purpose: the app's own email is the thing that is
        # broken, so the ntfy push inside this call is what actually reaches
        # the owner. Throttled there, not here — every cycle of an ongoing
        # outage calls it and at most one alert per window goes out.
        billing_alerts.notify_callup_alerts_undelivered(
            still_pending, len(abandoned), ALERT_MAX_AGE_HOURS,
        )
    return {
        "new": new_count,
        "emailed": emailed,
        "pending": still_pending,
        "abandoned": len(abandoned),
        # False when the upstream fetch failed and this cycle therefore saw no
        # transactions it could trust. The poller reports it as the cycle not
        # having done its whole job.
        "fetch_ok": fetch_ok,
    }
