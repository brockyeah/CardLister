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

## Decision: what does a stored naive datetime mean?

**A naive stored datetime is a UTC instant** — with one carve-out: a value
at exactly `00:00:00.000000` is a **date-only artifact** meaning "that
calendar date, verbatim". Real instants always come from `datetime.utcnow()`
(microseconds essentially never all-zero) or from a normalized aware value;
exact midnight only ever came from the date-picker and bare-date-import
paths above. The carve-out is what lets historical sold dates survive the
timezone change untouched.

## Approaches

### A. Keep storage UTC; convert at the edges (recommended)

Storage, defaults, and ops timestamps stay naive UTC exactly as today. A new
`backend/timeutils.py` owns one configured zone (`CARDLISTER_TZ`, default
`America/New_York`) and a small set of helpers; the handful of places that
turn instants into calendar days call them. Legacy midnight artifacts are
handled by a pure *read-side* rule (below), and the write paths that created
them start storing real instants (local noon), so the artifact class stops
growing.

- - No data migration, nothing destructive, trivially reversible.
- - Ops timestamps (JWT `exp` at `backend/auth.py:113`, poller heartbeat and
  health staleness at `backend/main.py:41,63,123`, the 48h orphan grace
  window — whose comment at `backend/routers/analytics.py:234-236` already
  documents a local-time pitfall) stay UTC, which is where they belong.
- - Small blast radius: ~6 backend call sites plus one frontend modal.
- – The artifact rule is a permanent quirk that future readers must know
  about (mitigated: it lives in one helper with its own tests and docstring).

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

### Sub-decision: legacy midnight rows — migrate or read-rule?

- **A1 — one-time data migration**: rewrite `sold_at`/`created_at` values at
  exact midnight to local noon of the same calendar date. Preserves dates and
  removes the quirk, but it mutates rows at startup, needs its own
  idempotency argument (`_COLUMN_MIGRATIONS` in `backend/database.py` is a
  column list, not a data-migration framework), and misclassifying a genuine
  midnight instant would silently move a real timestamp.
- **A2 — read-side rule (recommended)**: `card_date(dt)` returns
  `dt.date()` verbatim when `dt.time() == 00:00:00` and
  `dt.microsecond == 0`, else `to_local(dt).date()`. Pure, tested,
  reversible, no writes. New writes (mark-sold submits local noon; import
  parses bare dates to local noon) mean no new artifacts are minted.

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

`tzdata` is added to `backend/requirements.txt` (see facts above). Pinning
the pip package rather than apt-installing tzdata makes dev, CI, and the
image identical — no environment-dependent zoneinfo source.

### `backend/timeutils.py`

| Helper | Contract |
| --- | --- |
| `local_tz()` | resolved `ZoneInfo`, with the fallback rule above |
| `utc_naive(dt)` | aware → convert to UTC, strip tzinfo; naive → unchanged. The API-boundary normalizer. |
| `to_local(dt)` | naive-UTC instant → aware local |
| `local_day_key(dt)` | `to_local(dt).strftime("%Y-%m-%d")` — analytics buckets |
| `card_date(dt)` | the A2 artifact rule; returns a `date` for rendering and year filters |
| `local_noon_utc(d)` | calendar date → naive-UTC instant of local noon — bare-date import writes |
| `range_start_utc(range_key, now_utc)` | `today`/`month` starts computed in local calendar space, returned as naive UTC for the `created_at >=` filter. `7d`/`30d` stay rolling `now - timedelta` windows (tz-independent, unchanged semantics). |

### Call-site changes

- `backend/routers/analytics.py:52-61,71-77` — `_range_start` becomes
  `range_start_utc`; line 100 becomes `local_day_key(ev.created_at)`.
  `since`/`until` in the response stay UTC instants (nothing renders them —
  verified against `Analytics.jsx`).
- `backend/routers/cards.py:520` — `card.sold_at =
  utc_naive(payload.sold_at) or datetime.utcnow()` (defense for non-`Z`
  offsets, per the SQLAlchemy fact).
- `backend/routers/cards.py:163-182,198,223` — `_sold_row` dates, the
  `sold_years` set, and the year filter all go through `card_date`.
- `backend/routers/cards.py:264-268,378-389` — import: bare `YYYY-MM-DD` →
  `local_noon_utc`; ISO with offset → `utc_naive`; naive ISO → unchanged
  (legacy UTC meaning preserved, so re-importing an old export is stable).
- `backend/services/google_sheets.py:86-87` — "Date Listed" renders
  `to_local(created_at).isoformat()` for real instants and the bare date for
  artifacts; "Date Sold" renders date-only via `card_date` (it is a
  calendar-date field everywhere — the picker is date-only). Value *format*
  changes inside existing columns; no column moves, so invariant #1
  (append-only `SHEET_HEADERS`) is untouched, and one press of the existing
  resync button converges the whole sheet.
- `frontend/src/pages/Inventory.jsx:27,36` — modal defaults from **browser**
  local date parts and submits **browser-local noon** as ISO. Noon tolerates
  up to ±12h of browser-vs-`CARDLISTER_TZ` disagreement before the stored
  date shifts; both users are in the configured zone. New pure helpers in
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
5. **Artifact rule false positive** — a genuine instant at exactly
   `00:00:00.000000` UTC renders verbatim. Every real writer stamps
   microseconds, so the odds are ~1 in 8.6×10¹⁰ per event; accepted and
   documented in the helper.
6. **Analytics history re-buckets** — evening scans move to the (correct)
   local day, so historical daily bars change once. Presentation-only, no
   stored data changes; called out in the changelog entry rather than
   "fixed" with a migration.
7. **Sheet/CSV round-trip drift** — export formats change while import must
   keep accepting old exports. The import branch table above is
   backward-compatible by construction and pinned by a round-trip test
   (export → import → identical stored values).

## Verification

- Unit tests for every `timeutils` helper, including both DST transitions,
  the artifact rule, invalid-tz fallback, and `+05:00` normalization.
- Endpoint tests: an event at `2026-08-22T01:30Z` buckets on `2026-08-21`
  and is excluded from "today" at `now = 2026-08-22T02:00Z`; a Dec-31-evening
  ET sale lands in the earlier tax year in both `sold-years` and the export.
- Round-trip test: sold export / Sheets row for a legacy midnight row keeps
  its calendar date; CSV export → import preserves stored values.
- Frontend vitest for `lib/dates.js` (default value, noon submit, fmtDate
  artifact + UTC rendering).
- Ship gates as always: full backend suite green, frontend build green
  (plus `conftest.py` pins `CARDLISTER_TZ` in its env block so the suite is
  deterministic on any runner).

## Cost

Zero new Anthropic calls; per-scan cost delta is $0.00. One new pure-Python
pip dependency (`tzdata`, ~430 kB wheel, no transitive deps).
