# Feedback Features — Design (approved 2026-07-09)

Five features from user feedback (Alan G., "website questions/comments" email), approved by the owner with the following decisions: learning = cheat-sheet + exact-match (distillation deferred); batch = sequential queue; scope = all five; base = branch `feat/feedback-features` stacked on `feat/cardlister-improvements` (PR #6).

## 1. Quantity column
`cards.quantity` (int, default 1). Editable in the card form, shown in Inventory, appended as the last Google Sheet column ("Quantity"), and "Quantity available: N" added to the eBay listing description when N > 1. Because `create_all` never alters existing tables, this ships with a small idempotent startup migration helper (`ensure_columns`) that adds registered missing columns via `ALTER TABLE`. Alembic remains deferred.

## 2. Front & back scanning
The scan page gains an optional "back of card" slot alongside the front. Both images go to the vision API in a single call (two image blocks). New nullable `cards.back_image_path` column (uses the Task-1 migration helper); the review panel shows both thumbnails. Backs carry copyright year, full card number, serial numbers, and frequently the literal word "Refractor" — this is the largest accuracy lever.

## 3. Base chrome vs. refractor detection
Three levers, no new machinery: (a) expanded system-prompt guidance on refractor vs. base-chrome cues (prismatic rainbow sheen vs. plain mirror gloss; back-of-card "REFRACTOR" text; serial numbering implies a parallel; prefer `is_refractor=false` + a confidence note when uncertain); (b) per-preset image resolution — Accuracy sends ~2000px long edge, Balanced 1300, Cost 1100 — so shimmer detail survives downsampling when the user asks for accuracy; (c) synergy with feature 2.

## 4. Learning from corrections
Prompt-side learning; no fine-tuning.
- **Capture:** every real (non-mock, non-error) scan persists its raw extraction to a new `scans` table; the scan response carries `scan_id`; the frontend passes it back on save; the backend diffs extraction vs. saved values (normalized) and records non-empty diffs to a `corrections` table.
- **Cheat-sheet (generalizes):** each scan prompt gets a bounded digest (~30 most recent deduped corrections, ≤4000 chars) appended to the user message: past "you said X → correct was Y" pairs, with an explicit instruction to learn naming/numbering conventions but **never** copy parallel/serial status from them.
- **Exact-match override (repeat cards):** after extraction, if a past correction matches on normalized (brand, card number, year), overlay **identity fields only** — player, team, year, brand, set, card number, rookie — and note it in `confidence_notes`. Copy-specific fields (`parallel_color`, `serial_number`, `is_refractor`, `is_autograph`, `is_patch`, `condition`) are never overridden: the same card number exists as base, refractor, gold /50, etc.
- **Visibility:** Analytics totals gain a "corrections captured" count.
- **Deferred:** distillation of corrections into per-set rules (option B) when the digest outgrows its budget.

## 5. Batch scanning (sequential queue)
Frontend-only. The front file input accepts multiple files; >1 staged file enters batch mode: a queue panel lists each card (queued / scanning / ready / saved / error), files are scanned strictly one at a time via the existing `/api/scan`, and the user clicks any ready card to review it in the existing form (pricing fetched on selection, not during the queue run). Saving marks the item and auto-advances. No back-image support in batch v1. Backend unchanged.

## Non-goals
Stripe/billing, Alembic, model fine-tuning, correction distillation, concurrent batch scanning, per-user inventories.

## Testing
Backend: pytest (new dev dependency) — unit tests for the migration helper, sheets row builder, listing description, preset resolution, learning diff/digest/override; endpoint tests via FastAPI TestClient in mock mode. Frontend: `npm run build` gate (no JS test runner in this repo).
