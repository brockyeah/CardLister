import os
from unittest.mock import MagicMock, patch

from backend.services import mailer


def _configured(monkeypatch):
    monkeypatch.setenv("SMTP_USERNAME", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    monkeypatch.setenv("ALERT_EMAILS", "me@gmail.com, alan@example.com")


def test_not_configured_returns_false_without_network(monkeypatch):
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert mailer.is_configured() is False
    # Must not attempt a connection when unconfigured.
    with patch("smtplib.SMTP") as smtp:
        assert mailer.send_email("s", "b") is False
        smtp.assert_not_called()


def test_send_email_uses_starttls_and_recipients(monkeypatch):
    _configured(monkeypatch)
    server = MagicMock()
    with patch("smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = server
        assert mailer.send_email("Subject", "Body") is True
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("me@gmail.com", "app-pw")
    # Recipients parsed from the comma list (whitespace trimmed).
    args, kwargs = server.send_message.call_args
    msg = args[0]
    assert msg["To"] == "me@gmail.com, alan@example.com"


def test_send_email_swallows_smtp_errors(monkeypatch):
    _configured(monkeypatch)
    with patch("smtplib.SMTP", side_effect=OSError("no route")):
        assert mailer.send_email("s", "b") is False
