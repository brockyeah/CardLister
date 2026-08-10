"""Public eBay compliance + OAuth endpoints (no auth — eBay calls these).

Two portal prerequisites live here so the developer-portal configuration can
be done exactly once:

1. Marketplace account-deletion notifications. eBay disables a production
   keyset until the app either registers an HTTPS notification endpoint or
   claims an exemption. We register the endpoint so the config never has to
   change when we start storing eBay user data (seller OAuth tokens for
   draft listings).

   Verification handshake: eBay GETs the endpoint with ?challenge_code=…
   and expects {"challengeResponse": sha256hex(challengeCode +
   verificationToken + endpointUrl)}. Afterwards it POSTs deletion notices,
   which just need a fast 2xx ack.

2. OAuth redirect landing pages for the RuName registration (auth-accepted /
   auth-declined URLs) plus a privacy-policy page, all required fields on
   eBay's RuName form. The accepted page is a placeholder until the draft-
   listing feature wires up the real token exchange.

Env:
  EBAY_VERIFICATION_TOKEN  32-80 chars of [A-Za-z0-9_-]; same value is pasted
                           into the portal's notification-endpoint form.
  EBAY_DELETION_ENDPOINT_URL  full public URL of the deletion endpoint, e.g.
                           https://<prod-host>/api/ebay-compliance/account-deletion
                           (part of the challenge hash, so it must match the
                           portal exactly).
"""
import hashlib
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _verification_token() -> str:
    return os.getenv("EBAY_VERIFICATION_TOKEN", "").strip()


def _endpoint_url() -> str:
    return os.getenv("EBAY_DELETION_ENDPOINT_URL", "").strip()


@router.get("/account-deletion")
def account_deletion_challenge(challenge_code: str = ""):
    """Answer eBay's endpoint-verification handshake."""
    token, endpoint = _verification_token(), _endpoint_url()
    if not (token and endpoint):
        # Unset env: report unconfigured rather than an invalid hash, so a
        # portal validation failure points at the right problem.
        raise HTTPException(status_code=503, detail="Deletion endpoint not configured")
    if not challenge_code:
        raise HTTPException(status_code=400, detail="Missing challenge_code")
    digest = hashlib.sha256(
        (challenge_code + token + endpoint).encode()
    ).hexdigest()
    return {"challengeResponse": digest}


@router.post("/account-deletion")
async def account_deletion_notice(request: Request):
    """Ack an account-deletion notice.

    Nothing to erase yet — no eBay user data is persisted. When seller OAuth
    tokens land (draft-listing feature), this handler must delete the
    matching user's tokens. Log enough to audit that duty later.
    """
    try:
        payload = await request.json()
        user_id = (payload.get("notification", {}).get("data", {}) or {}).get("userId")
    except Exception:
        user_id = None
    log.info("eBay account-deletion notice received (userId=%s) — no eBay user data stored", user_id)
    return {"ack": True}


_CLOSE_PAGE = """<!doctype html><html><head><title>CardLister</title></head>
<body style="font-family: system-ui; background: #0b0f1a; color: #e5e7eb;
             display: flex; align-items: center; justify-content: center; height: 100vh">
<div style="text-align: center">
  <h1 style="color: #34d399">CardLister</h1>
  <p>{message}</p>
  <p style="color: #9ca3af">You can close this window.</p>
</div></body></html>"""


@router.get("/oauth/accepted", response_class=HTMLResponse)
def oauth_accepted():
    """RuName auth-accepted landing. Placeholder until the draft-listing
    feature exchanges the ?code=… here for seller tokens."""
    return _CLOSE_PAGE.format(message="eBay account connected. Draft-listing support is coming soon.")


@router.get("/oauth/declined", response_class=HTMLResponse)
def oauth_declined():
    """RuName auth-declined landing."""
    return _CLOSE_PAGE.format(message="eBay connection was cancelled. Nothing was linked.")


@router.get("/privacy", response_class=HTMLResponse)
def privacy_policy():
    """Privacy policy page — required field on eBay's RuName form."""
    return _CLOSE_PAGE.format(
        message=(
            "CardLister is a private inventory tool. Card photos and listing data "
            "stay on our server and are never sold or shared. eBay account access, "
            "once connected, is used only to create listing drafts you approve, and "
            "is deleted on request or on eBay account-deletion notice."
        )
    )
