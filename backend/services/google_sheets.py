"""Google Sheets sync.

Sheets is a secondary mirror of the SQLite DB. Failures here are logged
and swallowed — they must never fail the primary API request.
"""
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

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


def sync_card(card) -> Optional[int]:
    """Append or update a row for this card. Returns the 1-indexed row number, or None."""
    service, sheet_id = _get_service()
    if service is None:
        return None

    try:
        if not _ensure_tab(service, sheet_id):
            return None
        _ensure_header(service, sheet_id)
        row_values = _card_to_row(card)

        if card.sheets_row:
            # Update in place
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{SHEET_TAB}!A{card.sheets_row}:{END_COL}{card.sheets_row}",
                valueInputOption="RAW",
                body={"values": [row_values]},
            ).execute()
            return card.sheets_row
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
