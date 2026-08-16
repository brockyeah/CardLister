"""eBay account-deletion handshake + OAuth landing pages (all public, no auth)."""
import hashlib
import logging

from fastapi.testclient import TestClient

from backend.main import app

ENDPOINT = "https://cards.example.com/api/ebay-compliance/account-deletion"
TOKEN = "test-verification-token_0123456789abcdef"


def _configure(monkeypatch):
    monkeypatch.setenv("EBAY_VERIFICATION_TOKEN", TOKEN)
    monkeypatch.setenv("EBAY_DELETION_ENDPOINT_URL", ENDPOINT)


def test_challenge_hash_matches_ebay_formula(db_session, monkeypatch):
    _configure(monkeypatch)
    with TestClient(app) as client:
        r = client.get("/api/ebay-compliance/account-deletion", params={"challenge_code": "abc123"})
        assert r.status_code == 200, r.text
        expected = hashlib.sha256(("abc123" + TOKEN + ENDPOINT).encode()).hexdigest()
        assert r.json() == {"challengeResponse": expected}


def test_challenge_unconfigured_returns_503(db_session, monkeypatch):
    monkeypatch.delenv("EBAY_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("EBAY_DELETION_ENDPOINT_URL", raising=False)
    with TestClient(app) as client:
        r = client.get("/api/ebay-compliance/account-deletion", params={"challenge_code": "abc123"})
        assert r.status_code == 503


def test_challenge_missing_code_returns_400(db_session, monkeypatch):
    _configure(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/ebay-compliance/account-deletion").status_code == 400


def test_deletion_notice_acks_without_stored_data(db_session):
    with TestClient(app) as client:
        r = client.post("/api/ebay-compliance/account-deletion", json={
            "notification": {"data": {"userId": "ebay-user-1"}}
        })
        assert r.status_code == 200
        assert r.json() == {"ack": True}
        # Malformed body still acks — eBay retries on non-2xx and there is
        # nothing to erase, so never bounce the notice.
        assert client.post(
            "/api/ebay-compliance/account-deletion", content=b"not json",
            headers={"Content-Type": "application/json"},
        ).status_code == 200


def test_deletion_notice_sanitizes_user_id_in_log(db_session, caplog):
    # The body is unauthenticated; a crafted userId must not be able to inject
    # fake log lines (newlines) or bloat the audit log. Guards the repr()+cap
    # in the handler against a future "simplify" pass.
    evil = "x\nFAKE LOG LINE injected\n" + "A" * 500
    with TestClient(app) as client, caplog.at_level(logging.INFO):
        r = client.post("/api/ebay-compliance/account-deletion", json={
            "notification": {"data": {"userId": evil}}
        })
        assert r.status_code == 200
    messages = [rec.getMessage() for rec in caplog.records
                if "account-deletion notice" in rec.getMessage()]
    assert len(messages) == 1
    msg = messages[0]
    assert "\nFAKE" not in msg          # newline neutralized by repr()
    assert "\\nFAKE" in msg             # ...but the content is still auditable
    # The 64-char cap: the evil prefix is 25 chars, so exactly 39 of the 500
    # pad "A"s survive the truncation.
    assert "A" * 39 in msg
    assert "A" * 40 not in msg


def test_deletion_notice_rejects_oversized_body(db_session):
    # Unauthenticated route on a single-worker container: cap the body read so
    # a giant POST can't balloon memory. Real notices are ~1 KB.
    big = b'{"pad": "' + b"A" * (128 * 1024) + b'"}'
    with TestClient(app) as client:
        r = client.post(
            "/api/ebay-compliance/account-deletion", content=big,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413


def test_oauth_and_privacy_pages_are_public(db_session):
    with TestClient(app) as client:
        for path in ("/api/ebay-compliance/oauth/accepted",
                     "/api/ebay-compliance/oauth/declined",
                     "/api/ebay-compliance/privacy"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert "CardLister" in r.text
