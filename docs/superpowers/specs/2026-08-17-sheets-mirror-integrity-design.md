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

Replace `resync_all`'s per-card append loop with three calls:

0. a read of the tab's used range across `A:{END_COL}` (see "What could go
   wrong" — column A alone is not enough to find the last used row).
1. `values().clear()` over `A2:{END_COL}` — data rows only, never the header.
2. one `values().update()` writing every card's row in a deterministic order,
   re-stamping `sheets_row = index + 2` for each. "Deterministic" has to mean a
   *total* order: `created_at` alone is not one, since a CSV import stamps many
   rows in the same instant, and two runs could then order them differently and
   assign different rows — which would break the very idempotence this
   recommendation rests on. Order by `created_at` then `id`.

- **Fixes all three defects when combined with A** (see the recommendation
  below). On its own, C ends duplication because the clear precedes the write,
  mirrors imported cards because they are simply part of the DB, and sweeps away
  rows for already-deleted cards *whenever a resync is run*. It does not make an
  ordinary delete update the sheet — that is what A is for.
- **Makes the repair tool idempotent** — running it twice is a no-op. That is
  the defining property a repair tool must have and the one today's lacks.
- **Fewer API calls than today**, not more: three, versus one append per card.
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

- **A save racing the rewrite.** A background `_sync_card_to_sheets` task reads
  a card's `sheets_row`, then writes to it. If a rewrite reassigns that row to a
  *different* card in between, the late save overwrites the wrong card's row.
  This is worse than the "briefly stale" framing it deserves: the sheet ends up
  holding one card's data under another card's row, silently. The window is
  narrow (single worker; resync is a manual, rare action) but the consequence is
  corruption, so it needs a real guard.

  A generation counter alone is not enough, for two reasons. It is not atomic —
  checking the generation and then writing leaves the same window open, just
  narrower — and *skipping* a save that loses the race is not lossless: that
  card's edit never reaches the mirror at all, and may not until someone happens
  to edit it again, which could be never.

  Because there is exactly one process (invariant #9 forbids a second worker),
  a module-level `threading.Lock` is both simpler and genuinely atomic. Every
  writer — `sync_card`, `rewrite_all_rows`, and the delete-path blank — takes it,
  and each per-card writer re-reads its `sheets_row` *inside* the lock rather
  than trusting a value captured before. A save that arrives mid-rewrite then
  blocks briefly and writes to the row the rewrite just assigned it, instead of
  being dropped. The rewrite holds the lock for its two or three API calls;
  per-card syncs are already background tasks, so waiting costs nothing a user
  can see.

  The lock must span **re-read → Sheet write → `sheets_row` commit**, not just
  the API call. `_sync_card_to_sheets` writes the row index back to the DB after
  `sync_card` returns; if the lock were released in between, a rewrite could
  restamp that card and the background session would then commit its *old*
  index over the new one — putting the stale ownership back in the database
  after the sheet had already moved on.
- **A delete racing the rewrite.** The same hazard, and easy to miss because the
  delete path looks unrelated: `_blank_sheets_row` captures an absolute row
  number before the background task runs, so a resync in between would leave it
  blanking a row now owned by a different card — erasing a live card from the
  mirror.

  A row number alone cannot answer this, which is the subtlety: row 7 looks
  identical whether or not it changed hands. The check has to be about
  *ownership*, and the deleted card is gone by the time the task runs, so
  identity must be captured before the delete commits. Under the same lock, the
  task blanks row *N* only if no live card currently claims `sheets_row == N`.
  If one does, a rewrite reassigned it and the blank is silently dropped — the
  row now holds data that belongs there.
- **A blank that never lands.** If the Sheets call fails, the deleted card's row
  stays behind and nothing retries it — the card is gone, so there is no record
  left to retry *from*. That is an accepted degradation, not an oversight: the
  outcome is one stale row, which is exactly what resync now sweeps away, and it
  is the same failure the mirror has today for every delete. An outbox or
  tombstone table would make it self-healing, but that is a schema change and a
  new subsystem to earn one stale row on a rare path in a two-user tool — the
  wrong trade here. If deletes ever become frequent, revisit it.
- **A sheet longer than the DB.** The clear must cover the tab's full used
  range, not `len(cards)` rows — otherwise rows below the rewritten block
  survive, which is the exact residue of the bug being fixed. Crucially, the
  used range must be derived from **all** mirror columns (`A` through
  `END_COL`), not column A alone: a residue row whose Player cell is empty but
  which carries stale data further right would be invisible to an `A:A` probe
  and survive the clear.
- **Partial failure, in both orders.** These are two distinct bad states and
  both need an answer:
  - *`clear()` succeeds, `update()` fails.* The tab is now empty while every
    card's `sheets_row` still points into it, so the mirror silently reports an
    empty inventory and each card's next save writes one lonely row into a
    blank sheet. The rewrite must therefore treat a failed update as a hard
    failure: null every `sheets_row` in one commit so subsequent syncs re-append
    rather than write into a void, and surface the divergence to the caller
    instead of swallowing it the way `sync_card` does.
  - *`update()` succeeds, `db.commit()` fails.* SQLite keeps the old positions
    while the sheet holds new ones. **Here nulling would be actively harmful**,
    and it is worth being explicit about why, because the symmetry is tempting:
    the sheet is already correct and complete, so a null index would make every
    card *append* a second copy of itself on its next save — reintroducing
    exactly the duplication this whole design exists to remove. Retry the commit
    instead; the positions are deterministic (`index + 2`), so they can be
    recomputed rather than recovered. If the retry also fails, leave the indices
    untouched and report divergence: stale indices point at rows that at least
    exist, and the next resync — which clears first — repairs them, whereas
    duplicates would have to be deleted by hand.
  The asymmetry is the point: null when the sheet is *empty*, never when the
  sheet is *full*. In both cases the response must say the mirror diverged
  rather than reporting success — this is the one Sheets path that should *not*
  fail silently, because it is the repair tool.
- **Overwriting manual edits.** The rewrite discards anything typed directly
  into the tab. Already true of the existing per-card update path, and the sheet
  is documented as a mirror rather than a source of truth — but it must be
  stated in the UI next to the button, and that warning ships *with* the change
  rather than after it. It is the only cue the owner gets before a destructive
  action, so the plan carries it as a required step, not a nicety.
- **`SHEET_HEADERS` is append-only (invariant #1).** The rewrite derives every
  row from `_card_to_row`, so it inherits that contract rather than changing it.
  The clear range is derived from `END_COL`, which already tracks the header
  length.

## Cost impact (required check)

No Anthropic calls; no change to scan cost. Sheets API usage still drops
sharply, though not to the two calls an earlier draft of this doc claimed —
finding the used range needs its own read, so the repair path is a read, a
clear and an update: **three requests**, plus the existing `_ensure_tab` /
`_ensure_header` checks, against *N* appends today. The delete path adds one
call to a route that made none. Comfortably inside the free quota at two-user
scale.

## Verification

- Fake the Sheets service and record calls: assert `resync_all` run twice
  produces identical sheet contents (idempotence — the defining regression
  test, and it fails against today's code).
- Assert the clear range starts at row 2 so the header survives.
- Assert `delete_card` blanks exactly `A{row}:{END_COL}{row}` for the deleted
  card's stored row and touches nothing else.
- Assert import-then-resync yields exactly one row per card.
- Assert every `sheets_row` after a rewrite matches the card's position.
- Cover both partial-failure orders: `clear` succeeding then `update` raising,
  and `update` succeeding then the commit raising. In each case assert every
  `sheets_row` ends up null (so no card can write into a row it no longer owns)
  and that the response reports divergence rather than success.
- Cover a residue row whose column A is empty but which carries stale data in a
  later column — it must still fall inside the computed clear range.
- Cover an overlapping save and resync: a `sync_card` that read a `sheets_row`
  before a rewrite reassigned it must not write afterwards, and the rewritten
  row must still belong to the card the rewrite assigned it to.
