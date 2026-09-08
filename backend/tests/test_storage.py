"""Storage usage readout: DB file size + uploads count/bytes + the remainder."""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.database import DB_PATH, uploads_dir
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


def test_storage_reports_non_db_non_upload_files_separately(db_session):
    """A leaked backup snapshot is the case this figure exists for: it shares
    the volume, it can be a full copy of the database, and it used to be
    invisible to the only readout the app has of volume pressure."""
    volume = Path(DB_PATH).resolve().parent
    volume.mkdir(parents=True, exist_ok=True)
    leaked = volume / "cardlister-backup-storagetest.db"
    with TestClient(app) as client:
        headers = _auth(client)
        before = client.get("/api/analytics/storage", headers=headers).json()
        leaked.write_bytes(b"x" * 4096)
        try:
            after = client.get("/api/analytics/storage", headers=headers).json()
        finally:
            leaked.unlink(missing_ok=True)

    assert after["other_bytes"] == before["other_bytes"] + 4096
    # The snapshot is neither the database nor a photo, so neither of those
    # figures may absorb it — that conflation is the bug this closes.
    assert after["db_bytes"] == before["db_bytes"]
    assert after["uploads_bytes"] == before["uploads_bytes"]
    assert after["uploads_count"] == before["uploads_count"]


def test_storage_other_bytes_excludes_uploads_and_db(db_session):
    """uploads/ is reported on its own, so it must not also land in the
    remainder — double-counting would overstate the volume it is watching."""
    root = uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "other-bytes-marker.jpg"
    with TestClient(app) as client:
        headers = _auth(client)
        before = client.get("/api/analytics/storage", headers=headers).json()
        marker.write_bytes(b"x" * 1024)
        try:
            after = client.get("/api/analytics/storage", headers=headers).json()
        finally:
            marker.unlink(missing_ok=True)

    assert after["uploads_bytes"] == before["uploads_bytes"] + 1024
    assert after["other_bytes"] == before["other_bytes"]


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
