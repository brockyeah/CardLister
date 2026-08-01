# CardLister Backlog

Persistent idea ledger, maintained by the daily review routine. One line per idea;
move items to **Shipped** (with date) instead of deleting so runs don't re-propose them.

## Now / next

- [ ] Scan-accuracy report on Analytics: Corrections table already stores
      extracted-vs-corrected diffs — chart correction rate over time and
      most-corrected fields (medium; implement directly; inline; dataviz skill first)
- [ ] eBay Orders API polling → auto-mark cards sold (reuses call-up scheduler pattern; Phase 2 stub in `backend/routers/ebay.py`)
- [ ] Stale-listing reprice digest (scheduler + mailer + pricing chain all exist)
- [ ] Inventory value / P&L dashboard on Analytics (est. value, realized profit by player/brand)
- [ ] Bulk CSV **import** (Phase 2 stub; export shipped 2026-07-25)
- [ ] Sortable columns + multi-field search in Inventory: search currently matches
      player name only; no column sorting anywhere (quick win; implement directly; inline)
- [ ] Edit saved cards from Inventory: after save the only mutable field is price via
      the Comps modal — typos require delete + rescan; reuse CardForm in a modal
      (medium; implement directly; inline)
- [ ] Partial-quantity mark-sold: selling 1 of a qty-3 row currently marks the whole
      row sold; should decrement quantity and record a sold row (medium; implement
      directly — no schema change, split logic in mark_sold; inline)
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

## Later

- [ ] Validate `ebay_listing_url` server-side (require `https://` prefix) — hardening
      note from 2026-07-27 security review, below exploit threshold (quick win;
      implement directly; inline)
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
- [ ] React Router v6 → v7 migration: clears the two remaining moderate npm audit
      advisories (open redirect via backslash paths; SSR hydration — neither has a
      v6 fix). Low actual exposure: no SSR, no user-controlled link targets
      (medium; implement directly; inline)
- [ ] eBay OAuth + Sell API direct draft creation (replaces clipboard flow — see monetization notes Phase A)
- [ ] PSA/BGS grade slab detection in vision + grade-aware pricing queries
- [ ] Prospect watchlist: players whose 1st Bowmans you own, cross-referenced with news/call-ups
- [ ] Sold-comp price history per card (store lookups over time, sparkline in inventory)
- [ ] Production/multi-tenant track — see `docs/notes/2026-07-25-production-monetization.md`
- [ ] Soft-delete with undo: Delete is permanent behind a single confirm; add
      `deleted_at` + undo toast + periodic purge (medium; **plan doc first** —
      schema change; inline)
- [ ] Deep health endpoint + record prod URL: `/api/health` returns `{"ok": true}`
      without touching the DB; extend to report DB reachability, version, and poller
      heartbeat, and record the Railway production URL in docs so the daily routine
      can actually ping prod (quick win; implement directly; inline)

## Shipped

- [x] 2026-08-01 — 25 MB streamed per-file cap on `/api/scan` uploads (413 over
      limit, no partial file left behind; closes the unbounded-upload hardening
      note from the 2026-08-01 code review)
- [x] 2026-08-01 — Non-blocking dependency-audit CI job (`pip-audit` + `npm audit`
      high+) so advisories surface between Monday deep passes
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
