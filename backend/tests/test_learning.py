import json
from datetime import datetime

from fastapi.testclient import TestClient

from backend.models import Correction, Scan
from backend.services.learning import apply_exact_match, build_cheatsheet, diff_correction


def test_diff_ignores_case_and_blank_differences():
    extracted = {"player_name": "wander franco", "brand": "", "set_name": "Chrome"}
    saved = {"player_name": "Wander Franco", "brand": None, "set_name": "Chrome Prospects"}
    diff = diff_correction(extracted, saved)
    assert "player_name" not in diff
    assert "brand" not in diff
    assert diff["set_name"]["to"] == "Chrome Prospects"


def test_exact_match_overlays_identity_but_never_parallel(db_session):
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome Prospects",
        card_number="BCP-132",
        corrected_json=json.dumps({
            "player_name": "Tony Blanco Jr.", "year": 2024, "brand": "Bowman",
            "set_name": "Chrome Prospects", "card_number": "BCP-132",
            "team": "Washington Nationals", "is_rookie": False,
            "parallel_color": "Gold", "serial_number": "/50",
        }),
        diff_json=json.dumps({"set_name": {"from": "Chrome", "to": "Chrome Prospects"}}),
    ))
    db_session.commit()

    extracted = {"player_name": "", "year": 2024, "brand": "bowman", "set_name": "Chrome",
                 "card_number": "bcp-132", "parallel_color": None, "confidence_notes": ""}
    merged = apply_exact_match(db_session, extracted)
    assert merged["set_name"] == "Chrome Prospects"
    assert merged["player_name"] == "Tony Blanco Jr."
    assert merged["parallel_color"] is None  # copy-specific: never overridden
    assert "saved corrections" in merged["confidence_notes"]


def test_cheatsheet_dedupes_identical_rules(db_session):
    for i in range(40):
        db_session.add(Correction(
            username="tester", year=2024, brand="Bowman", set_name="Chrome",
            card_number=f"BCP-{i}",
            diff_json=json.dumps({"set_name": {"from": "Chrome", "to": "Chrome Prospects"}}),
        ))
    db_session.commit()
    sheet = build_cheatsheet(db_session)
    assert sheet
    assert sheet.count("\n") == 0  # 40 identical rules collapse to one line


def test_cheatsheet_caps_distinct_rules_at_max(db_session):
    # 40 *distinct* corrections must still clamp at CHEATSHEET_MAX_RULES —
    # this cap is what keeps per-scan prompt tokens at a plateau instead of
    # growing with every correction ever recorded.
    from backend.services.learning import CHEATSHEET_MAX_RULES

    for i in range(40):
        db_session.add(Correction(
            username="tester", year=2024, brand="Bowman", set_name=f"Set {i}",
            card_number=f"BCP-{i}",
            diff_json=json.dumps({"set_name": {"from": f"Set {i}", "to": f"Set {i} Prospects"}}),
        ))
    db_session.commit()
    sheet = build_cheatsheet(db_session)
    assert sheet.count("\n") == CHEATSHEET_MAX_RULES - 1


def test_cheatsheet_teaches_only_the_newest_correction_of_a_field(db_session):
    # A reversed correction: the user fixed set_name one way, then fixed it
    # back a week later because the first fix was wrong. Deduping on the
    # rendered rule kept both, so every later scan carried a contradictory
    # pair with nothing marking which one still stood.
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome",
        card_number="BCP-1", created_at=datetime(2026, 8, 1, 12, 0, 0),
        diff_json=json.dumps({"set_name": {"from": "Chrome", "to": "Chrome Prospects"}}),
    ))
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome",
        card_number="BCP-2", created_at=datetime(2026, 8, 8, 12, 0, 0),
        diff_json=json.dumps({"set_name": {"from": "Chrome Prospects", "to": "Chrome"}}),
    ))
    db_session.commit()

    sheet = build_cheatsheet(db_session)
    assert sheet.count("\n") == 0, f"expected one rule, got:\n{sheet}"
    # The surviving rule is the *newer* one — the correction that still stands.
    assert "you said set_name='Chrome Prospects'" in sheet
    assert "corrected it to 'Chrome'" in sheet


def test_cheatsheet_keeps_one_rule_per_field_not_per_value(db_session):
    # A single field corrected over and over in one set used to emit a distinct
    # rule per value and could consume the whole 30-rule budget, crowding out
    # every lesson from every other set. Only the newest survives now, leaving
    # room for the other field's rule.
    for i in range(40):
        db_session.add(Correction(
            username="tester", year=2024, brand="Bowman", set_name="Chrome",
            card_number=f"BCP-{i}", created_at=datetime(2026, 8, 1, 12, 0, i),
            diff_json=json.dumps({"card_number": {"from": f"{i}", "to": f"BCP-{i}"}}),
        ))
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome",
        card_number="BCP-99", created_at=datetime(2026, 8, 1, 11, 0, 0),
        diff_json=json.dumps({"team": {"from": "Nationals", "to": "Washington Nationals"}}),
    ))
    db_session.commit()

    sheet = build_cheatsheet(db_session)
    lines = sheet.splitlines()
    assert len(lines) == 2, f"expected one card_number rule + one team rule, got:\n{sheet}"
    assert any("card_number='39'" in line for line in lines)  # the newest of the 40
    assert any("team=" in line for line in lines)


def test_cheatsheet_keeps_the_same_field_across_different_sets(db_session):
    # Dedup is per (context, field), not per field: two sets that each need a
    # naming rule must both be taught.
    for set_name in ("Chrome", "Draft"):
        db_session.add(Correction(
            username="tester", year=2024, brand="Bowman", set_name=set_name,
            card_number="BCP-1",
            diff_json=json.dumps({"set_name": {"from": set_name, "to": f"{set_name} Prospects"}}),
        ))
    db_session.commit()

    sheet = build_cheatsheet(db_session)
    assert sheet.count("\n") == 1
    assert "2024 Bowman Chrome:" in sheet
    assert "2024 Bowman Draft:" in sheet


def test_cheatsheet_separates_sets_whose_context_lines_collide(db_session):
    # Vision splits one physical set two ways across scans, so brand "Bowman" +
    # set "Chrome Prospects" and brand "Bowman Chrome" + set "Prospects" both
    # render "2024 Bowman Chrome Prospects". Keying dedup on that joined string
    # would drop one of two genuinely different sets' lessons.
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome Prospects",
        card_number="BCP-1", created_at=datetime(2026, 8, 1, 12, 0, 0),
        diff_json=json.dumps({"card_number": {"from": "1", "to": "BCP-1"}}),
    ))
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman Chrome", set_name="Prospects",
        card_number="BCP-2", created_at=datetime(2026, 8, 8, 12, 0, 0),
        diff_json=json.dumps({"card_number": {"from": "2", "to": "BCP-2"}}),
    ))
    db_session.commit()

    sheet = build_cheatsheet(db_session)
    assert sheet.count("\n") == 1, f"expected both sets' rules, got:\n{sheet}"
    assert "to 'BCP-1'" in sheet
    assert "to 'BCP-2'" in sheet


def test_cheatsheet_treats_case_and_space_variants_as_one_set(db_session):
    # The mirror image of the collision above: "Bowman" and "bowman " are the
    # same set, so two corrections of the same field there are contradictory
    # and must collapse to the newest rather than becoming competing rules.
    db_session.add(Correction(
        username="tester", year=2024, brand="Bowman", set_name="Chrome",
        card_number="BCP-1", created_at=datetime(2026, 8, 1, 12, 0, 0),
        diff_json=json.dumps({"set_name": {"from": "Chrome", "to": "Chrome Prospects"}}),
    ))
    db_session.add(Correction(
        username="tester", year=2024, brand="bowman ", set_name=" CHROME",
        card_number="BCP-2", created_at=datetime(2026, 8, 8, 12, 0, 0),
        diff_json=json.dumps({"set_name": {"from": "Chrome Prospects", "to": "Chrome"}}),
    ))
    db_session.commit()

    sheet = build_cheatsheet(db_session)
    assert sheet.count("\n") == 0, f"expected one rule, got:\n{sheet}"
    assert "corrected it to 'Chrome'" in sheet  # the newer one


def test_create_card_with_scan_id_records_correction(db_session):
    from backend.main import app

    scan = Scan(username="tester", image_path="/uploads/x.jpg", model="claude-opus-4-7",
                extracted_json=json.dumps({"player_name": "Tony Blanco", "year": 2024,
                                           "brand": "Bowman", "set_name": "Chrome",
                                           "card_number": "BCP-132"}))
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    with TestClient(app) as client:
        tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
        r = client.post("/api/cards",
                        json={"player_name": "Tony Blanco Jr.", "year": 2024, "brand": "Bowman",
                              "set_name": "Chrome Prospects", "card_number": "BCP-132",
                              "scan_id": scan.id},
                        headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text

    corrections = db_session.query(Correction).all()
    assert len(corrections) == 1
    diff = json.loads(corrections[0].diff_json)
    assert diff["set_name"]["to"] == "Chrome Prospects"
    assert diff["player_name"]["to"] == "Tony Blanco Jr."
