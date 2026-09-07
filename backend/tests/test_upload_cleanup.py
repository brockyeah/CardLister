"""Orphaned upload cleanup: card references and the grace window protect files."""
import os
import time

from fastapi.testclient import TestClient

from backend.database import uploads_dir
from backend.main import app
from backend.models import Card, Scan
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
    # The uploads dir is shared across the test session; start from a clean
    # slate so the total_files assertion below is order-independent.
    root = uploads_dir()
    if root.is_dir():
        for f in root.iterdir():
            f.unlink()
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
        # total_files counts everything in uploads/ (stale, fresh, front, back)
        # so the UI can warn when the orphan set is most of the directory.
        assert r.json() == {"count": 1, "bytes": 100, "grace_hours": ORPHAN_GRACE_HOURS,
                            "total_files": 4}

        r = client.post("/api/analytics/uploads/cleanup", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"deleted": 1, "freed_bytes": 100, "scans_cleared": 0}

    assert not stale.exists()
    assert fresh.exists()
    assert front.exists()
    assert back.exists()


def test_cleanup_clears_scan_paths_for_deleted_files(db_session):
    """A swept file must not leave a Scan row pointing at it.

    Scan rows deliberately don't protect their files, so an unsaved scan's
    photo is exactly what the sweep reclaims — which is precisely why the row
    is the one left holding a dangling path.
    """
    root = uploads_dir()
    if root.is_dir():
        for f in root.iterdir():
            f.unlink()
    _make_file("scanfront.jpg", age_hours=ORPHAN_GRACE_HOURS + 1)
    _make_file("scanback.jpg", age_hours=ORPHAN_GRACE_HOURS + 1)
    kept = _make_file("kept.jpg", age_hours=ORPHAN_GRACE_HOURS + 1)
    # A second scan whose photo a card still references: its file survives the
    # sweep, so its paths must survive too.
    db_session.add(Card(player_name="Keeper", image_path="/uploads/kept.jpg"))
    db_session.add(Scan(username="tester", image_path="/uploads/scanfront.jpg",
                        back_image_path="/uploads/scanback.jpg"))
    db_session.add(Scan(username="tester", image_path="/uploads/kept.jpg"))
    db_session.commit()

    with TestClient(app) as client:
        r = client.post("/api/analytics/uploads/cleanup", headers=_auth(client))
        assert r.status_code == 200, r.text
        assert r.json() == {"deleted": 2, "freed_bytes": 20, "scans_cleared": 1}

    assert kept.exists()
    db_session.expire_all()
    swept, referenced = db_session.query(Scan).order_by(Scan.id).all()
    assert swept.image_path is None
    assert swept.back_image_path is None
    assert referenced.image_path == "/uploads/kept.jpg"


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
