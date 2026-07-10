"""1st Bowman flag: migration, extraction shape, learning identity, listing text."""
from sqlalchemy import create_engine, text

from backend.database import ensure_columns
from backend.models import Card
from backend.routers.ebay import build_description, build_title
from backend.services import claude_vision, learning


def _cols(engine, table):
    with engine.connect() as conn:
        return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def test_migration_adds_is_first_bowman(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cards (id INTEGER PRIMARY KEY, player_name VARCHAR)"))
    ensure_columns(engine)
    assert "is_first_bowman" in _cols(engine, "cards")


def test_extraction_shapes_include_first_bowman():
    assert '"is_first_bowman"' in claude_vision.SYSTEM_PROMPT
    assert "is_first_bowman" in claude_vision.MOCK_RESPONSE
    assert claude_vision._blank_card("x")["is_first_bowman"] is False


def test_first_bowman_is_identity_field():
    # Identity: every copy of the same card number shares 1st-Bowman status,
    # so exact-card overrides may set it — unlike copy-specific parallels.
    assert "is_first_bowman" in learning.IDENTITY_FIELDS
    assert "is_first_bowman" not in learning.COPY_SPECIFIC_FIELDS
    diff = learning.diff_correction(
        {"is_first_bowman": False}, {"is_first_bowman": True}
    )
    assert diff == {"is_first_bowman": {"from": False, "to": True}}


def test_listing_text_includes_first_bowman():
    card = Card(
        player_name="Jackson Holliday", year=2023, brand="Bowman", set_name="Chrome",
        card_number="BCP-9", team="Baltimore Orioles",
        is_first_bowman=True, is_rookie=False,
    )
    title = build_title(card)
    assert "1ST BOWMAN" in title
    assert len(title) <= 80
    assert "1st Bowman: YES" in build_description(card)


def test_migration_adds_first_bowman_count_to_callup_events(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE callup_events (id INTEGER PRIMARY KEY, tx_id INTEGER)"))
    ensure_columns(engine)
    assert "first_bowman_count" in _cols(engine, "callup_events")


def test_sheets_bounded_ranges_span_all_headers():
    # The A1 end column must track the row layout — a 19-column row written
    # to an A:R (18-col) range is rejected by the Sheets API and swallowed.
    from backend.services import google_sheets as gs

    assert gs._col_letter(1) == "A"
    assert gs._col_letter(19) == "S"
    assert gs._col_letter(27) == "AA"
    assert gs.END_COL == gs._col_letter(len(gs.SHEET_HEADERS))
