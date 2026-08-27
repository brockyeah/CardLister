"""Owner alerts for problems the app cannot fix and would otherwise hide:
Anthropic API billing (credits exhausted) and undelivered call-up alerts.

Two channels, both fired together: email through the existing mailer
(SendGrid/SMTP + ALERT_EMAILS) and a phone push via ntfy (set NTFY_TOPIC and
subscribe to that topic in the ntfy mobile app — no account required).
Throttled so a burst of failing scans produces one alert, not one per scan.
Never raises — an alerting failure must not break the scan that triggered it.

The two alerts keep separate throttle clocks. They report unrelated outages
that can be live at the same time, and sharing one clock would let whichever
fired first suppress the other for six hours.
"""
import logging
import os
import time

import httpx

from . import mailer
from .mailer import send_email

logger = logging.getLogger(__name__)

# Seconds between repeat alerts for the same ongoing outage.
ALERT_THROTTLE_SECONDS = int(os.getenv("BILLING_ALERT_THROTTLE_SECONDS", str(6 * 3600)))
CALLUP_ALERT_THROTTLE_SECONDS = int(
    os.getenv("CALLUP_ALERT_THROTTLE_SECONDS", str(6 * 3600))
)

_last_alert_at: float = 0.0
_last_callup_alert_at: float = 0.0


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


def send_test_alert() -> dict:
    """Fire both alert channels immediately (no throttle) so the owner can
    verify the ntfy topic + email recipients are wired up correctly."""
    title = "CardLister: test alert"
    body = (
        "This is a test of the credits-exhausted alert channels. "
        "If you can read this, the channel works. No action needed."
    )
    return {
        "email_configured": bool(os.getenv("SENDGRID_API_KEY") or os.getenv("SMTP_USERNAME")),
        "push_configured": bool(os.getenv("NTFY_TOPIC", "").strip()),
        "email_sent": send_email(title, body),
        "push_sent": _push_via_ntfy(title, body),
    }


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


def notify_callup_alerts_undelivered(
    pending: int, abandoned: int, max_age_hours: int
) -> bool:
    """Tell the owner that call-up alerts are not reaching him.

    Being told a prospect got called up while you hold his 1st Bowman is the
    feature this app was built around, and a failing mailer is the one way it
    breaks *quietly*: the poller retries the same events every cycle, stamps
    its heartbeat after the failure too — so `/api/health` keeps reporting the
    poller fresh — and then the events cross the retry window and leave it
    unemailed, permanently, with nothing recording that an alert was dropped.

    The push is the channel that matters here, because email is the channel
    that is failing. Email is still attempted: the failure may be transient,
    or specific to one recipient, and a second try costs one throttled request.

    Returns True if at least one channel delivered. Safe to call every poll
    cycle — the throttle collapses repeats into one alert per outage window.
    """
    global _last_callup_alert_at
    now = time.time()
    if now - _last_callup_alert_at < CALLUP_ALERT_THROTTLE_SECONDS:
        return False
    _last_callup_alert_at = now

    title = "CardLister: call-up alerts are not being delivered"
    lines = []
    if pending:
        lines.append(
            f"{pending} call-up alert(s) could not be emailed just now. They will "
            f"be retried every poll cycle until they are {max_age_hours}h old."
        )
    if abandoned:
        lines.append(
            f"{abandoned} call-up alert(s) passed {max_age_hours}h unsent in the "
            "last two days and will never be retried. Check the Prospect Wire in "
            "the app for the call-ups you missed."
        )
    if not mailer.is_configured():
        # A permanent misconfiguration and a provider outage produce the same
        # symptom, and the fix for each is completely different — so say which
        # one this is rather than leaving the owner to guess.
        lines.append(
            "No email delivery is configured: set SENDGRID_API_KEY (or "
            "SMTP_USERNAME/SMTP_PASSWORD) together with ALERT_EMAILS."
        )
    else:
        lines.append(
            "Email delivery is configured but the send failed — check the "
            "provider credentials, the sending account, and the Railway logs."
        )
    body = "\n\n".join(lines) + (
        f"\n\n(Repeat alerts suppressed for {CALLUP_ALERT_THROTTLE_SECONDS // 3600}h.)"
    )

    try:
        emailed = send_email(title, body)
        pushed = _push_via_ntfy(title, body)
        logger.warning(
            "Call-up delivery alert sent (email=%s, push=%s): pending=%s abandoned=%s",
            emailed, pushed, pending, abandoned,
        )
        return emailed or pushed
    except Exception:
        logger.exception("Call-up delivery alert failed")
        return False
