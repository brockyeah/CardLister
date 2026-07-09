import json

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
