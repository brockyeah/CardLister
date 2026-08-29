# Google Sheets Mirror Integrity — Design

**Status:** base design implemented (PR #46, merged 2026-08-17). The
**2026-08-29 addendum below** is proposed and awaiting owner approval — it
closes the gap between the lock protocol this document specified and the one
PR #46 actually shipped.
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

---

# Addendum (2026-08-29): the `sheets_row` commit runs outside the lock the protocol requires

**Status:** proposed, awaiting owner approval
**Filed:** 2026-08-29 (weekly deep-work run, from the 2026-08-23 weekly-review
backlog item; every claim re-verified against the code as shipped)
**Scope:** `backend/services/google_sheets.py`, `backend/routers/cards.py`
(the two background tasks), `backend/routers/sheets.py`
**Plan:** `docs/superpowers/plans/2026-08-29-sheets-lock-commit.md`

## The defect, concretely

The base design's race analysis ("What could go wrong", first bullet) is
explicit that the lock must span **re-read → Sheet write → `sheets_row`
commit**, and the shipped lock's own comment repeats the claim verbatim
(`google_sheets.py:19-22`: "Held across re-read -> Sheet write -> sheets_row
commit"). The implementation does not do this. Every writer releases the lock
when it returns, and the DB commit runs in the caller, after the release:

- `sync_card` takes the lock at `google_sheets.py:273` and releases it on
  return (`:289` update branch, `:304` append branch). The commit of the row
  it returns happens in `_sync_card_to_sheets` at `routers/cards.py:49-51`.
- `rewrite_all_rows` takes the lock at `google_sheets.py:184` and releases it
  on return (`:222`). The stamping loop and its commit run in `resync_all` at
  `routers/sheets.py:50-53`, and the `"cleared"`-branch nulling at
  `routers/sheets.py:38-41` — both after the lock is gone.
- `blank_row` does hold the lock across its `is_owned` check and its write
  (`google_sheets.py:241-251`), but the DB that `_is_owned`
  (`routers/cards.py:68-69`) consults can lag the sheet, because a resync's
  new assignments are committed only after the resync released the lock.

The invariant the lock exists to provide — *while it is held, the sheet and
the committed `Card.sheets_row` values agree* — is therefore not provided at
exactly the moments two writers interleave, which is the only time the lock
matters at all.

## The two concrete losses

**(a) A save racing a resync corrupts the sheet, then the DB.** Thread T1
(request) runs `resync_all`: `rewrite_all_rows` takes the lock, clears and
rewrites the tab — card X now lives at row 9 — and releases; the stamping loop
has not yet committed. Thread T2 (a save's background task) now enters
`sync_card`, takes the lock, and `_reread` (`cards.py:44-46`) refreshes X from
the DB — which still says row 5, because T1 hasn't committed. T2 writes X's
data over row 5, **a row the rewrite just assigned to a different card**, and
nothing raises. The DB half corrupts too, in the append-branch variant: a
sync that appended and returned row 12 commits `sheets_row = 12` at
`cards.py:49-51` *after* the resync committed row 9, so X's next edit writes
into row 12 — outside the rewritten block, or over whatever card the next
resync puts there. This is the base design's "stale ownership back in the
database after the sheet had already moved on", verbatim — the case the lock
was specified to close.

**(b) A delete racing a resync erases a live card from the mirror.**
`delete_card` captures row 7 (`cards.py:502`) and queues `_blank_sheets_row`.
A resync rewrites the tab, and live card Z now occupies row 7; the lock is
released; the stamping is not yet committed. The blank task takes the lock and
asks `_is_owned(7)` — which queries **committed** state, where no card claims
row 7 — so the blank lands and erases Z from the sheet. The resync then
commits `Z.sheets_row = 7`, pointing Z at a blank row until its next edit
happens to rewrite it.

**(c) `resync_one` bypasses the protocol entirely and has no caller.**
`POST /api/sheets/sync/{card_id}` (`routers/sheets.py:67-76`) calls
`sync_card` with no `reread_row` and commits outside the lock. Nothing invokes
it: `frontend/src/api.js:83-84` posts only to `/api/sheets/resync`, and no
test exercises the route.

## Why the existing tests can't see it

All 14 tests in `test_sheets_mirror.py` are single-threaded and stub the
callbacks: `test_sync_card_rereads_row_inside_the_lock`
(`test_sheets_mirror.py:318-333`) passes `reread_row=lambda: 9`, pinning the
callback's plumbing but not the locking, and
`test_delete_does_not_erase_a_row_a_resync_reassigned` (`:292-305`) passes
`lambda r: True`. Moving the reread *outside* the lock passes the whole file.
The lock has zero concurrency coverage.

## Approaches

### A. Commit callbacks passed into the writers (recommended)

Extend the shape `reread_row` already established: the caller owns the DB
work, the service owns the lock, and the service invokes the caller's DB work
at the right moment — inside the lock.

- `sync_card(card, reread_row=None, commit_row=None)`: after a successful
  sheet write, invoke `commit_row(row)` before releasing.
  `_sync_card_to_sheets` passes a callback that sets `card.sheets_row` and
  commits, and drops its post-hoc commit.
- `rewrite_all_rows(cards, commit_rows=None, null_rows=None)`: invoke
  `commit_rows(rows)` inside the lock once the update succeeds, and
  `null_rows()` inside the lock on the `"cleared"` path (an empty sheet with
  live indices pointing into it is exactly the state a racing save must not
  observe). `resync_all` moves its stamping loop and its nulling into the
  callbacks; the response contract — reason strings `"unconfigured"`,
  `"setup"`, `"cleared"`, `"commit"` — is unchanged.
- `blank_row` needs **no change**: once the two committing writers finish
  their commits before releasing, `_is_owned` always reads a DB that agrees
  with the sheet. Fixing (a)'s commit placement is what fixes (b).

Two narrow, obviously-named callbacks are deliberate — a single polymorphic
`on_result(rows, error)` would push the resync's branch logic into the service
and make the failure mapping implicit.

### B. Expose the lock and have callers hold it (rejected)

A `google_sheets.mirror_lock()` context manager, with callers running
re-read → write → commit inside it. Flatter control flow, but the protocol
becomes something every caller must remember rather than something the
writers enforce — and this defect *is* a caller getting the protocol wrong
while the module's comment said otherwise. The writers can't verify their
caller holds the lock without re-entrant bookkeeping that costs more than the
callbacks do.

### C. Pass the DB session into the service (rejected)

`google_sheets.py` is deliberately ORM-ignorant (its imports are `os`,
`json`, `logging`, `threading`); giving it the session couples the mirror to
the models, drags SQLAlchemy into every mirror test, and still needs a
callback-equivalent for the resync's stamping order. Strictly worse than A.

### `resync_one`: delete it (recommended) rather than fix it

It is dead code on the wrong side of the protocol. Its job — "push one card
to the sheet" — is what every mutating card route already does via
`_sync_card_to_sheets`, and the repair story is `resync_all`. Fixing it means
wiring `reread_row` + `commit_row` into a route nothing calls; deleting it
removes a bypass. `test_auth_sweep.py` walks the live OpenAPI schema, so
removal needs no test edits there.

## The lock-ordering hazard the fix introduces — and its resolution

Moving `db.commit()` inside `_sheets_lock` creates an ABBA shape with
SQLite's file lock that does not exist today, and the design is not sound
without naming it. The DB runs in rollback-journal mode (the storage backlog
item notes `-wal` sidecars would appear only "if journal mode is ever
changed"), where a read transaction holds SHARED for its lifetime, and
SQLAlchemy's autobegin opens one on the first query:

- T1 (resync) holds `_sheets_lock`; its under-lock commit needs EXCLUSIVE.
- T2 (`_sync_card_to_sheets`) ran `db.query(Card)...first()` (`cards.py:38`)
  before calling `sync_card`, so it holds SHARED — and is blocked waiting on
  `_sheets_lock`.

Neither yields; SQLite's busy timeout (~5s default) breaks it by failing T1's
commit with "database is locked", which maps to the `"commit"` failure — a
designed-in stall plus a spurious repair-tool failure in precisely the racing
case the lock exists to serve.

**Resolution:** the background tasks must wait on the lock holding no DB
transaction. `_sync_card_to_sheets` calls `db.rollback()` after loading the
card and before calling `sync_card`; `_reread`'s `db.refresh(card)` then
reopens the transaction *inside* the lock, where it is the only thread in the
protocol, and `commit_row` commits on the same session. `_blank_sheets_row`
already runs its first query inside the lock (`_is_owned` is only ever called
there) and must stay that way — the plan pins this with a comment, since it
is invisible load-bearing ordering. `resync_all`'s own session holds SHARED
from its card query and upgrades to EXCLUSIVE itself, which is ordinary
single-connection promotion, not the ABBA case: other request threads' reads
can stall the commit up to the busy timeout exactly as they can today, but
with the rollback fix no thread that waits on `_sheets_lock` holds SHARED.

## What could go wrong

- **`commit_row` failing after an append** leaves the row landed in the sheet
  and `sheets_row` NULL, so the card's next edit appends a duplicate row. This
  is the same degradation the open "malformed `updatedRange`" backlog item
  documents for the parse-failure case, it requires the local SQLite commit to
  fail (far rarer than the Sheets call failing), and it is logged. Accepted;
  the fallback-to-`_last_used_row` fix in that backlog item shrinks it further
  when it lands.
- **`commit_rows` failing under the lock** keeps today's exact semantics: the
  sheet is full and correct, indices are stale-but-valid, the response says
  `"commit"`, and re-running the resync re-records them (positions are
  deterministic, `index + 2`). The base design's asymmetry — null when the
  sheet is empty, never when it is full — is untouched.
- **Longer lock holds.** The commit adds local-disk milliseconds to a lock
  whose holds are already seconds of Sheets network I/O. Waiters are
  background tasks and the manual resync; nothing a user watches.
- **A future second worker** breaks this exactly as it breaks the existing
  lock — invariant #9 already forbids that, and this changes nothing about it.

## Cost impact (required check)

No Anthropic calls; scan cost delta is zero. No new Sheets API requests
either — the same calls happen in the same order; only the DB commits move.

## Verification

See the plan for the ordered steps; the properties are:

- A real two-thread save-vs-resync interleaving, gated by `threading.Event`
  (released in `finally` — never `sleep`, per the pricing-suite lesson in
  CLAUDE.md invariant #12), asserting every card's data sits in the row its
  committed `sheets_row` names. Fails against today's code.
- The same shape for delete-vs-resync: the blank must be dropped once the
  resync's assignments are committed under the lock. Fails against today's
  code.
- `commit_row` / `commit_rows` observe `_sheets_lock.locked() is True` when
  invoked — pins "under the lock" directly, so a refactor that moves the
  callback after the `with` block fails a unit test, not just the (timing-
  sensitive) interleaving tests.
- The resync `"commit"` failure branch gets its first test (the branch at
  `routers/sheets.py:52-62` is currently uncovered).
- A post-resync invariant assertion — every `sheets_row` equals the card's
  sheet position — reused across the new tests.
- The two-thread tests run against the real temp-file SQLite DB the suite
  already uses, so a regression on the rollback-before-wait rule surfaces as
  the resync's commit failing "database is locked" rather than passing.
