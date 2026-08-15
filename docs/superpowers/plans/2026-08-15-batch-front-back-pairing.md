# Batch Front/Back Auto-Pairing — Implementation Plan

**Design:** `docs/superpowers/specs/2026-08-15-batch-front-back-pairing-design.md`
(Approach A — client-side heuristic pairing + mandatory review step; Phase 1 is
frontend-only, no backend/schema/auth changes).

**Status: approved by owner 2026-08-15 — cleared for implementation.** Decided
defaults: multi-file batches propose adjacent pairs in front-then-back order
(matches how Alan uploads); the review step's all-singles toggle covers
all-fronts batches. The Phase 2 vision-classification assist stays parked (see
`docs/BACKLOG.md` Later).

Steps are ordered and independently testable; each lands with its validation
gate — unit tests where the repo's node-only vitest setup can reach (Step 1),
build + manual gates where it can't (Steps 2-3), ship-gate re-runs for docs
(Step 4). The
whole phase fits one PR, but every step leaves the app working if the PR is cut
there.

## Step 1 — Pure pairing module: `frontend/src/lib/pairImages.js`

The pairing state machine as pure functions over file *metadata*
(`{id, name, lastModified, type}`), never File objects, so it runs under the
repo's node-only vitest setup.

- `orderBatch(metas)` — stable ordering: numeric-aware filename sort when names
  differ meaningfully (IMG_1041 < IMG_1042 < IMG_1100), else `lastModified`,
  else input (selection) order.
- `proposePairs(metas)` — adjacent pairing over the ordered list into
  `[{front, back|null}]`; odd trailing image is a single; any PDF
  (`type === 'application/pdf'`) is never paired, as front or back.
- Operations, each returning a new pairs array: `swapPair(pairs, i)`,
  `splitPair(pairs, i)` (back becomes a trailing single), `attachBack(pairs,
  singleIndex, targetIndex)` (only onto a card with no back; rejects a PDF as
  either the source single or the target card, so the PDF-never-paired
  invariant holds across every operation, not just the proposal), `allSingles(pairs)`,
  `pairAdjacent(pairs)` (re-propose from current order).

**Test (this step):** `frontend/src/lib/pairImages.test.js` — proposal from
sorted names; lastModified fallback when names are identical; selection-order
fallback when both collide; odd count leaves a single; PDFs forced single in
every position; attachBack rejects a PDF as source and as target;
swap/split/attach round-trips; all-singles ↔ pair-adjacent
toggle is lossless on ordering. Run: `cd frontend && npx vitest run
src/lib/pairImages.test.js`.

## Step 2 — Review UI: `frontend/src/components/PairingReview.jsx`

Presentational component owning no pairing logic: props are the pairs (with
object-URL previews), and callbacks `onSwap(i)`, `onSplit(i)`,
`onAttach(singleIndex, targetIndex)`, `onAllSingles()`, `onPairAdjacent()`,
`onConfirm()`, `onCancel()`. Each proposed card renders front/back thumbnails
side by side with Swap/Split; singles render in a row below with a
tap-to-select → tap-target-card attach flow (works on mobile where drag is
unreliable; desktop drag can layer on later). Master toggle between "Paired"
and "All singles"; footer button **Start scanning (N cards)**.

**Test (this step):** no component tests by repo convention (node env only, no
jsdom — adding testing-library is an explicit non-goal here, per CLAUDE.md
testing notes). Gate: `npm run build` green with the component imported and
rendered behind a temporary storybook-less dev flag or directly in Step 3;
logic remains covered by Step 1's unit tests.

## Step 3 — Wire Scanner: stage → pairing review → queue

In `Scanner.jsx`:

- `stageFiles` (`Scanner.jsx:108-121`): multi-file selections build metadata,
  call `proposePairs`, and enter a new `pairing` state instead of creating the
  queue directly. Single-file staging is untouched.
- Confirm handler materializes the queue with items
  `{key, front, back, status: 'queued', result: null, error: null}` and
  revokes all preview URLs except those the queue rows still need; cancel
  revokes everything and returns to the drop zone.
- Sequential processor (`Scanner.jsx:190-202`): downscale front and back with
  `Promise.all` (back may be null) and call `scanCard(front, mode, back)` —
  the API client already posts the `back` part (`api.js:77-85`). The
  `processingRef` single-flight guard stays exactly as is.
- Queue rows and the review form already render `back_image_path` from the
  scan result (`Scanner.jsx:215, 549-551`) — no change needed there.
- Remove the "Back-of-card images aren't supported in batch mode" caption
  (`Scanner.jsx:405`) and update the drop-zone helper text.

**Test (this step):** full frontend suite `cd frontend && npm test` (Step 1
tests still green) + `npm run build` green. Manual smoke in mock mode (no
`ANTHROPIC_API_KEY`): 4 images → 2 proposed cards → swap/split/attach → Start
scanning → network tab shows two `/api/scan` posts each carrying a `back`
part → review form shows both images → save → row has `back_image_path`.
Negative paths: 3 images (trailing single), 1 image (legacy flow unchanged),
PDF in the batch (stays single).

## Step 4 — Process docs

- `CHANGELOG.md`: entry under `[Unreleased]` describing the prior pain
  (batch = fronts only, backs became garbage rows) per changelog convention.
- `docs/BACKLOG.md`: move "Batch scan front/back auto-pairing" to Shipped with
  date; also move "Batch-mode back images" to Shipped (subsumed — note it),
  so future runs don't re-propose it.

**Test (this step):** none (docs); ship gates re-run — full backend suite +
frontend build.

## Explicitly deferred (Phase 2 — needs its own go-ahead)

Vision classification assist (`POST /api/scan/classify`, one Haiku 4.5 call
per batch over thumbnails, <$0.01/batch): only if real-use shows the ordering
heuristic proposing wrong pairs often. It adds a backend endpoint (auth sweep
entry, threadpool pattern, mock-mode degrade to all-fronts, new `UsageEvent`
kind) and gets designed in a follow-up when justified.

## Estimated effort

Phase 1: roughly a day — ~150 lines of pure logic + tests, ~150 lines of
review UI, ~40 lines of Scanner wiring. No backend, schema, auth, or deploy
changes; no new dependencies.
