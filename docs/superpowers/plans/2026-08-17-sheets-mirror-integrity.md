# Sheets Mirror Integrity — Implementation Plan

Implements the recommendation in
`docs/superpowers/specs/2026-08-17-sheets-mirror-integrity-design.md`:
clear-then-rewrite for the repair path (C), blank-in-place for the delete path
(A). **Awaiting owner approval — the rewrite is a destructive write to a
user-visible sheet.**

Order matters: step 1 is pure and testable with no API surface, step 2 makes the
repair tool idempotent, step 3 stops new drift, step 4 makes the remaining gap
visible, and step 5 warns before the destructive action ships.

## Step 1 — `rewrite_all_rows(cards)` in `services/google_sheets.py`

New function beside `sync_card`; `sync_card` itself is untouched (hot path).

- Build `[_card_to_row(c) for c in cards]` so the row layout stays the single
  `SHEET_HEADERS`-derived contract (invariant #1).
- `_ensure_tab` + `_ensure_header` first, same as `sync_card`.
- Determine the tab's **full used range** before clearing, across **every mirror
  column** — read `{SHEET_TAB}!A:{END_COL}` (or take `gridProperties` /
  `dataRange` from `spreadsheets().get`) and take the last row with any
  non-empty cell. Do **not** probe `A:A` alone: the API omits trailing empty
  cells, so a residue row with an empty Player but stale data further right
  would be invisible and survive the clear — precisely the bug being fixed.
  Clear `A2:{END_COL}{max(used, len(rows) + 1)}`.
- `values().clear()` on that range, then one `values().update()` at
  `{SHEET_TAB}!A2` with `valueInputOption="RAW"` (the mirror is exempt from the
  CSV formula escaping precisely because it is RAW — do not change this).
- Return the list of assigned row numbers (`index + 2`), or `None` on any
  failure, matching `sync_card`'s never-raise contract. Distinguish the two
  failure points in the return value (or a second element) so the caller can
  tell "nothing happened" from "the tab was cleared but not rewritten" — they
  need different recovery.
- Never clear row 1.
- Serialize every Sheet write behind a module-level `threading.Lock` in
  `google_sheets.py`. `sync_card`, `rewrite_all_rows`, and the delete-path blank
  all take it. There is exactly one process (invariant #9), so a lock is both
  simpler and genuinely atomic — a generation counter is neither, since
  check-then-write leaves the window open and skipping a save loses that card's
  edit entirely.
- `sync_card` must be modified to re-read the card's `sheets_row` *inside* the
  lock rather than trusting a value read before it. A save that arrives
  mid-rewrite then blocks briefly and writes to the row the rewrite assigned it
  — nothing is dropped, so no retry queue is needed.
- The lock must be held across **re-read → Sheet write → `sheets_row` commit**,
  not just the API call. `_sync_card_to_sheets` commits the row index *after*
  `sync_card` returns; releasing in between would let a rewrite restamp the card
  and then have this session commit its stale index back over the new one.

## Step 2 — `resync_all` uses it (`routers/sheets.py`)

- Replace the per-card loop with a single `rewrite_all_rows(cards)` call over
  `db.query(Card).order_by(Card.created_at.asc(), Card.id.asc())`. The `id`
  tiebreaker is required, not cosmetic: `created_at` alone is not a total order
  (a CSV import stamps many rows in the same instant), so two runs could assign
  different rows and break the idempotence this whole step is for.
- Commit `sheets_row` re-stamps **only** after a successful update.
- Handle both partial-failure orders explicitly. They are **not** symmetric —
  null only when the sheet is empty, never when it is full:
  - *Cleared but not rewritten (sheet empty):* null every `sheets_row` in one
    commit, so each card re-appends instead of writing into a blank tab at a
    position nothing occupies any more.
  - *Rewritten but the commit failed (sheet full and correct):* do **not** null.
    The positions are deterministic (`index + 2`), so retry the commit. If that
    also fails, leave the indices alone and report divergence — nulling here
    would make every card append a second copy of itself, recreating the exact
    duplication this change exists to remove, and duplicates have to be deleted
    by hand whereas stale indices are repaired by the next resync.
- Report divergence in the response rather than swallowing it. This is the one
  Sheets path that must not fail silently: it is the repair tool, and a silent
  failure here is what produced the mess it exists to clean up.
- Extend the response shape (`synced` / `skipped` / `total` plus a failure
  reason) rather than replacing it, and surface the reason in the Analytics
  manage-data panel.

## Step 3 — `delete_card` blanks its row (`routers/cards.py`)

- Capture `card.sheets_row` **before** `db.delete(card)` — the attribute is gone
  afterwards.
- Queue a background task (new `_blank_sheets_row(row)`, mirroring
  `_sync_card_to_sheets`: takes a plain int, opens nothing, swallows failures)
  writing empty strings across `A{row}:{END_COL}{row}`.
- Skip entirely when `sheets_row` is falsy (never-mirrored card).
- Take the same lock as the rewrite, and verify **ownership**, not just the row
  number — row 7 looks the same whether or not it changed hands. Under the lock,
  blank row *N* only if no live card currently claims `sheets_row == N`; if one
  does, a rewrite reassigned it and the blank is dropped. Without this, a resync
  landing between the delete and the background blank erases a *live* card's row.
- A failed blank is accepted, not retried: the card is gone, so there is no
  record to retry from, and the residue is one stale row that the now-idempotent
  resync sweeps away. Do not add an outbox or tombstone table for this — see the
  design doc for why that trade is wrong at this scale.
- Do not attempt row removal or index re-stamping — see approach B in the design
  doc for why that is worse than the bug.

## Step 4 — Make the import gap visible (`routers/cards.py`)

- Add a line to `import_csv`'s existing `warnings` list stating the mirror was
  not updated and that a full resync will mirror the imported rows. The
  skip-bulk-mirroring rationale stays; it just stops being silent.

## Step 5 — Destructive-action warning in the UI (`frontend/src/pages/Analytics.jsx`)

Required, not optional — the design calls for it and this is the only cue the
owner gets before a destructive action.

- Next to the resync button on manage-data, state plainly that a resync
  **rewrites the whole Inventory tab** and discards anything typed directly into
  the sheet.
- Surface the new failure reason from step 2 when a resync reports divergence,
  rather than leaving it as a silent success.
- This makes the change frontend-touching, so the frontend gate applies (see
  Gates below).

## Step 6 — Tests (`backend/tests/test_sheets_mirror.py`, new)

Patch the module attribute `google_sheets._get_service` with a fake recording
`clear`/`update`/`append` calls and their ranges — patch the attribute, not a
bound import, per the repo's testing note.

- **Idempotence:** `resync_all` twice → identical recorded sheet contents and no
  `append` calls. Fails against today's code; this is the regression test.
- **Header survives:** every clear range starts at row 2.
- **Residue cleared:** with a fake sheet longer than the card count, the clear
  range covers the full used range.
- **Delete blanks one row:** exactly `A{row}:{END_COL}{row}` for the deleted
  card, nothing else; and no call at all when `sheets_row` is `None`.
- **Both partial-failure orders:** `clear` succeeding then `update` raising,
  and `update` succeeding then the commit raising. In each, assert every
  `sheets_row` ends up null (so no card writes into a row it no longer owns)
  and the response reports divergence rather than success.
- **Residue invisible to an A-only probe:** a row with an empty column A but
  stale data in a later mirror column must still fall inside the clear range.
- **Overlapping save and resync:** a `sync_card` that read its `sheets_row`
  before the rewrite reassigned it must not write to the stale row, and must
  still land its update on the card's new row — assert the save is not lost.
- **Overlapping delete and resync:** a queued `_blank_sheets_row` must not erase
  a row the rewrite reassigned to a live card.
- **Equal `created_at`:** several cards sharing a timestamp must land in the
  same rows across two resyncs (the `id` tiebreaker); without it this is flaky.
- **Import then resync:** exactly one row per card.
- Add `Card` to the `db_session` fixture's cleanup list if the new module needs
  isolation beyond what exists.

## Step 7 — Process

- `CHANGELOG.md` entry under `[Unreleased]`: prose on the prior pain — a repair
  button that duplicated the inventory, deletes that never reached the mirror.
- `docs/BACKLOG.md`: move the "Sheets mirror diverges permanently" item to
  Shipped with the date.
- Note in the changelog that the **first** resync after this ships will clean up
  duplicate blocks left by earlier runs — the owner should expect the sheet to
  change shape once, for the better.
- No CLAUDE.md invariant changes: `SHEET_HEADERS` stays append-only and the
  mirror stays RAW. Worth **adding** a line to the Sheets section noting that
  `resync_all` is now a clear-then-rewrite and therefore safe to run repeatedly.

## Gates

Full backend suite green, run from the repo root with the module form —
`.venv/bin/python -m pytest backend/tests -q` (there is no `pytest.ini` /
`pyproject.toml`, so bare `pytest` cannot resolve the `backend.` import path,
and CLAUDE.md notes bare `python` may not be on PATH).

Step 5 touches the frontend, so the frontend gate applies too:
`cd frontend && npm ci && npm test && npm run build`.

## Estimated effort

Half a day. Step 1 and step 6 carry the weight; steps 2–5 are small. No schema
change, no migration, no new dependency.

## Explicitly out of scope

- Removing rows so the tab has no gaps (approach B — rejected on corruption
  risk).
- The on-demand Sheets **drift detector** and the push-side **sync failure
  visibility** items already in the backlog. Both become more useful after this
  lands, and both remain separate.
- Bulk-mirroring on import. One safe resync afterwards is the answer.
