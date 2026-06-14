"""Mavin.io scraper for recent sold comps.

Mavin's HTML structure is brittle so this layer is intentionally defensive: any
parsing failure or empty result triggers a clean fallback rather than an exception.
"""
import statistics
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MOCK_PRICE = 9.99


def _build_query(
    year: Optional[int],
    brand: Optional[str],
    player_name: Optional[str],
    set_name: Optional[str],
    card_number: Optional[str],
) -> str:
    parts = [str(p) for p in (year, brand, player_name, set_name, card_number) if p]
    return " ".join(parts).strip()


def _parse_price(text: str) -> Optional[float]:
    """Extract first dollar amount from a string like '$12.50' or 'Sold for $9.99'."""
    cleaned = text.replace(",", "").strip()
    if "$" not in cleaned:
        return None
    try:
        after = cleaned.split("$", 1)[1]
        # Stop at first non-price character
        num = ""
        for ch in after:
            if ch.isdigit() or ch == ".":
                num += ch
            else:
                break
        return float(num) if num else None
    except (ValueError, IndexError):
        return None


def fetch_mavin_comps(
    player_name: str,
    year: Optional[int] = None,
    brand: Optional[str] = None,
    set_name: Optional[str] = None,
    card_number: Optional[str] = None,
) -> Tuple[List[dict], Optional[float], str, Optional[str]]:
    """Returns (comps, suggested_price, source, note).

    source is "mavin", "mock", or "none".
    """
    query = _build_query(year, brand, player_name, set_name, card_number)
    if not query:
        return [], None, "none", "Empty query."

    url = f"https://www.mavin.io/searches?q={quote_plus(query)}"

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        return [], None, "none", f"Mavin request failed ({e})."

    soup = BeautifulSoup(html, "html.parser")

    comps: List[dict] = []

    # Mavin's markup uses class names like "item" or "result" with price elements.
    # We try a few selectors to be resilient to minor template tweaks.
    candidates = soup.select(".item, .result, .search-result, li.product")
    if not candidates:
        # Last-ditch: scan every element with a price-looking child
        candidates = soup.find_all(lambda tag: tag.name in ("li", "div") and "$" in tag.get_text())

    for el in candidates[:20]:
        text = el.get_text(" ", strip=True)
        price = _parse_price(text)
        if price is None or price <= 0:
            continue
        title_el = el.find(["h3", "h4", "a", "span"])
        title = title_el.get_text(strip=True) if title_el else text[:120]
        comps.append({"title": title[:200], "price": price})
        if len(comps) >= 10:
            break

    if not comps:
        return [], None, "none", "Mavin returned no recent sales."

    prices = [c["price"] for c in comps]
    suggested = round(statistics.median(prices), 2)
    return comps, suggested, "mavin", None
