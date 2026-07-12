from backend.models import Card
from backend.routers.ebay import build_description
from backend.services.google_sheets import SHEET_HEADERS, _card_to_row


def _card(**kw):
    defaults = dict(player_name="Wander Franco", year=2021, brand="Bowman",
                    set_name="Chrome", card_number="BCP-100", condition="NM", quantity=1)
    defaults.update(kw)
    return Card(**defaults)


def test_sheet_row_matches_header_length_and_includes_quantity():
    row = _card_to_row(_card(quantity=3))
    assert len(row) == len(SHEET_HEADERS)
    assert SHEET_HEADERS[-2] == "Quantity"
    assert row[-2] == 3


def test_description_mentions_quantity_only_above_one():
    assert "Quantity available: 4" in build_description(_card(quantity=4))
    assert "Quantity available" not in build_description(_card(quantity=1))
