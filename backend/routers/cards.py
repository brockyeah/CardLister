"""Card CRUD endpoints. All routes require auth."""
import csv
import io
import math
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth import require_auth
from ..models import Card, Scan
from ..schemas import (
    CardCreate, CardUpdate, CardOut,
    DuplicateCheckRequest, DuplicateCheckResponse,
    EbayListingUpdate, MarkSoldRequest,
)
from ..services.google_sheets import SHEET_HEADERS, _card_to_row, sync_card
from ..services.learning import record_correction

router = APIRouter(dependencies=[Depends(require_auth)])


def _sync_card_to_sheets(card_id: int) -> None:
    """Background task: mirror a card to Google Sheets and persist its row index.

    Runs after the response is sent, on its own DB session — the request-scoped
    session is already closed by then. Sheets failures are swallowed inside
    sync_card, so a slow or failing Google API call never delays or breaks the
    user's save.
    """
    db = SessionLocal()
    try:
        card = db.query(Card).filter(Card.id == card_id).first()
        if card is None:
            return
        row = sync_card(card)
        if row and card.sheets_row != row:
            card.sheets_row = row
            db.commit()
    finally:
        db.close()


@router.get("", response_model=List[CardOut])
def list_cards(
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    team: Optional[str] = None,
    year: Optional[int] = None,
    player_name: Optional[str] = None,
):
    q = db.query(Card)
    if status:
        q = q.filter(Card.status == status)
    if team:
        q = q.filter(Card.team.ilike(f"%{team}%"))
    if year:
        q = q.filter(Card.year == year)
    if player_name:
        q = q.filter(Card.player_name.ilike(f"%{player_name}%"))
    return q.order_by(Card.created_at.desc()).all()


# Spreadsheet apps execute cells starting with these as formulas, so a crafted
# Notes value like "=HYPERLINK(...)" in an exported CSV could run in Excel.
# The Sheets mirror is unaffected (rows are written with valueInputOption=RAW).
_FORMULA_CHARS = ("=", "+", "-", "@")


def _needs_formula_escape(value: str) -> bool:
    # Apostrophe-lead values like "'-1/1 SP" must be escaped too — otherwise
    # the import-side unescape couldn't tell a user's literal apostrophe from
    # one the exporter added, and would strip it (round-trip corruption).
    return value.lstrip("'").startswith(_FORMULA_CHARS)


def _escape_formula_cell(value):
    if isinstance(value, str) and _needs_formula_escape(value):
        return "'" + value
    return value


def _unescape_formula_cell(value: str) -> str:
    if value.startswith("'") and _needs_formula_escape(value[1:]):
        return value[1:]
    return value


# Must be declared before GET /{card_id} — "export.csv" would otherwise 422
# against the int path param.
@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    """Full inventory as CSV, same column layout as the Sheets mirror."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SHEET_HEADERS)
    for card in db.query(Card).order_by(Card.created_at.asc()).all():
        writer.writerow([_escape_formula_cell(cell) for cell in _card_to_row(card)])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cardlister-inventory.csv"'},
    )


MAX_IMPORT_ROWS = 5000
_TRUTHY = {"y", "yes", "true", "1"}
_VALID_STATUSES = {"unlisted", "active", "sold"}

# Header name (lowercased) -> Card field, for columns that need no conversion.
# Includes aliases beyond the canonical export layout so hand-edited sheets
# with e.g. a "Parallel" column import without renaming.
_IMPORT_STR_FIELDS = {
    "brand": "brand", "set": "set_name", "card #": "card_number",
    "team": "team", "notes": "notes",
    "parallel": "parallel_color", "parallel color": "parallel_color",
    "serial": "serial_number", "serial #": "serial_number",
    "serial number": "serial_number",
}
_IMPORT_FLAG_FIELDS = {
    "rc": "is_rookie", "auto": "is_autograph", "patch": "is_patch",
    "1st bowman": "is_first_bowman", "refractor": "is_refractor",
}


def _parse_date(raw: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_int(raw: str) -> int:
    # Python ints are unbounded but SQLite's INTEGER binding is 64-bit; an
    # out-of-range value (say, a serial number pasted into the Year column)
    # would otherwise blow up as OverflowError at commit, aborting the whole
    # batch instead of skipping the one row.
    value = int(raw)
    if not -(2**63) <= value < 2**63:
        raise ValueError("value out of range")
    return value


def _parse_money(raw: str) -> float:
    value = float(raw.replace("$", "").replace(",", ""))
    if not math.isfinite(value):
        raise ValueError("value must be a finite number")
    if value < 0:
        # Card(**fields) below skips the CardCreate/MarkSoldRequest validators,
        # so the ge=0 price rule has to be enforced here too.
        raise ValueError("value must not be negative")
    return value


@router.post("/import.csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Bulk-create cards from a CSV in the export/Sheets column layout.

    Columns are matched by header name (case-insensitive), so column order
    doesn't matter and unknown columns are ignored. A bad row is skipped and
    reported with its line number; it never aborts the rest of the file.
    The Sheets mirror is NOT touched here — bulk-appending hundreds of rows
    through the per-card sync would hammer the Sheets API; imported cards
    sync individually on their next edit.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # -sig: tolerate Excel's BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File is not UTF-8 text — export a plain CSV and retry")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise HTTPException(status_code=422, detail="Empty file")
    idx = {name.strip().lower(): i for i, name in enumerate(rows[0])}
    if "player" not in idx:
        raise HTTPException(
            status_code=422,
            detail="First row must be a header row including a 'Player' column (use the CSV export as a template)",
        )
    if len(rows) - 1 > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=422, detail=f"Too many rows (max {MAX_IMPORT_ROWS})")

    created = 0
    skipped: list[dict] = []
    warnings: list[str] = []

    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # blank line

        def val(name: str) -> str:
            i = idx.get(name)
            if i is None or i >= len(row):
                return ""
            # Undo the export's formula-injection escape so values round-trip.
            return _unescape_formula_cell(row[i].strip())

        player = val("player")
        if not player:
            skipped.append({"row": line_no, "reason": "missing player name"})
            continue

        fields = {"player_name": player, "condition": val("condition") or "NM"}
        try:
            fields["year"] = _parse_int(val("year")) if val("year") else None
            fields["listed_price"] = _parse_money(val("listed price")) if val("listed price") else None
            fields["sold_price"] = _parse_money(val("sale price")) if val("sale price") else None
            fields["quantity"] = max(1, _parse_int(val("quantity"))) if val("quantity") else 1
        except ValueError as e:
            skipped.append({"row": line_no, "reason": f"bad number: {e}"})
            continue

        status = val("status").lower() or "unlisted"
        if status not in _VALID_STATUSES:
            skipped.append({"row": line_no, "reason": f"invalid status {val('status')!r}"})
            continue
        if status == "sold" and not fields["sold_price"]:
            # Card(**fields) bypasses MarkSoldRequest's sold_price > 0 rule; a
            # sold row without a real sale price corrupts revenue analytics
            # and the CSV export, so enforce the same rule here.
            skipped.append({"row": line_no, "reason": "sold row needs a Sale Price greater than 0"})
            continue
        fields["status"] = status

        for col, field in _IMPORT_STR_FIELDS.items():
            if val(col):
                fields[field] = val(col)
        for col, field in _IMPORT_FLAG_FIELDS.items():
            fields[field] = val(col).lower() in _TRUTHY

        # Same policy as the attach-listing endpoint: the URL is rendered as a
        # clickable link, so only https:// values are allowed through.
        url = val("ebay url")
        if url and not url.startswith("https://"):
            warnings.append(f"row {line_no}: non-https eBay URL dropped")
            url = ""
        if url:
            fields["ebay_listing_url"] = url

        for col, field in (("date listed", "created_at"), ("date sold", "sold_at")):
            if val(col):
                parsed = _parse_date(val(col))
                if parsed is None:
                    warnings.append(f"row {line_no}: unparseable {col} ignored")
                else:
                    fields[field] = parsed

        if status == "sold" and "sold_at" not in fields:
            # Same default as mark-sold: a sold card always carries a sale date.
            fields["sold_at"] = datetime.utcnow()
            warnings.append(f"row {line_no}: sold row missing Date Sold — set to today")

        db.add(Card(**fields))
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped, "warnings": warnings}


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


@router.post("/check-duplicate", response_model=DuplicateCheckResponse)
def check_duplicate(payload: DuplicateCheckRequest, db: Session = Depends(get_db)):
    """Find an owned (non-sold) copy of the same physical card.

    Identity fields match case/whitespace-insensitively; parallel, serial, and
    print flags must also agree so a Gold /50 never merges with the base card.
    Condition is deliberately NOT matched — vision-extracted condition is too
    noisy to gate on, and the user confirms in the UI before anything merges.
    """
    if not _norm(payload.player_name):
        return DuplicateCheckResponse(duplicate=None)
    q = db.query(Card).filter(
        Card.status != "sold",
        func.lower(func.trim(Card.player_name)) == _norm(payload.player_name),
        func.lower(func.trim(Card.brand)) == _norm(payload.brand),
        func.lower(func.trim(Card.set_name)) == _norm(payload.set_name),
        func.lower(func.trim(Card.card_number)) == _norm(payload.card_number),
        Card.year == payload.year,
        Card.is_autograph == payload.is_autograph,
        Card.is_patch == payload.is_patch,
        Card.is_refractor == payload.is_refractor,
        Card.is_first_bowman == payload.is_first_bowman,
    )
    # Parallel/serial live in nullable text columns where "" and NULL are
    # interchangeable — normalize in Python rather than fighting SQL nulls.
    for card in q.order_by(Card.created_at.desc()).all():
        if (_norm(card.parallel_color) == _norm(payload.parallel_color)
                and _norm(card.serial_number) == _norm(payload.serial_number)):
            return DuplicateCheckResponse(duplicate=card)
    return DuplicateCheckResponse(duplicate=None)


@router.get("/{card_id}", response_model=CardOut)
def get_card(card_id: int, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.post("", response_model=CardOut)
def create_card(payload: CardCreate, background_tasks: BackgroundTasks,
                username: str = Depends(require_auth), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"scan_id"})
    card = Card(**data)
    # Anything saved here is going on eBay next, so always mark it "active".
    card.status = "active"
    db.add(card)
    db.commit()
    db.refresh(card)
    # Learning: diff what the model extracted vs. what the user actually saved.
    if payload.scan_id:
        scan = db.query(Scan).filter(Scan.id == payload.scan_id).first()
        if scan is not None:
            record_correction(db, scan, data, card.id, username)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card


@router.patch("/{card_id}", response_model=CardOut)
def update_card(card_id: int, payload: CardUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(card, k, v)
    db.commit()
    db.refresh(card)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card


@router.delete("/{card_id}")
def delete_card(card_id: int, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(card)
    db.commit()
    return {"ok": True}


@router.post("/{card_id}/ebay-id", response_model=CardOut)
def attach_ebay_listing(card_id: int, payload: EbayListingUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """User pastes back the eBay listing ID + URL after publishing."""
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.ebay_listing_id = payload.ebay_listing_id
    card.ebay_listing_url = payload.ebay_listing_url
    db.commit()
    db.refresh(card)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card


@router.post("/{card_id}/mark-sold", response_model=CardOut)
def mark_sold(card_id: int, payload: MarkSoldRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    card.status = "sold"
    card.sold_price = payload.sold_price
    card.sold_at = payload.sold_at or datetime.utcnow()
    db.commit()
    db.refresh(card)
    background_tasks.add_task(_sync_card_to_sheets, card.id)
    return card
