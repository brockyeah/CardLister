"""Shared helpers for the pricing scrapers (130point, Mavin, eBay).

These were duplicated verbatim across all three scraper modules; centralising
them keeps the query format and price parsing consistent.
"""
import re
from typing import Optional

PRICE_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)")


def build_query(
    year: Optional[int],
    brand: Optional[str],
    player_name: Optional[str],
    set_name: Optional[str],
    card_number: Optional[str],
) -> str:
    """Join the populated card attributes into a single search string."""
    parts = [str(p) for p in (year, brand, player_name, set_name, card_number) if p]
    return " ".join(parts).strip()


def parse_price(text: str) -> Optional[float]:
    """Extract the first positive dollar amount from a string.

    Handles '$12.50', 'Sold for $9.99', '$10.00 to $15.00' (takes the lower
    bound) and '$1,250.00' (commas stripped first). Returns None when there is
    no parseable, positive amount.
    """
    if not text:
        return None
    match = PRICE_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if value > 0 else None
