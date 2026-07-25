# CardLister Backlog

Persistent idea ledger, maintained by the daily review routine. One line per idea;
move items to **Shipped** (with date) instead of deleting so runs don't re-propose them.

## Now / next

- [ ] eBay Orders API polling → auto-mark cards sold (reuses call-up scheduler pattern; Phase 2 stub in `backend/routers/ebay.py`)
- [ ] Stale-listing reprice digest (scheduler + mailer + pricing chain all exist)
- [ ] Inventory value / P&L dashboard on Analytics (est. value, realized profit by player/brand)
- [ ] Bulk CSV **import** (Phase 2 stub; export shipped 2026-07-25)

## Later

- [ ] Subscription-billed scan fallback (Claude Code OAuth via `claude -p` when API credits run out) — plan approved by owner? see `docs/notes/2026-07-25-subscription-vision-fallback.md`

- [ ] eBay OAuth + Sell API direct draft creation (replaces clipboard flow — see monetization notes Phase A)
- [ ] PSA/BGS grade slab detection in vision + grade-aware pricing queries
- [ ] Prospect watchlist: players whose 1st Bowmans you own, cross-referenced with news/call-ups
- [ ] Sold-comp price history per card (store lookups over time, sparkline in inventory)
- [ ] Production/multi-tenant track — see `docs/notes/2026-07-25-production-monetization.md`

## Shipped

- [x] 2026-07-25 — Duplicate detection at save time with "increase count" confirm pop-up
- [x] 2026-07-25 — Inventory CSV export (Sheets column layout)
- [x] 2026-07-25 — Mobile camera capture + PWA manifest/icon
- [x] 2026-07-25 — Per-row "Comps" re-check modal with one-click reprice
- [x] 2026-07-10 — 1st Bowman flag end-to-end (PR #13)
- [x] 2026-07-09 — Call-up alerts, prospect news, analytics manage-data (PRs #10–#12)
- [x] 2026-07-09 — Quantity, front/back scan, refractor detection, learning, batch queue
