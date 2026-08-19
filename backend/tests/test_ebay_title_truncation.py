"""Truncation rules for the eBay title.

The shared parity table (fixtures/ebay_title_cases.json) pins exact strings so
the frontend mirror can't drift. These tests pin the *property* those strings
exist to protect: an over-long title must never end in a partial token.

The title goes on the clipboard and straight into eBay's sell form, so a
mid-token cut is not a shorter title but a false one — `/99` sliced to `/9`
advertises a card numbered to 9 that the seller does not own, and `REFRACTOR`
sliced to `REFRACTO` drops out of every buyer search for the word.
"""
from types import SimpleNamespace

from backend.routers.ebay import EBAY_TITLE_MAX, build_title, truncate_title


def _card(**over):
    base = dict(
        year=None, brand=None, set_name=None, player_name=None, card_number=None,
        team=None, is_rookie=False, is_first_bowman=False, is_autograph=False,
        is_patch=False, is_refractor=False, serial_number=None, parallel_color=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_serial_is_dropped_whole_rather_than_cut_to_a_different_number():
    # This exact card used to render "... REFRACTOR /9" — a /99 card advertised
    # as a /9. Omitting the serial understates the card; renaming it misstates
    # it, and only one of those is recoverable by the buyer reading the photos.
    title = build_title(_card(
        year=2023, brand="Bowman", set_name="Chrome Prospects",
        player_name="Jackson Chourio", card_number="BCP-100", team="Brewers",
        is_rookie=True, is_first_bowman=True, is_refractor=True, serial_number="99",
    ))
    assert "/9" not in title
    assert title.endswith("REFRACTOR")


def test_flag_is_dropped_whole_rather_than_half_rendered():
    title = build_title(_card(
        year=2024, brand="Topps", set_name="Chrome Update Series Rookie Debut",
        player_name="Wyatt Langford", card_number="USC-150", team="Rangers",
        is_rookie=True, is_refractor=True,
    ))
    assert "REFRACTO" not in title  # also excludes the full word, which no longer fits
    assert title.endswith("RC")


def test_multi_word_flag_is_dropped_whole_rather_than_left_as_a_fragment():
    # "1ST BOWMAN" is two words but one flag. Cutting on word boundaries alone
    # left a bare trailing "1ST", which reads as the start of some other claim
    # about the card rather than as a shortened one.
    title = build_title(_card(
        player_name="Holliday", year=2023, brand="Bowman", card_number="1", team="Orioles",
        set_name="Chrome " + " ".join(["X"] * 19),
        is_first_bowman=True, is_rookie=True, is_autograph=True, is_refractor=True,
        serial_number="99", parallel_color="Gold",
    ))
    assert "1ST" not in title
    assert title.endswith("RC")  # the higher-priority flag still survives


def test_short_titles_are_returned_untouched():
    units = ["2024", "Topps", "Chrome", "Player", "#1"]
    assert truncate_title(units) == "2024 Topps Chrome Player #1"


def test_title_exactly_at_the_cap_is_not_truncated():
    exact = "x" * EBAY_TITLE_MAX
    assert truncate_title([exact]) == exact


def test_no_trailing_partial_unit_at_any_length():
    # Slide the boundary across every position around the cap: whatever the
    # length, the result must be a whole-unit prefix of the input.
    units = ["2024", "Topps", "Chrome", "Update", "Sapphire", "Edition",
             "Some", "Player", "Name", "#BCP-100", "1ST BOWMAN", "REFRACTOR", "/99", "Brewers"]
    for count in range(1, len(units) + 1):
        prefix = units[:count]
        out = truncate_title(prefix)
        assert len(out) <= EBAY_TITLE_MAX
        # The output is always some whole-unit prefix of the input.
        kept = out.split(" ") if out else []
        rejoined = []
        for unit in prefix:
            unit_words = unit.split(" ")
            if kept[len(rejoined):len(rejoined) + len(unit_words)] != unit_words:
                break
            rejoined.extend(unit_words)
        assert rejoined == kept


def test_single_unit_over_the_cap_still_yields_a_title():
    # No boundary exists to fall back to, so the hard slice is the only option —
    # an empty title would be worse than a clipped one.
    assert truncate_title(["X" * 95]) == "X" * EBAY_TITLE_MAX


def test_leading_oversized_unit_does_not_swallow_later_units():
    # The fallback applies only when nothing fits at all; here the first unit
    # is over the cap, so later units cannot be kept either.
    out = truncate_title(["Y" * 90, "Brewers"])
    assert len(out) == EBAY_TITLE_MAX
    assert "Brewers" not in out


def test_a_later_shorter_flag_never_jumps_ahead_of_a_dropped_one():
    # Skipping the flag that doesn't fit and keeping a shorter one after it
    # would silently reorder the deliberate flag priority.
    # "1ST BOWMAN" pushes past the cap; the shorter "AUTO" behind it would fit,
    # but keeping it would advertise the lesser flag and hide the greater one.
    out = truncate_title(["A" * 70, "1ST BOWMAN", "AUTO"])
    assert out == "A" * 70

