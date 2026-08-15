# Batch Scan Front/Back Auto-Pairing — Design

**Date:** 2026-08-15 · **Status:** Proposed (awaiting owner approval — docs-only PR, no implementation yet)

## The problem, concretely

Batch mode treats every staged image as its own card. `stageFiles` in
`frontend/src/pages/Scanner.jsx:108-121` routes any multi-file selection
straight into the queue with one item per file, and the sequential processor
(`Scanner.jsx:197-202`) calls `scanCard(file, mode)` with no back argument.
The UI says so out loud: *"Back-of-card images aren't supported in batch mode —
scan those individually"* (`Scanner.jsx:405`).

The most common capture pattern at a card table is a phone camera roll
alternating front, back, front, back. Upload those 20 photos of 10 cards today
and you get:

1. **20 card rows instead of 10** — every back becomes its own garbage
   extraction that has to be discarded by hand.
2. **20 Opus calls instead of 10** — roughly double the API spend, half of it
   on images of card backs the model was never told are backs.
3. **Lost accuracy on the 10 real cards.** The extraction prompt itself says
   the back is where the copyright year, full card number, serial numbering,
   and printed parallel/Refractor text live
   (`backend/services/claude_vision.py:386-388`, and the same instruction in
   the subscription path at `claude_vision.py:292-295`). Batch scans never get
   any of that, which feeds worse identity data into the learning loop and the
   pricing chain.

Meanwhile the single-card flow already does this right: the review stage has a
back slot (`Scanner.jsx:514-528`), `scanCard(file, preset, backFile)` posts an
optional `back` part (`frontend/src/api.js:77-85`), `POST /api/scan` saves it
and passes it through (`backend/routers/scan.py:93,107,113`), and the vision
call sends both images in one request (`claude_vision.py:384-388`). The Scan
row persists `back_image_path` (`scan.py:139-142`) and the save path carries it
onto the card. **The entire backend and API client already support paired
scans. Only batch staging never produces a pair.**

This item also subsumes the separate backlog entry "Batch-mode back images:
add a per-item back slot" — a pairing review step *is* that per-item back slot,
with the assignment proposed automatically instead of clicked together by hand.

## Approaches

### A. Client-side heuristic pairing + mandatory review step (recommended)

When 2+ images are staged, propose a pairing before anything scans:

- **Proposal heuristic:** sort by filename (camera rolls number sequentially —
  `IMG_1041.jpg`, `IMG_1042.jpg`), falling back to `file.lastModified` when
  names don't sort meaningfully. Propose adjacent pairing: (1,2), (3,4), …
  with an odd trailing image left as a single. PDFs are always singles (they
  can't be cheaply thumbnailed and the flatbed workflow doesn't alternate).
- **Review UI:** a pairing step rendered between staging and the queue — each
  proposed card shows front + back thumbnails side by side, with per-card
  **swap** (front↔back), **split** (back becomes its own single card), and a
  drag/tap-to-attach affordance to pair a single onto a card. One master
  toggle flips between "paired (adjacent)" and "all singles" so an all-fronts
  batch is one tap. A **Start scanning** button materializes the queue.
- **Queue change:** items become `{key, front, back, status, result, error}`;
  the processor downscales both (`Promise.all`, same as the single-card path
  at `Scanner.jsx:166-169`) and calls `scanCard(front, mode, back)`.

All pairing logic lives in a pure module (`frontend/src/lib/pairImages.js`)
operating on `{name, lastModified, type}` metadata — directly unit-testable
under the repo's node-only vitest setup (no jsdom needed), unlike anything
inside Scanner.jsx.

**Tradeoffs:** zero added API cost and zero backend change, but the heuristic
is order-based only — it cannot *see* that an image is a back. A user who
uploads all fronts then all backs gets a wrong proposal and must fix it in the
review step. That's acceptable because the review step is mandatory anyway: no
auto-pairing scheme should spend Opus tokens on an unconfirmed guess.

### B. Cheap vision classification pass before pairing

Add `POST /api/scan/classify` — the client sends ~256px thumbnails of the
whole batch, the server makes **one** Haiku 4.5 call ("for each image: front
or back?"), and the pairing proposal attaches each back to the nearest
preceding front. Cost is negligible (see cost section), and it fixes the
all-fronts-then-all-backs ordering that heuristics get wrong.

**Tradeoffs:** a new authenticated endpoint, a new blocking Anthropic call
that must follow the `run_in_threadpool` + positional-args pattern
(`scan.py:110-114`), a decision about the billing ladder in mock mode
(classify should degrade to "all fronts", making the feature invisible without
credentials), usage attribution (a new `UsageEvent` kind, priced fine since
`claude-haiku-4-5` is already in `MODEL_PRICES`,
`backend/routers/analytics.py:31-38`), and latency before the review step can
render. And it still requires the exact same review UI, because classification
can also be wrong — chrome card backs look front-like. So B is A plus an
endpoint, not an alternative to A.

### C. Server-side batch endpoint

Upload the whole batch to a new `POST /api/scan/batch`, pair and scan
server-side. Rejected: it moves batch state into the backend (a new table or
in-memory queue), fights the single-worker one-scan-at-a-time model the app is
built around (`CLAUDE.md` invariant 9, one uvicorn worker), duplicates the
queue UX the frontend already has, and makes the review-before-scan step *more*
awkward (images would upload before the user confirms pairing, then need
server-side reshuffling). Nothing about pairing needs to live on the server.

## Recommendation

**Approach A now; B as a later, optional escalation.** The review step is
non-negotiable under any approach, and once it exists the marginal value of
vision classification is only "fewer manual corrections when upload order is
unusual." Ship the heuristic + review UI, use it for a few real batches, and
only build B if the proposal is wrong often enough to annoy. Phase 1 touches
no backend code, no schema, no auth, and no money — the failure mode of a bad
proposal is a drag in the review UI, not a wasted scan.

## What could go wrong

- **A wrong pair that survives review** spends one Opus call on two images of
  different cards; the extraction will be confused. Mitigation: the review
  step defaults to visible thumbnails large enough to eyeball, and the scan
  result still lands in the normal review form where it can be discarded.
- **Scanner.jsx bloat.** The file is already the app's center of gravity
  (~650 lines) with a shipped race fix that new async writes must respect
  (the `pricingSeq` guard, `Scanner.jsx:126`). Mitigation: pairing state
  machine in `lib/pairImages.js`, review UI in a new
  `components/PairingReview.jsx`; Scanner only gains the wiring. Pairing
  happens strictly *before* any scan or pricing call, so it never touches the
  pricing guard — but the queue-processor edit must keep the existing
  `processingRef` single-flight guard (`Scanner.jsx:190-202`) intact.
- **Object-URL leaks.** Every staged image gets a preview URL; the review step
  multiplies how many are alive at once. The component must revoke on unmount
  and on queue materialization, same discipline as `clearStaged`
  (`Scanner.jsx:98-106`).
- **iOS filename quirks.** Shared/AirDropped images sometimes arrive with
  identical or unhelpful names and `lastModified` set to "now". The proposal
  degrades to selection order (the `FileList` order), which is still the
  camera-roll order in the common case — and the review step catches the rest.
- **Duplicate-detection interplay:** none. Pairing runs before scanning;
  save-time dup checks are unchanged.

## Cost impact (required check)

No new per-scan Anthropic calls in Phase 1 — pairing is pure client logic.
Per-card cost *shifts* because a paired scan sends a second image:

- Balance preset caps images at 1300px (`claude_vision.py:56`); a card-aspect
  image is ~1300×930 ≈ 1.2M px ≈ **~1,600 image tokens**, ~$0.008 of Opus
  input ($5/MTok, `analytics.py:33`). Cost preset (~1100px Sonnet): ~$0.003.
  Accuracy (2000px): ~$0.02.
- But the batch that motivates this — 20 images of 10 cards — currently runs
  **20 full extractions** (system prompt + cheatsheet + thinking, ~$0.05-0.06
  each on Balance ≈ ~$1.10). Paired it runs **10 extractions** with one extra
  image each (≈ ~$0.65). **The feature cuts the cost of its target workload by
  roughly 40% while fixing the output.** A batch that really is all fronts
  costs exactly what it does today.

Phase 2 (if ever built): one Haiku 4.5 call per batch over ~256px thumbnails
(~90 image tokens each; 20 images ≈ ~2k input + tiny output ≈ **well under
$0.01 per batch** at $1/$5 per MTok). Negligible, but it's a new call path and
gets its own sign-off before implementation.

## Verification

- **Unit (vitest, node env — the repo's existing frontend test shape):**
  `pairImages.test.js` covering adjacent proposal from sorted names, fallback
  to `lastModified`/selection order, odd counts, PDFs forced single, swap /
  split / attach operations, and the all-singles toggle round-trip.
- **Build gate:** `cd frontend && npm run build` green (ship gate per
  CLAUDE.md).
- **Backend suite:** `python -m pytest backend/tests -q` green — expected
  untouched in Phase 1, run anyway as the ship gate requires.
- **Manual smoke (mock mode, no API key):** stage 4 images → review proposes
  2 cards → swap one pair, split another and re-attach → Start scanning →
  both queue items scan with `back` attached (verify the multipart request
  carries a `back` part and the review form shows both images) → save →
  card row has `back_image_path`.
- **Manual negative:** stage 3 images → third stays single; stage 1 image →
  existing single-card flow unchanged; stage a PDF among images → PDF is
  never proposed as a back.
