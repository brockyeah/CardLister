"""Outbound email via SMTP (Gmail by default). Never raises — send_email
returns False on any failure so callers (the poller) keep running."""
import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _recipients() -> list[str]:
    return [a.strip() for a in os.getenv("ALERT_EMAILS", "").split(",") if a.strip()]


def is_configured() -> bool:
    return bool(os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD") and _recipients())


def send_email(subject: str, text_body: str) -> bool:
    if not is_configured():
        logger.info("Mailer not configured (SMTP_USERNAME/PASSWORD/ALERT_EMAILS) — skipping email")
        return False

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
        logger.warning("send_email failed: %s", e)
        return False
