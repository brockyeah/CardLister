"""eBay sold-listings scraper — fallback when Mavin returns nothing.

We scrape the public sold-listings search page (no API key required). eBay
returns far more reliable comps than Mavin for modern cards because they ARE
the marketplace; Mavin aggregates other sites and often misses.
"""
import statistics
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from .pricing_utils import build_query, parse_price

# Full browser-like headers — eBay returns 403 for minimal header sets.
# This is still vulnerable to deeper anti-bot measures; if scraping breaks
# regularly the proper fix is to use eBay's Browse API with EBAY_APP_ID.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# 261328 = Sports Trading Cards > Baseball. Keeps results sport-specific.
EBAY_BASEBALL_CATEGORY = "261328"


def fetch_ebay_sold_comps(
    player_name: str,
    year: Optional[int] = None,
    brand: Optional[str] = None,
    set_name: Optional[str] = None,
    card_number: Optional[str] = None,
) -> Tuple[List[dict], Optional[float], Optional[str]]:
    """Returns (comps, suggested_price, note). suggested_price is None if no comps."""
    query = build_query(year, brand, player_name, set_name, card_number)
    if not query:
        return [], None, "Empty query — cannot search eBay."

    url = (
        f"https://www.ebay.com/sch/i.html"
        f"?_nkw={quote_plus(query)}"
        f"&_sacat={EBAY_BASEBALL_CATEGORY}"
        f"&LH_Sold=1"
        f"&LH_Complete=1"
    )

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers=BROWSER_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as e:
        return [], None, f"blocked (HTTP {e.response.status_code})"
    except Exception as e:
        return [], None, f"request failed ({type(e).__name__})"

    soup = BeautifulSoup(html, "html.parser")

    comps: List[dict] = []

    # Each search result is an <li class="s-item">. The first item is sometimes
    # a "Shop on eBay" placeholder template — we skip any title containing that.
    items = soup.select("li.s-item")
    for item in items:
        title_el = item.select_one(".s-item__title")
        price_el = item.select_one(".s-item__price")
        if not title_el or not price_el:
            continue

        title = title_el.get_text(" ", strip=True)
        if "Shop on eBay" in title:
            continue

        price = parse_price(price_el.get_text(" ", strip=True))
        if price is None or price <= 0:
            continue

        comps.append({"title": title[:200], "price": price})
        if len(comps) >= 10:
            break

    if not comps:
        return [], None, "eBay returned no sold listings for this query."

    prices = [c["price"] for c in comps]
    suggested = round(statistics.median(prices), 2)
    return comps, suggested, None
