# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An internal tool for listing baseball cards on eBay: photo → Claude vision extracts card details → comp lookup suggests a price → review form → save copies listing text to the clipboard and mirrors the card to a Google Sheet. Two users (the owner and one other), single Railway container, SQLite.

## Commands

The venv is at the **repo root** (`.venv`). Bare `python` may not be on PATH — use `.venv/bin/python` or `python3`.

```bash
# Backend dev server — MUST run from repo root so the `backend.` import path resolves
.venv/bin/python -m uvicorn backend.main:app --reload --port 8000
# DISABLE_CALLUP_POLLER=1 silences the 15-min call-up poller locally

# Frontend dev server (proxies /api and /uploads to :8000)
cd frontend && npm run dev          # :5173

# Backend tests — all / one file / one test / one parametrized case
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pytest backend/tests/test_ebay_title_parity.py -q
.venv/bin/python -m pytest backend/tests/test_scan_endpoint.py::test_scan_accepts_optional_back_image -q
.venv/bin/python -m pytest "backend/tests/test_ebay_title_parity.py::test_build_title_matches_shared_table[serial already slashed]" -q

# Frontend tests — all / one file / one test name
cd frontend && npm test             # vitest run
cd frontend && npx vitest run src/lib/ebayTitle.test.js
cd frontend && npx vitest run -t "returns PDFs untouched"

cd frontend && npm run build        # → frontend/dist
```

Must be `python -m pytest` from the repo root — there is no `pytest.ini`/`pyproject.toml`, so bare `pytest` fails to resolve `backend.`. CI, the Dockerfile, and the local venv are all Python 3.11.

**There is no linter or formatter in this repo** (no eslint/prettier/ruff/black).

## Architecture

### Scan pipeline (`routers/scan.py` → `services/claude_vision.py`)

Three presets in `PRESETS` — `cost` (sonnet-4-6/low/1100px), `balance` (opus-4-7/medium/1300px), `accuracy` (opus-4-7/high/2000px) — arrive as a **form field** (multipart endpoint), and control model + thinking effort + image downsample cap. `resolve_preset()` never raises; unknown keys fall back to env defaults.

Billing ladder in `extract_card_from_image`, in order: API key → **subscription fallback** (headless `claude -p` CLI, requires both `CLAUDE_CODE_OAUTH_TOKEN` and the `claude` binary; also triggered when the API key exists but credits are exhausted, matched by three narrow substrings so 429s don't misfire) → mock response (`is_mock=True`) → blank card with an `error` string. The mock/error distinction is deliberate: the UI shows "set your API key" only for mock.

The 15–30s Anthropic call is sync, so `scan.py` wraps it in `run_in_threadpool` with **positional args** — argument order in `extract_card_from_image` is part of the contract. Keep this pattern for any new blocking call; there is only one worker.

### Pricing chain (`routers/pricing.py`)

Sources run **concurrently** and are resolved by walking the preference order — **eBay Browse API** (submitted only when `EBAY_APP_ID` + `EBAY_CERT_ID` are set) → 130point → Mavin → eBay HTML scrape → mock $9.99 — each returning a median of up to 10 comps. Resolution is by preference, **never** first-to-finish: a fast weak source must not beat a slow strong one. When a source succeeds, its fixed note is what the UI shows; only the final all-failed mock branch joins every attempted source's note with ` | `. `PRICING_DEADLINE_SECONDS` caps the whole lookup on our own wall clock, because a scalar `httpx` timeout applies per connect/read/write/pool rather than as a request budget.

Critical distinction: the Browse API returns **active listings (asking prices), not sales**. True sold comps need eBay's gated Marketplace Insights API. So the highest-priority source is structurally the least accurate comp type, while the scrapers return real sold prices — and the scrapers routinely 403 from a datacenter IP. Every source is written to never raise; each degrades to empty comps + a note (most return `([], None, note)`; Mavin returns a 4-tuple `(comps, price, source, note)`).

### Learning from corrections (`services/learning.py`)

Saving a card whose payload differs from its `Scan.extracted_json` writes a `Correction` row with a field-level diff. `build_cheatsheet()` runs on **every scan**, rendering the 200 most recent corrections into ≤30 dedup'd rules appended to the prompt. `find_exact_match()` additionally overlays prior corrections when brand + card # + year all match.

The load-bearing split: `IDENTITY_FIELDS` (player, year, brand, set, card #, team, rookie, 1st Bowman) may be overlaid; `COPY_SPECIFIC_FIELDS` (auto, patch, refractor, parallel color, serial) are recorded but **never** applied, because the same card number exists as base / refractor / gold /50. Both prompts explicitly tell the model not to copy those.

Note the loop is inert in mock mode — no API key means no `Scan` row, so no `scan_id`, so no corrections.

### Google Sheets mirror (`services/google_sheets.py`)

`SHEET_HEADERS` is a shared contract with three consumers: the Sheets mirror, `GET /api/cards/export.csv`, and `POST /api/cards/import.csv` (which imports the private `_card_to_row` across module boundaries). Mutating card routes queue `_sync_card_to_sheets` as a background task that takes the **card id, not the ORM object**, and opens its own session — the request session is closed by then. Sheets failures are swallowed; the mirror must never delay or break a save.

CSV export escapes formula-leading cells (`=`, `+`, `-`, `@`, and apostrophe-led variants); import unescapes so values round-trip. The Sheets mirror is exempt — it writes `valueInputOption=RAW`.

`POST /api/sheets/resync` is a **clear-then-rewrite** of the whole Inventory tab, so it is idempotent and safe to run repeatedly — that is what makes it a usable repair tool. Ordering is `created_at, id`; the `id` tiebreaker is load-bearing, since a CSV import stamps many rows in the same instant and without it two runs would assign different rows. `delete_card` **blanks** its row rather than removing it: removing a row shifts every row below it up and silently invalidates every later card's `sheets_row`. All three writers (`sync_card`, `rewrite_all_rows`, `blank_row`) serialize on a module-level `threading.Lock` and re-check their row *inside* it — dropping that guard lets a save or delete racing a resync write over another card's row.

### Canonical field values (`services/card_fields.py`)

`condition` reaches the DB from three places — the review form, vision extraction, and CSV import — and used to be free text on all three, so "NM", `"nm "`, and "Near Mint" accumulated as distinct values in the inventory, the Sheets `Condition` column, and the sold-cards tax export. `normalize_condition()` folds a *recognized spelling* to one of `CONDITION_VALUES`, and returns everything else **unchanged** — including non-strings. That pass-through is load-bearing twice over: `"-NM"` must keep its leading `-` or the CSV formula escape and the export/import round-trip both break, and `"Mint"`/`"PR"` are deliberately not folded because mapping a value onto a *different* grade restates what the seller is claiming about the card.

Applied at two seams only: the CSV importer (where other people's spellings arrive) and `CardForm`'s dropdown, which folds on receipt so a scanned "Near Mint" selects NM. **`POST /api/cards` deliberately does not fold** — that path stores strings verbatim, which is what the formula-injection tests in `test_export_csv.py` pin.

Same mirror shape as the eBay title: `frontend/src/lib/condition.js` duplicates the table, and `backend/tests/fixtures/condition_cases.json` is read by both suites so drift on a listed case fails loudly. An unrecognized value is appended to the dropdown as its own option — a `<select>` with no matching option renders the first one, which would silently rewrite a `PSA 10` card to `RAW` on the next save.

### Auth (`auth.py`)

`CARDLISTER_USERS="user:pass,user2:pass2"` parsed per-request (no caching, so env changes take effect live and removing a user invalidates their tokens immediately), falling back to a single `owner` user. HS256 JWT, 30-day TTL, `hmac.compare_digest`. `validate_secrets()` runs at startup and **refuses to boot** in production with default secrets.

`require_auth` is used two ways: as a router-level blanket guard, and as a value dependency where the username is needed for usage attribution. Deliberately public: `/api/auth/login`, `/api/health`, and all of `/api/ebay-compliance/*` (eBay's own servers call those).

### Background poller (`main.py` + `services/callups.py`)

An in-process asyncio task polls MLB transactions every `CALLUP_POLL_MINUTES`, emails one digest per batch, and stamps a heartbeat after both success and failure. `/api/health` reports it stale after 3 missed intervals, and returns **503** when the DB is unreachable so status-code-only monitors work.

### Database (`database.py`)

SQLite, no Alembic. `create_all()` only creates missing tables — it never ALTERs — so **every new column on an existing table needs an entry in `_COLUMN_MIGRATIONS`**, a hand-maintained list applied idempotently at startup. New *tables* need nothing. `uploads_dir()` is derived as `Path(DB_PATH).parent / "uploads"`, so one Railway volume at `/data` holds both the DB and every photo.

### Frontend (`frontend/src`)

**React 19 + react-router v8** — import from `'react-router'`; `react-router-dom` is not installed. Tailwind v3. Plain declarative `<Routes>`, no data-router APIs.

JWT in `localStorage`; an axios response interceptor on 401 clears it and hard-navigates to `/login`. The download endpoints (DB backup and both CSV exports) fetch as blobs and synthesize `<a download>` specifically because a plain href can't carry the Bearer header — don't "simplify" them into links.

`Scanner.jsx` is the center of gravity: a batch queue (`queued → scanning → ready → saved`) processed one item at a time behind a ref guard, front images only. Pricing lookups carry a monotonic `pricingSeq` and every write path bails if a newer lookup has started — this is a shipped race fix, so **any new async state write in Scanner needs the same guard**.

Uploads are downscaled client-side before hitting the API, with EXIF rotation baked in before re-encode; anything that fails or grows returns the original file untouched.

## Invariants that break silently

These have no compile-time or test-time guard unless noted — they fail in production or cost money.

1. **`SHEET_HEADERS` is append-only.** New columns go at the end, with a matching trailing element in `_card_to_row`. Inserting mid-list misaligns every already-synced sheet row, since `Card.sheets_row` writes a fixed bounded range. `SOLD_EXPORT_HEADERS`/`_sold_row` in `routers/cards.py` is a deliberately *separate* contract for the tax export — don't "unify" it with `SHEET_HEADERS`, or every future mirror column silently widens the tax report (the comment there says why).
2. **The `(subscription)` model suffix is load-bearing.** `analytics.py:_cost()` prices any model string *ending in* `(subscription)` at $0.00 (an `endswith` check, no leading-space requirement). Change the format the producer writes in `claude_vision.py` and subscription-billed scans start reporting phantom Opus dollars. Now pinned on both sides by `test_analytics_cost.py` and `test_vision_fallback.py`.
3. **Literal-path GET routes must be declared above `/{card_id}`** in `routers/cards.py`, or they 422 against the int path param. `export.csv` carries a comment saying so.
4. **New columns on existing tables need a `_COLUMN_MIGRATIONS` entry** — otherwise they work on a fresh DB and break every deployed one.
5. **New routers need `dependencies=[Depends(require_auth)]`** — `test_auth_sweep.py` walks the OpenAPI schema and fails CI otherwise. A genuinely public route means updating `PUBLIC`/`PUBLIC_PREFIXES` there.
6. **`VISION_MAX_IMAGE_PX=0` overrides every preset's cap** (pinned by a test), quietly multiplying token cost.
7. **Changing the eBay title format is a three-file change**: `routers/ebay.py:build_title`, `frontend/src/lib/ebayTitle.js`, and regenerated `expected` values in `backend/tests/fixtures/ebay_title_cases.json` — a fixture both suites read, the frontend one importing it across the repo boundary. Backend is the source of truth; the JS is preview-only.
8. **`MAX_DIMENSION_PX = 2000` in `downscaleImage.js` shadows the `accuracy` preset.** Raising the preset above 2000 does nothing until the client cap moves too.
9. **Never add `--workers` or a second replica** without moving the poller out of process — two pollers means duplicate call-up emails, plus a per-process health heartbeat and SQLite writers. The Sheets mirror lock (`google_sheets._sheets_lock`) is also a `threading.Lock`, atomic only inside one process — a second worker silently reopens the save-vs-resync row race it exists to close.
10. **Never add a `startCommand` to `railway.toml`** — Railway passes it literally and won't expand `$PORT`; the Dockerfile's `sh -c` does.
11. `app.mount("/", SpaStaticFiles(html=True))` is last in `main.py` and catches everything — routes registered after it are shadowed. It also serves the SPA shell for unmatched **page loads** (GET/HEAD), so a new API prefix whose first path segment isn't in `SpaStaticFiles.NON_SPA_ROOTS` (`api`, `uploads`, `assets`) returns 200 + HTML instead of 404 on a typo'd path. The match is on the whole first segment (case-folded), so both the bare root (`/api`) and every descendant (`/api/nope`) are excluded.
12. **Pricing resolution must stay preference-ordered, and its note strings are a contract.** `routers/pricing.py` fans the sources out concurrently; resolving by whoever finishes first would return a weaker comp with the wrong note and look entirely healthy. Do not introduce `concurrent.futures.wait()` before the cascade — it defaults to `ALL_COMPLETED`, which makes every lookup as slow as the slowest source. Keep the executor per-request so pools don't accumulate — but note it does not make shutdown instant: `cancel_futures` can't stop running work and the workers are non-daemon, so an abandoned source is still joined at exit. Shutdown is bounded by each source's network timeout, so those must stay bounded. A test that fakes a hanging source must release it (an `Event`, not `sleep`), or it adds that delay to every suite run — invisibly, since pytest's timer excludes the exit join. `test_pricing_chain.py` pins the order and every note string.
13. **The year-long `immutable` cache on `/uploads` and `/assets` depends on names never being reused.** Uploads are minted as `uuid.uuid4().hex` in `routers/scan.py` and Vite content-hashes bundle names — any future change that derives a filename from user input, reuses a name, or rewrites a file in place (e.g. a server-side thumbnail/re-encode pass) will serve year-stale bytes with no error anywhere. `index.html` is the deliberate exception: `SpaStaticFiles` stamps it `no-cache` so a cached shell can't outlive its bundles across a deploy.

## Testing notes

`backend/tests/conftest.py` sets env (temp `DB_PATH`, test secrets, `DISABLE_CALLUP_POLLER=1`, and **pops `ANTHROPIC_API_KEY`** so endpoint tests run in mock mode) **before any backend import**, because `database.py` binds `DB_PATH` into the engine at import time. A module-level import placed above those lines breaks the whole suite.

Use `with TestClient(app) as client:` — the context-manager form triggers the startup hook. Most endpoint tests define a local `_auth(client)` helper that logs in as `tester:pw`; there is no shared fixture. Patch *module attributes*, not bound imports (`patch.object(callups, "fetch_callup_transactions")`) — several modules import a module rather than a function specifically to stay patchable.

The `db_session` fixture hard-deletes a fixed list of models between tests; a new model needing isolation must be added to it.

Frontend tests are pure-function only (node environment, no jsdom, no testing-library). Adding a component test means adding jsdom + testing-library + a `test.environment` config first — a real decision, not a drop-in.

## Repo process

These conventions are enforced by convention, not tooling, and the daily review routine (`docs/notes/daily-routine-prompt.md`) depends on them.

- **CHANGELOG.md**: work lands under `[Unreleased]` on the feature branch and moves under a dated heading with its PR number when that PR merges. **The changelog as it reads on `main` is the record of what production runs** — read `git show origin/main:CHANGELOG.md` to know what actually shipped. Never edit dated (merged) sections. Entries are prose explaining the prior pain, tagged `(PR #N)`.
- **docs/BACKLOG.md**: persistent idea ledger, sections `Now / next` → `Later` → `Shipped`. **Move items to Shipped with a date instead of deleting** so runs don't re-propose them. Open items carry a sizing tag: `(medium; implement directly; inline)`, `(large; design first — …)`.
- **A feature without a changelog entry is not done.** Ship gates: full backend suite green, frontend build green.
- Anything touching schema, auth, money, or 3+ subsystems gets a design doc in `docs/superpowers/specs/` and a plan in `docs/superpowers/plans/` before code.
## Two agents work in this repo — stay out of each other's way

Scheduled cloud routines and interactive sessions both commit here, and they
cannot see each other's working trees. A routine's uncommitted work lives in its
own sandbox and is unreachable from a local machine, so "leave it for the owner
to push" does not work across the two.

- **Branches named `claude/*` belong to the scheduled routines.** An interactive
  session must not push to one, even to fix a real finding on its PR. Both
  pushing to one branch is how the same fix gets written twice.
- **To fix something on a routine's PR, branch off `main` instead** and open a
  separate PR, or hand the finding to the owner to relay. The exception is the
  owner explicitly saying the routine is stopped.
- **Changelog housekeeping is idempotent — check before doing it.** Dating a
  merged PR's `[Unreleased]` entries is the routine's step 11, but a conflict
  resolution may need it too. Before adding a dated heading, check whether it
  already exists on `main` or on another open branch; it has been done twice in
  one day.
- **Check `git log` on a branch before pushing to it.** A push rejected as
  non-fast-forward usually means the other agent got there first — re-read
  before re-applying, rather than force-pushing your version over theirs.

- **Never merge PRs — that is the owner's call.** Open the PR, drive it to green, respond to the Claude auto-review action's findings (it exists to give a second opinion from a clean context; don't self-review in its place).

**NOTE** Codex will review your output once you are done with any implementation. This happens outside GitHub — the owner runs Codex themselves and relays its findings back in chat. Nothing will appear on the PR, so don't wait for it, look for it in CI, or treat its absence as a pass. Expect follow-up concerns to arrive from the owner after work looks finished, and treat them as review feedback on code you already shipped.

## Other agent configs

A Codex config exists at `~/.codex/config.toml`. To import anything portable from it (MCP servers, commands, subagents, instructions), reply `/import` to scan and list what's importable, then `/import --yes=<digest>` to apply — the scan output names the digest.
