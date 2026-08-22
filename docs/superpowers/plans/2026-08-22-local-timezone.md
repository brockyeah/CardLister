# Local timezone (`CARDLISTER_TZ`) — implementation plan

**Design:** `docs/superpowers/specs/2026-08-22-local-timezone-design.md`
(read it first — it records runtime-proven facts the steps below depend on,
notably that SQLAlchemy's SQLite dialect drops tzinfo without converting and
that the production image has no timezone database).

Steps are ordered and independently testable; each lands with its test and
leaves the suite green. Steps 2–6 all depend on step 1 but not on each
other, so they can ship as one PR or several.

## Step 1 — dependency, config, and `backend/timeutils.py`

- Add `tzdata` to `backend/requirements.txt`, exact-pinned like every other
  entry there (hard prerequisite: the `python:3.11-slim` image has no OS
  zoneinfo — deploy would crash while CI stays green). Deliberately no
  `PYTHONTZPATH` manipulation — see the design's configuration section.
- Pin `CARDLISTER_TZ=America/New_York` in the `conftest.py` env block (with
  the other env setup, before any backend import) so the suite is
  deterministic on any runner.
- New module `backend/timeutils.py`: `local_tz()`, `utc_naive()`,
  `to_local()`, `local_day_key()`, `card_date()`, `range_start_utc()` —
  contracts as tabled in the design. Invalid
  `CARDLISTER_TZ` logs one warning and falls back to the default; resolution
  is `lru_cache`d on the raw env string so changes take effect live.

**Test (`backend/tests/test_timeutils.py`):**
- `utc_naive`: `+05:00` aware → correct naive UTC; naive passes through.
- `card_date`: `2026-08-22 00:00:00.000000` → `2026-08-22` verbatim (the
  date-only representation); `2026-08-22 01:30:00.123456` → `2026-08-21`
  (ET).
- `local_day_key` and `range_start_utc` across both 2026 DST transitions
  (Mar 8, Nov 1): `today` start is `04:00Z` under EDT and `05:00Z` under
  EST; `month` start on Nov 1; `7d`/`30d` stay `now - timedelta`.
- Invalid tz (`CARDLISTER_TZ=Mars/Olympus`) falls back to America/New_York
  without raising.

## Step 2 — analytics windows and day buckets

- `backend/routers/analytics.py`: replace `_range_start` (lines 52-61) with
  `timeutils.range_start_utc`; keep `now = datetime.utcnow()` (line 71) as
  the UTC anchor; bucket with `local_day_key(ev.created_at)` (line 100).
  No schema or response-shape change; `since`/`until` stay UTC instants.

**Test (extend `backend/tests/test_analytics_cost.py`):** seed a UsageEvent
at `2026-08-22T01:30:00Z` (= 21:30 EDT Aug 21): `by_day` reports a
`2026-08-21` bucket, and with `range=today` mocked to
`now = 2026-08-22T02:00:00Z` (still Aug 21 ET) the event **is** included,
while at `now = 2026-08-22T05:00:00Z` (Aug 22 ET has begun) it is not.
Patch time via the module attribute per the conftest note.

## Step 3 — mark-sold write path (backend)

- `backend/routers/cards.py:520`: `card.sold_at =
  timeutils.utc_naive(payload.sold_at) if payload.sold_at else
  datetime.utcnow()`.
- No schema change: pydantic 2.13.4 already parses a bare `"2026-08-22"`
  into naive midnight (runtime-verified — see the design's facts), which is
  the canonical date-only representation. The frontend switches to sending
  exactly that in step 6.

**Test:** POST `/api/cards/{id}/mark-sold` with
`sold_at="2026-08-22T12:00:00+05:00"` → stored value is naive
`2026-08-22 07:00:00` (this fails today: the pinned SQLAlchemy stores
`12:00:00`); with `sold_at="2026-08-22"` → stored naive
`2026-08-22 00:00:00` and `card_date` renders `2026-08-22` regardless of
zone. Existing mark-sold tests unchanged.

## Step 4 — tax export and sold-years

- `backend/routers/cards.py`: `_sold_row`'s `date()` (163-164) becomes
  `timeutils.card_date`; `sold_years` (198) and the year filter (223) use
  `card_date(...).year`.

**Test (extend `backend/tests/test_export_sold_csv.py`):**
- Date-only row (`sold_at=2026-03-15 00:00:00`) exports Date Sold
  `2026-03-15` and appears under year 2026 — unchanged by the tz switch.
- Real instant `2027-01-01T02:30:00Z` (Dec 31 2026, 21:30 ET) lands in year
  **2026** in both `sold-years` and the `year=2026` export, and its Date
  Sold cell reads `2026-12-31`.

## Step 5 — Sheets mirror / CSV date columns, import symmetry

- `backend/services/google_sheets.py:86-87`: "Date Listed" → local ISO with
  offset for real instants, bare date for date-only values; "Date Sold" → date-only
  via `card_date`.
- `backend/routers/cards.py` import (264-268, 378-389): one new branch
  only — ISO with offset → `utc_naive`. Bare `YYYY-MM-DD` already parses to
  naive midnight, which is now the canonical date-only representation, and
  naive ISO with a time part keeps its legacy UTC meaning.

**Test (extend `backend/tests/test_import_csv.py` +
`test_sheets_mirror.py`):** round-trip — export a card and import the file:
a date-only `sold_at` (naive midnight) reimports **value-exact**, a real
`created_at` instant reimports equal to the second via the offset-carrying
"Date Listed" form, and a bare `Date Sold` `2026-08-21` renders back as
`2026-08-21` everywhere. Do **not** assert instant equality for a *legacy*
real-instant `sold_at` — Date Sold exports date-only, so only its calendar
date survives, by design (see the design's risk #7).

## Step 6 — frontend: modal defaults, date-only submit, `fmtDate`

- New `frontend/src/lib/dates.js`: `todayLocalDateInput()` (browser-local
  `YYYY-MM-DD` from date parts — the picker default, the only remaining
  browser-timezone use) and `displayDate(iso)` — the `fmtDate` replacement
  mirroring the backend date-only rule (exact-midnight no-offset string →
  date part verbatim; otherwise parse as UTC by appending `Z`, then
  `toLocaleDateString()`).
- `frontend/src/pages/Inventory.jsx:27,36`: default from
  `todayLocalDateInput()`; submit the picked `YYYY-MM-DD` string **as-is**
  (no `new Date()`, no `toISOString()`) — the server owns date semantics,
  so browser vs `CARDLISTER_TZ` disagreement cannot shift the stored date.
- `frontend/src/components/CardTable.jsx:50-56` uses `displayDate`.

**Test (`frontend/src/lib/dates.test.js`, node env — pure functions only,
per the repo's no-jsdom testing note):** `todayLocalDateInput` composes
from local date parts (mocked `Date` at ±11h offsets);
`displayDate('2026-08-21T00:00:00')` → Aug 21 regardless of environment tz;
`displayDate` of a real instant appends `Z` before parsing.

## Step 7 — docs and process

- README + `.env.example`: document `CARDLISTER_TZ` (default
  `America/New_York`; IANA name; invalid values fall back with a logged
  warning).
- CHANGELOG `[Unreleased]` entry noting the one-time visual re-bucket of
  historical analytics bars (expected, presentation-only).
- BACKLOG: move "Analytics day boundaries are UTC" and "Mark-sold date is
  computed in UTC" to Shipped; annotate the `listed_at` item (its future
  "Date Listed" writes must go through the same helpers).

**Gate:** full backend suite + frontend build green, per repo ship gates.

## Estimated effort

One focused session (steps 1–4), a second for 5–7. No schema change, no
`_COLUMN_MIGRATIONS` entry (no new columns), no new Anthropic calls
($0.00 per-scan delta), one pure-Python dependency (`tzdata`).

## Decisions needed from the owner before implementation

1. Approve Approach A + A2: storage stays naive UTC, **exact midnight is
   the documented date-only representation** (legacy rows and new date-only
   writes share it; the mark-sold modal submits the bare date), and there is
   **no data migration**. Residual caveat accepted: an API caller
   hand-sending `...T00:00:00Z` while meaning that instant gets date-only
   semantics (design risk #5).
2. Confirm `CARDLISTER_TZ` default `America/New_York` and the
   warn-and-fall-back (not refuse-to-boot) behavior for invalid values.
3. Confirm the Sheets column format change: "Date Sold" becomes date-only,
   "Date Listed" becomes local-offset ISO (one resync converges the sheet).
