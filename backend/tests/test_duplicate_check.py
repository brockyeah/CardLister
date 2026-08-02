from fastapi.testclient import TestClient

from backend.main import app


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _payload(**kw):
    base = dict(player_name="Wander Franco", year=2021, brand="Bowman",
                set_name="Chrome", card_number="BCP-100", condition="NM")
    base.update(kw)
    return base


def test_finds_duplicate_ignoring_case_and_whitespace(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post("/api/cards/check-duplicate",
                        json=_payload(player_name="  wander FRANCO ", brand="bowman"),
                        headers=headers)
        assert r.status_code == 200, r.text
        dup = r.json()["duplicate"]
        assert dup is not None and dup["id"] == created["id"]


def test_different_parallel_or_flags_is_not_a_duplicate(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=_payload(), headers=headers)
        for variant in (dict(parallel_color="Gold"), dict(serial_number="12/50"),
                        dict(is_refractor=True), dict(is_first_bowman=True)):
            r = client.post("/api/cards/check-duplicate", json=_payload(**variant), headers=headers)
            assert r.json()["duplicate"] is None, variant


def test_condition_difference_still_matches(db_session):
    # Condition is intentionally excluded from matching (extraction is noisy);
    # the user confirms in the UI before any merge happens.
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(condition="NM"), headers=headers).json()
        r = client.post("/api/cards/check-duplicate", json=_payload(condition="LP"), headers=headers)
        assert r.json()["duplicate"]["id"] == created["id"]


def test_sold_cards_and_blank_players_never_match(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        client.post(f"/api/cards/{created['id']}/mark-sold", json={"sold_price": 9.99}, headers=headers)
        assert client.post("/api/cards/check-duplicate", json=_payload(),
                           headers=headers).json()["duplicate"] is None
        assert client.post("/api/cards/check-duplicate", json=_payload(player_name="  "),
                           headers=headers).json()["duplicate"] is None
