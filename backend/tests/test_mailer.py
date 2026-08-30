import httpx
from unittest.mock import MagicMock, patch

from backend.services import mailer


def _configured(monkeypatch):
    monkeypatch.setenv("SMTP_USERNAME", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    monkeypatch.setenv("ALERT_EMAILS", "me@gmail.com, alan@example.com")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)


def _sendgrid_configured(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.fake-key")
    monkeypatch.setenv("ALERT_FROM", "alerts@example.com")
    monkeypatch.setenv("ALERT_EMAILS", "me@gmail.com, alan@example.com")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)


def test_not_configured_returns_false_without_network(monkeypatch):
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("ALERT_FROM", raising=False)
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


def test_send_email_uses_sendgrid_when_configured(monkeypatch):
    _sendgrid_configured(monkeypatch)
    resp = MagicMock()
    resp.status_code = 202
    with patch("httpx.post", return_value=resp) as post:
        assert mailer.send_email("Subject", "Body") is True

    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "https://api.sendgrid.com/v3/mail/send"
    assert kwargs["headers"]["Authorization"] == "Bearer SG.fake-key"
    payload = kwargs["json"]
    assert payload["personalizations"] == [
        {"to": [{"email": "me@gmail.com"}, {"email": "alan@example.com"}]}
    ]
    assert payload["from"] == {"email": "alerts@example.com"}
    assert payload["subject"] == "Subject"
    assert payload["content"] == [{"type": "text/plain", "value": "Body"}]


def test_send_email_sendgrid_non_2xx_returns_false(monkeypatch):
    _sendgrid_configured(monkeypatch)
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Unauthorized"
    with patch("httpx.post", return_value=resp):
        assert mailer.send_email("s", "b") is False


def test_send_email_sendgrid_connect_error_returns_false(monkeypatch):
    _sendgrid_configured(monkeypatch)
    with patch("httpx.post", side_effect=httpx.ConnectError("boom")):
        assert mailer.send_email("s", "b") is False


def test_send_email_prefers_sendgrid_over_smtp(monkeypatch):
    _sendgrid_configured(monkeypatch)
    monkeypatch.setenv("SMTP_USERNAME", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    resp = MagicMock()
    resp.status_code = 202
    with patch("httpx.post", return_value=resp), patch("smtplib.SMTP") as smtp:
        assert mailer.send_email("s", "b") is True
    smtp.assert_not_called()
