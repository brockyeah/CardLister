from fastapi.testclient import TestClient

from backend.main import app


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _make_card(client, headers):
    return client.post("/api/cards", json={"player_name": "Wander Franco"}, headers=headers).json()


def test_https_url_is_accepted_and_trimmed(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        card = _make_card(client, headers)
        r = client.post(f"/api/cards/{card['id']}/ebay-id",
                        json={"ebay_listing_id": "123", "ebay_listing_url": "  https://www.ebay.com/itm/123  "},
                        headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["ebay_listing_url"] == "https://www.ebay.com/itm/123"


def test_non_https_urls_are_rejected(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        card = _make_card(client, headers)
        for bad in ("http://www.ebay.com/itm/123", "javascript:alert(1)", "ebay.com/itm/123", ""):
            r = client.post(f"/api/cards/{card['id']}/ebay-id",
                            json={"ebay_listing_id": "123", "ebay_listing_url": bad},
                            headers=headers)
            assert r.status_code == 422, bad
