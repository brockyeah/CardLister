"""Subscription-billed scan fallback + credits-exhausted alerting."""
import json
import sys
import types

from PIL import Image

from backend.services import billing_alerts
from backend.services import claude_vision as cv


EXTRACTED = {"player_name": "Wander Franco", "year": 2021, "confidence_notes": ""}


def _fake_cli_run(returncode=0, result=EXTRACTED):
    def run(cmd, **kwargs):
        assert "-p" in cmd and "--allowedTools" in cmd
        assert "ANTHROPIC_API_KEY" not in kwargs.get("env", {})
        stdout = json.dumps({"type": "result", "result": json.dumps(result),
                             "usage": {"input_tokens": 100, "output_tokens": 50}})
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
    return run


def _enable_subscription(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-test")
    monkeypatch.setattr(cv.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(cv.subprocess, "run", _fake_cli_run())


def _png(tmp_path):
    path = tmp_path / "card.png"
    Image.new("RGB", (100, 140), (20, 80, 40)).save(path)
    return str(path)


def _credit_error_anthropic(monkeypatch):
    """Fake the anthropic module so messages.create raises an out-of-credits error."""
    class FakeMessages:
        def create(self, **kwargs):
            raise RuntimeError("Your credit balance is too low to access the Anthropic API.")

    class FakeClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeClient))


def test_no_key_prefers_subscription_over_mock(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _enable_subscription(monkeypatch)
    data, is_mock, error, usage = cv.extract_card_from_image("card.jpg")
    assert not is_mock and error is None
    assert data["player_name"] == "Wander Franco"
    assert usage["model"].endswith("(subscription)")


def test_no_key_no_subscription_still_mocks(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    data, is_mock, error, usage = cv.extract_card_from_image("card.jpg")
    assert is_mock and usage is None


def test_credit_error_alerts_and_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dead")
    _credit_error_anthropic(monkeypatch)
    _enable_subscription(monkeypatch)
    alerts = []
    monkeypatch.setattr(cv, "notify_credits_exhausted", alerts.append)

    data, is_mock, error, usage = cv.extract_card_from_image(_png(tmp_path))
    assert len(alerts) == 1 and "credit balance" in alerts[0]
    assert not is_mock and error is None
    assert "billed to the Claude subscription" in data["confidence_notes"]
    assert usage["model"].endswith("(subscription)")


def test_credit_error_without_fallback_reports_topup(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dead")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    _credit_error_anthropic(monkeypatch)
    alerts = []
    monkeypatch.setattr(cv, "notify_credits_exhausted", alerts.append)

    data, is_mock, error, usage = cv.extract_card_from_image(_png(tmp_path))
    assert len(alerts) == 1
    assert error and "credits are exhausted" in error
    assert data["player_name"] == ""  # blank card, not mock values


def test_non_billing_errors_do_not_alert(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ok")

    class FakeMessages:
        def create(self, **kwargs):
            raise RuntimeError("overloaded_error: try again later")

    class FakeClient:
        def __init__(self, api_key=None):
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeClient))
    alerts = []
    monkeypatch.setattr(cv, "notify_credits_exhausted", alerts.append)

    data, is_mock, error, usage = cv.extract_card_from_image(_png(tmp_path))
    assert alerts == []
    assert error and "Vision extraction failed" in error


def test_alerts_test_endpoint_reports_channel_status(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app

    monkeypatch.setattr(billing_alerts.mailer, "send_email", lambda s, b: True)
    monkeypatch.setattr(billing_alerts.mailer, "is_configured", lambda: True)
    monkeypatch.setenv("NTFY_TOPIC", "cardlister-test-topic")
    monkeypatch.setattr(billing_alerts.httpx, "post",
                        lambda url, **kw: types.SimpleNamespace(status_code=200, text=""))

    with TestClient(app) as client:
        assert client.post("/api/analytics/alerts/test").status_code == 401
        tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
        r = client.post("/api/analytics/alerts/test", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["push_configured"] is True and body["push_sent"] is True
        assert body["email_configured"] is True and body["email_sent"] is True


def test_alerts_test_reports_email_unconfigured_without_recipients(monkeypatch):
    """`email_configured` follows the mailer's own definition of configured.

    Provider credentials without recipients cannot send, and this endpoint
    exists to verify wiring — so SMTP_USERNAME alone must report False, the
    same answer `notify_callup_alerts_undelivered` gives when it diagnoses a
    misconfiguration. The two used to disagree.
    """
    # Full SMTP credentials, so the only thing missing is the recipient list —
    # without SMTP_PASSWORD the test passed for the wrong reason (no password
    # is unconfigured too) and pinned nothing about recipients.
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("ALERT_EMAILS", raising=False)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)

    body = billing_alerts.send_test_alert()
    assert body["email_configured"] is False
    assert body["email_sent"] is False


def test_alert_throttles_and_hits_both_channels(monkeypatch):
    sent, pushed = [], []
    monkeypatch.setattr(billing_alerts.mailer, "send_email", lambda s, b: sent.append(s) or True)
    monkeypatch.setenv("NTFY_TOPIC", "cardlister-test-topic")

    def fake_post(url, **kwargs):
        pushed.append(url)
        return types.SimpleNamespace(status_code=200, text="")
    monkeypatch.setattr(billing_alerts.httpx, "post", fake_post)

    monkeypatch.setattr(billing_alerts, "_last_alert_at", 0.0)
    assert billing_alerts.notify_credits_exhausted("credit balance is too low") is True
    assert len(sent) == 1 and len(pushed) == 1 and "cardlister-test-topic" in pushed[0]
    # Second call inside the throttle window is suppressed entirely.
    assert billing_alerts.notify_credits_exhausted("still broke") is False
    assert len(sent) == 1 and len(pushed) == 1
