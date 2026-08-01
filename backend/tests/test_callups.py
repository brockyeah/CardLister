import json
from pathlib import Path
from unittest.mock import patch

from backend.services import callups
from backend.models import Card

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "transactions.json").read_text())


def test_normalize_name_strips_accents_and_case():
    assert callups.normalize_name("Acuña Jr.") == callups.normalize_name("acuna jr")
    assert callups.normalize_name(None) == ""


def test_fetch_keeps_only_callup_types():
    with patch.object(callups, "_get_json", return_value=FIXTURE):
        rows = callups.fetch_callup_transactions("2026-07-07", "2026-07-08")
    types = {r["type_desc"] for r in rows}
    assert types == {"Selected", "Recalled"}          # Optioned dropped
    holliday = next(r for r in rows if r["player_name"] == "Jackson Holliday")
    assert holliday["tx_id"] == 1001 and holliday["person_id"] == 700001
    assert holliday["to_team"] == "Baltimore Orioles"


def test_fetch_returns_empty_on_network_failure():
    with patch.object(callups, "_get_json", side_effect=RuntimeError("boom")):
        assert callups.fetch_callup_transactions("2026-07-07", "2026-07-08") == []


def test_count_inventory_matches(db_session):
    db_session.add_all([
        Card(player_name="Jackson Holliday", quantity=2, is_first_bowman=True),
        Card(player_name="jackson  holliday", quantity=1),  # normalized dup, not 1st Bowman
        Card(player_name="Someone Else", quantity=5, is_first_bowman=True),
    ])
    db_session.commit()
    assert callups.count_inventory_matches(db_session, "Jackson Holliday") == (3, 2)
    assert callups.count_inventory_matches(db_session, "Nobody") == (0, 0)


def test_count_inventory_matches_excludes_sold(db_session):
    db_session.add_all([
        Card(player_name="Jackson Holliday", quantity=2, is_first_bowman=True, status="sold"),
        Card(player_name="Jackson Holliday", quantity=1, is_first_bowman=False, status="active"),
    ])
    db_session.commit()
    assert callups.count_inventory_matches(db_session, "Jackson Holliday") == (1, 0)


def test_is_alertable_rule():
    assert callups.is_alertable("Selected", False) is True      # first call-up always
    assert callups.is_alertable("Recalled", True) is True       # recall of owned player
    assert callups.is_alertable("Recalled", False) is False     # recall, not owned → skip
