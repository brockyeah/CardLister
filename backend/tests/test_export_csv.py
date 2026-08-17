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
            parallel_color="Gold", serial_number="12/50", is_refractor=True,
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
        assert rows[1][SHEET_HEADERS.index("Parallel")] == "Gold"
        assert rows[1][SHEET_HEADERS.index("Serial #")] == "12/50"
        assert rows[1][SHEET_HEADERS.index("Refractor")] == "Y"


def test_export_escapes_formula_cells(db_session):
    """Cells starting with = + - @ get a leading apostrophe so a crafted value
    can't execute as a formula when the CSV is opened in Excel/Sheets."""
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="=HYPERLINK(\"http://evil\",\"click\")",
            notes="@SUM(A1)", condition="-NM", serial_number="'-1/1 SP",
        ), headers=headers)
        r = client.get("/api/cards/export.csv", headers=headers)
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[1][SHEET_HEADERS.index("Player")] == "'=HYPERLINK(\"http://evil\",\"click\")"
        assert rows[1][SHEET_HEADERS.index("Notes")] == "'@SUM(A1)"
        assert rows[1][SHEET_HEADERS.index("Condition")] == "'-NM"
        # A literal apostrophe before a formula char is escaped too, so the
        # importer can tell it apart from an exporter-added apostrophe.
        assert rows[1][SHEET_HEADERS.index("Serial #")] == "''-1/1 SP"
        # Ordinary cells are untouched.
        assert rows[1][SHEET_HEADERS.index("Status")] == "ACTIVE"


def test_export_escapes_formulas_hidden_behind_leading_whitespace(db_session):
    """A formula preceded by tab/CR/space must be escaped too.

    Spreadsheets discard leading whitespace and control characters before
    deciding whether a cell is a formula, so testing only for a leading
    apostrophe let "\t=HYPERLINK(...)" through unescaped — Excel drops the tab
    and evaluates the rest. The write path never normalizes strings, so such a
    value reaches the CSV verbatim from POST /api/cards.
    """
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="\t=HYPERLINK(\"http://evil\",\"click\")",
            notes="\r=1+1", condition=" =cmd|' /c calc'!A1",
            team="\t'=1+1",
        ), headers=headers)
        r = client.get("/api/cards/export.csv", headers=headers)
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[1][SHEET_HEADERS.index("Player")] == "'\t=HYPERLINK(\"http://evil\",\"click\")"
        assert rows[1][SHEET_HEADERS.index("Notes")] == "'\r=1+1"
        assert rows[1][SHEET_HEADERS.index("Condition")] == "' =cmd|' /c calc'!A1"
        # Noise characters are a set, so any mix of them peels off.
        assert rows[1][SHEET_HEADERS.index("Team")] == "'\t'=1+1"


def test_export_leaves_harmless_whitespace_cells_alone(db_session):
    """Widening the check must not escape every space-led cell — only the ones
    that hide a formula character."""
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name=" Bobby Witt Jr.", notes="\tsecond copy", condition="' ",
        ), headers=headers)
        r = client.get("/api/cards/export.csv", headers=headers)
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[1][SHEET_HEADERS.index("Player")] == " Bobby Witt Jr."
        assert rows[1][SHEET_HEADERS.index("Notes")] == "\tsecond copy"
        assert rows[1][SHEET_HEADERS.index("Condition")] == "' "
