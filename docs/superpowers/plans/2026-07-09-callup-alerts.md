# Call-Up Alerts + Prospect News + User-Data Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Email the owner when a prospect is called up to the Majors (inventory matches + all first call-ups), show a call-up ticker + prospect news on the scan page, and add an Analytics panel to merge/delete stale usernames (fixing the `cardlister-user` ghost).

**Architecture:** FastAPI + SQLAlchemy + SQLite backend (`backend/`), React 18 + Vite frontend (`frontend/src/`). Detection uses the free MLB Stats API transactions endpoint; news reuses an RSS engine (`feedparser`) ported from the owner's Daryls-Digest project. New tables are created by `create_all`. An in-process asyncio task polls on a cadence. Spec: `docs/superpowers/specs/2026-07-09-callup-alerts-design.md`.

**Tech Stack:** Python 3.12 (`.venv`), pytest, FastAPI TestClient, `feedparser` (new dep), stdlib `smtplib`, React/Vite/Tailwind.

## Global Constraints

- Branch: `feat/callup-alerts` (already created off `main`). Commit after every task.
- Backend tests: run from repo root with `.venv/bin/python -m pytest backend/tests -q`. All must pass before each commit.
- Frontend gate: `cd frontend && npm run build` must succeed before each commit that touches `frontend/`.
- Tests must set `DISABLE_CALLUP_POLLER=1` (added to `conftest.py`) so the scheduler never starts during tests.
- Secrets (`SMTP_PASSWORD` etc.) are read from env only — never hardcode, never write to `.env`. Do not modify `docs/`, `.env`, or anything under `uploads/`.
- Match existing code style: comments explain constraints, not narration; no type-hint retrofits of untouched code.
- Every network call (MLB API, RSS, SMTP) must be wrapped so failure returns a safe empty/false value and is logged — never let it 500 a request or crash the poller.
- New table `callup_events` is created by `create_all` — no `ensure_columns` migration needed.

---

### Task 1: `callup_events` model + MLB transactions fetch/filter/match

**Files:**
- Modify: `backend/models.py` (add `CallupEvent`)
- Create: `backend/services/callups.py` (pure functions: fetch, normalize, filter, match — NO scheduler/email yet)
- Create: `backend/tests/fixtures/transactions.json` (trimmed real API shape)
- Create: `backend/tests/test_callups.py`
- Modify: `backend/tests/conftest.py` (add `DISABLE_CALLUP_POLLER=1`; import new models in the cleanup fixture)

**Interfaces:**
- Produces:
  - `CallupEvent` ORM model (`__tablename__ = "callup_events"`) with columns per spec.
  - `normalize_name(s: Optional[str]) -> str`
  - `fetch_callup_transactions(start_date: str, end_date: str) -> list[dict]` → list of `{tx_id:int, date:str, type_desc:str, player_name:str, person_id:Optional[int], to_team:str, description:str}`
  - `count_inventory_matches(db: Session, player_name: str) -> int` (sum of `Card.quantity` for normalized-name matches)
  - `is_alertable(type_desc: str, inventory_match: bool) -> bool`

- [ ] **Step 1: Add the model**

In `backend/models.py`, append after the `Correction` class:

```python
class CallupEvent(Base):
    """One MLB roster transaction we care about (a call-up). Doubles as the
    dedup ledger (unique tx_id) and the data behind the news ticker."""
    __tablename__ = "callup_events"

    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(Integer, unique=True, index=True, nullable=False)  # MLB transaction id
    date = Column(String, default="")           # YYYY-MM-DD
    type_desc = Column(String, default="")      # "Selected" | "Recalled"
    player_name = Column(String, default="")
    person_id = Column(Integer, nullable=True)
    to_team = Column(String, default="")
    description = Column(Text, default="")
    inventory_match = Column(Boolean, default=False)
    matched_card_count = Column(Integer, default=0)
    emailed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 2: Update conftest**

In `backend/tests/conftest.py`, add to the env block (before `import pytest`):

```python
os.environ.setdefault("DISABLE_CALLUP_POLLER", "1")
```

And in the `db_session` fixture, extend the import + cleanup to include the new table:

```python
    from backend.models import Correction, Scan, CallupEvent  # noqa: E402
```
Add `db.query(CallupEvent).delete()` alongside the existing deletes.

- [ ] **Step 3: Create the fixture**

Create `backend/tests/fixtures/transactions.json` (real API shape, trimmed to what the parser reads):

```json
{
  "transactions": [
    {"id": 1001, "date": "2026-07-08", "typeDesc": "Selected", "description": "Baltimore Orioles selected the contract of SS Jackson Holliday from Norfolk Tides.", "person": {"id": 700001, "fullName": "Jackson Holliday"}, "toTeam": {"name": "Baltimore Orioles"}},
    {"id": 1002, "date": "2026-07-08", "typeDesc": "Recalled", "description": "Tampa Bay Rays recalled RHP Mason Englert from Durham Bulls.", "person": {"id": 700002, "fullName": "Mason Englert"}, "toTeam": {"name": "Tampa Bay Rays"}},
    {"id": 1003, "date": "2026-07-08", "typeDesc": "Optioned", "description": "Some team optioned a player.", "person": {"id": 700003, "fullName": "Bench Guy"}, "toTeam": {"name": "Whoever"}}
  ]
}
```

- [ ] **Step 4: Write the failing test**

Create `backend/tests/test_callups.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

from backend.services import callups
from backend.models import Card

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "transactions.json").read_text())


def test_normalize_name_strips_accents_and_case():
    assert callups.normalize_name("Acuña Jr.") == callups.normalize_name("acuna jr")
    assert callups.normalize_name(None) == ""


def test_fetch_keeps_only_callup_types():
    with patch.object(callups, "_get_json", return_value=FIXTURE):
        rows = callups.fetch_callup_transactions("2026-07-07", "2026-07-08")
    types = {r["type_desc"] for r in rows}
    assert types == {"Selected", "Recalled"}          # Optioned dropped
    holliday = next(r for r in rows if r["player_name"] == "Jackson Holliday")
    assert holliday["tx_id"] == 1001 and holliday["person_id"] == 700001
    assert holliday["to_team"] == "Baltimore Orioles"


def test_fetch_returns_empty_on_network_failure():
    with patch.object(callups, "_get_json", side_effect=RuntimeError("boom")):
        assert callups.fetch_callup_transactions("2026-07-07", "2026-07-08") == []


def test_count_inventory_matches(db_session):
    db_session.add_all([
        Card(player_name="Jackson Holliday", quantity=2),
        Card(player_name="jackson  holliday", quantity=1),  # normalized dup
        Card(player_name="Someone Else", quantity=5),
    ])
    db_session.commit()
    assert callups.count_inventory_matches(db_session, "Jackson Holliday") == 3
    assert callups.count_inventory_matches(db_session, "Nobody") == 0


def test_is_alertable_rule():
    assert callups.is_alertable("Selected", False) is True      # first call-up always
    assert callups.is_alertable("Recalled", True) is True       # recall of owned player
    assert callups.is_alertable("Recalled", False) is False     # recall, not owned → skip
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_callups.py -q`
Expected: FAIL (`module 'backend.services.callups' has no attribute ...`).

- [ ] **Step 6: Implement `callups.py`**

Create `backend/services/callups.py`:

```python
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_callups.py -q`
Expected: PASS (5 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/models.py backend/services/callups.py backend/tests/test_callups.py backend/tests/fixtures/transactions.json backend/tests/conftest.py
git commit -m "feat: MLB call-up detection (model + fetch/filter/inventory match)"
```

---

### Task 2: Mailer service

**Files:**
- Create: `backend/services/mailer.py`
- Create: `backend/tests/test_mailer.py`

**Interfaces:**
- Produces: `is_configured() -> bool`; `send_email(subject: str, text_body: str) -> bool` (never raises).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_mailer.py`:

```python
import os
from unittest.mock import MagicMock, patch

from backend.services import mailer


def _configured(monkeypatch):
    monkeypatch.setenv("SMTP_USERNAME", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    monkeypatch.setenv("ALERT_EMAILS", "me@gmail.com, alan@example.com")


def test_not_configured_returns_false_without_network(monkeypatch):
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert mailer.is_configured() is False
    # Must not attempt a connection when unconfigured.
    with patch("smtplib.SMTP") as smtp:
        assert mailer.send_email("s", "b") is False
        smtp.assert_not_called()


def test_send_email_uses_starttls_and_recipients(monkeypatch):
    _configured(monkeypatch)
    server = MagicMock()
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        assert mailer.send_email("Subject", "Body") is True
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("me@gmail.com", "app-pw")
    # Recipients parsed from the comma list (whitespace trimmed).
    args, kwargs = server.send_message.call_args
    msg = args[0]
    assert msg["To"] == "me@gmail.com, alan@example.com"


def test_send_email_swallows_smtp_errors(monkeypatch):
    _configured(monkeypatch)
    with patch("smtplib.SMTP", side_effect=OSError("no route")):
        assert mailer.send_email("s", "b") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_mailer.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `mailer.py`**

Create `backend/services/mailer.py`:

```python
"""Outbound email via SMTP (Gmail by default). Never raises — send_email
returns False on any failure so callers (the poller) keep running."""
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _recipients() -> list[str]:
    return [a.strip() for a in os.getenv("ALERT_EMAILS", "").split(",") if a.strip()]


def is_configured() -> bool:
    return bool(os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD") and _recipients())


def send_email(subject: str, text_body: str) -> bool:
    if not is_configured():
        logger.info("Mailer not configured (SMTP_USERNAME/PASSWORD/ALERT_EMAILS) — skipping email")
        return False

    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    recipients = _recipients()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.warning("send_email failed: %s", e)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_mailer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/mailer.py backend/tests/test_mailer.py
git commit -m "feat: SMTP mailer service (never-raise send_email)"
```

---

### Task 3: Poll cycle + scheduler wiring

**Files:**
- Modify: `backend/services/callups.py` (add `run_poll_cycle`, `_compose_digest`)
- Modify: `backend/main.py` (start the asyncio poller on startup unless disabled)
- Create: `backend/tests/test_poll_cycle.py`

**Interfaces:**
- Consumes: `fetch_callup_transactions`, `count_inventory_matches`, `is_alertable` (Task 1); `mailer.send_email` (Task 2); `CallupEvent` (Task 1).
- Produces: `run_poll_cycle(db: Session) -> dict` returning `{"new": int, "emailed": int}`; `_compose_digest(events: list[CallupEvent]) -> tuple[str, str]` (subject, body).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_poll_cycle.py`:

```python
from datetime import datetime, timedelta
from unittest.mock import patch

from backend.services import callups
from backend.models import Card, CallupEvent

TX = [
    {"tx_id": 2001, "date": "2026-07-08", "type_desc": "Selected", "player_name": "Jackson Holliday",
     "person_id": 1, "to_team": "Baltimore Orioles", "description": "selected contract"},
    {"tx_id": 2002, "date": "2026-07-08", "type_desc": "Recalled", "player_name": "Owned Guy",
     "person_id": 2, "to_team": "Rays", "description": "recalled"},
    {"tx_id": 2003, "date": "2026-07-08", "type_desc": "Recalled", "player_name": "Nobody Special",
     "person_id": 3, "to_team": "Reds", "description": "recalled"},
]


def test_poll_cycle_records_and_emails(db_session):
    db_session.add(Card(player_name="Owned Guy", quantity=2))
    db_session.commit()

    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=True) as send:
        result = callups.run_poll_cycle(db_session)

    assert result == {"new": 3, "emailed": 2}          # Selected + owned Recalled; Nobody skipped
    send.assert_called_once()
    subject, body = send.call_args.args
    assert "Jackson Holliday" in subject
    assert "You own 2" in body                          # inventory match surfaced
    # emailed rows stamped; skipped row not
    rows = {e.tx_id: e for e in db_session.query(CallupEvent).all()}
    assert rows[2001].emailed_at is not None and rows[2003].emailed_at is None
    assert rows[2002].inventory_match is True and rows[2002].matched_card_count == 2


def test_poll_cycle_dedups_second_run(db_session):
    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=True):
        callups.run_poll_cycle(db_session)
        second = callups.run_poll_cycle(db_session)
    assert second == {"new": 0, "emailed": 0}
    assert db_session.query(CallupEvent).count() == 3


def test_email_failure_leaves_rows_for_retry(db_session):
    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=False):
        result = callups.run_poll_cycle(db_session)
    assert result["emailed"] == 0
    assert all(e.emailed_at is None for e in db_session.query(CallupEvent).all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_poll_cycle.py -q`
Expected: FAIL (`run_poll_cycle` undefined).

- [ ] **Step 3: Implement the poll cycle**

In `backend/services/callups.py`, add imports at top:

```python
import os
from datetime import datetime, timedelta

from . import mailer
```

Append to `backend/services/callups.py`:

```python
ALERT_MAX_AGE_HOURS = 48  # don't email events older than this (bounds retry)


def _compose_digest(events: list) -> tuple[str, str]:
    """(subject, plaintext body) for a batch of alertable CallupEvents.
    Inventory matches first."""
    ordered = sorted(events, key=lambda e: (not e.inventory_match, e.player_name))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_poll_cycle.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire the scheduler into startup**

In `backend/main.py`, add imports near the top:

```python
import asyncio
import logging
import os
```

Add a module-level logger after the imports: `logger = logging.getLogger(__name__)`.

Add this background loop function above `on_startup`:

```python
async def _callup_poller():
    """Poll for MLB call-ups on a cadence. In-process; Railway keeps us alive."""
    from .services.callups import run_poll_cycle
    from .database import SessionLocal

    minutes = int(os.getenv("CALLUP_POLL_MINUTES", "60"))
    while True:
        try:
            db = SessionLocal()
            try:
                result = run_poll_cycle(db)
                if result["new"] or result["emailed"]:
                    logger.info("Call-up poll: %s", result)
            finally:
                db.close()
        except Exception:
            logger.exception("Call-up poll cycle errored")
        await asyncio.sleep(minutes * 60)
```

In `on_startup`, after `uploads_dir().mkdir(...)`, add:

```python
    # Background call-up poller — skip in tests/dev via env.
    if os.getenv("DISABLE_CALLUP_POLLER") != "1":
        asyncio.create_task(_callup_poller())
```

- [ ] **Step 6: Run the full suite (poller must stay off in tests)**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: PASS (all tests; no hanging — `DISABLE_CALLUP_POLLER=1` is set in conftest).

- [ ] **Step 7: Commit**

```bash
git add backend/services/callups.py backend/main.py backend/tests/test_poll_cycle.py
git commit -m "feat: call-up poll cycle + in-process scheduler"
```

---

### Task 4: Prospect news service + `/api/news` endpoint

**Files:**
- Create: `backend/services/prospect_news.py`
- Create: `backend/routers/news.py`
- Modify: `backend/main.py` (include router)
- Modify: `backend/requirements.txt` (add `feedparser==6.0.11`)
- Create: `backend/tests/test_news.py`

**Interfaces:**
- Consumes: `CallupEvent` (Task 1), `require_auth` (existing).
- Produces: `score_article(article: dict) -> int`; `fetch_articles() -> list[dict]` (cached, each `{title, link, source, published_iso, age_days}`); `GET /api/news` → `{"callups": [...], "articles": [...]}`.
- **Mock-location note:** the router imports the `prospect_news` *module* and calls `prospect_news.fetch_articles()` (not a bound `from … import fetch_articles`), so `patch.object(prospect_news, "fetch_articles", …)` in tests takes effect.

- [ ] **Step 1: Install the dependency**

```bash
.venv/bin/pip install feedparser==6.0.11
```

Add to `backend/requirements.txt` (after `beautifulsoup4==4.12.3`):
```
feedparser==6.0.11
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_news.py`:

```python
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import prospect_news
from backend.models import CallupEvent


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_score_article_rewards_keywords_and_recency():
    hit = {"title": "Top prospect called up to the Majors", "summary": "", "published_parsed": datetime.utcnow().timetuple()}
    miss = {"title": "Team wins game", "summary": "", "published_parsed": datetime.utcnow().timetuple()}
    assert prospect_news.score_article(hit) > prospect_news.score_article(miss)


def test_news_endpoint_returns_callups_and_articles(db_session):
    db_session.add(CallupEvent(tx_id=9001, date="2026-07-08", type_desc="Selected",
                               player_name="Jackson Holliday", to_team="Baltimore Orioles",
                               inventory_match=True, matched_card_count=3,
                               created_at=datetime.utcnow()))
    db_session.commit()

    fake_articles = [{"title": "Jackson Holliday called up", "link": "http://x/1",
                      "source": "MLB.com", "published_iso": "2026-07-08T12:00:00", "age_days": 0}]
    with TestClient(app) as client:
        with patch.object(prospect_news, "fetch_articles", return_value=fake_articles):
            r = client.get("/api/news", headers=_auth(client))
    assert r.status_code == 200
    body = r.json()
    assert body["articles"] == fake_articles
    assert any(c["player_name"] == "Jackson Holliday" and c["inventory_match"] for c in body["callups"])


def test_news_requires_auth():
    with TestClient(app) as client:
        assert client.get("/api/news").status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_news.py -q`
Expected: FAIL (modules missing).

- [ ] **Step 4: Implement the news service**

Create `backend/services/prospect_news.py`:

```python
"""Prospect-news RSS aggregation (ported from Daryls-Digest). Fetches MLB feeds,
scores by call-up keywords + recency, caches in-process for 15 minutes."""
import logging
import os
import time
from datetime import datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://www.mlb.com/feeds/news/rss.xml",
    "https://www.mlb.com/orioles/feeds/news/rss.xml",
]
KEYWORDS = ["called up", "call-up", "call up", "contract selected", "selected the contract",
            "promoted", "top prospect", "debut", "recalled", "roster move"]
_CACHE_TTL = 900  # 15 min
_cache = {"at": 0.0, "articles": []}


def _feeds() -> list[str]:
    raw = os.getenv("NEWS_FEEDS", "").strip()
    return [u.strip() for u in raw.split(",") if u.strip()] or DEFAULT_FEEDS


def score_article(article: dict) -> int:
    score = 0
    text = f"{article.get('title','')} {article.get('summary','')}".lower()
    for kw in KEYWORDS:
        if kw in text:
            score += 10
            if kw in article.get("title", "").lower():
                score += 5
    published = article.get("published_parsed")
    if published:
        days = (datetime.utcnow() - datetime(*published[:6])).days
        score += 20 if days == 0 else 10 if days == 1 else 5 if days <= 3 else 0
    return score


def _fetch_feed(url: str) -> list[dict]:
    try:
        resp = httpx.get(url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0 CardLister"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        source = parsed.feed.get("title", url)
        out = []
        for e in parsed.entries:
            published = e.get("published_parsed")
            age = (datetime.utcnow() - datetime(*published[:6])).days if published else None
            out.append({
                "title": e.get("title", ""), "summary": e.get("summary", ""),
                "link": e.get("link", ""), "source": source,
                "published_parsed": published,
                "published_iso": datetime(*published[:6]).isoformat() if published else None,
                "age_days": age,
            })
        return out
    except Exception as ex:
        logger.warning("Feed fetch failed (%s): %s", url, ex)
        return []


def fetch_articles(limit: int = 8) -> list[dict]:
    """Top scored articles across all feeds. Cached 15 min."""
    now = time.time()
    if _cache["articles"] and now - _cache["at"] < _CACHE_TTL:
        return _cache["articles"]
    all_articles = []
    for url in _feeds():
        all_articles.extend(_fetch_feed(url))
    scored = sorted(all_articles, key=score_article, reverse=True)
    top = [{"title": a["title"], "link": a["link"], "source": a["source"],
            "published_iso": a["published_iso"], "age_days": a["age_days"]}
           for a in scored[:limit] if score_article(a) > 0]
    _cache.update(at=now, articles=top)
    return top
```

- [ ] **Step 5: Implement the router**

Create `backend/routers/news.py`:

```python
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
    } for e in events]
    # Attribute access (not a bound import) so patch.object(prospect_news, "fetch_articles") works.
    return {"callups": callups, "articles": prospect_news.fetch_articles()}
```

In `backend/main.py`, add `news` to the routers import and include it:

```python
from .routers import cards, scan, pricing, ebay, sheets, analytics, news
```
```python
app.include_router(news.router, prefix="/api/news", tags=["news"])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_news.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/services/prospect_news.py backend/routers/news.py backend/main.py backend/requirements.txt backend/tests/test_news.py
git commit -m "feat: prospect news RSS aggregation + /api/news"
```

---

### Task 5: News section on the scan page (frontend)

**Files:**
- Modify: `frontend/src/api.js` (add `getNews`)
- Create: `frontend/src/components/NewsSection.jsx`
- Modify: `frontend/src/pages/Scanner.jsx` (render `<NewsSection />` below the dropzone)

**Interfaces:**
- Consumes: `GET /api/news` shape from Task 4.
- Produces: `getNews()` in api.js; `NewsSection` default export.

- [ ] **Step 1: Add the API wrapper**

In `frontend/src/api.js`, after the analytics wrapper, add:

```javascript
// --- News / call-up ticker ---
export const getNews = () => api.get('/api/news').then((r) => r.data)
```

- [ ] **Step 2: Create the component**

Create `frontend/src/components/NewsSection.jsx`:

```jsx
import { useEffect, useState } from 'react'
import { getNews } from '../api'

const KEY = 'cardlister_news_open'

export default function NewsSection() {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(() => localStorage.getItem(KEY) !== '0')

  useEffect(() => {
    getNews().then(setData).catch(() => setData({ callups: [], articles: [] }))
  }, [])

  const toggle = () => {
    const next = !open
    setOpen(next)
    localStorage.setItem(KEY, next ? '1' : '0')
  }

  // Render nothing until we have content — no empty error box.
  if (!data || (data.callups.length === 0 && data.articles.length === 0)) return null

  return (
    <div className="card-panel">
      <button onClick={toggle} className="w-full flex items-center justify-between text-left">
        <span className="label mb-0">Prospect news &amp; call-ups</span>
        <span className="text-gray-400 text-sm">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {data.callups.length > 0 && (
            <div className="space-y-1.5">
              {data.callups.map((c, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="text-gray-500 font-mono text-xs w-20 flex-shrink-0">{c.date}</span>
                  <span className="text-gray-200 font-medium">{c.player_name}</span>
                  <span className="text-gray-400">· {c.to_team}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${c.type_desc === 'Selected' ? 'bg-emerald-700/40 text-emerald-300' : 'bg-ink-700 text-gray-400'}`}>
                    {c.type_desc === 'Selected' ? 'call-up' : 'recalled'}
                  </span>
                  {c.inventory_match && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-600 text-white font-bold">
                      YOU OWN {c.matched_card_count}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {data.articles.length > 0 && (
            <div className="space-y-1">
              {data.articles.map((a, i) => (
                <a key={i} href={a.link} target="_blank" rel="noopener noreferrer"
                   className="block text-sm text-gray-300 hover:text-emerald-400 truncate">
                  {a.title}
                  <span className="text-gray-500 text-xs"> — {a.source}{a.age_days === 0 ? ' · today' : a.age_days ? ` · ${a.age_days}d` : ''}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Render it on the scan page**

In `frontend/src/pages/Scanner.jsx`: add the import at the top with the other imports:

```jsx
import NewsSection from '../components/NewsSection.jsx'
```

Render `<NewsSection />` immediately after the Scan-mode `card-panel` block and before the `{toast && (` block (so it sits under the mode selector, above the dropzone/stages). Add on its own line:

```jsx
      <NewsSection />
```

- [ ] **Step 4: Build to verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/components/NewsSection.jsx frontend/src/pages/Scanner.jsx
git commit -m "feat: prospect news + call-up ticker on the scan page"
```

---

### Task 6: User-data admin — token rejection + reassign/delete endpoints

**Files:**
- Modify: `backend/auth.py` (`require_auth` rejects non-configured usernames)
- Modify: `backend/routers/analytics.py` (add reassign + delete endpoints)
- Modify: `backend/schemas.py` (add `ReassignRequest`)
- Create: `backend/tests/test_user_admin.py`

**Interfaces:**
- Consumes: `get_users` (existing in auth.py), `UsageEvent`/`Scan`/`Correction` (existing).
- Produces: `POST /api/analytics/users/reassign` `{from_user, to_user}` → `{moved: {usage_events, scans, corrections}}`; `DELETE /api/analytics/users/{username}/data` → `{deleted: {...}}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_admin.py`:

```python
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import create_token
from backend.models import UsageEvent


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_token_for_unconfigured_user_is_rejected():
    # A token minted for a username not in CARDLISTER_USERS (the ghost case).
    ghost = create_token("cardlister-user")
    with TestClient(app) as client:
        r = client.get("/api/analytics", headers={"Authorization": f"Bearer {ghost}"})
    assert r.status_code == 401


def test_reassign_moves_rows(db_session):
    db_session.add_all([
        UsageEvent(username="cardlister-user", model="claude-opus-4-7", input_tokens=100),
        UsageEvent(username="cardlister-user", model="claude-opus-4-7", input_tokens=200),
    ])
    db_session.commit()
    with TestClient(app) as client:
        r = client.post("/api/analytics/users/reassign",
                        json={"from_user": "cardlister-user", "to_user": "tester"},
                        headers=_auth(client))
    assert r.status_code == 200, r.text
    assert r.json()["moved"]["usage_events"] == 2
    assert db_session.query(UsageEvent).filter_by(username="cardlister-user").count() == 0
    assert db_session.query(UsageEvent).filter_by(username="tester").count() == 2


def test_reassign_rejects_unconfigured_target(db_session):
    with TestClient(app) as client:
        r = client.post("/api/analytics/users/reassign",
                        json={"from_user": "cardlister-user", "to_user": "not-a-user"},
                        headers=_auth(client))
    assert r.status_code == 400


def test_delete_user_data(db_session):
    db_session.add(UsageEvent(username="cardlister-user", model="m", input_tokens=1))
    db_session.commit()
    with TestClient(app) as client:
        r = client.delete("/api/analytics/users/cardlister-user/data", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["deleted"]["usage_events"] == 1
    assert db_session.query(UsageEvent).filter_by(username="cardlister-user").count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_user_admin.py -q`
Expected: FAIL (token still accepted; endpoints missing).

- [ ] **Step 3: Reject non-configured usernames in `require_auth`**

In `backend/auth.py`, in `require_auth`, after `username = payload.get("sub")` and the `if not username` check, add:

```python
    if username not in get_users():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
```

- [ ] **Step 4: Add the schema**

In `backend/schemas.py`, in the Analytics section, add:

```python
class ReassignRequest(BaseModel):
    from_user: str
    to_user: str
```

- [ ] **Step 5: Add the endpoints**

In `backend/routers/analytics.py`: extend imports —

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from ..auth import require_auth, get_users
from ..models import Correction, Scan, UsageEvent
from ..schemas import (
    AnalyticsReport, AnalyticsTotals, UsageRow, ModelRow, DayRow, ReassignRequest,
)
```

Append these endpoints to the router:

```python
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
```

> Note: `scans`/`corrections` table names come from `Scan.__tablename__` = `"scans"` and `Correction.__tablename__` = `"corrections"`; `UsageEvent.__tablename__` = `"usage_events"`. The test reads `moved["usage_events"]`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_user_admin.py -q`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full suite (token-rejection change is global)**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: PASS — existing tests authenticate as `tester` (configured), so the new check doesn't break them.

- [ ] **Step 8: Commit**

```bash
git add backend/auth.py backend/routers/analytics.py backend/schemas.py backend/tests/test_user_admin.py
git commit -m "feat: reject ghost tokens; reassign/delete user data endpoints"
```

---

### Task 7: Analytics "Manage data" panel (frontend)

**Files:**
- Modify: `frontend/src/api.js` (`reassignUser`, `deleteUserData`)
- Modify: `frontend/src/pages/Analytics.jsx` (Manage-data panel)

**Interfaces:**
- Consumes: reassign/delete endpoints (Task 6); existing `getAnalytics` report which returns `users` (distinct usernames) and `models`.
- Produces: `reassignUser(from_user, to_user)`, `deleteUserData(username)` in api.js.

- [ ] **Step 1: Add API wrappers**

In `frontend/src/api.js`, after `getAnalytics`, add:

```javascript
export const reassignUser = (from_user, to_user) =>
  api.post('/api/analytics/users/reassign', { from_user, to_user }).then((r) => r.data)
export const deleteUserData = (username) =>
  api.delete(`/api/analytics/users/${encodeURIComponent(username)}/data`).then((r) => r.data)
```

- [ ] **Step 2: Add the Manage-data panel to Analytics**

In `frontend/src/pages/Analytics.jsx`:

Update the import to include the new wrappers and the configured-user list source. Change:
```jsx
import { getAnalytics } from '../api'
```
to:
```jsx
import { getAnalytics, reassignUser, deleteUserData } from '../api'
```

After the main report render (near the end of the returned JSX, after the by-day panel and the estimate note, still inside `report && !loading`), add a management panel. It lets the user pick a source username (from `report.users`) and a target (also from `report.users`) and merge, or delete. Insert:

```jsx
          <ManageData users={report.users} onDone={() => window.location.reload()} />
```

Then define the component at the bottom of the file (before or after `Analytics`), module-scope:

```jsx
function ManageData({ users, onDone }) {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const merge = async () => {
    if (!from || !to || from === to) { setMsg('Pick two different users.'); return }
    setBusy(true); setMsg('')
    try {
      const r = await reassignUser(from, to)
      const n = r.moved.usage_events + r.moved.scans + r.moved.corrections
      setMsg(`Moved ${n} rows from ${from} to ${to}.`)
      setTimeout(onDone, 1200)
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Merge failed.')
    } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!from) { setMsg('Pick a user to delete.'); return }
    if (!window.confirm(`Delete all analytics data for "${from}"? This cannot be undone.`)) return
    setBusy(true); setMsg('')
    try {
      await deleteUserData(from)
      setMsg(`Deleted ${from}'s data.`)
      setTimeout(onDone, 1200)
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Delete failed.')
    } finally { setBusy(false) }
  }

  return (
    <div className="card-panel">
      <div className="font-bold mb-1">Manage data</div>
      <p className="text-xs text-gray-500 mb-3">
        Merge a stale/renamed username into a real user (keeps its cost history), or delete it.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="label">User</label>
          <select value={from} onChange={(e) => setFrom(e.target.value)} className="input">
            <option value="">Select…</option>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Merge into</label>
          <select value={to} onChange={(e) => setTo(e.target.value)} className="input">
            <option value="">Select…</option>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <button onClick={merge} disabled={busy} className="btn-secondary">Merge</button>
        <button onClick={remove} disabled={busy}
                className="px-3 py-2 rounded-lg text-sm font-semibold bg-red-900/40 border border-red-700 text-red-200 hover:bg-red-900/60">
          Delete
        </button>
      </div>
      {msg && <div className="text-xs text-gray-400 mt-2">{msg}</div>}
    </div>
  )
}
```

Ensure `useState` is imported (it already is in Analytics.jsx).

- [ ] **Step 3: Build to verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Final full backend suite**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api.js frontend/src/pages/Analytics.jsx
git commit -m "feat: Analytics Manage-data panel (merge/delete usernames)"
```

---

## Post-implementation (owner, not the agent)

Set in Railway when ready to enable alerts (never commit these): `SMTP_USERNAME` (Gmail address), `SMTP_PASSWORD` (Gmail **App Password**), `ALERT_EMAILS` (you + Alan, comma-separated). Optional: `CALLUP_POLL_MINUTES`, `NEWS_FEEDS`. The ticker + news work without SMTP; only the emails need it. After deploy, merge `cardlister-user` → `brock` from the Analytics → Manage data panel.
