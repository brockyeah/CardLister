"""Pricing endpoint.

We try multiple sources in order of expected quality, falling back when each
one returns nothing. No single source is reliable for every card:

  1. 130point — aggregates eBay sold comps specifically for trading cards.
     Highest signal when it works, less aggressively blocked than eBay direct.
  2. Mavin — broader aggregator; patchy on modern releases but sometimes has
     comps the card-specific sources miss.
  3. eBay direct sold listings — canonical source but their anti-bot will
     usually 403 from a datacenter IP. Kept in the chain so it works if/when
     we add a proxy or run from a residential IP.
  4. Mock $9.99 — last resort so the form still has SOMETHING for the user
     to override, with a note explaining why.
"""
from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..schemas import PricingRequest, PricingResponse
from ..services.onethirtypoint import fetch_130point_comps
from ..services.mavin import fetch_mavin_comps, MOCK_PRICE
from ..services.ebay_pricing import fetch_ebay_sold_comps

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("", response_model=PricingResponse)
def get_pricing(payload: PricingRequest):
    args = dict(
        player_name=payload.player_name,
        year=payload.year,
        brand=payload.brand,
        set_name=payload.set_name,
        card_number=payload.card_number,
    )

    # 1) 130point — card-specific eBay sold-comps aggregator
    op_comps, op_price, op_note = fetch_130point_comps(**args)
    if op_comps:
        return PricingResponse(
            comps=op_comps,
            suggested_price=op_price,
            source="130point",
            note=None,
        )

    # 2) Mavin — broader aggregator
    mavin_comps, mavin_price, mavin_source, mavin_note = fetch_mavin_comps(**args)
    if mavin_source == "mavin" and mavin_comps:
        return PricingResponse(
            comps=mavin_comps,
            suggested_price=mavin_price,
            source="mavin",
            note="130point had no comps — using Mavin.",
        )

    # 3) eBay direct
    ebay_comps, ebay_price, ebay_note = fetch_ebay_sold_comps(**args)
    if ebay_comps:
        return PricingResponse(
            comps=ebay_comps,
            suggested_price=ebay_price,
            source="ebay_sold",
            note="130point + Mavin had no comps — using eBay sold listings.",
        )

    # 4) Mock with a transparent explanation of what failed
    parts = []
    if op_note:
        parts.append(f"130point: {op_note}")
    if mavin_note:
        parts.append(f"Mavin: {mavin_note}")
    if ebay_note:
        parts.append(f"eBay: {ebay_note}")
    note = " | ".join(parts) or "No comps found anywhere — please price manually."

    return PricingResponse(
        comps=[],
        suggested_price=MOCK_PRICE,
        source="mock",
        note=note,
    )
