"""Outbound email via SendGrid's HTTP API (preferred) or SMTP (Gmail, local
dev fallback). Railway blocks outbound SMTP — connecting to smtp.gmail.com
fails there with `[Errno 101] Network is unreachable` — so SendGrid's HTTPS
API (port 443) is used whenever SENDGRID_API_KEY is set; SMTP still works for
local development without a SendGrid account. Never raises — send_email
returns False on any failure so callers (the poller) keep running."""
import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

logger = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def _recipients() -> list[str]:
    return [a.strip() for a in os.getenv("ALERT_EMAILS", "").split(",") if a.strip()]


def _from_address() -> str | None:
    return os.getenv("ALERT_FROM") or os.getenv("SMTP_USERNAME")


def is_configured() -> bool:
    recipients = _recipients()
    if os.getenv("SENDGRID_API_KEY") and _from_address() and recipients:
        return True
    return bool(os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD") and recipients)


def _send_via_sendgrid(api_key: str, subject: str, text_body: str) -> bool:
    from_address = _from_address()
    recipients = _recipients()
    payload = {
        "personalizations": [{"to": [{"email": r} for r in recipients]}],
        "from": {"email": from_address},
        "subject": subject,
        "content": [{"type": "text/plain", "value": text_body}],
    }
    try:
        resp = httpx.post(
            SENDGRID_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=20.0,
        )
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("send_email (SendGrid) failed: status=%s body=%s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("send_email (SendGrid) failed: %s", e)
        return False


def _send_via_smtp(subject: str, text_body: str) -> bool:
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    recipients = _recipients()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = ", ".join(recipients)
    msg.set_content(text_body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.warning("send_email (SMTP) failed: %s", e)
        return False


def send_email(subject: str, text_body: str) -> bool:
    if not is_configured():
        logger.info("Mailer not configured (SendGrid or SMTP + ALERT_EMAILS) — skipping email")
        return False

    api_key = os.getenv("SENDGRID_API_KEY")
    if api_key:
        return _send_via_sendgrid(api_key, subject, text_body)
    return _send_via_smtp(subject, text_body)
