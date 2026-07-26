import csv
import io

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.google_sheets import SHEET_HEADERS


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_export_requires_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/cards/export.csv").status_code == 401


def test_export_matches_sheet_layout(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="Wander Franco", year=2021, brand="Bowman",
            set_name="Chrome", card_number="BCP-100", quantity=3,
            is_first_bowman=True, listed_price=25.0,
        ), headers=headers)
        r = client.get("/api/cards/export.csv", headers=headers)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == SHEET_HEADERS
        assert len(rows) == 2
        assert rows[1][0] == "Wander Franco"
        assert rows[1][SHEET_HEADERS.index("Quantity")] == "3"
        assert rows[1][SHEET_HEADERS.index("1st Bowman")] == "Y"
