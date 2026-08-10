# CardLister Backlog

Persistent idea ledger, maintained by the daily review routine. One line per idea;
move items to **Shipped** (with date) instead of deleting so runs don't re-propose them.

## Now / next

- [ ] Batch scan front/back auto-pairing: uploading 20 images of 10 cards
      currently treats each image as its own card; match front+back pairs
      before extraction. Candidate signals: upload order/adjacency (phone
      camera rolls alternate front,back), filename timestamps, then a cheap
      vision pass ("is this a card back?") to pair each back with the
      preceding front; unpaired images fall back to single-sided scan. UI:
      pairing review step in the batch queue with drag-to-repair before
      Claude extraction runs (large; design first — touches Scanner queue,
      /api/scan, and scan cost per card)
- [ ] Comps accuracy — parallel/variant contamination: suggested price
      factors in parallel + serialized listings when pricing a base card
      (and vice versa), skewing high. Filter comp results against the
      card's own parallel_color/serial/refractor flags: exclude comps whose
      titles carry non-matching variant markers (Gold, /99, Refractor,
      Auto, etc.), require matching markers when the card HAS them, and
      surface which comps were excluded in the modal so mispricing is
      auditable (medium; implement directly — pricing chain +
      title-token filter shared across ebay_api and scrapers; needs a
      title-marker test table)
- [ ] Interactive pricing agent on the post-scan page: instead of a single
      suggested price, collect the full comp set (eBay API + scrapers, raw
      titles/prices/dates) into context and open a chat box — "my card is a
      PSA 10, what should I list at?", "now price it without parallels",
      "why is this one $40?". Agent answers from the gathered comps, can
      re-query sources with refined terms (graded, base-only), and can
      write its conclusion back into the listed-price field on request.
      Cost-aware: comps gathered once per card, cheap model for chat
      turns, usage metered into the existing UsageEvent tracking (large;
      design first — new agent loop endpoint + chat UI on review form;
      pairs with the comp variant-filter item above)
      extracted-vs-corrected diffs — chart correction rate over time and
      most-corrected fields (medium; implement directly; inline; dataviz skill first)
- [ ] eBay Orders API polling → auto-mark cards sold (reuses call-up scheduler pattern; Phase 2 stub in `backend/routers/ebay.py`)
- [ ] Stale-listing reprice digest (scheduler + mailer + pricing chain all exist)
- [ ] Inventory value / P&L dashboard on Analytics (est. value, realized profit by player/brand)
- [ ] Edit saved cards from Inventory: after save the only mutable field is price via
      the Comps modal — typos require delete + rescan; reuse CardForm in a modal
      (medium; implement directly; inline)
- [ ] Partial-quantity mark-sold: selling 1 of a qty-3 row currently marks the whole
      row sold; should decrement quantity and record a sold row (medium; implement
      directly — no schema change, split logic in mark_sold; inline)
- [ ] Row-level "Copy listing text" button: today clipboard text only comes via the
      Open eBay flow, which also opens a tab and fires an alert; add a quiet
      copy-only action reusing `getEbayListingText` (quick win; implement directly;
      inline)
- [ ] Unmark-sold (undo): mark-sold is irreversible in the UI — a misclick needs a
      manual PATCH; add an action that restores status and clears sold_price/sold_at
      (quick win; implement directly; inline)
- [ ] Re-scan in a higher mode without re-upload: extraction misses currently mean
      re-staging the photo; the file and Scan row are already on the server, so add
      `POST /api/scan/{scan_id}/rescan` with a preset param + a "Re-scan in
      Accuracy" button on the review form (medium; implement directly; inline)
- [ ] Storage usage panel on Analytics manage-data: DB file size + uploads
      count/size so Railway volume pressure is visible; pairs with orphan cleanup
      (quick win; implement directly; inline; dataviz skill first for stat tiles)
- [ ] Batch-mode back images: batch queue is front-only today (UI says "scan
      those individually"); add a per-item back slot before scanning starts
      (medium; implement directly; inline)
- [ ] Remember inventory sort choice in localStorage (builds on the 2026-07-28
      sortable columns; touches Inventory.jsx so wait for PR #18 to merge)
      (quick win; implement directly; inline)
- [ ] Parallel / Serial # / Refractor columns in CSV export + Sheets mirror: the
      row layout omits all three, so a Gold /50 is indistinguishable from base in
      the export — the 2026-07-30 importer already reads these columns when present
      (quick win; implement directly; inline — touches `google_sheets.py` row layout)
- [ ] CSV import dry-run preview: run the 2026-07-30 import parser without
      committing and show would-be created/skipped counts before the real import
      (quick win; implement directly; inline)
- [ ] Duplicate sweep over existing inventory: check-duplicate only fires at save
      time; add a "Find duplicates" tool that applies the same identity rules
      across all non-sold rows and offers merge (sum quantities, keep earliest row)
      (medium; implement directly — no schema change; inline)
- [ ] Scan history browser: the Scans table keeps every real extraction + photos,
      but nothing surfaces them — list past scans and allow saving one that was
      never saved as a card (medium; implement directly; inline; UI as its own
      panel so it doesn't collide with Scanner.jsx changes in PR #19)
- [ ] Weekly inventory digest email: Sunday summary via the existing mailer —
      cards added, scans + est. API cost, actives missing a listing URL, stale
      actives (medium; **plan doc first** — touches 3 subsystems: scheduler,
      mailer, analytics queries; inline)
- [ ] Sheets drift detector on Analytics manage-data: on-demand compare of the
      Sheets mirror vs DB (row count + per-card diff), showing mismatches next
      to the existing one-click full resync — today drift is invisible until
      someone eyeballs the sheet; `resync` endpoints already exist in
      `backend/routers/sheets.py` (medium; implement directly; inline)
- [ ] Bulk row selection in Inventory: checkbox column + bulk mark-sold /
      delete / copy-listing-text over the selection; today every action is
      one row at a time, which hurts at 100+ cards (medium; implement
      directly; inline — builds on CardTable.jsx after PR #18 lands)
- [ ] Photo backup zip: the SQLite snapshot backs up the database only — card
      photos on the Railway volume still have no backup story; add
      `GET /api/analytics/backup-photos.zip` streaming all card-referenced
      uploads (medium; implement directly; inline)
- [ ] Server-side thumbnails: the inventory table's `<img>` cells load the
      original scan photos; generate a ~256px thumbnail at upload time (Pillow
      already a dependency) and serve that in `CardTable`, keeping the original
      for the lightbox (medium; implement directly; inline — touches CardTable,
      wait for the open PR queue to land)
- [ ] Magic-byte validation of scan uploads: today only the file extension is
      checked; verify image content with Pillow (and `%PDF-` header for PDFs)
      before storing, so mislabeled non-image content is never stored and
      re-served from `/uploads` (quick win; implement directly; inline)
- [ ] Router-wide auth sweep test: parametrized test walking `app.routes` and
      asserting every `/api` route except login and health returns 401 without
      a token — guards a future router forgetting `Depends(require_auth)`
      (quick win; implement directly; inline; test-only)
- [ ] Backend error visibility: unhandled 500s only live in Railway logs; add
      exception middleware that records recent errors to a small table with a
      "recent errors" readout on Analytics manage-data, reusing the ntfy push
      for spikes (medium; **plan doc first** — new table/schema; inline)
- [ ] eBay fee + net-proceeds estimate: show the final-value fee (env-configurable
      rate, default ~13.25% + $0.30) and net proceeds next to the price in the
      Comps modal and mark-sold dialog — pricing today shows gross only, so
      thin-margin cards look better than they are (quick win; implement directly —
      display-only math, no schema; inline)
- [ ] Condition dropdown with canonical values: `condition` is a free-text input
      (defaults "NM"), so typos like "nm "/"Near Mint" fragment the data; replace
      with a select (RAW, GEM-MT, NM-MT, NM, EX, VG, POOR) and normalize known
      variants on CSV import (quick win; implement directly; inline — touches
      CardForm.jsx, land after the open PR queue clears)
- [ ] Scanner batch-review keyboard shortcuts: Enter = save & advance, ←/→ move
      through the queue — batch review is the highest-repetition flow in the app
      and is entirely mouse-driven today (quick win–medium; implement directly;
      inline — touches Scanner.jsx, land after the open PR queue clears)
- [ ] Monthly scan-cost budget alert: usage table already tracks est. cost per
      scan; add an env-configurable monthly cap with an Analytics banner and the
      existing ntfy push when 80% / 100% is crossed, checked in the poll cycle
      (medium; implement directly — reuses usage table + alerts, no schema; inline)
- [ ] Sold-cards tax-year CSV export: `GET /api/cards/export-sold.csv?year=` with
      sold date/price columns for tax reporting — sold data and the CSV writer
      both exist, but sold rows only export mixed into the full inventory dump
      (quick win; implement directly; inline)

## Later

- [ ] Scanner batch-review race: `fetchPricing` in Scanner.jsx isn't cancelled when
      the user switches queue items quickly, so a slow response for item A can land
      after item B is opened and silently overwrite B's comps/suggested price with
      A's — needs a request-id or AbortController guard (quick win–medium; implement
      directly; inline)
- [ ] Login rate limiting on `/api/auth/login`: sliding window per IP+username —
      currently unlimited attempts (quick win–medium; **plan doc first** — touches
      auth; inline)
- [ ] Early request-body size reject on `/api/scan`: the 25 MB per-file cap
      (2026-08-01) stops oversized files landing in `uploads/`, but Starlette's
      multipart parser still receives/spools the whole request body before the
      cap fires — reject early on the `Content-Length` header (or add an
      ASGI-level body limit) so an oversized request is refused before upload
      completes (quick win; implement directly; inline — auto-review note on
      PR #23)
- [ ] ecdsa PYSEC-2026-1325 (transitive via python-jose, surfaced by the CI
      audit job on its first run 2026-08-01): no fixed ecdsa release exists;
      ignored in the pip-audit step since JWTs here are HS256 (ECDSA paths
      unused). Revisit when a fix ships — or swap python-jose for PyJWT, which
      drops the ecdsa dependency entirely (quick win–medium; implement
      directly; inline — touches auth)
- [x] 2026-08-02 — React Router v6 → v8 migration (with React 19): went past v7
      because 7.12.0–8.2.0 carries an unpatched RSC-CSRF advisory; 8.3.0 clears
      every react-router advisory (npm audit: 0 vulnerabilities). React 19 was
      required by v8's peer range.
- [ ] eBay OAuth + Sell API direct draft creation (replaces clipboard flow — see monetization notes Phase A)
- [ ] PSA/BGS grade slab detection in vision + grade-aware pricing queries
- [ ] Prospect watchlist: players whose 1st Bowmans you own, cross-referenced with news/call-ups
- [ ] Sold-comp price history per card (store lookups over time, sparkline in inventory)
- [ ] Production/multi-tenant track — see `docs/notes/2026-07-25-production-monetization.md`
- [ ] Soft-delete with undo: Delete is permanent behind a single confirm; add
      `deleted_at` + undo toast + periodic purge (medium; **plan doc first** —
      schema change; inline)
- [ ] Nightly automated backup delivery: email the SQLite snapshot (or push it to
      Drive) on a schedule — backup endpoint, scheduler, and mailer all exist
      (medium; **plan doc first** — touches 3 subsystems: scheduler, mailer,
      backup service; inline)
- [ ] Cost basis (`purchase_price`) field on cards: record what was paid so the
      planned P&L dashboard can show true realized profit instead of revenue only
      (medium; **plan doc first** — schema change; inline)
- [ ] Record the Railway production URL in README (owner input needed — the
      README now has a placeholder next to the deploy steps; the deep health
      endpoint shipped 2026-07-29)
- [ ] Pricing-source telemetry: the comps chain silently falls through five
      sources to a $9.99 mock, so a blocked scraper looks like "pricing works
      but is weird" — log source/hit/latency per lookup and chart hit rates on
      Analytics, with a callout when mock share spikes (medium; **plan doc
      first** — new table/schema; inline; dataviz skill for the panel)
- [ ] Playwright E2E smoke in CI: login → scan (mocked vision) → save →
      inventory round-trip against a real dev server; unit suites can't catch
      broken page wiring like a bad api.js import (medium; implement directly;
      inline)
- [ ] Escape leading `=` `+` `-` `@` in CSV export cells (prefix `'`): formula
      injection hardening note from the 2026-07-30 security review — import now
      ingests third-party files, so a crafted Notes cell round-trips into an
      Excel-interpretable formula on export; Sheets mirror unaffected (RAW input)
      (quick win; implement directly; inline)

## Shipped

- [x] 2026-08-01 — 25 MB streamed per-file cap on `/api/scan` uploads (413 over
      limit, no partial file left behind; closes the unbounded-upload hardening
      note from the 2026-08-01 code review)
- [x] 2026-08-01 — Non-blocking dependency-audit CI job (`pip-audit` + `npm audit`
      high+) so advisories surface between Monday deep passes
- [x] 2026-08-01 — Code review: eBay listing URL http(s)-only validation (server +
      client + defensive render guard) — closed a stored-XSS/token-theft path via
      `javascript:` URLs; PATCH no longer accepts `status` directly; mark-sold and
      listed-price now reject non-positive values; call-up matches exclude sold cards

- [x] 2026-07-30 — Bulk CSV inventory import (export layout round-trip, header-name
      column mapping, per-row skip reasons, https-only eBay URLs)
- [x] 2026-07-30 — Orphaned photo cleanup with preview + confirm on Analytics
      manage-data (unreferenced by any card, 48h grace window)

- [x] 2026-07-29 — Deep `/api/health` (DB ping, revision, poller heartbeat, 503 on DB failure)
- [x] 2026-07-29 — Client-side photo downscale to ≤2000px before scan upload (server's largest preset — no accuracy loss; faster mobile uploads, smaller volume)
- [x] 2026-07-28 — Sortable inventory columns + multi-field search (player, team, brand, set, card #, parallel, notes, year)
- [x] 2026-07-28 — Server-side https-only validation of `ebay_listing_url` (2026-07-27 security-review hardening note)
- [x] 2026-07-27 — Inventory image lightbox (front/back full-size overlay)
- [x] 2026-07-27 — Vitest + shared JSON parity table for the eBay title mirror; CI runs frontend tests

- [x] 2026-07-26 — One-click SQLite backup download (VACUUM INTO snapshot) on Analytics
- [x] 2026-07-26 — Live eBay title preview with 80-char truncation warning in the card form
- [x] 2026-07-25 — Subscription-billed scan fallback + credits-exhausted alerts (email + ntfy phone push); Actions workflows moved to subscription auth
- [x] 2026-07-25 — Duplicate detection at save time with "increase count" confirm pop-up
- [x] 2026-07-25 — Inventory CSV export (Sheets column layout)
- [x] 2026-07-25 — Mobile camera capture + PWA manifest/icon
- [x] 2026-07-25 — Per-row "Comps" re-check modal with one-click reprice
- [x] 2026-07-10 — 1st Bowman flag end-to-end (PR #13)
- [x] 2026-07-09 — Call-up alerts, prospect news, analytics manage-data (PRs #10–#12)
- [x] 2026-07-09 — Quantity, front/back scan, refractor detection, learning, batch queue
