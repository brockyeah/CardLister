"""Google Sheets sync.

Sheets is a secondary mirror of the SQLite DB. Failures here are logged
and swallowed — they must never fail the primary API request.
"""
import os
import json
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Serializes every write to the mirror. The app runs exactly one process
# (CLAUDE.md invariant #9 forbids a second worker), so a lock is genuinely
# atomic here — unlike a generation counter, where check-then-write leaves the
# race window open and losing the race would silently drop a card's edit.
#
# Held across re-read -> Sheet write -> sheets_row commit, not just the API
# call: _sync_card_to_sheets commits the row index after sync_card returns, so
# releasing in between would let a rewrite restamp the card and then have that
# background session commit its stale index back over the new one.
_sheets_lock = threading.Lock()

SHEET_HEADERS = [
    "Player", "Year", "Brand", "Set", "Card #", "Team",
    "RC", "Auto", "Patch", "Condition", "Listed Price",
    "eBay URL", "Status", "Date Listed", "Date Sold", "Sale Price", "Notes",
    "Quantity", "1st Bowman", "Parallel", "Serial #", "Refractor",
]

SHEET_TAB = "Inventory"


def _col_letter(n: int) -> str:
    """1-indexed column number -> A1 letter(s): 1->A, 19->S, 27->AA."""
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


END_COL = _col_letter(len(SHEET_HEADERS))  # keeps bounded ranges in sync with the row layout


def _get_service():
    """Build a Sheets API client. Returns None if not configured."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not raw or not sheet_id:
        return None, None

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds_info = json.loads(raw)
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return service, sheet_id
    except Exception as e:
        logger.warning("Google Sheets client init failed: %s", e)
        return None, None


def _card_to_row(card) -> list:
    """Convert a Card ORM instance into the canonical row layout."""
    return [
        card.player_name or "",
        card.year or "",
        card.brand or "",
        card.set_name or "",
        card.card_number or "",
        card.team or "",
        "Y" if card.is_rookie else "",
        "Y" if card.is_autograph else "",
        "Y" if card.is_patch else "",
        card.condition or "",
        card.listed_price if card.listed_price is not None else "",
        card.ebay_listing_url or "",
        (card.status or "").upper(),
        card.created_at.isoformat() if card.created_at else "",
        card.sold_at.isoformat() if card.sold_at else "",
        card.sold_price if card.sold_price is not None else "",
        card.notes or "",
        card.quantity if card.quantity is not None else 1,
        "Y" if card.is_first_bowman else "",
        card.parallel_color or "",
        card.serial_number or "",
        "Y" if card.is_refractor else "",
    ]


def _ensure_tab(service, sheet_id: str) -> bool:
    """Make sure the target tab exists in the spreadsheet. Creates it if missing.

    A fresh Google Sheet only has a default tab named 'Sheet1', so any
    reference to 'Inventory!...' would fail until we create it.
    """
    try:
        meta = service.spreadsheets().get(
            spreadsheetId=sheet_id,
            fields="sheets(properties(title))",
        ).execute()
        existing_titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if SHEET_TAB in existing_titles:
            return True
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": SHEET_TAB}}}]},
        ).execute()
        return True
    except Exception as e:
        logger.warning("Could not ensure '%s' tab exists: %s", SHEET_TAB, e)
        return False


def _ensure_header(service, sheet_id: str) -> None:
    """Write header row if the sheet is empty. Best-effort, never raises."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"{SHEET_TAB}!A1:{END_COL}1",
        ).execute()
        values = result.get("values")
        if not values or len(values[0]) < len(SHEET_HEADERS):
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{SHEET_TAB}!A1",
                valueInputOption="RAW",
                body={"values": [SHEET_HEADERS]},
            ).execute()
    except Exception as e:
        logger.warning("Sheets header check failed: %s", e)


def _last_used_row(service, sheet_id: str) -> int:
    """Last row holding any data, probed across every mirror column.

    Deliberately not `A:A`: the API omits trailing empty cells, so a residue row
    with an empty Player but stale data further right is invisible to a
    column-A probe and would survive the clear — exactly the bug being fixed.
    Returns 1 (header only) when the tab has no data rows.
    """
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"{SHEET_TAB}!A:{END_COL}",
    ).execute()
    values = result.get("values", []) or []
    last = 0
    for i, row in enumerate(values, start=1):
        if any(str(cell).strip() for cell in row):
            last = i
    return max(last, 1)


def rewrite_all_rows(cards) -> tuple:
    """Clear the data rows and rewrite the whole tab from `cards`, in order.

    Idempotent by construction — the clear precedes the write, so running it
    twice produces the same sheet. That is the property the old per-card
    append loop lacked, and why it duplicated the inventory on every press.

    Returns (rows, error) where `rows` is the list of 1-indexed row numbers
    assigned (parallel to `cards`) and `error` is None on success. On failure
    `rows` is None and `error` is one of:
      "unconfigured"  — no credentials; nothing happened
      "setup"         — tab/header/probe failed; nothing was cleared
      "cleared"       — the tab WAS cleared but the rewrite failed (sheet now
                        empty; caller must null every sheets_row)
    The caller needs these distinguished: "nothing happened" and "the tab was
    cleared but not rewritten" require opposite recovery.
    """
    service, sheet_id = _get_service()
    if service is None:
        return None, "unconfigured"

    rows = [_card_to_row(c) for c in cards]

    with _sheets_lock:
        try:
            if not _ensure_tab(service, sheet_id):
                return None, "setup"
            _ensure_header(service, sheet_id)
            used = _last_used_row(service, sheet_id)
        except Exception as e:
            logger.warning("Sheets rewrite setup failed: %s", e)
            return None, "setup"

        # Cover both the existing sheet and the incoming block, so a sheet
        # longer than the DB leaves no residue below the rewritten rows.
        # Never row 1 — the header is not ours to clear.
        clear_last = max(used, len(rows) + 1, 2)
        try:
            service.spreadsheets().values().clear(
                spreadsheetId=sheet_id,
                range=f"{SHEET_TAB}!A2:{END_COL}{clear_last}",
                body={},
            ).execute()
        except Exception as e:
            logger.warning("Sheets rewrite clear failed: %s", e)
            return None, "setup"  # nothing was cleared; safe to retry as-is

        if not rows:
            return [], None  # no cards: a cleared tab is the correct end state

        try:
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{SHEET_TAB}!A2",
                valueInputOption="RAW",
                body={"values": rows},
            ).execute()
        except Exception as e:
            logger.warning("Sheets rewrite update failed after clear: %s", e)
            return None, "cleared"

        return [i + 2 for i in range(len(rows))], None


def blank_row(row: int, is_owned) -> bool:
    """Blank one row in place, if no live card still claims it.

    Blanking rather than deleting keeps every other card's absolute
    `sheets_row` valid — removing a row shifts everything below it up and
    silently invalidates every later index.

    `is_owned(row)` is called under the lock and must report whether a live
    card currently claims that row: a rewrite may have reassigned it between
    the delete and this task, and row 7 looks identical either way. If it is
    owned, the blank is dropped rather than erasing a live card's data.
    """
    service, sheet_id = _get_service()
    if service is None or not row:
        return False

    with _sheets_lock:
        try:
            if is_owned(row):
                logger.info("Skipping blank of row %s — reassigned to a live card", row)
                return False
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{SHEET_TAB}!A{row}:{END_COL}{row}",
                valueInputOption="RAW",
                body={"values": [[""] * len(SHEET_HEADERS)]},
            ).execute()
            return True
        except Exception as e:
            # Accepted degradation: the card is gone, so there is nothing to
            # retry from. The residue is one stale row, which the now-idempotent
            # resync sweeps away.
            logger.warning("Sheets blank failed for row %s: %s", row, e)
            return False


def sync_card(card, reread_row=None) -> Optional[int]:
    """Append or update a row for this card. Returns the 1-indexed row number, or None.

    `reread_row` is an optional callable returning the card's current
    `sheets_row`; it is invoked *inside* the lock so a save that arrives
    mid-rewrite writes to the row the rewrite just assigned, instead of the
    stale one it read beforehand. Nothing is dropped, so no retry queue.
    """
    service, sheet_id = _get_service()
    if service is None:
        return None

    with _sheets_lock:
        try:
            if not _ensure_tab(service, sheet_id):
                return None
            _ensure_header(service, sheet_id)
            row_values = _card_to_row(card)
            sheets_row = reread_row() if reread_row is not None else card.sheets_row

            if sheets_row:
                # Update in place
                service.spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range=f"{SHEET_TAB}!A{sheets_row}:{END_COL}{sheets_row}",
                    valueInputOption="RAW",
                    body={"values": [row_values]},
                ).execute()
                return sheets_row
            else:
                # Append and figure out which row it landed on
                resp = service.spreadsheets().values().append(
                    spreadsheetId=sheet_id,
                    range=f"{SHEET_TAB}!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row_values]},
                ).execute()
                updated_range = resp.get("updates", {}).get("updatedRange", "")
                # updatedRange looks like "Inventory!A5:S5" — pull the row number
                try:
                    row_part = updated_range.split("!")[1]
                    row_num = int("".join(ch for ch in row_part.split(":")[0] if ch.isdigit()))
                    return row_num
                except (IndexError, ValueError):
                    return None
        except Exception as e:
            logger.warning("Sheets sync failed for card %s: %s", getattr(card, "id", "?"), e)
            return None
