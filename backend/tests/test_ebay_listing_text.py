"""The listing text must never invent a price.

`clipboard_text` is pasted straight into eBay's sell form, so a fabricated
`$0.00` is not a shortened truth — it reads as a filled-in field, and unlike a
wrong player name it is not the kind of thing a seller catches on review.
"""
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


def _listing(client, headers, **card_kw):
    created = client.post("/api/cards", json=_payload(**card_kw), headers=headers).json()
    r = client.get(f"/api/ebay/{created['id']}/listing-text", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_priceless_card_says_so_instead_of_zero(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        body = _listing(client, headers)  # no suggested_price, no listed_price

        assert body["has_price"] is False
        assert body["price"] is None
        assert "$0.00" not in body["clipboard_text"]
        assert "PRICE:\n(not set — look up comps before listing)" in body["clipboard_text"]


def test_listed_price_wins_over_suggested(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        body = _listing(client, headers, suggested_price=9.99, listed_price=24.5)

        assert body["has_price"] is True
        assert body["price"] == 24.5
        assert "PRICE:\n$24.50" in body["clipboard_text"]


def test_suggested_price_used_when_not_yet_listed(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        body = _listing(client, headers, suggested_price=12.0)

        assert body["has_price"] is True
        assert body["price"] == 12.0
        assert "PRICE:\n$12.00" in body["clipboard_text"]


def test_zero_price_counts_as_unset(db_session):
    """A $0.00 sale price is never a real one, so it can only mislead."""
    with TestClient(app) as client:
        headers = _auth(client)
        body = _listing(client, headers, suggested_price=0.0, listed_price=0.0)

        assert body["has_price"] is False
        assert body["price"] is None
        assert "$0.00" not in body["clipboard_text"]


def test_listing_text_missing_card_404(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.get("/api/ebay/999999/listing-text", headers=headers)
        assert r.status_code == 404, r.text
