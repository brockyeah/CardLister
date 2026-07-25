"""Owner alerts for Anthropic API billing problems (credits exhausted).

Two channels, both fired together: email through the existing mailer
(SendGrid/SMTP + ALERT_EMAILS) and a phone push via ntfy (set NTFY_TOPIC and
subscribe to that topic in the ntfy mobile app — no account required).
Throttled so a burst of failing scans produces one alert, not one per scan.
Never raises — an alerting failure must not break the scan that triggered it.
"""
import logging
import os
import time

import httpx

from .mailer import send_email

logger = logging.getLogger(__name__)

# Seconds between repeat alerts for the same ongoing outage.
ALERT_THROTTLE_SECONDS = int(os.getenv("BILLING_ALERT_THROTTLE_SECONDS", str(6 * 3600)))

_last_alert_at: float = 0.0


def _push_via_ntfy(title: str, body: str) -> bool:
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        resp = httpx.post(
            f"{server}/{topic}",
            content=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "warning,moneybag"},
            timeout=15.0,
        )
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("ntfy push failed: status=%s body=%s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("ntfy push failed: %s", e)
        return False


def notify_credits_exhausted(detail: str) -> bool:
    """Tell the owner the pay-as-you-go API key is out of credits.

    Returns True if at least one channel delivered. Safe to call on every
    failing scan — the throttle collapses repeats.
    """
    global _last_alert_at
    now = time.time()
    if now - _last_alert_at < ALERT_THROTTLE_SECONDS:
        return False
    _last_alert_at = now

    title = "CardLister: Anthropic API credits exhausted"
    body = (
        "Card scans can no longer bill the ANTHROPIC_API_KEY — the account looks "
        "out of credits.\n\n"
        f"API error: {detail}\n\n"
        "Scans are falling back to the Claude subscription (CLAUDE_CODE_OAUTH_TOKEN) "
        "if configured, or mock mode otherwise. Top up credits at "
        "https://console.anthropic.com to restore normal billing.\n\n"
        f"(Repeat alerts suppressed for {ALERT_THROTTLE_SECONDS // 3600}h.)"
    )
    try:
        emailed = send_email(title, body)
        pushed = _push_via_ntfy(title, body)
        logger.warning("Credits-exhausted alert sent (email=%s, push=%s): %s", emailed, pushed, detail)
        return emailed or pushed
    except Exception:
        logger.exception("Credits-exhausted alert failed")
        return False
