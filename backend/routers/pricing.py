"""Pricing endpoint.

Multiple sources, tried in order of expected quality. No single source is
reliable for every card:

  0. eBay API — the reliable source once credentials are configured. Dormant
     (returns nothing) until EBAY_APP_ID / EBAY_CERT_ID are set.
  1. 130point — aggregates eBay sold comps specifically for trading cards.
     Highest signal when it works, less aggressively blocked than eBay direct.
  2. Mavin — broader aggregator; patchy on modern releases but sometimes has
     comps the card-specific sources miss.
  3. eBay direct sold listings (scrape) — canonical source but their anti-bot
     will usually 403 from a datacenter IP. Kept as a fallback.
  4. Mock $9.99 — last resort so the form still has SOMETHING for the user
     to override, with a note explaining why.

The order expresses PREFERENCE, not dependency: no source's input comes from
another's output. They therefore run concurrently, and the winner is chosen by
walking this list — never by whoever finishes first, which would let a weak
source beat a strong slow one. Serially the user paid the sum of four timeouts
(15 + 20 + 15 + 15s), and on Railway — where the scrapers routinely 403 — the
common case was the worst case, on every card.

Two deliberate choices worth keeping:

* Resolution waits on each future in preference order rather than calling
  `concurrent.futures.wait(...)` first. `wait()` defaults to ALL_COMPLETED, so
  waiting up front would make *every* lookup as slow as the slowest source and
  give back most of the win.
* The executor is per-request and shut down without waiting, so pools do not
  accumulate across requests. Note what this does NOT buy: `cancel_futures`
  cannot cancel work already running, and the workers are non-daemon, so the
  interpreter still joins an abandoned source at exit. The real bound on
  shutdown is each source's own network timeout — which is why those must stay
  bounded, and why a module-level pool would be strictly worse (its workers
  outlive every request, not just one).
"""
import concurrent.futures
import logging
import time

from fastapi import APIRouter, Depends

from ..auth import require_auth
from ..schemas import PricingRequest, PricingResponse
from ..services.ebay_api import fetch_ebay_api_comps, is_configured as ebay_api_configured
from ..services.onethirtypoint import fetch_130point_comps
from ..services.mavin import fetch_mavin_comps, MOCK_PRICE
from ..services.ebay_pricing import fetch_ebay_sold_comps

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])

# Wall-clock ceiling for the whole lookup, enforced here rather than inferred
# from the per-source httpx timeouts: a scalar httpx timeout applies to connect,
# read, write and pool *each*, and reads are per-operation, so a slow-drip
# response has no total budget. Sized just above the slowest nominal source
# (130point, 20s) so a legitimately slow answer still lands.
PRICING_DEADLINE_SECONDS = 25.0


def _result(future, deadline):
    """A finished source's tuple, or None if it hasn't answered in budget.

    Never raises: the endpoint must always return a price, and a source that
    breaks its own never-raise contract must not take the request down with it.
    """
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # Past the deadline — harvest only what is already in hand.
            if not future.done():
                return None
            remaining = 0
        return future.result(timeout=max(remaining, 0))
    except concurrent.futures.TimeoutError:
        return None
    except Exception as e:  # a source raised despite the contract
        logger.warning("Pricing source raised: %s", e)
        return None


@router.post("", response_model=PricingResponse)
def get_pricing(payload: PricingRequest):
    args = dict(
        player_name=payload.player_name,
        year=payload.year,
        brand=payload.brand,
        set_name=payload.set_name,
        card_number=payload.card_number,
    )

    api_on = ebay_api_configured()
    deadline = time.monotonic() + PRICING_DEADLINE_SECONDS

    # One executor per request, shut down without waiting (see module docstring).
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="pricing")
    try:
        # The eBay API is only submitted when configured — an unconfigured
        # source contributes no note to the all-failed message, as before.
        f_api = pool.submit(fetch_ebay_api_comps, **args) if api_on else None
        f_op = pool.submit(fetch_130point_comps, **args)
        f_mavin = pool.submit(fetch_mavin_comps, **args)
        f_ebay = pool.submit(fetch_ebay_sold_comps, **args)

        # 0) eBay API — preferred when configured.
        api_note = None
        if f_api is not None:
            api = _result(f_api, deadline)
            if api:
                api_comps, api_price, api_note = api
                if api_comps:
                    return PricingResponse(comps=api_comps, suggested_price=api_price,
                                           source="ebay_api", note=None)

        # 1) 130point — card-specific eBay sold-comps aggregator
        op_note = None
        op = _result(f_op, deadline)
        if op:
            op_comps, op_price, op_note = op
            if op_comps:
                return PricingResponse(comps=op_comps, suggested_price=op_price,
                                       source="130point", note=None)

        # 2) Mavin — broader aggregator. Note the 4-tuple.
        mavin_note = None
        mavin = _result(f_mavin, deadline)
        if mavin:
            mavin_comps, mavin_price, mavin_source, mavin_note = mavin
            if mavin_source == "mavin" and mavin_comps:
                return PricingResponse(comps=mavin_comps, suggested_price=mavin_price,
                                       source="mavin",
                                       note="130point had no comps — using Mavin.")

        # 3) eBay direct
        ebay_note = None
        ebay = _result(f_ebay, deadline)
        if ebay:
            ebay_comps, ebay_price, ebay_note = ebay
            if ebay_comps:
                return PricingResponse(
                    comps=ebay_comps, suggested_price=ebay_price, source="ebay_sold",
                    note="130point + Mavin had no comps — using eBay sold listings.")
    finally:
        # Don't wait: a source still in flight has its own bounded timeout and
        # nothing left to deliver to this request.
        pool.shutdown(wait=False, cancel_futures=True)

    # 4) Mock with a transparent explanation of what failed
    parts = []
    if api_note:
        parts.append(f"eBay API: {api_note}")
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
