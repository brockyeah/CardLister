# Sheets Mirror: Commit Under the Lock — Implementation Plan

**Design:** the 2026-08-29 addendum in
`docs/superpowers/specs/2026-08-17-sheets-mirror-integrity-design.md`
**Status:** awaiting owner approval — do not start until the three decisions
at the bottom are made.
**Touches:** `backend/services/google_sheets.py`, `backend/routers/cards.py`,
`backend/routers/sheets.py`, `backend/tests/test_sheets_mirror.py`. No schema
change (no `_COLUMN_MIGRATIONS` entry needed), no frontend change, no new
dependencies.

Every step leaves the suite green and is independently shippable; steps 1–2
are the fix, 3 removes the bypass, 4–5 are the concurrency regression tests
the lock has never had, 6 is bookkeeping. Run
`.venv/bin/python -m pytest backend/tests/test_sheets_mirror.py -q` after each
step and the full backend suite before the PR.

---

## Step 1 — `sync_card` commits its row under the lock

**Change.** Add an optional `commit_row` callable to
`sync_card(card, reread_row=None, commit_row=None)`
(`services/google_sheets.py:261`). In both branches, once the Sheets write has
succeeded and the row number is known, invoke `commit_row(row)` **before the
`with _sheets_lock:` block exits**, inside the existing `try` (a callback
failure is logged by the existing handler and swallowed — the mirror stays
fire-and-forget). Still return the row.

In `_sync_card_to_sheets` (`routers/cards.py:28-53`):

- after loading the card, call `db.rollback()` so the task waits on the lock
  holding no SQLite read transaction (the ABBA hazard in the addendum —
  `_reread`'s `db.refresh(card)` reopens it inside the lock);
- pass `commit_row` that does `card.sheets_row = row; db.commit()` (keep the
  existing `card.sheets_row != row` cheap-skip);
- delete the post-return commit at `cards.py:49-51`.

Update the `_sheets_lock` comment (`google_sheets.py:14-23`): its "held
across … sheets_row commit" claim becomes true only now — reword it to name
the callback mechanism that makes it true.

**Test (same step).**
- `commit_row` observes `google_sheets._sheets_lock.locked() is True` when
  invoked, for both the update and append branches — the direct pin on
  "under the lock", immune to timing.
- A save through the API (`TestClient` + `FakeSheet`) still persists
  `sheets_row` — proving the moved commit actually runs, since the caller no
  longer commits after the fact.
- `commit_row` raising does not propagate out of `sync_card` (logged +
  swallowed, per decision 2).

## Step 2 — `rewrite_all_rows` commits (or nulls) under the lock

**Change.** Add optional `commit_rows` and `null_rows` callables to
`rewrite_all_rows(cards, commit_rows=None, null_rows=None)`
(`services/google_sheets.py:161`):

- on the success path, invoke `commit_rows(rows)` inside the lock after the
  `update` succeeds, then return `(rows, None)`;
- on the `"cleared"` path (`google_sheets.py:218-220`), invoke `null_rows()`
  inside the lock before returning `(None, "cleared")` — an empty sheet with
  live indices pointing into it is the state a racing save must never observe;
- exceptions from either callback are **not** swallowed by the service — let
  them propagate to `resync_all`, which already owns the failure mapping.

In `resync_all` (`routers/sheets.py:20-64`): move the stamping loop + commit
(`:50-53`) into `commit_rows`, and the nulling (`:38-41`) into `null_rows`;
wrap the `rewrite_all_rows` call so a `commit_rows` failure still rolls back
and returns the existing `"commit"` reason with indices untouched. Every
reason string and response shape stays byte-identical (`_FAILURE_DETAIL` is a
UI contract).

**Test (same step).**
- `commit_rows` and `null_rows` each observe `_sheets_lock.locked() is True`.
- **First test for the `"commit"` failure branch** (currently uncovered):
  patch the session's commit inside `commit_rows` to raise; assert the
  response reports `reason == "commit"`, `ok is False`, and every
  `sheets_row` keeps its pre-resync value (stale-but-valid, never nulled).
- Existing tests `test_cleared_but_not_rewritten_nulls_every_row` and
  `test_setup_failure_leaves_indices_alone` must pass unchanged — they pin
  the asymmetry the callbacks must preserve.

## Step 3 — delete `resync_one`

**Change.** Remove `POST /api/sheets/sync/{card_id}`
(`routers/sheets.py:67-76`) and the now-unused `sync_card` import there.
Verified before this plan was written: no frontend caller
(`frontend/src/api.js:83-84` posts only to `/api/sheets/resync`) and no test
references it.

**Test (same step).** The auth sweep (`test_auth_sweep.py`) walks the live
OpenAPI schema, so it adjusts itself; run the full suite to prove nothing
else referenced the route. Add one line to
`test_sheets_mirror.py` asserting the path is absent from
`app.openapi()["paths"]` so the bypass can't quietly return.

## Step 4 — two-thread save-vs-resync interleaving test

**Change (test only).** Extend `FakeSheet` so `update` can block on a
`threading.Event` for a chosen range (the resync's `A2` bulk write), with the
event set in a `finally` — never `sleep`, per the CLAUDE.md invariant #12
lesson from the pricing suite. Choreography:

1. Cards A and B mirrored at rows 2 and 3; force the rewrite to assign them
   differently (e.g. give B the earlier `created_at` so order flips).
2. Thread 1 calls `resync_all`; the fake blocks it inside the rewrite's
   `update`, lock held.
3. Thread 2 runs `_sync_card_to_sheets(A.id)`; it must block on the lock
   (assert it has made no Sheets call while thread 1 is paused).
4. Release the event; join both threads (bounded `join(timeout=...)`,
   asserting liveness).

**Assert** the post-resync invariant with a shared helper
`assert_mirror_consistent(db, fake)`: every card's committed `sheets_row`
names the fake row holding that card's player, no row holds two cards' data,
and no card's data sits under another card's index. Against today's code this
fails (the save writes A into the row the rewrite gave B, and/or commits a
stale index); after steps 1–2 it passes. Running on the suite's real temp-file
SQLite, a regression of step 1's `db.rollback()` shows up here as the
resync's commit failing "database is locked".

## Step 5 — two-thread delete-vs-resync interleaving test

**Change (test only).** Same event-gated fake:

1. Card D at row 2, live card Z at row 3; delete D via the API but run the
   captured `_blank_sheets_row(2)` on a controlled thread.
2. Thread 1 `resync_all`, paused inside the rewrite with the lock held; the
   rewrite will assign Z to row 2.
3. Thread 2 calls `_blank_sheets_row(2)`; it must block on the lock.
4. Release; join.

**Assert** the blank was dropped (`fake.ops("update")` contains no
`A2:{END_COL}2` blank write after the rewrite), Z's data is intact at row 2,
and `Z.sheets_row == 2`. Fails against today's code — `_is_owned` reads the
pre-commit DB and erases Z — and needs no change to `blank_row` itself to
pass: step 2's under-lock commit is what fixes it, which this test proves.

## Step 6 — bookkeeping

- CHANGELOG entry under `[Unreleased]` (prose: the lock's comment promised a
  protocol the code didn't run; what could be lost; what changed).
- BACKLOG: move the "sheets_row DB commit happens outside `_sheets_lock`"
  item to **Shipped** with the date, noting `resync_one`'s deletion.
- CLAUDE.md: the Sheets-mirror architecture paragraph already says the three
  writers "re-check their row inside" the lock — extend the sentence to say
  the row *commits* inside it too, via caller-supplied callbacks.

---

## Effort and risk

One focused session: roughly +40 lines of production code across three files,
−10 (`resync_one`), and ~180 lines of tests. The risky part is step 4/5
choreography, not the production change — the callbacks are mechanical. No
data migration; deployed installs are unaffected until the first racing
save/resync, which is the point.

## Decisions needed before implementation

1. **Delete `resync_one`, or fix it?** Plan assumes delete (dead code,
   protocol bypass; its job is covered by save-sync and `resync_all`).
2. **A `commit_row` failure in the save path stays swallowed** (logged, mirror
   fire-and-forget, worst case one duplicate row on a later edit — same class
   as the open malformed-`updatedRange` item). OK, or should it surface?
3. **Callback shape (Approach A)** over exposing the lock to callers
   (Approach B) — confirm, since it changes three public-ish signatures in
   `google_sheets.py`.
