"""Condition normalization, and the CSV-import path that applies it.

The case table in fixtures/condition_cases.json is shared with the frontend
mirror test (frontend/src/lib/condition.test.js). If the recognized spellings
change intentionally, update the table and both implementations — the two
suites must stay green off the same file.
"""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import Card
from backend.services.card_fields import CONDITION_VALUES, normalize_condition

TABLE = json.loads(
    (Path(__file__).parent / "fixtures" / "condition_cases.json").read_text()
)
CASES = TABLE["cases"]


def _auth(client):
    r = client.post("/api/auth/login", json={"username": "tester", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_normalize_condition_matches_shared_table(case):
    assert normalize_condition(case["input"]) == case["expected"]


def test_canonical_list_matches_shared_table():
    """The dropdown's grades and their order are part of the shared contract."""
    assert CONDITION_VALUES == TABLE["canonical"]


def test_every_canonical_value_is_a_fixed_point():
    """The form folds on every render, so a second pass must change nothing."""
    for value in CONDITION_VALUES:
        assert normalize_condition(value) == value
        assert normalize_condition(normalize_condition(value)) == value


def test_non_strings_pass_through_untouched():
    assert normalize_condition(None) is None
    assert normalize_condition(7) == 7


def test_import_folds_a_recognized_spelling(db_session):
    """A hand-edited sheet saying "Near Mint" imports as NM.

    Import is the one entry point that sees other people's spellings, which is
    why the fold lives here and not on POST /api/cards — that path deliberately
    stores strings verbatim so the formula-injection escape has something to
    escape.
    """
    csv_text = "Player,Year,Condition\nBobby Witt Jr.,2019,Near Mint\n"
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post(
            "/api/cards/import.csv",
            files={"file": ("cards.csv", io.BytesIO(csv_text.encode()), "text/csv")},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["created"] == 1

    card = db_session.query(Card).filter(Card.player_name == "Bobby Witt Jr.").one()
    assert card.condition == "NM"


def test_import_leaves_an_unrecognized_condition_alone(db_session):
    """"LP" is a real grade this app doesn't know; guessing at it would be worse
    than carrying it through, and the export/import round-trip depends on it."""
    csv_text = "Player,Condition\nJulio Rodriguez,LP\n"
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post(
            "/api/cards/import.csv",
            files={"file": ("cards.csv", io.BytesIO(csv_text.encode()), "text/csv")},
            headers=headers,
        )
        assert r.status_code == 200

    card = db_session.query(Card).filter(Card.player_name == "Julio Rodriguez").one()
    assert card.condition == "LP"


def test_import_still_defaults_a_blank_condition_to_nm(db_session):
    """The pre-existing default survives the fold — a blank cell is not a grade."""
    csv_text = "Player,Condition\nElly De La Cruz,\n"
    with TestClient(app) as client:
        headers = _auth(client)
        client.post(
            "/api/cards/import.csv",
            files={"file": ("cards.csv", io.BytesIO(csv_text.encode()), "text/csv")},
            headers=headers,
        )

    card = db_session.query(Card).filter(Card.player_name == "Elly De La Cruz").one()
    assert card.condition == "NM"


def test_import_does_not_undo_the_formula_escape(db_session):
    """A condition of "-NM" is escaped to "'-NM" on export and unescaped back to
    "-NM" on import. The fold must not then strip the "-" and call it NM: that
    would rewrite the value the injection test pins, and export -> import would
    stop being an identity for it."""
    csv_text = "Player,Condition\nWyatt Langford,'-NM\n"
    with TestClient(app) as client:
        headers = _auth(client)
        client.post(
            "/api/cards/import.csv",
            files={"file": ("cards.csv", io.BytesIO(csv_text.encode()), "text/csv")},
            headers=headers,
        )

    card = db_session.query(Card).filter(Card.player_name == "Wyatt Langford").one()
    assert card.condition == "-NM"
