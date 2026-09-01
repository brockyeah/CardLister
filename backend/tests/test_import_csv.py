"""Bulk CSV import: header-name mapping, per-row skips, round-trip with export."""
import io
from datetime import datetime

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import Card


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _post_csv(client, headers, text):
    return client.post(
        "/api/cards/import.csv",
        files={"file": ("inventory.csv", io.BytesIO(text.encode()), "text/csv")},
        headers=headers,
    )


def test_import_requires_auth(db_session):
    with TestClient(app) as client:
        r = client.post("/api/cards/import.csv", files={"file": ("a.csv", io.BytesIO(b"Player\n"), "text/csv")})
        assert r.status_code == 401


def test_import_rejects_missing_player_header(db_session):
    with TestClient(app) as client:
        r = _post_csv(client, _auth(client), "Year,Brand\n2021,Bowman\n")
        assert r.status_code == 422
        assert "Player" in r.json()["detail"]


def test_export_import_round_trip(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="Wander Franco", year=2021, brand="Bowman",
            set_name="Chrome", card_number="BCP-100", quantity=3,
            is_first_bowman=True, listed_price=25.0, notes="PC",
            parallel_color="Gold", serial_number="12/50", is_refractor=True,
        ), headers=headers)
        exported = client.get("/api/cards/export.csv", headers=headers).text

        r = _post_csv(client, headers, exported)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1 and body["skipped"] == []
        # The only warning is the standing note that imported cards are not
        # mirrored until a resync — no per-row problems in a clean round-trip.
        assert len(body["warnings"]) == 1 and "Resync sheet" in body["warnings"][0]

        cards = db_session.query(Card).order_by(Card.id.asc()).all()
        assert len(cards) == 2
        imported = cards[1]
        assert imported.player_name == "Wander Franco"
        assert imported.year == 2021
        assert imported.set_name == "Chrome"
        assert imported.card_number == "BCP-100"
        assert imported.quantity == 3
        assert imported.is_first_bowman is True
        assert imported.listed_price == 25.0
        assert imported.notes == "PC"
        assert imported.parallel_color == "Gold"
        assert imported.serial_number == "12/50"
        assert imported.is_refractor is True
        # Export upper-cases status; import normalizes it back.
        assert imported.status == "active"
        # created_at round-trips through the "Date Listed" column.
        assert imported.created_at == cards[0].created_at


def test_escaped_formula_cells_round_trip(db_session):
    """The export's formula-injection escape (leading apostrophe) is stripped
    on import, so export -> import preserves the original value."""
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="Bobby Witt Jr.", notes="=SUM(A1:A9)", condition="-NM",
            serial_number="'-1/1 SP",
        ), headers=headers)
        exported = client.get("/api/cards/export.csv", headers=headers).text
        assert "'=SUM(A1:A9)" in exported

        r = _post_csv(client, headers, exported)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 1
        imported = db_session.query(Card).order_by(Card.id.desc()).first()
        assert imported.notes == "=SUM(A1:A9)"
        assert imported.condition == "-NM"
        # A hand-typed leading apostrophe survives the round trip: the export
        # escapes it to ''-1/1 SP and the import strips exactly one level.
        assert imported.serial_number == "'-1/1 SP"


def test_import_maps_columns_by_name_not_position(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Quantity,player,Parallel,Serial #,Refractor,Mystery Column\n"
            "2,Jackson Holliday,Gold,/50,Y,ignored\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 1
        card = db_session.query(Card).one()
        assert card.player_name == "Jackson Holliday"
        assert card.quantity == 2
        assert card.parallel_color == "Gold"
        assert card.serial_number == "/50"
        assert card.is_refractor is True
        assert card.status == "unlisted"


def test_import_skips_bad_rows_and_keeps_good_ones(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Player,Year,Status,Listed Price\n"
            ",2021,,\n"                       # no player
            "Good Card,notayear,,\n"          # bad year
            "Also Good,2020,bogus,\n"         # bad status
            "Keeper,2019,ACTIVE,$1,\n"        # note: $1 then trailing empty col
            "Elly De La Cruz,2022,ACTIVE,12.50\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        reasons = {s["row"]: s["reason"] for s in body["skipped"]}
        assert set(reasons) == {2, 3, 4}
        assert "player" in reasons[2]
        assert "number" in reasons[3]
        assert "status" in reasons[4]
        keeper = db_session.query(Card).filter(Card.player_name == "Keeper").one()
        assert keeper.status == "active"
        assert keeper.listed_price == 1.0


def test_import_drops_non_https_ebay_url_with_warning(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Player,eBay URL\n"
            "Safe,https://www.ebay.com/itm/123\n"
            "Unsafe,javascript:alert(1)\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        row_warnings = [w for w in body["warnings"] if "Resync sheet" not in w]
        assert len(row_warnings) == 1 and "row 3" in row_warnings[0]
        by_name = {c.player_name: c for c in db_session.query(Card).all()}
        assert by_name["Safe"].ebay_listing_url == "https://www.ebay.com/itm/123"
        assert by_name["Unsafe"].ebay_listing_url is None


def test_import_parses_sold_fields_and_dates(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Player,Status,Date Listed,Date Sold,Sale Price\n"
            "Sold Guy,SOLD,2026-01-05T10:00:00,2026-02-01,40\n"
            "Bad Date,ACTIVE,not-a-date,,\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        assert any("date listed" in w for w in body["warnings"])
        sold = db_session.query(Card).filter(Card.player_name == "Sold Guy").one()
        assert sold.sold_price == 40.0
        assert sold.created_at.isoformat() == "2026-01-05T10:00:00"
        assert sold.sold_at.isoformat() == "2026-02-01T00:00:00"


def test_import_skips_out_of_range_numbers_without_losing_batch(db_session):
    """A value that parses as a Python int but overflows SQLite's 64-bit
    INTEGER binding (e.g. a serial number pasted into the Year column) must be
    skipped per-row, not abort the whole import at commit time."""
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Player,Year,Quantity,Listed Price\n"
            f"Overflow Year,{'9' * 25},1,\n"
            f"Overflow Qty,2021,{'9' * 25},\n"
            "Infinite Price,2021,1,1e999\n"
            "Fine,2021,2,9.99\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        assert {s["row"] for s in body["skipped"]} == {2, 3, 4}
        assert all("number" in s["reason"] for s in body["skipped"])
        card = db_session.query(Card).one()
        assert card.player_name == "Fine"


def test_import_rejects_non_utf8(db_session):
    with TestClient(app) as client:
        r = client.post(
            "/api/cards/import.csv",
            files={"file": ("a.csv", io.BytesIO(b"\xff\xfe\x00bad"), "text/csv")},
            headers=_auth(client),
        )
        assert r.status_code == 422


def test_import_skips_negative_prices(db_session):
    """Card(**fields) bypasses the Pydantic ge=0 price guards, so _parse_money
    must reject negatives itself (auto-review finding on PR #24)."""
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Player,Year,Status,Listed Price,Sale Price\n"
            "Neg Listed,2021,ACTIVE,-5,\n"
            "Neg Sold,2021,SOLD,,-3.50\n"
            "Fine,2021,ACTIVE,0,\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        reasons = {s["row"]: s["reason"] for s in body["skipped"]}
        assert set(reasons) == {2, 3}
        assert all("negative" in reason for reason in reasons.values())
        assert db_session.query(Card).filter(Card.player_name == "Fine").one().listed_price == 0.0


def test_import_sold_row_requires_positive_sale_price(db_session):
    """Card(**fields) bypasses MarkSoldRequest's sold_price > 0 rule, so the
    importer must enforce it: a SOLD row with no (or zero) sale price would
    corrupt revenue analytics and the CSV export."""
    with TestClient(app) as client:
        headers = _auth(client)
        csv_text = (
            "Player,Status,Sale Price\n"
            "No Price,SOLD,\n"
            "Zero Price,SOLD,0\n"
            "Fine,SOLD,12.50\n"
        )
        r = _post_csv(client, headers, csv_text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        assert {s["row"] for s in body["skipped"]} == {2, 3}
        assert all("Sale Price" in s["reason"] for s in body["skipped"])
        assert db_session.query(Card).one().player_name == "Fine"


def test_import_drops_a_future_sold_date(db_session):
    """The other way a sale date reaches the database, and the one where the
    value came out of a file someone else edited. The row is kept — the rest of
    it is fine — and falls back to the same default a row with no Date Sold at
    all gets, rather than filing the sale under a year that has not happened."""
    with TestClient(app) as client:
        headers = _auth(client)
        future_year = datetime.utcnow().year + 36
        r = _post_csv(
            client, headers,
            "Player,Status,Date Sold,Sale Price\n"
            f"Typo Guy,SOLD,{future_year}-02-01,40\n",
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        assert any("in the future" in w for w in body["warnings"])
        card = db_session.query(Card).one()
        assert card.sold_at is not None
        assert card.sold_at.year != future_year


def test_import_sold_row_defaults_missing_sold_date(db_session):
    """Mirrors mark-sold: a sold card always carries a sale date."""
    with TestClient(app) as client:
        headers = _auth(client)
        r = _post_csv(client, _auth(client), "Player,Status,Sale Price\nSold Guy,SOLD,20\n")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 1
        assert any("Date Sold" in w for w in body["warnings"])
        assert db_session.query(Card).one().sold_at is not None


def test_whitespace_hidden_formula_round_trips(db_session):
    """The widened export escape must stay symmetric with the import unescape,
    or a tab-hidden formula would come back with its apostrophe still attached."""
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="Jackson Holliday", notes="\t=SUM(A1:A9)",
        ), headers=headers)
        exported = client.get("/api/cards/export.csv", headers=headers).text
        assert "'\t=SUM(A1:A9)" in exported

        r = _post_csv(client, headers, exported)
        assert r.status_code == 200, r.text
        imported = db_session.query(Card).order_by(Card.id.desc()).first()
        assert imported.notes == "\t=SUM(A1:A9)"
