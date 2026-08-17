# Sheets Mirror Integrity — Implementation Plan

Implements the recommendation in
`docs/superpowers/specs/2026-08-17-sheets-mirror-integrity-design.md`:
clear-then-rewrite for the repair path (C), blank-in-place for the delete path
(A). **Awaiting owner approval — the rewrite is a destructive write to a
user-visible sheet.**

Order matters: step 1 is pure and testable with no API surface, step 2 makes the
repair tool idempotent, step 3 stops new drift, step 4 makes the remaining gap
visible.

## Step 1 — `rewrite_all_rows(cards)` in `services/google_sheets.py`

New function beside `sync_card`; `sync_card` itself is untouched (hot path).

- Build `[_card_to_row(c) for c in cards]` so the row layout stays the single
  `SHEET_HEADERS`-derived contract (invariant #1).
- `_ensure_tab` + `_ensure_header` first, same as `sync_card`.
- Determine the tab's **full used range** before clearing — read
  `{SHEET_TAB}!A:A` and clear `A2:{END_COL}{max(used, len(rows) + 1)}`. Clearing
  only `len(rows)` rows would leave the existing duplicate residue in place,
  which is the bug.
- `values().clear()` on that range, then one `values().update()` at
  `{SHEET_TAB}!A2` with `valueInputOption="RAW"` (the mirror is exempt from the
  CSV formula escaping precisely because it is RAW — do not change this).
- Return the list of assigned row numbers (`index + 2`), or `None` on any
  failure, matching `sync_card`'s never-raise contract.
- Never clear row 1.

## Step 2 — `resync_all` uses it (`routers/sheets.py`)

- Replace the per-card loop with a single `rewrite_all_rows(cards)` call over
  `db.query(Card).order_by(Card.created_at.asc())` — the ordering already used,
  so existing row positions stay broadly stable.
- Commit `sheets_row` re-stamps **only** after a non-`None` return. On `None`,
  leave every `sheets_row` untouched and report the failure in the response, so
  the DB never claims positions the sheet does not have.
- Keep the response shape (`synced` / `skipped` / `total`) so the Analytics
  manage-data panel needs no change.

## Step 3 — `delete_card` blanks its row (`routers/cards.py`)

- Capture `card.sheets_row` **before** `db.delete(card)` — the attribute is gone
  afterwards.
- Queue a background task (new `_blank_sheets_row(row)`, mirroring
  `_sync_card_to_sheets`: takes a plain int, opens nothing, swallows failures)
  writing empty strings across `A{row}:{END_COL}{row}`.
- Skip entirely when `sheets_row` is falsy (never-mirrored card).
- Do not attempt row removal or index re-stamping — see approach B in the design
  doc for why that is worse than the bug.

## Step 4 — Make the import gap visible (`routers/cards.py`)

- Add a line to `import_csv`'s existing `warnings` list stating the mirror was
  not updated and that a full resync will mirror the imported rows. The
  skip-bulk-mirroring rationale stays; it just stops being silent.

## Step 5 — Tests (`backend/tests/test_sheets_mirror.py`, new)

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
- **No commit on failure:** service raising → `sheets_row` values unchanged.
- **Import then resync:** exactly one row per card.
- Add `Card` to the `db_session` fixture's cleanup list if the new module needs
  isolation beyond what exists.

## Step 6 — Process

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

Full backend suite green (`python3 -m pytest backend/tests -q` from the repo
root). No frontend change, so no frontend gate unless step 2 alters the response
shape — it should not.

## Estimated effort

Half a day. Step 1 and step 5 carry the weight; steps 2–4 are small. No schema
change, no migration, no new dependency.

## Explicitly out of scope

- Removing rows so the tab has no gaps (approach B — rejected on corruption
  risk).
- The on-demand Sheets **drift detector** and the push-side **sync failure
  visibility** items already in the backlog. Both become more useful after this
  lands, and both remain separate.
- Bulk-mirroring on import. One safe resync afterwards is the answer.
