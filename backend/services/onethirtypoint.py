"""130point.com sold-listings scraper.

130point aggregates eBay sold comps specifically for trading cards, so it's
usually the highest-signal source for our use case. Their server isn't as
aggressive about blocking automated requests as eBay direct, which is why
this exists as a layer between Mavin and the eBay scraper.

Defensive parsing: 130point's HTML may shift over time so we try multiple
selectors and fall back to a "find any element with a price near a title"
heuristic before giving up.
"""
import statistics
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from .pricing_utils import PRICE_RE, build_query, parse_price

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

def _extract_comps_from_html(html: str) -> List[dict]:
    """Best-effort parse. Tries structured selectors first, then a fallback heuristic."""
    soup = BeautifulSoup(html, "html.parser")
    comps: List[dict] = []

    # --- Path A: structured table rows (most common 130point layout) ---
    for row in soup.select("table tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        row_text = row.get_text(" ", strip=True)
        if "$" not in row_text:
            continue

        # Title is usually the longest text cell; price is the cell containing "$"
        title_text = ""
        price_value = None
        for cell in cells:
            text = cell.get_text(" ", strip=True)
            if "$" in text and price_value is None:
                price_value = parse_price(text)
            elif len(text) > len(title_text):
                title_text = text

        if price_value and title_text:
            comps.append({"title": title_text[:200], "price": price_value})
            if len(comps) >= 10:
                return comps

    if comps:
        return comps

    # --- Path B: card-style result blocks ---
    for el in soup.select(".result, .sale, .item, .listing, li.product, div.card-result"):
        text = el.get_text(" ", strip=True)
        price = parse_price(text)
        if not price:
            continue
        title_el = el.find(["h3", "h4", "a", "span"])
        title = title_el.get_text(strip=True) if title_el else text[:120]
        comps.append({"title": title[:200], "price": price})
        if len(comps) >= 10:
            return comps

    if comps:
        return comps

    # --- Path C: last-ditch heuristic ---
    # Find any small/medium element that contains a price; use surrounding text as title.
    for el in soup.find_all(["li", "div", "tr"]):
        text = el.get_text(" ", strip=True)
        if len(text) < 10 or len(text) > 400:
            continue
        if "$" not in text:
            continue
        price = parse_price(text)
        if not price:
            continue
        # Skip elements that contain a bunch of other priced children — we want leaves.
        if len(el.find_all(string=PRICE_RE)) > 2:
            continue
        comps.append({"title": text[:200], "price": price})
        if len(comps) >= 10:
            break

    return comps


def fetch_130point_comps(
    player_name: str,
    year: Optional[int] = None,
    brand: Optional[str] = None,
    set_name: Optional[str] = None,
    card_number: Optional[str] = None,
) -> Tuple[List[dict], Optional[float], Optional[str]]:
    """Returns (comps, suggested_price, note). suggested_price is None if no comps."""
    query = build_query(year, brand, player_name, set_name, card_number)
    if not query:
        return [], None, "Empty query — cannot search 130point."

    # 130point exposes a search page that takes a `query` parameter. They've used
    # several URL shapes over the years; this is the most stable one currently.
    url = f"https://www.130point.com/sales/?query={quote_plus(query)}&sortBy=date&sortOrder=desc"

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url, headers=BROWSER_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as e:
        return [], None, f"blocked (HTTP {e.response.status_code})"
    except Exception as e:
        return [], None, f"request failed ({type(e).__name__})"

    comps = _extract_comps_from_html(html)
    if not comps:
        return [], None, "130point returned no recent sales for this query."

    prices = [c["price"] for c in comps]
    suggested = round(statistics.median(prices), 2)
    return comps, suggested, None