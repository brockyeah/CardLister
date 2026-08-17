# CardLister Backlog

Persistent idea ledger, maintained by the daily review routine. One line per idea;
move items to **Shipped** (with date) instead of deleting so runs don't re-propose them.

## Now / next

- [ ] eBay deletion-notice signature verification: the account-deletion
      endpoint acks any POST — eBay signs notices with `X-EBAY-SIGNATURE`
      (ECDSA, public key from the Notification API) and the handler never
      checks it, so the log it keeps as the future audit trail is forgeable by
      anyone with the URL. Harmless while nothing is stored, but a **hard
      prerequisite** of the draft-listing/OAuth feature: once seller tokens
      exist, an unverified notice becomes an unauthenticated "delete this
      user's tokens" request (medium; **design first** — key fetch + cache +
      verify, still 2xx on failure per eBay retry semantics; found by the
      2026-08-16 weekly deep review)
- [ ] SPA mount wiring test: `test_spa_fallback.py` exercises `SpaStaticFiles`
      on a throwaway app over a temp dir, and `backend/static` doesn't exist
      in CI — so reverting `main.py`'s mount to plain `StaticFiles(html=True)`
      passes the whole suite. Cleanest fix is an app-factory refactor so a
      test can build the app with a temp static dir; note the prefix check
      also runs on the normalized path, so raw `/api/..`-style requests get
      the shell (cosmetic — browsers normalize before sending) (medium;
      implement directly; inline — found by the 2026-08-16 weekly deep review)
- [ ] Batch scan front/back auto-pairing: uploading 20 images of 10 cards
      currently treats each image as its own card; match front+back pairs
      before extraction. Candidate signals: upload order/adjacency (phone
      camera rolls alternate front,back), filename timestamps, then a cheap
      vision pass ("is this a card back?") to pair each back with the
      preceding front; unpaired images fall back to single-sided scan. UI:
      pairing review step in the batch queue with drag-to-repair before
      Claude extraction runs (large; design first — touches Scanner queue,
      /api/scan, and scan cost per card) — **design + plan written 2026-08-15**
      (`docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`,
      `docs/superpowers/plans/2026-08-15-batch-front-back-pairing.md`):
      Phase 1 is frontend-only (heuristic pairing + review step, $0 added
      cost, ~40% cheaper on the target workload). **Approved by owner
      2026-08-15 — Approach A, pairs proposed by default in front-then-back
      order; cleared for implementation per the plan doc.** Subsumes the
      "Batch-mode back images" item below.
- [ ] Comps accuracy — parallel/variant contamination: suggested price
      factors in parallel + serialized listings when pricing a base card
      (and vice versa), skewing high, and it's worst on exactly the cards
      worth the most. Two halves of one fix: (a) plumb the attributes
      through — `PricingRequest` carries only player/year/brand/set/card #,
      so parallel color, serial number, refractor, and auto never reach the
      pricing chain at all (schemas, pricing router, service query builders,
      CompsModal/Scanner callers); (b) filter results against the card's own
      parallel_color/serial/refractor flags — exclude comps whose titles
      carry non-matching variant markers (Gold, /99, Refractor, Auto, etc.),
      require matching markers when the card HAS them, and surface which
      comps were excluded in the modal so mispricing is auditable (medium;
      implement directly — title-token filter shared across ebay_api and
      scrapers; needs a title-marker test table)
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
- [ ] Scan-accuracy report on Analytics: Corrections table already stores
      extracted-vs-corrected diffs — chart correction rate over time and
      most-corrected fields (medium; implement directly; inline; dataviz skill first)
- [ ] eBay Orders API polling → auto-mark cards sold (reuses call-up scheduler
      pattern; Phase 2 stub in `backend/routers/ebay.py`) (large; design first —
      needs eBay OAuth + a second poller concern, see invariant #9)
- [ ] Stale-listing reprice digest (scheduler + mailer + pricing chain all
      exist) (medium; implement directly; inline)
- [ ] Inventory value / P&L dashboard on Analytics (est. value, realized profit
      by player/brand) (medium; implement directly; inline; dataviz skill first)
- [ ] Edit saved cards from Inventory: after save the only mutable field is price via
      the Comps modal — typos require delete + rescan; reuse CardForm in a modal
      (medium; implement directly; inline)
- [ ] Partial-quantity mark-sold: selling 1 of a qty-3 row currently marks the whole
      row sold; should decrement quantity and record a sold row (medium; implement
      directly — no schema change, split logic in mark_sold; inline)
- [ ] Days-to-sell analytics: avg/median `created_at → sold_at` interval plus a
      distribution view on Analytics, so pricing strategy gets feedback ("Bowman
      autos sell in 4 days, base sits for 60") (medium; implement directly;
      inline; dataviz skill first)
- [ ] CSV import duplicate handling: import blindly creates rows even when an
      identical non-sold card exists — reuse the check-duplicate identity rules
      per row to warn (or opt-in merge quantities), preventing double-ups on
      re-import of an edited export (medium; implement directly; inline —
      builds on the import parser + `check_duplicate` matcher)
- [ ] Re-scan in a higher mode without re-upload: extraction misses currently mean
      re-staging the photo; the file and Scan row are already on the server, so add
      `POST /api/scan/{scan_id}/rescan` with a preset param + a "Re-scan in
      Accuracy" button on the review form (medium; implement directly; inline)
- [ ] Batch-mode back images: batch queue is front-only today (UI says "scan
      those individually"); add a per-item back slot before scanning starts
      (medium; implement directly; inline) — **do not implement separately:
      subsumed by the batch front/back auto-pairing design above**
      (`docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`);
      its review step is the per-item back slot
- [ ] Remember inventory sort choice in localStorage (builds on the 2026-07-28
      sortable columns; touches Inventory.jsx) (quick win; implement directly;
      inline)
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
      panel so it doesn't collide with in-flight Scanner.jsx work)
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
      directly; inline — builds on CardTable.jsx)
- [ ] Photo backup zip: the SQLite snapshot backs up the database only — card
      photos on the Railway volume still have no backup story; add
      `GET /api/analytics/backup-photos.zip` streaming all card-referenced
      uploads (medium; implement directly; inline)
- [ ] Server-side thumbnails: the inventory table's `<img>` cells load the
      original scan photos; generate a ~256px thumbnail at upload time (Pillow
      already a dependency) and serve that in `CardTable`, keeping the original
      for the lightbox (medium; implement directly; inline — touches CardTable;
      NOTE: thumbnails must be new files, never in-place rewrites — invariant
      #12, /uploads is cached immutable)
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
      CardForm.jsx)
- [ ] Scanner batch-review keyboard shortcuts: Enter = save & advance, ←/→ move
      through the queue — batch review is the highest-repetition flow in the app
      and is entirely mouse-driven today (quick win–medium; implement directly;
      inline — touches Scanner.jsx)
- [ ] Monthly scan-cost budget alert: usage table already tracks est. cost per
      scan; add an env-configurable monthly cap with an Analytics banner and the
      existing ntfy push when 80% / 100% is crossed, checked in the poll cycle
      (medium; implement directly — reuses usage table + alerts, no schema; inline)
- [ ] Sold-cards tax-year CSV export: `GET /api/cards/export-sold.csv?year=` with
      sold date/price columns for tax reporting — sold data and the CSV writer
      both exist, but sold rows only export mixed into the full inventory dump
      (quick win; implement directly; inline)
- [ ] Card permalink deep link: `/inventory?card=123` scrolls to and highlights
      the row (clearing the search/filters if they hide it) — the QR-labels
      item below explicitly needs a permalink first, and shared links/bookmarks
      get it for free (quick win; implement directly; inline — touches
      Inventory.jsx only)
- [ ] Player-name autocomplete in CardForm: a `<datalist>` fed from existing
      inventory player names, so repeat players are picked instead of retyped —
      free-text typos ("Jackson Holiday") fragment search and the planned
      per-player analytics (quick win; implement directly; inline — CardForm.jsx
      plus a tiny names endpoint or reuse of the already-loaded card list)
- [ ] Backup-staleness nudge on Analytics manage-data: remember the last
      "Download database backup" click (localStorage) and show a banner when
      it's older than 14 days — the backup story is entirely manual until the
      plan-doc-gated nightly delivery ships, and nothing reminds anyone today
      (quick win; implement directly; inline — Analytics.jsx only)
- [ ] Call-up poller stale push alert: `/api/health` already computes poller
      staleness (3 missed intervals) but only reports it to whoever looks; fire
      the existing ntfy push (billing_alerts) once per stale episode from the
      poll-cycle watchdog so a silently dead poller gets noticed — prospects
      can get called up during the outage (medium; implement directly — reuses
      `_poller_state` + ntfy, no schema; inline)
- [ ] eBay Seller Hub bulk-listing CSV export: export active cards in eBay's
      bulk-upload template (title from `build_title`, price, condition,
      category) so a batch of drafts can be created in one Seller Hub upload —
      a no-OAuth stepping stone to the Sell API item in Later (medium;
      implement directly; inline — new endpoint beside `export.csv`)
- [ ] Inventory pagination / windowed rendering: `GET /api/cards` returns every
      row and CardTable renders them all — payload and DOM both grow unbounded
      with the collection; add `limit`/`offset` (or cursor) + a "load more" or
      windowing on the table (medium; implement directly; inline — touches
      Inventory.jsx)
- [ ] Scanner drag-and-drop + paste-from-clipboard upload: staging photos is
      file-picker/camera only; accept dropped files on the stage area and
      Ctrl+V image paste for desktop workflows (quick win; implement directly;
      inline — Scanner.jsx only, no open-PR overlap)
- [ ] Inventory filter chips: status / RC / Auto / 1st Bowman / Refractor
      toggle filters next to the existing search box — search can't express
      "all my active autos" today (quick win; implement directly; inline —
      touches Inventory.jsx + CardTable.jsx)
- [ ] QR labels for physical storage: print a sheet of QR codes (selected rows
      or a filter) that deep-link back to the card in Inventory, so a physical
      box/toploader can be matched to its row; needs a card permalink/filter
      param first (medium; implement directly; inline)
- [ ] Sheets sync failure visibility: `_sync_card_to_sheets` runs as a
      fire-and-forget background task, so a dead Google credential or quota
      error means the mirror silently drifts forever; add bounded retries plus
      an in-memory "last sync error" readout on manage-data — push-side
      complement to the on-demand drift detector above (medium; implement
      directly — no schema, in-memory state only; inline)
- [ ] "See sold comps on eBay" deep link: build the eBay sold/completed search
      URL from player/year/brand/set/card # next to the suggested price in the
      Scanner pricing panel and the Comps modal — a zero-API sanity check on
      the five-source pricing chain, especially when it quietly falls back to
      mock (quick win; implement directly; inline — touches Scanner.jsx +
      Inventory comps modal)
- [ ] Scan preset refresh to the current model lineup: PRESETS pin Sonnet 4.6 /
      Opus 4.7 and the Scanner mode cards hardcode the same names — evaluate
      newer models (e.g. Haiku 4.5 for Cost, current Sonnet/Opus for
      Balanced/Accuracy) on a sample of corrected scans before switching, and
      update analytics MODEL_PRICES + Scanner labels in the same change
      (medium; implement directly, gated on a small accuracy eval; inline —
      touches claude_vision.py, analytics.py, Scanner.jsx)
- [ ] Research cheaper extraction paths than Claude vision: vision is the only
      per-card cost that scales with the collection, and the preset item above
      only shops within the Claude lineup. Survey the alternatives on the same
      corrected-scan sample — cheaper vision models from other providers, plain
      OCR (Tesseract/PaddleOCR, or a cloud OCR) feeding a *text*-only model,
      card-database lookup by set + card # (TCDB/Sportlots/Beckett) with vision
      reduced to reading the number off the card, and a local model on the
      Railway container. Score each on per-card cost, accuracy vs. the
      Corrections table, latency, and setup burden; a hybrid is the likely
      answer (cheap path first, escalate to Claude when confidence is low or
      the user hits Re-scan). Output is a findings note in `docs/notes/`, not
      code (medium; research spike — write the note before any implementation
      item is opened; pairs with the preset-refresh item above)

## Later

- [ ] Batch-pairing vision assist (rainy-day; explicitly deferred by owner
      2026-08-15): one cheap Haiku call per batch classifying thumbnails as
      front/back to improve the pairing proposal — Approach B in
      `docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`,
      <$0.01 per batch. Only worth building if the shipped order-based
      heuristic proposes wrong pairs often in real use; needs its own design
      pass (new authenticated endpoint, threadpool pattern, mock-mode
      degrade, new UsageEvent kind) (medium; **plan doc first** — new
      Anthropic call path; inline)
- [ ] Offline scan queue (PWA): stage photos while offline (IndexedDB) and
      auto-upload when connectivity returns — card shows and garage sales have
      bad signal, and the PWA manifest already exists (long-term; **plan doc
      first** — service worker, upload queue, and Scanner UI; inline)
- [ ] Inventory mutation audit trail: multi-user households share one
      inventory, but deletes / mark-solds / imports are anonymous today; add a
      small `audit_events` table (who, what, when) with a recent-activity
      readout on manage-data (medium; **plan doc first** — new table/schema;
      inline)
- [ ] Login rate limiting on `/api/auth/login`: sliding window per IP+username —
      currently unlimited attempts (quick win–medium; **plan doc first** — touches
      auth; inline). Same pass should cap the request body: login shares the
      unbounded-buffer exposure the compliance endpoint closed 2026-08-16
      (pydantic buffers the whole body before validating).
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
- [ ] eBay OAuth + Sell API direct draft creation (replaces clipboard flow — see
      monetization notes Phase A) (large; design first — prerequisites: the
      deletion-notice signature verification item in Now/next, and note the
      `oauth/accepted` landing receives `?code=…` which lands in access logs
      today; the token exchange must address that) (2026-08-16 weekly review)
- [ ] PSA/BGS grade slab detection in vision + grade-aware pricing queries
      (large; design first — touches vision prompts + pricing chain)
- [ ] Prospect watchlist: players whose 1st Bowmans you own, cross-referenced
      with news/call-ups (medium; implement directly; inline)
- [ ] Sold-comp price history per card (store lookups over time, sparkline in
      inventory) (large; design first — new table/schema)
- [ ] Production/multi-tenant track — see
      `docs/notes/2026-07-25-production-monetization.md` (large; design first)
- [ ] Auth on `/uploads` photo serving: `/uploads/{filename}` is deliberately
      unauthenticated and relies on unguessable uuid names (capability URLs) —
      a leaked URL (browser history, pasted link) exposes the photo forever,
      and `<img>` tags can't carry the Bearer token; needs short-lived signed
      URLs or a cookie-scheme decision (medium; **plan doc first** — touches
      auth; inline)
- [ ] Restore-from-snapshot: backup download exists but there is no restore
      path — recovering a Railway volume means manual SQLite surgery; add an
      upload-snapshot flow with integrity check (`PRAGMA integrity_check` +
      expected schema) and a pre-restore safety copy (medium; **plan doc
      first** — destructive, replaces the live DB; inline)
- [ ] Soft-delete with undo: Delete is permanent behind a single confirm; add
      `deleted_at` + undo toast + periodic purge (medium; **plan doc first** —
      schema change; inline)
- [ ] Unmark-sold restores CSV-imported "unlisted" cards to "active" (PR #29
      auto-review note): a correct restore needs a `previous_status` column set
      by mark-sold — the no-schema heuristic (unlisted iff no listing attached)
      would wrongly demote saved-but-unattached active cards; fold into the
      same schema pass as soft-delete (quick win once the column exists;
      **plan doc first** — schema change; inline)
- [ ] Nightly automated backup delivery: email the SQLite snapshot (or push it to
      Drive) on a schedule — backup endpoint, scheduler, and mailer all exist
      (medium; **plan doc first** — touches 3 subsystems: scheduler, mailer,
      backup service; inline)
- [ ] Cost basis (`purchase_price`) field on cards: record what was paid so the
      planned P&L dashboard can show true realized profit instead of revenue only
      (medium; **plan doc first** — schema change; inline)
- [ ] Pricing-source telemetry: the comps chain silently falls through five
      sources to a $9.99 mock, so a blocked scraper looks like "pricing works
      but is weird" — log source/hit/latency per lookup and chart hit rates on
      Analytics, with a callout when mock share spikes (medium; **plan doc
      first** — new table/schema; inline; dataviz skill for the panel)
- [ ] Playwright E2E smoke in CI: login → scan (mocked vision) → save →
      inventory round-trip against a real dev server; unit suites can't catch
      broken page wiring like a bad api.js import (medium; implement directly;
      inline)
- [ ] Tailwind CSS 3.4 → 4.x migration: surfaced by the 2026-08-03 Monday
      dependency pass (only major-version drift left; npm/pip audits clean) —
      v4 changes the config/PostCSS pipeline, so defer until a quiet window
      (medium; implement directly; inline)

## Shipped

- [x] 2026-08-17 — HEAD support on `/api/health` and `/uploads/{filename}`:
      `@app.get` registers GET only, so HEAD probes fell through to the static
      mount and 404'd whether the app was healthy or not, defeating the deep
      health check's 503 for the status-code-only monitors that default to HEAD
- [x] 2026-08-17 — Filter-aware inventory stat tiles: totals describe the rows
      the table is showing, with an "of N overall" caption on every narrowed
      tile and a badge naming the matching row count
- [x] 2026-08-17 — CI fail-open guards dropped: backend and frontend test steps
      run unconditionally, so a moved test directory or a renamed test file
      can't skip a whole suite while the job stays green

- [x] 2026-08-16 — Cache headers for the built frontend: `index.html` is
      `no-cache` (a cached shell could outlive its bundles across a deploy and
      white-screen), Vite's content-hashed `/assets/*` bundles are immutable
      like `/uploads` (weekly deep review PR)
- [x] 2026-08-16 — Railway production URL recorded in README (was a
      placeholder; the daily-routine doc already pinged it)

- [x] 2026-08-14 — SPA deep-link fallback: hard loads of /inventory, /analytics
      and friends served the app shell instead of a 404, with `api/`,
      `uploads/`, and `assets/` prefixes keeping their real 404s
- [x] 2026-08-14 — Quantity-aware inventory stats: Total Cards / Listed / Sold
      count copies and Est. Active Value multiplies by quantity, with a
      "N rows" caption when rows and copies differ (revenue stays per-row)
- [x] 2026-08-14 — Immutable cache headers on `/uploads` (uuid-hex names never
      change content, so `public, max-age=31536000, immutable`)

- [x] 2026-08-06 — Storage usage tiles on Analytics manage-data: DB file size +
      photo count/bytes via `GET /api/analytics/storage`, refreshed after
      import/cleanup
- [x] 2026-08-06 — Scanner pricing race fix: comps lookups carry a monotonic id
      so a stale response can't overwrite the currently reviewed card's
      comps/suggested price (was listed under Later as "Scanner batch-review
      race")

- [x] 2026-08-05 — Parallel / Serial # / Refractor columns in CSV export +
      Sheets mirror (appended after 1st Bowman; importer already read them,
      so the round-trip now preserves all three)
- [x] 2026-08-05 — CSV formula-injection escaping on export (leading `'` for
      `=` `+` `-` `@` cells, stripped back out on import; Sheets mirror
      unaffected — RAW input)

- [x] 2026-08-04 — Magic-byte validation of scan uploads (415 on unrecognized
      content before write; stored suffix derived from sniffed content, not the
      client filename)
- [x] 2026-08-04 — Router-wide auth sweep test: every `/api` route except
      login/health must 401 without a token (walks the OpenAPI schema, with a
      self-check that the sweep is non-empty)

- [x] 2026-08-03 — Unmark-sold undo: `POST /api/cards/{id}/unmark-sold` restores
      status to active and clears sold_price/sold_at, with confirm-gated
      "Unmark Sold" button on sold rows
- [x] 2026-08-03 — Row-level "Copy Text" button: quiet clipboard-only listing
      text on non-sold rows (transient Copied ✓, prompt fallback)

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
