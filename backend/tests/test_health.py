"""Deep /api/health endpoint: DB reachability, revision, poller heartbeat."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from backend.main import app
from backend.services import callups


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
        # Alert delivery, which `stale` cannot speak to: a process that has
        # never completed a cycle reports null rather than claiming a good one.
        assert body["poller"]["last_cycle_ok"] is None
        assert body["poller"]["alerts_pending"] == 0
        assert body["poller"]["alerts_abandoned"] == 0
        # No Railway env in tests — revision is null, not "".
        assert body["revision"] is None


def test_health_requires_no_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


def test_health_answers_head_with_the_same_status(db_session):
    # Status-code-only uptime monitors default to HEAD. `@app.get` registers GET
    # alone, so HEAD used to fall through to the static mount and 404 whether the
    # app was healthy or not — which silently defeats the 503 below.
    with TestClient(app) as client:
        r = client.head("/api/health")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")


def test_health_head_503_when_db_unreachable(db_session):
    # The whole point of HEAD support: an unhealthy deploy must be
    # distinguishable from a healthy one without parsing a body.
    @contextmanager
    def broken_connect():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    with TestClient(app) as client:
        with patch.object(main.engine, "connect", broken_connect):
            assert client.head("/api/health").status_code == 503


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


def _run_one_poll_cycle():
    """Drive `_callup_poller` through exactly one iteration.

    The loop is `while True: cycle; stamp heartbeat; sleep`, so cancelling it
    once the heartbeat lands gives one complete cycle without patching
    `asyncio.sleep` — which is module-global and shared with the threadpool
    machinery `run_poll_cycle` is dispatched through.
    """

    async def drive():
        task = asyncio.create_task(main._callup_poller())
        try:
            for _ in range(400):
                await asyncio.sleep(0.005)
                if main._poller_state["last_cycle_at"] is not None:
                    return True
            return False
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return asyncio.run(drive())


def test_health_reports_alerts_the_poller_could_not_deliver(db_session):
    """`stale` proves the loop is alive; it says nothing about delivery.

    A mailer outage drops every call-up alert while the poller keeps cycling
    happily, so `last_cycle_at` is stamped, `stale` stays false, and
    health.yml — which fails a scheduled run on `stale` — sails straight past
    the one failure this app exists to avoid being quiet about. The counts
    `run_poll_cycle` already computes have to reach the response for the probe
    to see them.
    """
    with patch.dict(main._poller_state,
                    {"enabled": True, "last_cycle_at": None, "last_cycle_ok": None,
                     "alerts_pending": 0, "alerts_abandoned": 0}):
        with patch.object(callups, "run_poll_cycle",
                          return_value={"new": 0, "emailed": 0, "pending": 3, "abandoned": 2}):
            assert _run_one_poll_cycle(), "the poll cycle never completed"

        with TestClient(app) as client:
            body = client.get("/api/health").json()

    poller = body["poller"]
    assert poller["last_cycle_ok"] is True
    assert poller["alerts_pending"] == 3
    assert poller["alerts_abandoned"] == 2
    # The point of the test: a poller dropping every alert still looks fresh.
    assert poller["stale"] is False


def test_a_cycle_that_raises_is_reported_without_clearing_the_counts(db_session):
    """An erroring cycle must not read as a clean one — nor as a recovery.

    The heartbeat is stamped after a failure as deliberately as after a
    success (it proves liveness), so without `last_cycle_ok` an exception
    every cycle reports perfectly healthy. And the counts are left alone
    rather than zeroed: a cycle that raised did not un-abandon anything, so
    reporting 0 would clear a real signal on the strength of a *second*
    failure.
    """
    with patch.dict(main._poller_state,
                    {"enabled": True, "last_cycle_at": None, "last_cycle_ok": True,
                     "alerts_pending": 1, "alerts_abandoned": 4}):
        with patch.object(callups, "run_poll_cycle", side_effect=RuntimeError("boom")):
            assert _run_one_poll_cycle(), "the poll cycle never completed"

        with TestClient(app) as client:
            poller = client.get("/api/health").json()["poller"]

    assert poller["last_cycle_ok"] is False
    assert poller["alerts_abandoned"] == 4, "an errored cycle wiped a real abandoned count"
    assert poller["alerts_pending"] == 1
    # The loop is still alive — which is exactly why `stale` cannot carry this.
    assert poller["stale"] is False
