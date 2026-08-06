"""Storage usage readout: DB file size + uploads count/bytes."""
from fastapi.testclient import TestClient

from backend.database import uploads_dir
from backend.main import app


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_storage_requires_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/analytics/storage").status_code == 401


def test_storage_reports_db_and_uploads(db_session):
    root = uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "storage-test-marker.jpg"
    marker.write_bytes(b"x" * 2048)
    try:
        with TestClient(app) as client:
            r = client.get("/api/analytics/storage", headers=_auth(client))
            assert r.status_code == 200, r.text
            data = r.json()
            # init_db has run, so the SQLite file exists and has size.
            assert data["db_bytes"] > 0
            assert data["uploads_count"] >= 1
            assert data["uploads_bytes"] >= 2048
    finally:
        marker.unlink(missing_ok=True)


def test_storage_counts_only_files(db_session):
    root = uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    sub = root / "storage-test-subdir"
    sub.mkdir(exist_ok=True)
    try:
        with TestClient(app) as client:
            before = client.get("/api/analytics/storage", headers=_auth(client)).json()
            # A directory contributes neither to the count nor the byte total.
            marker = sub / "nested.jpg"
            marker.write_bytes(b"x" * 512)
            after = client.get("/api/analytics/storage", headers=_auth(client)).json()
            assert after["uploads_count"] == before["uploads_count"]
            assert after["uploads_bytes"] == before["uploads_bytes"]
    finally:
        for p in sub.iterdir():
            p.unlink()
        sub.rmdir()
