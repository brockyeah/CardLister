# 1st Bowman Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit "1st Bowman" designation to cards so the vision model detects it at scan time, the inventory and eBay listing text surface it, and call-up alert emails call out when an owned match includes the player's 1st Bowman card.

**Architecture:** One new boolean (`is_first_bowman`) on `cards` plus one derived counter (`first_bowman_count`) on `callup_events`, both added via the existing `ensure_columns` registry (no Alembic). The flag flows through the existing generic paths: vision prompt → extraction JSON → CardForm FLAGS checkbox → CardCreate/CardUpdate schemas → learning IDENTITY_FIELDS → eBay title/description → Sheets mirror → digest email.

**Tech Stack:** FastAPI + SQLAlchemy + SQLite, pytest; React 18 + Tailwind (ink/emerald tokens).

## Spec summary (approved in conversation, 2026-07-10)

A "1st Bowman" is a player's first-ever card in a Topps Bowman set, marked with a printed "1st" logo on the card front (2016+). It is the definitive prospect card and spikes in value on call-up — Alan asked that call-up alerts be tied to these cards.

Requirements:
1. Cards carry an `is_first_bowman` boolean; vision extraction sets it only when the "1st" logo is visibly printed on the card (no guessing from training data).
2. Users can correct the flag in the card form; the learning system treats it as an identity field (every copy of the same card number shares 1st-Bowman status) so exact-card overrides apply.
3. The call-up digest's inventory-match line upgrades from "⭐ You own N card(s) of this player." to note when any matched card is a 1st Bowman; 1st Bowman matches sort ahead of other inventory matches.
4. Inventory table shows a small "1st" badge next to the player name; eBay title gains a `1ST BOWMAN` flag token; the Sheets mirror gains a trailing "1st Bowman" Y/blank column.
5. Alert recipients, poller cadence, and env semantics are unchanged.

## Global Constraints

- Schema changes go through `_COLUMN_MIGRATIONS` in `backend/database.py` (SQLite `ALTER TABLE`, idempotent) — never Alembic, never editing existing entries.
- UI colors: existing ink/emerald Tailwind tokens only (bg ink-700/800, borders ink-600/700, text gray-100→500, accent emerald-400/500/600). No new palette values, no hex literals.
- Backend test gate: `.venv/bin/python -m pytest backend/tests -q` from the repo root (all ~50 tests green, not just new ones).
- Frontend gate: `npm run build` inside `frontend/` (no test runner exists; the build is the gate).
- Work on a feature branch off `main` (e.g. `feat/first-bowman-flag`); commit per task; the owner merges the PR himself — never run `gh pr merge`.
- Copy style: the token is written "1st Bowman" in prose/UI, `1ST BOWMAN` in eBay title flags, "1st" in the tiny inventory badge.

---

### Task 1: Backend flag — model, migration, schemas, vision, learning, eBay text, Sheets mirror

**Files:**
- Modify: `backend/models.py` (Card class, Flags block ~line 21)
- Modify: `backend/database.py` (`_COLUMN_MIGRATIONS`, ~line 25)
- Modify: `backend/schemas.py` (CardBase ~line 27, CardUpdate ~line 55)
- Modify: `backend/services/claude_vision.py` (SYSTEM_PROMPT rules + JSON shape ~lines 90–115, `MOCK_RESPONSE` ~line 118, `_blank_card` ~line 136)
- Modify: `backend/services/learning.py` (IDENTITY_FIELDS, line 20)
- Modify: `backend/routers/ebay.py` (`build_title` ~line 21, `build_description` ~line 68)
- Modify: `backend/services/google_sheets.py` (`SHEET_HEADERS` line 13, `_card_to_row` ~line 46)
- Test: `backend/tests/test_first_bowman.py` (create)

**Interfaces:**
- Consumes: existing `Card` ORM model, `ensure_columns(engine)` from `backend/database.py`, `learning.IDENTITY_FIELDS` list, `build_title(card) -> str` / `build_description(card) -> str`.
- Produces: `Card.is_first_bowman: bool` (ORM attribute, default `False`) — Task 2 reads it in `count_inventory_matches`; Task 3's form posts it through `CardCreate`/`CardUpdate`, which include `is_first_bowman` after this task.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_first_bowman.py`:

```python
"""1st Bowman flag: migration, extraction shape, learning identity, listing text."""
from sqlalchemy import create_engine, text

from backend.database import ensure_columns
from backend.models import Card
from backend.routers.ebay import build_description, build_title
from backend.services import claude_vision, learning


def _cols(engine, table):
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def test_migration_adds_is_first_bowman(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cards (id INTEGER PRIMARY KEY, player_name VARCHAR)"))
    ensure_columns(engine)
    assert "is_first_bowman" in _cols(engine, "cards")


def test_extraction_shapes_include_first_bowman():
    assert '"is_first_bowman"' in claude_vision.SYSTEM_PROMPT
    assert "is_first_bowman" in claude_vision.MOCK_RESPONSE
    assert claude_vision._blank_card("x")["is_first_bowman"] is False


def test_first_bowman_is_identity_field():
    # Identity: every copy of the same card number shares 1st-Bowman status,
    # so exact-card overrides may set it — unlike copy-specific parallels.
    assert "is_first_bowman" in learning.IDENTITY_FIELDS
    assert "is_first_bowman" not in learning.COPY_SPECIFIC_FIELDS
    diff = learning.diff_correction(
        {"is_first_bowman": False}, {"is_first_bowman": True}
    )
    assert diff == {"is_first_bowman": {"from": False, "to": True}}


def test_listing_text_includes_first_bowman():
    card = Card(
        player_name="Jackson Holliday", year=2023, brand="Bowman", set_name="Chrome",
        card_number="BCP-9", team="Baltimore Orioles",
        is_first_bowman=True, is_rookie=False,
    )
    title = build_title(card)
    assert "1ST BOWMAN" in title
    assert len(title) <= 80
    assert "1st Bowman: YES" in build_description(card)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_first_bowman.py -v`
Expected: 4 failures — `AssertionError` on the migration/prompt/identity assertions and `TypeError: 'is_first_bowman' is an invalid keyword argument for Card` on the listing test.

- [ ] **Step 3: Model + migration + schemas**

In `backend/models.py`, Flags block of `Card` (after `is_rookie`):

```python
    # Flags
    is_rookie = Column(Boolean, default=False)
    is_first_bowman = Column(Boolean, default=False)  # printed "1st" logo (Bowman prospects)
    is_autograph = Column(Boolean, default=False)
    is_patch = Column(Boolean, default=False)
    is_refractor = Column(Boolean, default=False)
```

In `backend/database.py`, append to `_COLUMN_MIGRATIONS` (never reorder existing entries):

```python
_COLUMN_MIGRATIONS = [
    ("cards", "quantity", "INTEGER NOT NULL DEFAULT 1"),
    ("cards", "back_image_path", "VARCHAR"),
    ("cards", "is_first_bowman", "BOOLEAN NOT NULL DEFAULT 0"),
]
```

In `backend/schemas.py`, `CardBase` (after `is_rookie: bool = False`):

```python
    is_first_bowman: bool = False
```

and `CardUpdate` (after `is_rookie: Optional[bool] = None`):

```python
    is_first_bowman: Optional[bool] = None
```

(`CardOut` inherits from `CardBase`, so API responses pick the field up automatically.)

- [ ] **Step 4: Vision prompt + mock + blank shapes**

In `backend/services/claude_vision.py`, insert a new numbered rule after rule 7 (`is_rookie`) and renumber the following rules (current 8→9, 9→10):

```
8. is_first_bowman = true ONLY if the card front visibly shows Bowman's printed "1st" logo/stamp (the small badge on Bowman prospect cards since 2016). Do NOT infer it from training data or from the card being a prospect card — if you cannot see the logo, set false and note the uncertainty in confidence_notes.
```

Add the field to the JSON shape block (after `"is_rookie": false,`):

```
  "is_rookie": false,
  "is_first_bowman": false,
  "is_autograph": false,
```

Add to `MOCK_RESPONSE` (after `"is_rookie": True,` — the mock is a Bowman Chrome prospect, so `True` exercises the UI in mock mode):

```python
    "is_rookie": True,
    "is_first_bowman": True,
    "is_autograph": False,
```

Add to `_blank_card` (after `"is_rookie": False,`):

```python
        "is_rookie": False,
        "is_first_bowman": False,
        "is_autograph": False,
```

- [ ] **Step 5: Learning identity field**

In `backend/services/learning.py` line 20:

```python
IDENTITY_FIELDS = ["player_name", "year", "brand", "set_name", "card_number", "team", "is_rookie", "is_first_bowman"]
```

(`COPY_SPECIFIC_FIELDS` unchanged — 1st-Bowman status belongs to the card's identity, not the physical copy.)

- [ ] **Step 6: eBay listing text**

In `backend/routers/ebay.py` `build_title`, add before the `is_rookie` check (collectors search "1st Bowman", so it leads the flag tokens):

```python
    flags = []
    if card.is_first_bowman:
        flags.append("1ST BOWMAN")
    if card.is_rookie:
        flags.append("RC")
```

In `build_description`, after the `is_rookie` line:

```python
    if card.is_rookie:
        lines.append("Rookie Card: YES")
    if card.is_first_bowman:
        lines.append("1st Bowman: YES")
```

- [ ] **Step 7: Sheets mirror (append-at-end, matching the Quantity precedent)**

In `backend/services/google_sheets.py`, `SHEET_HEADERS` gains a trailing entry:

```python
SHEET_HEADERS = [
    "Player", "Year", "Brand", "Set", "Card #", "Team",
    "RC", "Auto", "Patch", "Condition", "Listed Price",
    "eBay URL", "Status", "Date Listed", "Date Sold", "Sale Price", "Notes",
    "Quantity", "1st Bowman",
]
```

and `_card_to_row` gains the matching trailing element:

```python
        card.quantity if card.quantity is not None else 1,
        "Y" if card.is_first_bowman else "",
    ]
```

(`_ensure_header` already rewrites the header row when it is shorter than `SHEET_HEADERS`, so existing sheets pick up the new column on next sync.)

- [ ] **Step 8: Run the new tests, then the full suite**

Run: `.venv/bin/python -m pytest backend/tests/test_first_bowman.py -v`
Expected: 4 passed.

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: all tests pass (no existing test asserts an exact extraction-shape key set, but if one fails on the new key, fix the test's expectation — the new field is intended).

- [ ] **Step 9: Commit**

```bash
git add backend/models.py backend/database.py backend/schemas.py backend/services/claude_vision.py backend/services/learning.py backend/routers/ebay.py backend/services/google_sheets.py backend/tests/test_first_bowman.py
git commit -m "feat: is_first_bowman flag through model, extraction, learning, listings"
```

---

### Task 2: Call-up digest — 1st Bowman-aware match counts + email copy

**Files:**
- Modify: `backend/models.py` (CallupEvent, ~line 120)
- Modify: `backend/database.py` (`_COLUMN_MIGRATIONS`)
- Modify: `backend/services/callups.py` (`count_inventory_matches` ~line 73, `_compose_digest` ~line 95, `run_poll_cycle` ~line 135)
- Test: `backend/tests/test_callups.py` (update `test_count_inventory_matches`), `backend/tests/test_poll_cycle.py` (update `test_poll_cycle_records_and_emails`), `backend/tests/test_first_bowman.py` (add migration assertion)

**Interfaces:**
- Consumes: `Card.is_first_bowman` from Task 1.
- Produces: `count_inventory_matches(db, player_name) -> tuple[int, int]` — `(total_qty, first_bowman_qty)`; `CallupEvent.first_bowman_count: int` (default 0). **Breaking change:** the old `-> int` signature has exactly two call sites — `run_poll_cycle` and `test_count_inventory_matches` — both updated in this task; verify with `grep -rn "count_inventory_matches" backend/`.

- [ ] **Step 1: Update the tests to the new behavior (failing first)**

In `backend/tests/test_callups.py`, replace `test_count_inventory_matches`:

```python
def test_count_inventory_matches(db_session):
    db_session.add_all([
        Card(player_name="Jackson Holliday", quantity=2, is_first_bowman=True),
        Card(player_name="jackson  holliday", quantity=1),  # normalized dup, not 1st Bowman
        Card(player_name="Someone Else", quantity=5, is_first_bowman=True),
    ])
    db_session.commit()
    assert callups.count_inventory_matches(db_session, "Jackson Holliday") == (3, 2)
    assert callups.count_inventory_matches(db_session, "Nobody") == (0, 0)
```

In `backend/tests/test_poll_cycle.py`, replace `test_poll_cycle_records_and_emails`:

```python
def test_poll_cycle_records_and_emails(db_session):
    db_session.add(Card(player_name="Owned Guy", quantity=2, is_first_bowman=True))
    db_session.commit()

    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=True) as send:
        result = callups.run_poll_cycle(db_session)

    assert result == {"new": 3, "emailed": 2}          # Selected + owned Recalled; Nobody skipped
    send.assert_called_once()
    subject, body = send.call_args.args
    assert "Owned Guy" in subject                       # inventory match leads per spec
    assert subject.endswith("(+1 more)")
    assert "You own 2" in body                          # inventory match surfaced
    assert "1st Bowman" in body                         # 1st Bowman ownership called out
    assert body.index("Owned Guy") < body.index("Jackson Holliday")
    # emailed rows stamped; skipped row not
    rows = {e.tx_id: e for e in db_session.query(CallupEvent).all()}
    assert rows[2001].emailed_at is not None and rows[2003].emailed_at is None
    assert rows[2002].inventory_match is True and rows[2002].matched_card_count == 2
    assert rows[2002].first_bowman_count == 2 and rows[2001].first_bowman_count == 0
```

In `backend/tests/test_first_bowman.py`, add:

```python
def test_migration_adds_first_bowman_count_to_callup_events(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE callup_events (id INTEGER PRIMARY KEY, tx_id INTEGER)"))
    ensure_columns(engine)
    assert "first_bowman_count" in _cols(engine, "callup_events")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_callups.py::test_count_inventory_matches backend/tests/test_poll_cycle.py::test_poll_cycle_records_and_emails backend/tests/test_first_bowman.py::test_migration_adds_first_bowman_count_to_callup_events -v`
Expected: 3 failures (tuple-vs-int assertion, missing "1st Bowman" in body / missing attribute, missing column).

- [ ] **Step 3: CallupEvent column + migration**

In `backend/models.py`, `CallupEvent` (after `matched_card_count`):

```python
    inventory_match = Column(Boolean, default=False)
    matched_card_count = Column(Integer, default=0)
    first_bowman_count = Column(Integer, default=0)  # of the matches, how many are 1st Bowmans
```

In `backend/database.py`:

```python
_COLUMN_MIGRATIONS = [
    ("cards", "quantity", "INTEGER NOT NULL DEFAULT 1"),
    ("cards", "back_image_path", "VARCHAR"),
    ("cards", "is_first_bowman", "BOOLEAN NOT NULL DEFAULT 0"),
    ("callup_events", "first_bowman_count", "INTEGER NOT NULL DEFAULT 0"),
]
```

- [ ] **Step 4: Service changes**

In `backend/services/callups.py`, replace `count_inventory_matches`:

```python
def count_inventory_matches(db: Session, player_name: str) -> tuple[int, int]:
    """(total_qty, first_bowman_qty) of cards whose normalized name matches.
    Normalizes in Python (SQLite lacks accent folding), so scans all cards —
    fine at this scale (hundreds of rows)."""
    target = normalize_name(player_name)
    if not target:
        return 0, 0
    total = first_bowman = 0
    rows = db.query(Card.player_name, Card.quantity, Card.is_first_bowman).all()
    for name, qty, is_fb in rows:
        if normalize_name(name) == target:
            total += qty or 0
            if is_fb:
                first_bowman += qty or 0
    return total, first_bowman
```

In `_compose_digest`, update the sort key (1st Bowman matches lead the matches) and the ⭐ line:

```python
    ordered = sorted(
        events,
        key=lambda e: (
            not e.inventory_match,
            not (e.first_bowman_count or 0),
            e.type_desc != "Selected",
            e.player_name,
        ),
    )
```

```python
        if e.inventory_match:
            note = f"    ⭐ You own {e.matched_card_count} card(s) of this player"
            if e.first_bowman_count:
                note += f" — including his 1st Bowman ({e.first_bowman_count})!"
            else:
                note += "."
            lines.append(note)
```

In `run_poll_cycle`, unpack the tuple:

```python
        matches, first_bowman = count_inventory_matches(db, tx["player_name"])
        db.add(CallupEvent(
            tx_id=tx["tx_id"], date=tx["date"], type_desc=tx["type_desc"],
            player_name=tx["player_name"], person_id=tx["person_id"],
            to_team=tx["to_team"], description=tx["description"],
            inventory_match=matches > 0, matched_card_count=matches,
            first_bowman_count=first_bowman,
        ))
```

- [ ] **Step 5: Run the full backend suite**

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: all pass. If any other test calls `count_inventory_matches` with the old int expectation, update it to the tuple (Step 1 should already have covered both known call sites).

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py backend/services/callups.py backend/tests/test_callups.py backend/tests/test_poll_cycle.py backend/tests/test_first_bowman.py
git commit -m "feat: call-up digest flags 1st Bowman inventory matches"
```

---

### Task 3: Frontend — form checkbox + inventory badge

**Files:**
- Modify: `frontend/src/pages/Scanner.jsx` (`EMPTY_FORM`, ~line 14)
- Modify: `frontend/src/components/CardForm.jsx` (`FLAGS`, ~line 16)
- Modify: `frontend/src/components/CardTable.jsx` (Player cell, ~line 57)

**Interfaces:**
- Consumes: `is_first_bowman` on card objects from `/api/cards` and in extraction results (Task 1's `CardBase`/extraction shape).
- Produces: user-visible checkbox labeled "1st Bowman" (posts the key through the existing generic form state) and a "1st" badge in the inventory table. No new exports.

- [ ] **Step 1: Scanner blank form**

In `frontend/src/pages/Scanner.jsx`, `EMPTY_FORM` (after `is_rookie: false,`):

```js
  is_rookie: false,
  is_first_bowman: false,
  is_autograph: false,
```

- [ ] **Step 2: CardForm flag checkbox**

In `frontend/src/components/CardForm.jsx`, `FLAGS` (after the Rookie entry — the existing `FLAGS.map` renders the checkbox, no other change needed):

```js
const FLAGS = [
  { key: 'is_rookie', label: 'Rookie' },
  { key: 'is_first_bowman', label: '1st Bowman' },
  { key: 'is_autograph', label: 'Auto' },
  { key: 'is_patch', label: 'Patch' },
  { key: 'is_refractor', label: 'Refractor' },
]
```

- [ ] **Step 3: Inventory badge**

In `frontend/src/components/CardTable.jsx`, replace the Player cell:

```jsx
              <td className="px-3 py-2 font-semibold text-gray-100">
                {c.player_name || '—'}
                {c.is_first_bowman && (
                  <span className="ml-2 align-middle text-[10px] font-bold uppercase tracking-wide bg-emerald-500/15 text-emerald-400 border border-emerald-500/40 rounded px-1.5 py-0.5">
                    1st
                  </span>
                )}
              </td>
```

- [ ] **Step 4: Build gate**

Run: `cd frontend && npm run build`
Expected: build succeeds with no errors (this is the frontend gate; there is no JS test runner).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Scanner.jsx frontend/src/components/CardForm.jsx frontend/src/components/CardTable.jsx
git commit -m "feat: 1st Bowman checkbox in card form + inventory badge"
```

---

## Verification (whole feature)

1. `.venv/bin/python -m pytest backend/tests -q` — all green.
2. `cd frontend && npm run build` — clean.
3. Manual smoke after merge/deploy (mock mode works locally without an API key): scan any image → the form shows a "1st Bowman" checkbox pre-checked by `MOCK_RESPONSE` → save → Inventory shows the emerald "1st" badge → Copy Listing Text contains `1ST BOWMAN` in the title.
4. Digest behavior lands with the next real call-up of an owned 1st Bowman player (covered by the poll-cycle test; no manual step required).
