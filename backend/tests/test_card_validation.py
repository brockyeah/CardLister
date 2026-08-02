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


def test_ebay_listing_url_rejects_non_http_scheme(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/ebay-id",
                        json={"ebay_listing_id": "123",
                              "ebay_listing_url": "javascript:alert(document.cookie)"},
                        headers=headers)
        assert r.status_code == 422, r.text


def test_ebay_listing_url_accepts_https(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/ebay-id",
                        json={"ebay_listing_id": "123",
                              "ebay_listing_url": "https://www.ebay.com/itm/123"},
                        headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["ebay_listing_url"] == "https://www.ebay.com/itm/123"


def test_mark_sold_rejects_non_positive_price(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/mark-sold",
                        json={"sold_price": 0}, headers=headers)
        assert r.status_code == 422, r.text
        r = client.post(f"/api/cards/{created['id']}/mark-sold",
                        json={"sold_price": -5}, headers=headers)
        assert r.status_code == 422, r.text


def test_patch_cannot_set_status_directly(db_session):
    """Status can only change via /mark-sold; PATCH must not accept it."""
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.patch(f"/api/cards/{created['id']}", json={"status": "sold"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"  # unchanged, "status" was silently ignored


def test_listed_price_rejects_negative(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post("/api/cards", json=_payload(listed_price=-10), headers=headers)
        assert r.status_code == 422, r.text


def test_quantity_rejects_zero_and_negative(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        for bad in (0, -1):
            r = client.post("/api/cards", json=_payload(quantity=bad), headers=headers)
            assert r.status_code == 422, r.text


def test_patch_quantity_rejects_zero_and_negative(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        for bad in (0, -3):
            r = client.patch(f"/api/cards/{created['id']}", json={"quantity": bad}, headers=headers)
            assert r.status_code == 422, r.text
        r = client.patch(f"/api/cards/{created['id']}", json={"quantity": 4}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["quantity"] == 4
