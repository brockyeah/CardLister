# Google Sheets Mirror Integrity — Design

**Status:** proposed, awaiting owner approval
**Filed:** 2026-08-17 (daily review run; all three defects verified against the code)
**Scope:** `backend/services/google_sheets.py`, `backend/routers/sheets.py`,
`backend/routers/cards.py` (delete path only)

## The problem, concretely

Three defects compound into one failure: the mirror drifts permanently, and the
tool provided to repair it makes the drift worse.

**1. Deletes never reach the mirror.** `delete_card` (`routers/cards.py:341`) is
the only mutating card route with no `_sync_card_to_sheets` background task and
no Sheets call of any kind. Create, update, attach-listing, mark-sold, and
unmark-sold all queue one. So a deleted card's row survives in the sheet
forever — the mirror keeps advertising a card that no longer exists, and nothing
in the app will ever remove it.

**2. The repair tool duplicates the entire inventory.** `resync_all`
(`routers/sheets.py:13`) sets `card.sheets_row = None` for every card and then
calls `sync_card`. In `sync_card` (`services/google_sheets.py:141`) a falsy
`sheets_row` selects the **append** branch, not update. So the "push every card
to the Sheet" button adds a complete second copy of the collection on every
run — and a third on the next. This is the button the UI offers when the sheet
looks wrong, which is exactly when it will be pressed.

**3. Imported cards are never mirrored.** `import_csv` deliberately skips the
mirror (documented at `routers/cards.py:166-168`: bulk-appending hundreds of
rows would hammer the API) and relies on each card syncing "on its next edit".
Cards that are never edited are never mirrored. Someone who imports their
collection sees an empty sheet and reaches for the resync button in defect 2.

## Root cause

`Card.sheets_row` is an **absolute row index** into a shared tab, and every
write is a bounded range: `A{row}:{END_COL}{row}`. That makes the index
positional state duplicated between SQLite and a document the user can also
edit by hand.

The consequence is the crux of this design: **there is no operation in the
current model that can remove a row safely.** Deleting row *N* via the Sheets
API shifts every row below it up by one, silently invalidating the stored
`sheets_row` of every card after the deleted one. Each of those cards then
writes its next update over its *neighbour's* row.

## Approaches

### A. Blank the row in place on delete

Write empty values across `A{row}:{END_COL}{row}` instead of removing the row.

- Every other card's index stays valid — no shifting, no re-stamping.
- One API call, on a path that currently makes none.
- The sheet accumulates blank gaps. Row count stops matching inventory count,
  and sorting or filtering in Sheets surfaces the holes.
- Does nothing for defects 2 or 3.

### B. Delete the row and re-stamp every later index

`batchUpdate` with `deleteDimension`, then
`UPDATE cards SET sheets_row = sheets_row - 1 WHERE sheets_row > <deleted>`.

- Keeps the sheet tidy with no gaps.
- **Rejected.** The sheet mutation and the bulk re-stamp must both succeed or
  both fail, and they cannot: the mirror is explicitly fire-and-forget with
  swallowed failures (`sync_card` returns `None` on every exception, and
  `_sync_card_to_sheets` runs after the response). If the sheet delete succeeds
  and the DB re-stamp does not, every subsequent card is off by one and
  overwrites the wrong row — a silent, unbounded corruption strictly worse than
  the phantom row it set out to fix.

### C. Clear-then-rewrite the whole tab (recommended for the repair path)

Replace `resync_all`'s per-card append loop with two calls:

1. `values().clear()` over `A2:{END_COL}` — data rows only, never the header.
2. one `values().update()` writing every card's row in a deterministic order,
   re-stamping `sheets_row = index + 2` for each.

- **Fixes all three defects at once.** Deleted cards vanish because the rewrite
  reflects the DB. Duplication ends because the clear precedes the write.
  Imported cards get mirrored because they are simply part of the DB.
- **Makes the repair tool idempotent** — running it twice is a no-op. That is
  the defining property a repair tool must have and the one today's lacks.
- **Fewer API calls than today**, not more: two, versus one append per card.
- **Self-healing for existing damage.** The first run cleans up whatever
  duplicate blocks past resyncs already left behind.
- It is a destructive write to a user-visible document, which is the reason this
  needs approval rather than being shipped as a quick win.

## Recommendation

**C for the repair path, plus A for the incremental delete path.**

They compose well. Blank-in-place keeps `delete_card` cheap and index-safe
(one call, no shifting), and the blank gaps it leaves are acceptable *precisely
because* C is now safe to run whenever the sheet looks untidy. Without C,
option A's gaps would be permanent; without A, every delete would need a full
tab rewrite.

Deliberately unchanged: **the per-card sync on save.** It is the hot path, it
works, and `_sync_card_to_sheets` already takes a card id and opens its own
session. This design touches only the repair path and the delete path.

Also worth doing in the same pass: have `import_csv` report that the mirror was
not updated and point at resync, so defect 3 stops being invisible. The
rationale for skipping bulk mirroring stays valid — one resync afterwards is
now the correct, safe answer.

## What could go wrong

- **A save racing the rewrite.** A background `_sync_card_to_sheets` landing
  mid-rewrite could write to a row the rewrite is about to reassign. Narrow
  (single worker, and the rewrite re-stamps every index on completion) but real:
  worst case one row is briefly stale until that card's next sync. Accept and
  document; do not add locking for a two-user internal tool.
- **A sheet longer than the DB.** The clear must cover the tab's full used
  range, not `len(cards)` rows — otherwise rows below the rewritten block
  survive, which is the exact residue of the bug being fixed.
- **Partial failure.** `sheets_row` re-stamps must be committed only after the
  update call returns successfully, or the DB will claim positions the sheet
  does not have. Prefer one `update` over chunked writes for that reason; if
  inventory size later forces chunking, commit per chunk.
- **Overwriting manual edits.** The rewrite discards anything typed directly
  into the tab. Already true of the existing per-card update path, and the sheet
  is documented as a mirror rather than a source of truth — but it should be
  stated in the UI next to the button.
- **`SHEET_HEADERS` is append-only (invariant #1).** The rewrite derives every
  row from `_card_to_row`, so it inherits that contract rather than changing it.
  The clear range is derived from `END_COL`, which already tracks the header
  length.

## Cost impact (required check)

No Anthropic calls; no change to scan cost. Sheets API usage strictly
decreases: the repair path goes from *N* appends to two calls, and the delete
path adds one call to a route that made none. Well inside the free quota at
two-user scale.

## Verification

- Fake the Sheets service and record calls: assert `resync_all` run twice
  produces identical sheet contents (idempotence — the defining regression
  test, and it fails against today's code).
- Assert the clear range starts at row 2 so the header survives.
- Assert `delete_card` blanks exactly `A{row}:{END_COL}{row}` for the deleted
  card's stored row and touches nothing else.
- Assert import-then-resync yields exactly one row per card.
- Assert every `sheets_row` after a rewrite matches the card's position, and
  that nothing is committed when the update call raises.
