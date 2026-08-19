"""Sold-cards tax-year export.

Sold rows already leave the app in `export.csv`, but mixed into the whole
inventory with no sale date to sort or filter on. These tests pin the two
things that make the file usable for a return: it contains exactly the sales
of the requested year, and it is ordered by sale date.
"""
import csv
import io
from datetime import datetime

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.cards import SOLD_EXPORT_HEADERS


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _rows(response):
    return list(csv.reader(io.StringIO(response.text)))


def _sell(client, headers, card_id, price, sold_at):
    r = client.post(
        f"/api/cards/{card_id}/mark-sold",
        json={"sold_price": price, "sold_at": sold_at.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text


def _create(client, headers, **fields):
    r = client.post("/api/cards", json=fields, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_export_sold_requires_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/cards/export-sold.csv").status_code == 401
        assert client.get("/api/cards/sold-years").status_code == 401


def test_export_sold_contains_only_that_years_sales(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        a = _create(client, headers, player_name="Sold In 2025", listed_price=20.0)
        b = _create(client, headers, player_name="Sold In 2026", listed_price=30.0)
        _create(client, headers, player_name="Still Active")
        _sell(client, headers, a, 18.5, datetime(2025, 11, 4, 15, 0))
        _sell(client, headers, b, 41.0, datetime(2026, 3, 9, 15, 0))

        rows = _rows(client.get("/api/cards/export-sold.csv?year=2026", headers=headers))
        assert rows[0] == SOLD_EXPORT_HEADERS
        assert len(rows) == 2, rows
        row = rows[1]
        assert row[SOLD_EXPORT_HEADERS.index("Player")] == "Sold In 2026"
        assert row[SOLD_EXPORT_HEADERS.index("Date Sold")] == "2026-03-09"
        assert row[SOLD_EXPORT_HEADERS.index("Sale Price")] == "41.00"
        assert row[SOLD_EXPORT_HEADERS.index("Listed Price")] == "30.00"


def test_export_sold_without_a_year_returns_every_sale(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        a = _create(client, headers, player_name="A")
        b = _create(client, headers, player_name="B")
        _sell(client, headers, a, 5.0, datetime(2025, 1, 2, 12, 0))
        _sell(client, headers, b, 6.0, datetime(2026, 1, 2, 12, 0))

        rows = _rows(client.get("/api/cards/export-sold.csv", headers=headers))
        assert len(rows) == 3
        assert "cardlister-sold-all.csv" in (
            client.get("/api/cards/export-sold.csv", headers=headers)
            .headers["content-disposition"]
        )


def test_export_sold_is_ordered_by_sale_date(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        # Created out of order so insertion order can't accidentally pass.
        late = _create(client, headers, player_name="December")
        early = _create(client, headers, player_name="February")
        mid = _create(client, headers, player_name="July")
        _sell(client, headers, late, 9.0, datetime(2026, 12, 20, 10, 0))
        _sell(client, headers, early, 9.0, datetime(2026, 2, 3, 10, 0))
        _sell(client, headers, mid, 9.0, datetime(2026, 7, 8, 10, 0))

        rows = _rows(client.get("/api/cards/export-sold.csv?year=2026", headers=headers))
        players = [r[SOLD_EXPORT_HEADERS.index("Player")] for r in rows[1:]]
        assert players == ["February", "July", "December"]


def test_export_sold_names_the_file_after_the_year(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.get("/api/cards/export-sold.csv?year=2026", headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert 'filename="cardlister-sold-2026.csv"' in r.headers["content-disposition"]


def test_export_sold_year_is_a_year(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        assert client.get("/api/cards/export-sold.csv?year=99", headers=headers).status_code == 422
        assert client.get("/api/cards/export-sold.csv?year=abc", headers=headers).status_code == 422


def test_export_sold_escapes_formula_cells(db_session):
    """Same escape as export.csv — this file is opened in a spreadsheet by
    definition, and the player name is model-extracted from a photo."""
    with TestClient(app) as client:
        headers = _auth(client)
        card = _create(
            client, headers,
            player_name='=HYPERLINK("http://evil","click")',
            condition="-NM", serial_number="'-1/1 SP",
        )
        _sell(client, headers, card, 12.0, datetime(2026, 5, 5, 10, 0))
        rows = _rows(client.get("/api/cards/export-sold.csv?year=2026", headers=headers))
        assert rows[1][SOLD_EXPORT_HEADERS.index("Player")] == '\'=HYPERLINK("http://evil","click")'
        assert rows[1][SOLD_EXPORT_HEADERS.index("Condition")] == "'-NM"
        assert rows[1][SOLD_EXPORT_HEADERS.index("Serial #")] == "''-1/1 SP"


def test_sold_years_lists_years_with_sales_newest_first(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        assert client.get("/api/cards/sold-years", headers=headers).json() == {"years": []}

        a = _create(client, headers, player_name="A")
        b = _create(client, headers, player_name="B")
        c = _create(client, headers, player_name="C")
        _create(client, headers, player_name="Unsold")
        _sell(client, headers, a, 1.0, datetime(2025, 6, 1, 12, 0))
        _sell(client, headers, b, 1.0, datetime(2026, 6, 1, 12, 0))
        _sell(client, headers, c, 1.0, datetime(2025, 9, 1, 12, 0))

        assert client.get("/api/cards/sold-years", headers=headers).json() == {"years": [2026, 2025]}


def test_unmarking_a_sale_removes_it_from_the_export(db_session):
    """The export must track the ledger, not a snapshot of it — a mis-clicked
    mark-sold that was undone is not a sale to report."""
    with TestClient(app) as client:
        headers = _auth(client)
        card = _create(client, headers, player_name="Mistake")
        _sell(client, headers, card, 30.0, datetime(2026, 4, 1, 12, 0))
        assert len(_rows(client.get("/api/cards/export-sold.csv?year=2026", headers=headers))) == 2

        assert client.post(f"/api/cards/{card}/unmark-sold", headers=headers).status_code == 200
        assert len(_rows(client.get("/api/cards/export-sold.csv?year=2026", headers=headers))) == 1
        assert client.get("/api/cards/sold-years", headers=headers).json() == {"years": []}


def test_literal_routes_are_not_shadowed_by_the_card_id_route(db_session):
    """Invariant #3: a literal GET path declared below /{card_id} 422s against
    the int path param. Both new routes must resolve as themselves."""
    with TestClient(app) as client:
        headers = _auth(client)
        assert client.get("/api/cards/export-sold.csv", headers=headers).status_code == 200
        assert client.get("/api/cards/sold-years", headers=headers).status_code == 200
