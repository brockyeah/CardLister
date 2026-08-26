# Local timezone (`CARDLISTER_TZ`) — design

**Date:** 2026-08-22 (weekly deep-work session)
**Status:** awaiting owner approval — docs only, no implementation
**Backlog items:** "Analytics day boundaries are UTC" (design first) and
"Mark-sold date is computed in UTC" (quick win) — the backlog itself says the
fix should be one pass, so this design covers both, plus the Sheets/CSV date
columns and the tax-year export that inherit the same defect.

## The problem, concretely

Every timestamp in the app is naive UTC (`Column(DateTime,
default=datetime.utcnow)` on all five models — `backend/models.py:47-48,70,84,104,124`),
and every place that turns a timestamp into a *calendar day* does it in UTC
too. For an east-coast owner the day rolls over at 8pm EDT, which produces
four distinct user-visible wrongs:

1. **Analytics buckets and windows** (`backend/routers/analytics.py`):
   `analytics()` takes `now = datetime.utcnow()` (line 71) and `_range_start`
   builds the `today` and `month` windows from it by zeroing UTC fields
   (lines 52-61). `by_day` buckets each event on
   `ev.created_at.strftime("%Y-%m-%d")` (line 100) — the UTC date. A card
   scanned at 9pm EDT lands on *tomorrow's* bar in the daily cost chart, the
   "Today" filter after 8pm reports a window that began yesterday evening,
   and on the 1st of each month the "This month" total is wrong for four
   hours. The frontend renders the bucket strings verbatim
   (`frontend/src/pages/Analytics.jsx:172-173`), so fixing the backend fixes
   the chart with no frontend change.

2. **Mark-sold dates** (`frontend/src/pages/Inventory.jsx`): the modal
   defaults its picker to `new Date().toISOString().slice(0, 10)` (line 27) —
   the UTC date, i.e. **tomorrow** from 8pm EDT on. On submit it sends
   `new Date(date).toISOString()` (line 36); a bare `YYYY-MM-DD` parses as
   UTC midnight per spec, so the stored instant renders as the *previous*
   day anywhere west of UTC. Both halves of the bug in one modal.

3. **The tax-year export** (`backend/routers/cards.py`): `sold_years`
   collects `sold_at.year` (line 198) and `export_sold_csv` filters on
   `c.sold_at.year == year` (line 223) — UTC years. A sale recorded the
   evening of Dec 31 ET is stamped into the next tax year. A sale in the
   wrong tax year is a wrong tax return, which is the whole reason the
   export exists.

4. **Human-read date columns**: the Sheets mirror writes
   `created_at.isoformat()` / `sold_at.isoformat()` UTC
   (`backend/services/google_sheets.py:86-87`); the sold export renders
   `strftime("%Y-%m-%d")` UTC (`backend/routers/cards.py:163-164,167,179`);
   and the inventory table's "Added" column does `new Date(v)` on a
   no-offset ISO string (`frontend/src/components/CardTable.jsx:50-56,171`),
   which JavaScript parses as *browser-local* — so it currently displays the
   UTC clock reading as if it were local, the same evening off-by-one in a
   different coat.

## Facts established against the runtime

These were verified while writing this design; the implementation must not
re-litigate them.

- **SQLAlchemy's SQLite `DATETIME` silently drops tzinfo without
  converting.** Verified on sqlalchemy 2.0.51 (the pinned version): storing
  `2026-08-22T00:00:00+00:00` and `2026-08-22T00:00:00+05:00` both produce
  the row `'2026-08-22 00:00:00.000000'`, and the round-trip comes back
  naive. Consequence: `card.sold_at = payload.sold_at` at
  `backend/routers/cards.py:520` only stores the correct instant because the
  browser's `toISOString()` always emits `Z`. Any client sending a non-UTC
  offset (curl, a future importer) would store its **local clock reading**
  labeled as UTC. Aware datetimes must be normalized to naive UTC at the API
  boundary, explicitly.

- **The production image has no timezone database.** The runtime stage is
  `python:3.11-slim` (`Dockerfile:13`) and its apt step installs only
  `build-essential curl ca-certificates` (`Dockerfile:16-20`) — Debian slim
  ships no `tzdata` package, and `backend/requirements.txt` has no `tzdata`
  pip package either. `ZoneInfo("America/New_York")` would raise
  `ZoneInfoNotFoundError` **in production only**: CI's ubuntu runners and
  dev machines have `/usr/share/zoneinfo`, so every test would pass and the
  deploy would crash. Adding `tzdata` to `requirements.txt` is a hard
  prerequisite of everything below (zoneinfo falls back to the pip package
  when the OS database is absent).

- **Existing `sold_at` rows are largely midnight-UTC artifacts, and so are
  CSV-imported dates.** The mark-sold submit path has always stored UTC
  midnight of the picked date (Inventory.jsx:36), and CSV import's
  `_parse_date` is bare `datetime.fromisoformat` (cards.py:264-268), so an
  imported `Date Sold` of `2026-08-21` also stores midnight. Rendering those
  instants in ET without special handling would shift **every historical
  sold date back one day** — the fix would corrupt exactly the data it
  exists to protect.

- **Pydantic parses a bare `YYYY-MM-DD` string into a naive midnight
  datetime.** Verified on pydantic 2.13.4 (the pinned version):
  `MarkSoldRequest(sold_at="2026-08-22")` yields naive
  `datetime(2026, 8, 22, 0, 0)`. The existing `Optional[datetime]` schema
  (`backend/schemas.py:149-151`) therefore already accepts a date-only
  submit with no schema change — which is what makes the date-only contract
  below possible.

## Decision: what does a stored naive datetime mean?

**A naive stored datetime is a UTC instant** — with one carve-out: a value
at exactly `00:00:00.000000` is a **date-only value** meaning "that
calendar date, verbatim". Real instants always come from `datetime.utcnow()`
(microseconds essentially never all-zero) or from a normalized aware value;
exact midnight only ever came from the date-picker and bare-date-import
paths above.

This carve-out is a **contract, not a legacy accommodation** (revised after
CodeRabbit's review of the first draft, which correctly observed that a
heuristic without provenance can misread a deliberate midnight instant):
exact midnight *is* the canonical stored representation of a date-only
field. The mark-sold modal submits the bare picked date (pydantic fact
above), CSV import keeps storing bare dates at midnight — the existing
`_parse_date` behavior, unchanged — and `card_date()` renders the calendar
date back verbatim. Sold dates are date-semantics fields end to end (the
picker is date-only), so nothing is lost, historical rows and new writes
share one representation, and the round-trip is exact. The residual
misread — an API caller hand-sending `...T00:00:00Z` while *meaning* that
instant — is documented under "What could go wrong".

## Approaches

### A. Keep storage UTC; convert at the edges (recommended)

Storage, defaults, and ops timestamps stay naive UTC exactly as today. A new
`backend/timeutils.py` owns one configured zone (`CARDLISTER_TZ`, default
`America/New_York`) and a small set of helpers; the handful of places that
turn instants into calendar days call them. Date-only fields keep their
existing midnight-UTC representation — now promoted to an explicit contract
(the decision above) — and a pure read-side rule renders them verbatim, so
legacy rows and new writes are indistinguishable by design.

- - No data migration, nothing destructive, trivially reversible.
- - Ops timestamps (JWT `exp` at `backend/auth.py:113`, poller heartbeat and
  health staleness at `backend/main.py:41,63,123`, the 48h orphan grace
  window — whose comment at `backend/routers/analytics.py:234-236` already
  documents a local-time pitfall) stay UTC, which is where they belong.
- - Small blast radius: ~6 backend call sites plus one frontend modal.
- – The date-only contract is a permanent convention future readers must
  know (mitigated: it lives in one helper with its own tests and docstring,
  and it is the *documented meaning* of midnight, not a heuristic).

### B. Store local time

Rewrite every writer to local-naive and migrate all existing rows.

- – Touches every model default, every comparison, and the time math the
  analytics comment explicitly warns about; DST makes stored local times
  ambiguous for one hour a year (2026-11-01 01:30 happens twice).
- – A future `CARDLISTER_TZ` change re-interprets every stored row.
- – JWT expiry and heartbeat staleness in local time is strictly worse.
- Rejected.

### C. Store timezone-aware values

SQLite has no timestamptz, and the pinned SQLAlchemy dialect provably drops
tzinfo (fact above) — aware storage would mean string columns and custom
types across five models. Rejected as cost without benefit: with a single
configured zone, aware storage buys nothing over convert-at-the-edges.

### Sub-decision: midnight rows — migrate, or make midnight the contract?

- **A1 — one-time data migration**: rewrite `sold_at`/`created_at` values at
  exact midnight to local noon of the same calendar date. Preserves dates and
  removes the quirk, but it mutates rows at startup, needs its own
  idempotency argument (`_COLUMN_MIGRATIONS` in `backend/database.py` is a
  column list, not a data-migration framework), and misclassifying a genuine
  midnight instant would silently move a real timestamp.
- **A2 — midnight-as-date-only contract (recommended)**: `card_date(dt)`
  returns `dt.date()` verbatim when `dt.time() == 00:00:00` and
  `dt.microsecond == 0`, else `to_local(dt).date()`. Pure, tested,
  reversible, no writes — and the write side *keeps producing* the same
  representation on purpose: the mark-sold modal submits the bare picked
  date (which pydantic parses to naive midnight, fact above) and CSV
  import's existing bare-date parse is left exactly as it is. One
  representation for legacy and new rows, exact round-trips, and no
  browser-timezone dependence anywhere in the sold-date path.

An earlier draft of this design had A2 storing *local noon* for new
date-only writes, treating midnight purely as a legacy artifact. CodeRabbit's
review surfaced two real flaws in that: the export/import round-trip could
not be instant-exact (noon in, date-only out, noon back), and computing noon
in the *browser's* zone reintroduced a browser-vs-`CARDLISTER_TZ` skew.
Making midnight the canonical representation dissolves both.

**Recommendation: A with A2.**

## Design

### Configuration

`CARDLISTER_TZ` env var, default `America/New_York`. Resolved through an
`lru_cache` keyed on the raw string, so an env change takes effect without
restart (matching `get_users()`'s live-read convention in
`backend/auth.py`) while the ZoneInfo lookup costs nothing per request. An
**invalid value logs one loud warning and falls back to the default** — it
does not refuse to boot. This deliberately follows the correction recorded
in the 2026-08-18 owner-gate design (validating an optional var in
`validate_secrets` crashes production on a typo): a mis-bucketed chart is
strictly less bad than a down app, and the fallback zone is the right one
for this household anyway. Document the var in README and `.env.example`.

`tzdata` is added to `backend/requirements.txt`, exact-pinned like every
other entry in that file (see facts above). Pinning the pip package rather
than apt-installing tzdata guarantees the database exists in every
environment. Note `zoneinfo` consults the OS `TZPATH` *first* and falls back
to the pip wheel, so dev and CI will read `/usr/share/zoneinfo` while the
slim image reads the wheel; we deliberately do **not** force
`PYTHONTZPATH=""` to unify the source — IANA data for a stable US zone does
not meaningfully skew between contemporaneous sources, and the failure mode
that matters (no database at all in production) is closed by the pin.

### `backend/timeutils.py`

| Helper | Contract |
| --- | --- |
| `local_tz()` | resolved `ZoneInfo`, with the fallback rule above |
| `utc_naive(dt)` | aware → convert to UTC, strip tzinfo; naive → unchanged. The API-boundary normalizer. |
| `to_local(dt)` | naive-UTC instant → aware local |
| `local_day_key(dt)` | `to_local(dt).strftime("%Y-%m-%d")` — analytics buckets |
| `card_date(dt)` | the A2 date-only contract; returns a `date` for rendering and year filters |
| `range_start_utc(range_key, now_utc)` | `today`/`month` starts computed in local calendar space, returned as naive UTC for the `created_at >=` filter. `7d`/`30d` stay rolling `now - timedelta` windows (tz-independent, unchanged semantics). |

### Call-site changes

- `backend/routers/analytics.py:52-61,71-77` — `_range_start` becomes
  `range_start_utc`; line 100 becomes `local_day_key(ev.created_at)`.
  `since`/`until` in the response stay UTC instants (nothing renders them —
  verified against `Analytics.jsx`).
- `backend/routers/cards.py:520` — `card.sold_at =
  utc_naive(payload.sold_at) if payload.sold_at else datetime.utcnow()`
  (defense for non-`Z` offsets, per the SQLAlchemy fact). A date-only submit
  arrives as naive midnight (pydantic fact) and passes through unchanged —
  the canonical date-only representation.
- `backend/routers/cards.py:163-182,198,223` — `_sold_row` dates, the
  `sold_years` set, and the year filter all go through `card_date`.
- `backend/routers/cards.py:264-268,378-389` — import: bare `YYYY-MM-DD` →
  **unchanged** (`_parse_date` already yields naive midnight, which is now
  the canonical date-only representation); ISO with offset → `utc_naive`
  (the only new branch); naive ISO with a time part → unchanged (legacy UTC
  meaning preserved, so re-importing an old export is stable).
- `backend/services/google_sheets.py:86-87` — "Date Listed" renders
  `to_local(created_at).isoformat()` for real instants and the bare date for
  date-only values; "Date Sold" renders date-only via `card_date` (it is a
  calendar-date field everywhere — the picker is date-only). Value *format*
  changes inside existing columns; no column moves, so invariant #1
  (append-only `SHEET_HEADERS`) is untouched, and one press of the existing
  resync button converges the whole sheet.
- `frontend/src/pages/Inventory.jsx:27,36` — the modal defaults its picker
  from **browser** local date parts (the only remaining browser-timezone
  use: "today" for the person clicking) and submits the picked
  `YYYY-MM-DD` string **as-is** — no `new Date()`, no `toISOString()`, no
  noon. The server owns all date semantics; browser vs `CARDLISTER_TZ`
  disagreement cannot shift the stored date. New pure helper in
  `frontend/src/lib/dates.js` (vitest, node env — no jsdom needed).
- `frontend/src/components/CardTable.jsx:50-56` — `fmtDate` moves to
  `lib/dates.js` and mirrors the backend rule: exact-midnight no-offset ISO
  → render the date part verbatim; otherwise treat the naive string as UTC
  (append `Z`) before `toLocaleDateString()`. Mirroring backend logic in a
  tested frontend lib has precedent (`ebayTitle.js`).

### Explicit non-goals

JWT expiry, poller heartbeat and health staleness, the orphan grace window,
the backup filename stamp (`analytics.py:208`, cosmetic), and
`services/callups.py:141`'s `today` (a parameter to MLB's own API, a
different domain) all **stay UTC**. Per-user timezones are out of scope —
one household, one zone.

## What could go wrong

1. **Green CI, crashed deploy** — the tzdata gap is invisible everywhere but
   the Railway image. Mitigation: the pip `tzdata` pin (dependency of step 1
   of the plan, not an afterthought); CI cannot catch this class, which is
   why it is solved by making the environments identical.
2. **Historical sold dates shift by a day** — prevented by the A2 rule;
   pinned by tests that feed legacy midnight rows through the sold export,
   `sold_years`, and the Sheets row builder.
3. **Aware datetimes stored wrong** — proven failure mode; `utc_naive` at
   the boundary plus a test that POSTs a `+05:00` mark-sold payload.
4. **DST edges** — `today`/`month` window starts are built in local calendar
   space with zoneinfo and converted once, then tested on the 2026
   transitions (Mar 8, Nov 1): bucket keys and window starts on both sides,
   including the repeated 01:30 on fall-back day.
5. **Date-only contract misread** — an API caller hand-sending
   `...T00:00:00Z` while *meaning* that instant (curl with a rounded
   timestamp) gets date-only semantics: `2026-01-01T00:00:00Z` renders as
   Jan 1, though as an instant it is Dec 31 evening ET — potentially the
   wrong tax year. Raised by CodeRabbit on the first draft. Accepted
   deliberately rather than adding a provenance column (a schema change this
   design avoids): none of the app's own writers can produce it
   (`datetime.utcnow()` stamps microseconds; the modal and CSV import send
   dates *as* dates), a hand-typed round midnight almost always means the
   calendar date anyway, and the contract is documented in the helper, the
   README var description, and this spec. Callers who mean a midnight
   instant send `00:00:01` or better precision.
6. **Analytics history re-buckets** — evening scans move to the (correct)
   local day, so historical daily bars change once. Presentation-only, no
   stored data changes; called out in the changelog entry rather than
   "fixed" with a migration.
7. **Sheet/CSV round-trip drift** — export formats change while import must
   keep accepting old exports. The import branch table above is
   backward-compatible by construction and pinned by a round-trip test:
   date-only fields round-trip **value-exact** (midnight in, bare date out,
   midnight back); "Date Listed" real instants round-trip to the second via
   the offset-carrying ISO form. A *legacy* real-instant `sold_at` exports
   date-only and reimports as the date-only representation — calendar date
   preserved, sub-day precision deliberately dropped (it is a date-semantics
   field; the precision was never meaningful).

## Verification

- Unit tests for every `timeutils` helper, including both DST transitions,
  the date-only rule, invalid-tz fallback, and `+05:00` normalization.
- Endpoint tests: an event at `2026-08-22T01:30Z` (21:30 EDT Aug 21)
  buckets on `2026-08-21`, is **included** in "today" at
  `now = 2026-08-22T02:00Z` (still Aug 21 in ET), and is excluded once the
  ET day turns, e.g. at `now = 2026-08-22T05:00Z`; a Dec-31-evening ET sale
  lands in the earlier tax year in both `sold-years` and the export.
- Round-trip test: sold export / Sheets row for a midnight (date-only) row
  keeps its calendar date and reimports value-exact; "Date Listed" real
  instants reimport equal to the second; a mark-sold submit of a bare
  `YYYY-MM-DD` stores naive midnight of that date.
- Frontend vitest for `lib/dates.js` (picker default from local date parts,
  `displayDate` date-only + UTC-instant rendering).
- Ship gates as always: full backend suite green, frontend build green
  (plus `conftest.py` pins `CARDLISTER_TZ` in its env block so the suite is
  deterministic on any runner).

## Cost

Zero new Anthropic calls; per-scan cost delta is $0.00. One new pure-Python
pip dependency (`tzdata`, ~430 kB wheel, no transitive deps).
