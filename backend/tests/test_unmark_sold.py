from fastapi.testclient import TestClient

from backend.main import app


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _payload(**kw):
    base = dict(player_name="Jackson Holliday", year=2023, brand="Bowman",
                set_name="Chrome", card_number="BCP-50", condition="NM")
    base.update(kw)
    return base


def test_unmark_sold_restores_active_and_clears_sale(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/mark-sold",
                        json={"sold_price": 25.0}, headers=headers)
        assert r.status_code == 200, r.text
        sold = r.json()
        assert sold["status"] == "sold" and sold["sold_price"] == 25.0 and sold["sold_at"]

        r = client.post(f"/api/cards/{created['id']}/unmark-sold", headers=headers)
        assert r.status_code == 200, r.text
        restored = r.json()
        assert restored["status"] == "active"
        assert restored["sold_price"] is None
        assert restored["sold_at"] is None


def test_unmark_sold_rejects_non_sold_card(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/unmark-sold", headers=headers)
        assert r.status_code == 409, r.text


def test_unmark_sold_missing_card_404(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post("/api/cards/999999/unmark-sold", headers=headers)
        assert r.status_code == 404, r.text
