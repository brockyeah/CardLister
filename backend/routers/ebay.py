"""eBay listing text builder.

eBay's pre-fill URL params no longer reliably populate the sell form, so the
working flow is a clipboard hand-off: we build the title + description + price
and the user pastes them into eBay's sell page. Direct API listing is Phase 2.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Card

router = APIRouter(dependencies=[Depends(require_auth)])

EBAY_TITLE_MAX = 80


def build_title(card: Card) -> str:
    """{year} {brand} {set_name} {player_name} #{card_number} {flags} {team} — capped at 80 chars."""
    flags = []
    if card.is_rookie:
        flags.append("RC")
    if card.is_first_bowman:
        flags.append("1ST BOWMAN")
    if card.is_autograph:
        flags.append("AUTO")
    if card.is_patch:
        flags.append("PATCH")
    if card.is_refractor:
        flags.append("REFRACTOR")
    if card.serial_number:
        # Normalise so '/99' or '99' both render as '/99'
        sn = card.serial_number.strip()
        if sn:
            flags.append(sn if sn.startswith("/") else f"/{sn}")
    if card.parallel_color:
        flags.append(card.parallel_color.upper())

    card_no = f"#{card.card_number}" if card.card_number else ""
    # Units the title may be cut between, in title order. Free-text fields
    # contribute one unit per word (a prefix of a set or player name is still
    # true of the card), while each flag is a single indivisible unit even when
    # it contains a space — "1ST BOWMAN" cut to "1ST" is not a shorter way of
    # saying it, just a fragment. Splitting here also collapses the internal
    # whitespace the old " ".join(title.split()) pass did.
    units = []
    for text in (
        str(card.year) if card.year else "",
        card.brand or "",
        card.set_name or "",
        card.player_name or "",
        card_no,
    ):
        units.extend(text.split())
    units.extend(" ".join(flag.split()) for flag in flags)
    units.extend((card.team or "").split())
    return truncate_title(units)


def truncate_title(units: list) -> str:
    """Join title units, dropping whole units that don't fit inside the cap.

    A bare `title[:80]` slices wherever the 80th character lands, and the
    things that get sliced are what carry the card's identity: a `/99` serial
    becomes `/9`, `REFRACTOR` becomes `REFRACTO`, `1ST BOWMAN` becomes `1ST`.
    Those are not shortened titles, they are *wrong* ones — a buyer searching
    `/9` finds a listing for a card numbered to 99, and the seller has
    advertised something they do not own. Dropping the whole unit instead is an
    honest omission: the title says less, but nothing it says is false. This
    matters because the title is the product — it goes on the clipboard and
    straight into eBay's sell form.

    Stops at the first unit that doesn't fit rather than skipping ahead to a
    shorter one, so a lower-priority flag can never jump in front of a
    higher-priority one that was dropped (the flag order is deliberate — see
    test_first_bowman.py).

    Note this only changes *how* an over-long title is cut, not the field or
    flag order that decides what gets cut first (invariant #7 — the format
    itself is a deliberate three-file change and is not what this fixes).
    """
    kept = ""
    for unit in units:
        candidate = f"{kept} {unit}" if kept else unit
        if len(candidate) > EBAY_TITLE_MAX:
            # A first unit longer than the cap has no boundary to fall back to,
            # so the hard slice is the only option left — better a clipped
            # 80-character set name than an empty title.
            return kept or unit[:EBAY_TITLE_MAX].rstrip()
        kept = candidate
    return kept


def build_description(card: Card) -> str:
    """Plaintext multiline description listing every attribute."""
    lines = [
        f"Player: {card.player_name}",
        f"Year: {card.year or ''}",
        f"Brand: {card.brand or ''}",
        f"Set: {card.set_name or ''}",
        f"Card Number: {card.card_number or ''}",
        f"Team: {card.team or ''}",
        f"Condition: {card.condition or ''}",
    ]
    if card.quantity and card.quantity > 1:
        lines.append(f"Quantity available: {card.quantity}")
    if card.is_rookie:
        lines.append("Rookie Card: YES")
    if card.is_first_bowman:
        lines.append("1st Bowman: YES")
    if card.is_autograph:
        lines.append("Autograph: YES")
    if card.is_patch:
        lines.append("Patch: YES")
    if card.is_refractor:
        lines.append("Refractor: YES")
    if card.parallel_color:
        lines.append(f"Parallel: {card.parallel_color}")
    if card.serial_number:
        lines.append(f"Serial Number: {card.serial_number}")
    if card.notes:
        lines.append("")
        lines.append(f"Notes: {card.notes}")
    lines.append("")
    lines.append("Ships in a protective sleeve and top loader. Combined shipping available.")
    return "\n".join(lines)


@router.get("/{card_id}/listing-text")
def ebay_listing_text(card_id: int, db: Session = Depends(get_db)):
    """Return title + description + price as plain text, ready to paste into eBay.

    eBay's pre-fill URL params no longer reliably populate the sell form (the link
    just lands you on eBay's listing page with an empty form). Until we implement
    the eBay Sell API (Phase 2), the working flow is: copy this text to clipboard,
    open eBay's sell page, paste title and description in manually.
    """
    card = db.query(Card).filter(Card.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    title = build_title(card)
    description = build_description(card)
    price = card.listed_price if card.listed_price is not None else (card.suggested_price or 0)

    return {
        "title": title,
        "description": description,
        "price": round(float(price), 2),
        # Pre-baked text ready for navigator.clipboard.writeText on the frontend.
        # Two newlines between sections so it's easy to grab one piece at a time.
        "clipboard_text": (
            f"TITLE:\n{title}\n\n"
            f"PRICE:\n${price:.2f}\n\n"
            f"DESCRIPTION:\n{description}"
        ),
        "ebay_sell_url": "https://www.ebay.com/sl/sell",
    }


# TODO (Phase 2): Replace clipboard workaround with eBay Sell API direct draft creation.
#   Requires: eBay developer account, registered app, OAuth user consent flow,
#   token storage, calls to /sell/inventory/v1/inventory_item + /sell/inventory/v1/offer.
# TODO (Phase 2): Orders API polling job to auto-mark cards sold.
