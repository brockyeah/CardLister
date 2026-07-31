"""Deep /api/health endpoint: DB reachability, revision, poller heartbeat."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from backend.main import app


def test_health_ok_reports_db_and_poller(db_session):
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["db"] is True
        # Tests run with DISABLE_CALLUP_POLLER=1 (conftest), so the poller is
        # reported off and can never be stale.
        assert body["poller"]["enabled"] is False
        assert body["poller"]["stale"] is False
        assert body["poller"]["last_cycle_at"] is None
        assert body["poller"]["interval_minutes"] == main.POLL_MINUTES
        # No Railway env in tests — revision is null, not "".
        assert body["revision"] is None


def test_health_requires_no_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


def test_health_503_when_db_unreachable(db_session):
    @contextmanager
    def broken_connect():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    with TestClient(app) as client:
        with patch.object(main.engine, "connect", broken_connect):
            r = client.get("/api/health")
        assert r.status_code == 503
        assert r.json()["ok"] is False
        assert r.json()["db"] is False


def test_health_marks_enabled_poller_stale_after_three_intervals(db_session):
    old = datetime.utcnow() - timedelta(minutes=main.POLL_MINUTES * 3 + 1)
    with TestClient(app) as client:
        with patch.dict(main._poller_state, {"enabled": True, "last_cycle_at": old}):
            body = client.get("/api/health").json()
        assert body["poller"]["enabled"] is True
        assert body["poller"]["stale"] is True
        assert body["poller"]["last_cycle_at"].startswith(old.isoformat()[:19])

        # A recent heartbeat is not stale.
        with patch.dict(main._poller_state, {"enabled": True, "last_cycle_at": datetime.utcnow()}):
            body = client.get("/api/health").json()
        assert body["poller"]["stale"] is False
