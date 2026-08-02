"""Upload size cap on /api/scan: over-cap requests get 413 and leave no file behind."""
import io

from fastapi.testclient import TestClient

import backend.routers.scan as scan_module
from backend.database import uploads_dir
from backend.main import app


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _scan(client, headers, **files):
    return client.post("/api/scan", files=files, data={"preset": "balance"}, headers=headers)


def _upload_names():
    d = uploads_dir()
    return set(p.name for p in d.glob("*")) if d.exists() else set()


def test_oversize_front_rejected_with_413_and_no_partial_file(monkeypatch):
    monkeypatch.setattr(scan_module, "MAX_UPLOAD_BYTES", 1024)
    with TestClient(app) as client:
        before = _upload_names()
        r = _scan(client, _auth(client), image=("big.jpg", io.BytesIO(b"x" * 4096), "image/jpeg"))
        assert r.status_code == 413, r.text
        assert "limit" in r.json()["detail"].lower()
        assert _upload_names() == before


def test_oversize_back_rejected_with_413_and_front_cleaned_up(monkeypatch):
    # The front image saves fine before the back overflows — the already-saved
    # front file must not be left orphaned on the volume.
    monkeypatch.setattr(scan_module, "MAX_UPLOAD_BYTES", 1024)
    with TestClient(app) as client:
        before = _upload_names()
        r = _scan(
            client, _auth(client),
            image=("front.jpg", io.BytesIO(b"x" * 512), "image/jpeg"),
            back=("back.jpg", io.BytesIO(b"x" * 4096), "image/jpeg"),
        )
        assert r.status_code == 413, r.text
        assert _upload_names() == before


def test_upload_exactly_at_cap_accepted(monkeypatch):
    # The cap is exclusive: exactly MAX_UPLOAD_BYTES must still succeed
    # (mock extraction — conftest strips ANTHROPIC_API_KEY).
    monkeypatch.setattr(scan_module, "MAX_UPLOAD_BYTES", 1024)
    with TestClient(app) as client:
        r = _scan(client, _auth(client), image=("ok.jpg", io.BytesIO(b"x" * 1024), "image/jpeg"))
        assert r.status_code == 200, r.text
        assert r.json()["mock"] is True
