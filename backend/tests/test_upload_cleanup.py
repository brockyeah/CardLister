"""Orphaned upload cleanup: card references and the grace window protect files."""
import os
import time

from fastapi.testclient import TestClient

from backend.database import uploads_dir
from backend.main import app
from backend.models import Card
from backend.routers.analytics import ORPHAN_GRACE_HOURS


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _make_file(name, age_hours=0, size=10):
    root = uploads_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(b"x" * size)
    if age_hours:
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))
    return path


def test_uploads_endpoints_require_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/analytics/uploads/orphans").status_code == 401
        assert client.post("/api/analytics/uploads/cleanup").status_code == 401


def test_orphan_detection_and_cleanup(db_session):
    stale = _make_file("stale.jpg", age_hours=ORPHAN_GRACE_HOURS + 1, size=100)
    fresh = _make_file("fresh.jpg", age_hours=0)
    front = _make_file("front.jpg", age_hours=ORPHAN_GRACE_HOURS + 1)
    back = _make_file("back.jpg", age_hours=ORPHAN_GRACE_HOURS + 1)
    db_session.add(Card(player_name="Keeper", image_path="/uploads/front.jpg",
                        back_image_path="/uploads/back.jpg"))
    db_session.commit()

    with TestClient(app) as client:
        headers = _auth(client)
        r = client.get("/api/analytics/uploads/orphans", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"count": 1, "bytes": 100, "grace_hours": ORPHAN_GRACE_HOURS}

        r = client.post("/api/analytics/uploads/cleanup", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"deleted": 1, "freed_bytes": 100}

    assert not stale.exists()
    assert fresh.exists()
    assert front.exists()
    assert back.exists()


def test_cleanup_with_no_uploads_dir(db_session):
    root = uploads_dir()
    if root.is_dir():
        for f in root.iterdir():
            f.unlink()
        root.rmdir()
    with TestClient(app) as client:
        headers = _auth(client)
        assert client.get("/api/analytics/uploads/orphans", headers=headers).json()["count"] == 0
        assert client.post("/api/analytics/uploads/cleanup", headers=headers).json()["deleted"] == 0
