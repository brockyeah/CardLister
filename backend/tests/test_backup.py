import errno
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import DB_PATH
from backend.main import app
from backend.routers import analytics


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _snapshots():
    """Snapshot files currently sitting in the staging directory."""
    return sorted(analytics._snapshot_dir().glob(f"{analytics.SNAPSHOT_PREFIX}*.db"))


def test_backup_requires_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/analytics/backup.db").status_code == 401


def test_backup_is_a_valid_snapshot(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="Jackson Holliday", year=2023, brand="Bowman",
            set_name="Chrome", card_number="BCP-19",
        ), headers=headers)
        r = client.get("/api/analytics/backup.db", headers=headers)
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers["content-disposition"]
        assert "cardlister-backup-" in r.headers["content-disposition"]

        # The download must itself be a readable SQLite DB containing the card.
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snap.db"
            snap.write_bytes(r.content)
            conn = sqlite3.connect(snap)
            try:
                players = [row[0] for row in conn.execute("SELECT player_name FROM cards")]
            finally:
                conn.close()
        assert "Jackson Holliday" in players


def test_snapshot_is_staged_beside_the_database(db_session):
    """Not in the container's /tmp.

    On Railway the database sits on a mounted volume and `/tmp` is ephemeral
    container-local disk, so `VACUUM INTO` used to write a full copy of the DB
    onto the one disk that is neither sized for it nor persistent.
    """
    assert analytics._snapshot_dir() == Path(DB_PATH).resolve().parent
    assert analytics._snapshot_dir() != Path(tempfile.gettempdir()).resolve()

    seen = {}
    real_mkstemp = tempfile.mkstemp

    def recording_mkstemp(*args, **kwargs):
        seen["dir"] = kwargs.get("dir")
        return real_mkstemp(*args, **kwargs)

    with patch.object(analytics.tempfile, "mkstemp", recording_mkstemp):
        with TestClient(app) as client:
            r = client.get("/api/analytics/backup.db", headers=_auth(client))
    assert r.status_code == 200, r.text
    assert Path(seen["dir"]).resolve() == Path(DB_PATH).resolve().parent


def test_snapshot_is_removed_after_the_response(db_session):
    """The staging file is transient — on the volume, a leak is permanent."""
    before = _snapshots()
    with TestClient(app) as client:
        assert client.get("/api/analytics/backup.db", headers=_auth(client)).status_code == 200
    assert _snapshots() == before


def test_stale_snapshots_are_swept(db_session):
    """A client that disconnects mid-download leaves the BackgroundTask unrun.

    That file used to die with the container; on the volume it would sit there
    forever, and `storage_usage` counts only the DB file and the uploads dir,
    so nothing would report it.
    """
    staging = analytics._snapshot_dir()
    stale = staging / f"{analytics.SNAPSHOT_PREFIX}stale.db"
    stale.write_bytes(b"leaked")
    old = time.time() - (analytics.STALE_SNAPSHOT_SECONDS + 60)
    os.utime(stale, (old, old))

    fresh = staging / f"{analytics.SNAPSHOT_PREFIX}fresh.db"
    fresh.write_bytes(b"in flight")

    unrelated = staging / "cardlister-notes.db"
    unrelated.write_bytes(b"not ours")

    try:
        with TestClient(app) as client:
            assert client.get("/api/analytics/backup.db", headers=_auth(client)).status_code == 200
        assert not stale.exists(), "an abandoned snapshot should be reclaimed"
        # A snapshot that a concurrent request is still streaming must survive.
        assert fresh.exists()
        assert unrelated.exists(), "the sweep must only touch its own snapshots"
    finally:
        for p in (stale, fresh, unrelated):
            p.unlink(missing_ok=True)


def test_out_of_space_says_so_instead_of_failing_blankly(db_session):
    """"Backup snapshot failed" told the owner nothing about what to fix."""
    full = sqlite3.OperationalError("database or disk is full")
    with patch.object(analytics.sqlite3, "connect", side_effect=full):
        with TestClient(app) as client:
            r = client.get("/api/analytics/backup.db", headers=_auth(client))
    assert r.status_code == 507, r.text
    assert "disk space" in r.json()["detail"]
    # The half-written staging file must not survive the failure.
    assert _snapshots() == []


def test_staging_enospc_is_reported_as_out_of_space(db_session):
    """The OS reports a full disk as ENOSPC; SQLite reports it in a message."""
    with patch.object(analytics.tempfile, "mkstemp",
                      side_effect=OSError(errno.ENOSPC, "No space left on device")):
        with TestClient(app) as client:
            r = client.get("/api/analytics/backup.db", headers=_auth(client))
    assert r.status_code == 507, r.text
    assert "disk space" in r.json()["detail"]


def test_other_snapshot_failures_still_report_a_generic_500(db_session):
    """Only out-of-space gets the specific message; nothing else is guessed at."""
    with patch.object(analytics.sqlite3, "connect",
                      side_effect=sqlite3.OperationalError("database is locked")):
        with TestClient(app) as client:
            r = client.get("/api/analytics/backup.db", headers=_auth(client))
    assert r.status_code == 500, r.text
    assert r.json()["detail"] == "Backup snapshot failed"
    assert _snapshots() == []
