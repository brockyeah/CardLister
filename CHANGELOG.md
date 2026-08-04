# Changelog

All notable changes to CardLister are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com); since the app is continuously
deployed from `main` (no version tags), entries are grouped by merge date and
PR instead of version numbers.

**Convention:** work lands under `[Unreleased]` on the feature branch; the
entry moves under a dated heading when its PR merges to `main`. The changelog
as it reads **on `main` is the record of what production runs** — anything
only in `[Unreleased]` on a branch is not in prod yet.

## 2026-08-02 — React Router v8 + React 19 (PR #28)

### Changed
- React Router v6.30 → v8.3 and React 18.3 → 19.2 (v8's peer requirement).
  Clears all three Dependabot advisories against the v6 line (open-redirect
  XSS, backslash-path bypass CVE-2025-68470, SSR deserializeErrors injection —
  none exploitable here, but unfixable on v6) and skips the 7.12–8.2 range,
  which carries an unpatched RSC-CSRF advisory. `npm audit` is now clean.
  Package moves from `react-router-dom` to `react-router` per the v7+ layout;
  no API changes were needed (BrowserRouter/Routes/Route/Navigate/NavLink/
  useNavigate/Link all unchanged). Verified: 24 frontend tests, build, and a
  live click-through of login → scan → inventory → analytics → logout.

## 2026-08-02 — Post-#24 follow-ups (PR #25)

### Fixed
- CSV import enforces sold-row consistency: a SOLD row without a Sale Price
  greater than 0 is skipped with a reason (the import path bypasses the
  mark-sold validators, so a bad row would corrupt revenue analytics), and a
  SOLD row missing Date Sold gets today's date with a warning, mirroring
  mark-sold's default.
- Orphaned-photo cleanup warns before bulk deletion: when the orphan set is
  half or more of all uploads (and at least 10 files), the confirm dialog
  explains the likely cause — cards that lost their photo links, e.g. after a
  CSV restore (the CSV carries no photo columns) — instead of presenting the
  files as safe-to-delete junk. The orphans preview endpoint now reports
  `total_files` to support this.
- Orphan grace window computed with `time.time()` instead of a naive
  `utcnow().timestamp()`, which shrank the 48h window on non-UTC hosts.
- Prospect-news article links get the same scheme guard as listing links:
  a non-http(s) `link` from an external RSS feed renders as plain text
  instead of a clickable href.

### Changed
- The CI dependency-audit job no longer exits non-zero when advisories are
  found — it emits a warning annotation and a step summary instead. The job
  never blocked merges, so its red X only taught people to ignore red.

## 2026-08-02 — One-click integration of PRs #18–#23 (PR #24)

### Added
- Bulk CSV inventory import: `POST /api/cards/import.csv` plus an "Import
  inventory CSV" button on the Analytics manage-data panel. Accepts the CSV
  export's column layout with columns matched by header name (order-independent,
  unknown columns ignored, optional Parallel / Serial # / Refractor columns
  picked up), skips bad rows individually with per-row reasons instead of
  aborting the file, and enforces the same https-only rule for eBay URLs as the
  attach-listing endpoint. Round-trips the export, so backup-restore and bulk
  hand-edited sheets both work.
- Orphaned photo cleanup: scanned photos previously stayed on the Railway
  volume forever even when the card was never saved or later deleted.
  `GET /api/analytics/uploads/orphans` previews reclaimable files (not
  referenced by any card, older than a 48-hour grace window so unsaved
  batch-queue scans survive); `POST /api/analytics/uploads/cleanup` deletes
  them behind a count-and-size confirm on the manage-data panel.
- Sortable inventory columns: every data column header (player, year, brand,
  set, card #, condition, qty, listed price, status, added) is clickable to
  sort ascending/descending, with blanks always sorted last and card numbers
  compared numerically ("BCP-9" before "BCP-100").
- Inventory search now matches across player, team, brand, set, card number,
  parallel color, notes, and year — previously player name only.
- Deep health endpoint: `GET /api/health` now pings the database, reports the
  deployed revision (Railway commit SHA), and exposes a call-up poller
  heartbeat (enabled / interval / last cycle / stale after 3 missed
  intervals). Returns 503 when the database is unreachable so plain HTTP
  uptime monitors can alert on status code alone. README gains a placeholder
  for recording the production URL so tooling can actually ping prod.
- Non-blocking `audit` job in CI: `pip-audit` over the backend requirements and
  `npm audit` (high and above) over the frontend on every PR and push to main,
  so new dependency advisories surface between Monday deep passes — the repo
  has no Dependabot. The job never blocks a merge; npm's bar is set to high
  because the two known moderate react-router advisories are already tracked
  in the backlog pending the v7 migration. On its first run the job surfaced
  ecdsa PYSEC-2026-1325 (transitive via python-jose, no fix released, ECDSA
  unused here — JWTs are HS256); that advisory is pinned as ignored with a
  backlog entry to revisit, so the job's red state stays reserved for
  genuinely new findings.

### Changed
- `ebay_listing_url` is now validated server-side: the attach-listing endpoint
  rejects anything that doesn't start with `https://` (hardening item from the
  2026-07-27 security review — the value is rendered as a clickable link). The
  Attach eBay modal validates the prefix client-side too and surfaces server
  rejections instead of failing silently (auto-review follow-up).
- Card photos are downscaled in the browser before scan upload: at most
  2000px on the long side (matching the largest server-side vision preset, so
  no scan mode loses input quality), JPEG-encoded at q0.85 with EXIF rotation
  baked in. Cuts multi-MB phone photos to a few hundred KB — faster mobile
  scans and far less Railway volume growth — with automatic fallback to the
  original file if in-browser decoding fails. PDFs pass through untouched.

### Security
- `/api/scan` uploads are now streamed to disk in 1 MB chunks with a 25 MB
  per-file cap (front and back images independently) — previously the whole
  file was read into memory with no size limit, so a single oversized upload
  could exhaust memory or fill the Railway volume. Over-cap requests get a
  `413` with a clean error message and leave no partial file behind.
  (Hardening note from the 2026-08-01 code review.)
- Stored-XSS path via listing links closed end-to-end (PR #22): `ebay_listing_url`
  is validated server-side (https-only, unified with the PR #18 rule), the
  Inventory table's link render carries a defensive scheme guard, and the Attach
  eBay modal validates client-side before submitting.

### Fixed
- `PATCH /api/cards/{id}` no longer accepts `status` — sold/active can only
  change through the mark-sold flow, so a stray PATCH can't silently flip a
  card's state (PR #22).
- Data-integrity guards: `/mark-sold` rejects `sold_price <= 0`,
  `listed_price` rejects negative values, and `quantity` must be ≥ 1 on both
  create and patch (a negative
  quantity could render "Quantity available: -3" in an eBay description and
  suppress call-up alerts by dragging the summed inventory match count to
  zero). Quantity input in the card form now enforces `min=1` too (PR #22 +
  auto-review follow-up).
- Call-up inventory matches exclude sold cards (PR #22).
- CSV import rejects negative Listed/Sale Price values (row skipped with a
  reason, like other malformed values) — the import path builds rows directly
  against the model, so it bypassed the ge=0 guards above (auto-review finding
  on this PR).

## 2026-07-28 — Lightbox, title parity tests, dependency refresh (PR #17)

### Added
- Inventory image lightbox: clicking a card's thumbnail opens a full-size
  overlay showing the front (and back, when one was scanned); Esc or a click
  anywhere closes it.
- Frontend test runner (vitest) with a shared parity table: 12 cases in
  `backend/tests/fixtures/ebay_title_cases.json` are asserted by both the
  backend (`build_title`) and the client-side title mirror (`ebayTitle.js`),
  so the live preview can no longer silently drift from the real listing
  title. CI now runs the frontend unit tests before the build.

### Changed
- Dependency refresh (Monday deep pass): all backend pins brought current —
  notably python-jose 3.5.0 and python-multipart 0.0.32 (both clear known
  CVEs), fastapi 0.140, pydantic 2.13, SQLAlchemy 2.0.51, httpx 0.28,
  Pillow 12, anthropic 0.120, pytest 9 — plus frontend vite 8 / vitest 4 /
  plugin-react 6 (clears the esbuild/vite/vitest dev-server advisories) and
  in-range minors. Remaining: two moderate react-router advisories whose only
  fix is the v7 major, deferred to the backlog (no SSR, no user-controlled
  link targets here).

## 2026-07-26 — Title preview & database backup (PR #16)

### Added
- Live eBay title preview in the card form: shows the exact title the listing
  flow will generate (client-side mirror of `build_title`) with an 80-character
  counter; anything past the cap renders struck-through in red so truncation is
  visible before saving instead of after pasting into eBay.
- One-click database backup: `GET /api/analytics/backup.db` streams a
  consistent point-in-time SQLite snapshot (`VACUUM INTO`, safe against
  concurrent writes), with a "Download database backup" button on the
  Analytics manage-data panel. Inventory, scans, and usage history all live in
  this one file on a single Railway volume, which previously had no backup
  story at all.

### Fixed
- A whitespace-only serial number no longer renders a bare `/` flag in the
  eBay title (backend now matches the preview mirror's behavior).

## 2026-07-26 — 1st Bowman follow-ups (PR #15)

### Added
- Call-up ticker shows a "1st Bowman ×N" badge when a call-up matches owned
  1st Bowman cards (`first_bowman_count` now included in `/api/news`), matching
  the email digest's behavior.

### Fixed
- eBay title flag order: `RC` now renders ahead of `1ST BOWMAN` in
  `build_title`, so the rookie flag is less likely to be dropped by the
  80-character title truncation.

## 2026-07-26 — Duplicate detection, CSV export, comps, PWA, billing fallback (PR #14)

### Added
- Duplicate detection on save: the Scanner checks for an owned (non-sold) copy of
  the same card and offers "increase your card count" instead of creating a new
  row. Identity matching is case-insensitive; parallel color, serial number, and
  print flags must match exactly so a Gold /50 never merges with a base card.
  (`POST /api/cards/check-duplicate`)
- Inventory CSV export (`GET /api/cards/export.csv` + button), same column
  layout as the Google Sheets mirror.
- Per-row "Comps" modal in Inventory: re-runs the pricing chain for a card,
  shows the delta against the listed price, and offers a one-click reprice.
- Mobile camera capture ("Take a Photo" button) and a PWA manifest + icon so
  the app installs to a phone home screen.
- `docs/BACKLOG.md` idea ledger, production/monetization strategy notes, and
  the daily-routine prompt doc.
- Subscription-billed scan fallback: when `ANTHROPIC_API_KEY` is missing or out
  of credits, scans run headlessly through the Claude Code CLI
  (`CLAUDE_CODE_OAUTH_TOKEN`) and bill the owner's Claude plan instead of
  failing; analytics prices those scans at $0. The Docker image now bundles the
  Claude Code CLI.
- Credits-exhausted alerts: out-of-credit API errors page the owner by email
  (existing mailer) and phone push (ntfy topic via `NTFY_TOPIC`), throttled to
  one alert per 6h. `POST /api/analytics/alerts/test` fires both channels on
  demand (no throttle) to verify the wiring.

### Changed
- GitHub Actions workflows (@claude assistant + auto-review) authenticate with
  `CLAUDE_CODE_OAUTH_TOKEN` (owner's Claude subscription) instead of
  `ANTHROPIC_API_KEY` pay-as-you-go credits.

## 2026-07-12 — 1st Bowman flag (PR #13)

### Added
- `is_first_bowman` flag end-to-end: vision extraction (printed "1st" logo
  only, no guessing), card form checkbox, inventory "1st" badge, `1ST BOWMAN`
  eBay title token, trailing Sheets column, and learning-system identity field.
- Call-up digest emails call out and sort first any inventory matches that are
  1st Bowman cards (`first_bowman_count` on call-up events).

### Fixed
- Sheets range end column derived from the header count so future column adds
  can't silently truncate rows.

## 2026-07-10 — News UI & email provider (PRs #11, #12)

### Added
- Newspaper-clipping styled news section below the scan area, with article
  summaries, recolored to the app's ink+emerald theme.

### Fixed
- Call-up alert emails switched to SendGrid's HTTP API (Railway blocks
  outbound SMTP); SMTP kept as the local-dev fallback.

## 2026-07-10 — Call-up alerts, prospect news, user-data admin (PR #10)

### Added
- MLB call-up detection: transaction polling, inventory matching, and an
  in-process poll scheduler (`CALLUP_POLL_MINUTES`, default 15).
- Alert email digest (never-raise mailer); digests lead with inventory matches
  and retry unsent events within a 48-hour cutoff.
- Prospect news RSS aggregation (`/api/news`) and a call-up ticker on the scan
  page.
- Analytics "Manage data" panel: merge or delete usernames, with the
  merge-target dropdown limited to configured users.

### Security
- Ghost tokens (JWTs for users no longer configured) are rejected.

## 2026-07-10 — Upload hardening & CI (PRs #8, #9)

### Added
- GitHub Actions: pytest + frontend-build CI, Claude auto-review, and the
  @claude assistant workflow.

### Security
- Served uploads restricted to safe inline image types (everything else forced
  to download with nosniff); API errors no longer leak exception text.

## 2026-07-10 — Feedback features (PR #7)

### Added
- Quantity column with an idempotent `ensure_columns` migration helper.
- Optional back-of-card image in scans (front + back in one vision call).
- Refractor-focused extraction prompt and per-preset image resolution
  (`VISION_MAX_IMAGE_PX`, `0` disables downsampling).
- Learning from corrections: cheat-sheet prompt injection plus exact-card
  identity overrides.
- Sequential batch-scan queue (multi-file staging, one scan in flight,
  auto-advance through review).
- pytest test infrastructure (`backend/tests`).

## 2026-06-22 — Improvements batch (PR #6)

### Added
- eBay API as the primary comp source when credentials are configured
  (scrapers 130point → Mavin → eBay kept as fallback).
- Multi-user auth (`CARDLISTER_USERS`) with per-user cost tracking, and the
  Analytics page (usage, tokens, estimated cost by user/model/day).
- Scan-mode presets (Cost / Balanced / Accuracy) controlling model, thinking
  effort, and image resolution.
- Production secret checks: refuses to boot with default password/JWT secret.

## 2026-06-14 — Initial release

### Added
- Core loop: photo upload → Claude vision extraction → sold-comp pricing
  (130point → Mavin → eBay scrape) → editable form → clipboard listing text +
  eBay sell page.
- SQLite inventory with mark-sold and eBay-listing attachment, Google Sheets
  write-only mirror, JWT auth, mock mode without API keys.
- Single-container Docker deploy on Railway (fixed port binding 2026-06-20).
