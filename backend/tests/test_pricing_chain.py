"""Pricing chain contract: preference order and every note string.

Written against the SERIAL implementation before the concurrent fan-out, so
these tests pin the behaviour that must survive the refactor rather than
describing whatever it became. Nothing else covers this endpoint.

Patches module attributes on `routers.pricing` — the router binds the fetchers
with `from ... import`, so patching the service module would not be seen.
"""
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import pricing
from backend.services.mavin import MOCK_PRICE

QUERY = {"player_name": "Elly De La Cruz", "year": 2022, "brand": "Bowman",
         "set_name": "Chrome", "card_number": "BCP-100"}

COMP = {"title": "2022 Bowman Chrome Elly De La Cruz BCP-100", "price": 42.0}


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _chain(*, api=None, api_configured=False, op=None, mavin=None, ebay=None):
    """Patch all four sources. Each arg is the tuple that fetcher returns."""
    return [
        patch.object(pricing, "ebay_api_configured", lambda: api_configured),
        patch.object(pricing, "fetch_ebay_api_comps",
                     lambda **k: api or ([], None, None)),
        patch.object(pricing, "fetch_130point_comps",
                     lambda **k: op or ([], None, None)),
        # Mavin is the odd one out: a 4-tuple (comps, price, source, note).
        patch.object(pricing, "fetch_mavin_comps",
                     lambda **k: mavin or ([], None, "mavin", None)),
        patch.object(pricing, "fetch_ebay_sold_comps",
                     lambda **k: ebay or ([], None, None)),
    ]


def _post(**chain_kwargs):
    patches = _chain(**chain_kwargs)
    for p in patches:
        p.start()
    try:
        with TestClient(app) as client:
            return client.post("/api/pricing", json=QUERY, headers=_auth(client)).json()
    finally:
        for p in patches:
            p.stop()


def test_ebay_api_wins_when_configured_and_answering():
    body = _post(api_configured=True, api=([COMP], 42.0, None),
                 op=([COMP], 99.0, None))          # lower-preference source also has comps
    assert body["source"] == "ebay_api"
    assert body["suggested_price"] == 42.0
    assert body["note"] is None


def test_unconfigured_ebay_api_is_skipped_entirely():
    # Its note must not reach the joined all-failed note either.
    body = _post(api_configured=False, api=([], None, "should never be seen"))
    assert body["source"] == "mock"
    assert "should never be seen" not in (body["note"] or "")


def test_130point_wins_over_mavin_and_ebay():
    body = _post(op=([COMP], 42.0, None),
                 mavin=([COMP], 99.0, "mavin", None),
                 ebay=([COMP], 77.0, None))
    assert body["source"] == "130point"
    assert body["note"] is None


def test_mavin_note_is_exact():
    body = _post(mavin=([COMP], 42.0, "mavin", None))
    assert body["source"] == "mavin"
    assert body["note"] == "130point had no comps — using Mavin."


def test_mavin_is_ignored_when_its_source_is_not_mavin():
    # The 4-tuple's third element gates use of the result.
    body = _post(mavin=([COMP], 42.0, "something-else", "note from mavin"),
                 ebay=([COMP], 55.0, None))
    assert body["source"] == "ebay_sold"


def test_ebay_sold_note_is_exact():
    body = _post(ebay=([COMP], 42.0, None))
    assert body["source"] == "ebay_sold"
    assert body["note"] == "130point + Mavin had no comps — using eBay sold listings."


def test_all_failed_joins_every_attempted_note_in_order():
    body = _post(api_configured=True,
                 api=([], None, "api down"),
                 op=([], None, "403"),
                 mavin=([], None, "mavin", "no recent sales"),
                 ebay=([], None, "blocked"))
    assert body["source"] == "mock"
    assert body["suggested_price"] == MOCK_PRICE
    assert body["comps"] == []
    assert body["note"] == (
        "eBay API: api down | 130point: 403 | Mavin: no recent sales | eBay: blocked"
    )


def test_all_failed_with_no_notes_falls_back_to_the_generic_message():
    body = _post()
    assert body["source"] == "mock"
    assert body["note"] == "No comps found anywhere — please price manually."


def test_pricing_requires_auth():
    with TestClient(app) as client:
        assert client.post("/api/pricing", json=QUERY).status_code == 401


# --- concurrency behaviour ---------------------------------------------------

def _slow(seconds, value):
    def fetch(**kwargs):
        time.sleep(seconds)
        return value
    return fetch


def test_preference_beats_speed():
    """A slow high-preference source still wins over a fast low-preference one.

    This is the regression that matters: resolving by whoever finishes first
    would silently return the weaker comp with the wrong note, and the app
    would look fine while pricing cards off the wrong data.
    """
    patches = [
        patch.object(pricing, "ebay_api_configured", lambda: True),
        patch.object(pricing, "fetch_ebay_api_comps", _slow(0.4, ([COMP], 42.0, None))),
        patch.object(pricing, "fetch_130point_comps", _slow(0.0, ([COMP], 99.0, None))),
        patch.object(pricing, "fetch_mavin_comps", _slow(0.0, ([COMP], 88.0, "mavin", None))),
        patch.object(pricing, "fetch_ebay_sold_comps", _slow(0.0, ([COMP], 77.0, None))),
    ]
    for p in patches:
        p.start()
    try:
        with TestClient(app) as client:
            body = client.post("/api/pricing", json=QUERY, headers=_auth(client)).json()
    finally:
        for p in patches:
            p.stop()
    assert body["source"] == "ebay_api"
    assert body["suggested_price"] == 42.0


def test_sources_run_concurrently_not_serially():
    """Four 0.3s sources should finish in about 0.3s, not 1.2s."""
    patches = [
        patch.object(pricing, "ebay_api_configured", lambda: True),
        patch.object(pricing, "fetch_ebay_api_comps", _slow(0.3, ([], None, "a"))),
        patch.object(pricing, "fetch_130point_comps", _slow(0.3, ([], None, "b"))),
        patch.object(pricing, "fetch_mavin_comps", _slow(0.3, ([], None, "mavin", "c"))),
        patch.object(pricing, "fetch_ebay_sold_comps", _slow(0.3, ([], None, "d"))),
    ]
    for p in patches:
        p.start()
    try:
        with TestClient(app) as client:
            headers = _auth(client)
            started = time.monotonic()
            body = client.post("/api/pricing", json=QUERY, headers=headers).json()
            elapsed = time.monotonic() - started
    finally:
        for p in patches:
            p.stop()
    # Serial would be >= 1.2s. Generous ceiling so this can't flake on a loaded
    # machine while still failing loudly if the fan-out is lost.
    assert elapsed < 0.9, f"took {elapsed:.2f}s — sources appear to be serial"
    assert body["source"] == "mock"
    # Every attempted source still contributes its note.
    assert body["note"] == "eBay API: a | 130point: b | Mavin: c | eBay: d"


def test_deadline_bounds_a_hanging_lookup():
    """A source that never answers cannot hold the request open indefinitely.

    The hanging sources block on an Event rather than sleeping: an abandoned
    worker is a non-daemon thread that the interpreter joins at exit, so a bare
    `time.sleep(30)` here would add 30s of invisible wall clock to every run of
    the whole backend suite — time pytest does not report, which reads as a hung
    runner. Releasing them in `finally` costs nothing and proves the same thing.
    """
    release = threading.Event()

    def hangs(value):
        def fetch(**kwargs):
            release.wait(timeout=30)   # released in finally; the cap is a backstop
            return value
        return fetch

    patches = [
        patch.object(pricing, "PRICING_DEADLINE_SECONDS", 0.3),
        patch.object(pricing, "ebay_api_configured", lambda: False),
        patch.object(pricing, "fetch_130point_comps", hangs(([COMP], 1.0, None))),
        patch.object(pricing, "fetch_mavin_comps", hangs(([COMP], 1.0, "mavin", None))),
        patch.object(pricing, "fetch_ebay_sold_comps", hangs(([COMP], 1.0, None))),
    ]
    for p in patches:
        p.start()
    try:
        with TestClient(app) as client:
            headers = _auth(client)
            started = time.monotonic()
            body = client.post("/api/pricing", json=QUERY, headers=headers).json()
            elapsed = time.monotonic() - started
    finally:
        release.set()          # let the abandoned workers exit immediately
        for p in patches:
            p.stop()
    assert elapsed < 5, f"took {elapsed:.2f}s — the deadline did not bound it"
    assert body["source"] == "mock"
    assert body["suggested_price"] == MOCK_PRICE
