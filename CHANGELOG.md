# Changelog

All notable changes to CardLister are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com); since the app is continuously
deployed from `main` (no version tags), entries are grouped by merge date and
PR instead of version numbers.

**Convention:** work lands under `[Unreleased]` on the feature branch; the
entry moves under a dated heading when its PR merges to `main`. The changelog
as it reads **on `main` is the record of what production runs** — anything
only in `[Unreleased]` on a branch is not in prod yet.

## [Unreleased] — branch `claude/happy-ramanujan-5q3uz5`

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
