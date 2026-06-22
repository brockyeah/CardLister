"""eBay API pricing — the reliable replacement for the HTML scrapers.

This is a *scaffold*: it is fully wired into the pricing chain but stays dormant
until eBay developer credentials are configured. With no creds it returns an
empty result + an explanatory note, so the chain falls through to the existing
scrapers exactly as before — nothing breaks while the eBay dev account is
pending.

When you have credentials, set:
  EBAY_APP_ID    — your App ID (OAuth client_id)
  EBAY_CERT_ID   — your Cert ID (OAuth client_secret)
  EBAY_MARKETPLACE_ID (optional, default EBAY_US)
  EBAY_ENV       (optional, "production" [default] or "sandbox")

Auth: OAuth 2.0 client-credentials grant → a short-lived application token
(cached here until ~1 min before expiry). No user consent needed for Browse.

⚠️ Active vs. sold:
  The **Browse API** (used here) searches *active* listings — a reasonable price
  proxy and what a standard dev account can call. True *sold* comps come from the
  **Marketplace Insights API** (item_sales/search), which requires a separate
  gated access grant from eBay. Once that's approved, flip USE_MARKETPLACE_INSIGHTS
  (see _search_path) — the request/parse shape is nearly identical.
"""
import base64
import logging
import os
import statistics
import time
from typing import List, Optional, Tuple

import httpx

from .pricing_utils import build_query

logger = logging.getLogger(__name__)

# 261328 = Sports Trading Cards > Baseball.
EBAY_BASEBALL_CATEGORY = "261328"

_OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"

# Cached application token: {"token": str, "expires_at": epoch_seconds}
_token_cache: dict = {}


def _base_url() -> str:
    if os.getenv("EBAY_ENV", "production").strip().lower() == "sandbox":
        return "https://api.sandbox.ebay.com"
    return "https://api.ebay.com"


def _credentials() -> Optional[Tuple[str, str]]:
    app_id = os.getenv("EBAY_APP_ID")
    cert_id = os.getenv("EBAY_CERT_ID")
    if app_id and cert_id:
        return app_id, cert_id
    return None


def is_configured() -> bool:
    return _credentials() is not None


def _get_app_token() -> Optional[str]:
    """Return a cached or freshly-minted application access token, or None."""
    creds = _credentials()
    if creds is None:
        return None

    now = time.time()
    cached = _token_cache.get("token")
    if cached and _token_cache.get("expires_at", 0) > now + 60:
        return cached

    app_id, cert_id = creds
    basic = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{_base_url()}/identity/v1/oauth2/token",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials", "scope": _OAUTH_SCOPE},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as e:
        logger.warning("eBay OAuth token request failed: %s", e)
        return None

    token = payload.get("access_token")
    if not token:
        return None
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + int(payload.get("expires_in", 7200))
    return token


def fetch_ebay_api_comps(
    player_name: str,
    year: Optional[int] = None,
    brand: Optional[str] = None,
    set_name: Optional[str] = None,
    card_number: Optional[str] = None,
    limit: int = 20,
) -> Tuple[List[dict], Optional[float], Optional[str]]:
    """Returns (comps, suggested_price, note), matching the scraper interface.

    suggested_price is None when there are no comps. Never raises — any failure
    degrades to ([], None, note) so the pricing chain can fall through.
    """
    if not is_configured():
        return [], None, "eBay API not configured (set EBAY_APP_ID and EBAY_CERT_ID)."

    query = build_query(year, brand, player_name, set_name, card_number)
    if not query:
        return [], None, "Empty query — cannot search eBay API."

    token = _get_app_token()
    if not token:
        return [], None, "eBay API auth failed — check EBAY_APP_ID / EBAY_CERT_ID."

    marketplace = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    url = f"{_base_url()}/buy/browse/v1/item_summary/search"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace,
                },
                params={
                    "q": query,
                    "category_ids": EBAY_BASEBALL_CATEGORY,
                    "limit": str(limit),
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return [], None, f"eBay API error (HTTP {e.response.status_code})."
    except Exception as e:
        return [], None, f"eBay API request failed ({type(e).__name__})."

    comps: List[dict] = []
    for item in data.get("itemSummaries", []):
        price = item.get("price", {}) or {}
        try:
            value = float(price.get("value"))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        title = (item.get("title") or "")[:200]
        comps.append({"title": title, "price": value})
        if len(comps) >= 10:
            break

    if not comps:
        return [], None, "eBay API returned no listings for this query."

    suggested = round(statistics.median(c["price"] for c in comps), 2)
    return comps, suggested, None
