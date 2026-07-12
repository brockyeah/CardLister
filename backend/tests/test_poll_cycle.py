from datetime import datetime, timedelta
from unittest.mock import patch

from backend.services import callups
from backend.models import Card, CallupEvent

TX = [
    {"tx_id": 2001, "date": "2026-07-08", "type_desc": "Selected", "player_name": "Jackson Holliday",
     "person_id": 1, "to_team": "Baltimore Orioles", "description": "selected contract"},
    {"tx_id": 2002, "date": "2026-07-08", "type_desc": "Recalled", "player_name": "Owned Guy",
     "person_id": 2, "to_team": "Rays", "description": "recalled"},
    {"tx_id": 2003, "date": "2026-07-08", "type_desc": "Recalled", "player_name": "Nobody Special",
     "person_id": 3, "to_team": "Reds", "description": "recalled"},
    {"tx_id": 2004, "date": "2026-07-08", "type_desc": "Recalled", "player_name": "Plain Match",
     "person_id": 4, "to_team": "Cubs", "description": "recalled"},
]


def test_poll_cycle_records_and_emails(db_session):
    db_session.add(Card(player_name="Owned Guy", quantity=2, is_first_bowman=True))
    db_session.add(Card(player_name="Plain Match", quantity=1))
    db_session.commit()

    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=True) as send:
        result = callups.run_poll_cycle(db_session)

    assert result == {"new": 4, "emailed": 3}          # Selected + owned Recalled(x2); Nobody skipped
    send.assert_called_once()
    subject, body = send.call_args.args
    assert "Owned Guy" in subject                       # inventory match leads per spec
    assert subject.endswith("(+2 more)")
    assert "You own 2" in body                          # inventory match surfaced
    assert "1st Bowman" in body                         # 1st Bowman ownership called out
    assert body.index("Owned Guy") < body.index("Plain Match") < body.index("Jackson Holliday")
    # emailed rows stamped; skipped row not
    rows = {e.tx_id: e for e in db_session.query(CallupEvent).all()}
    assert rows[2001].emailed_at is not None and rows[2003].emailed_at is None
    assert rows[2002].inventory_match is True and rows[2002].matched_card_count == 2
    assert rows[2002].first_bowman_count == 2 and rows[2001].first_bowman_count == 0
    assert rows[2004].first_bowman_count == 0 and rows[2004].inventory_match is True


def test_poll_cycle_dedups_second_run(db_session):
    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=True):
        callups.run_poll_cycle(db_session)
        second = callups.run_poll_cycle(db_session)
    assert second == {"new": 0, "emailed": 0}
    assert db_session.query(CallupEvent).count() == 4


def test_email_failure_leaves_rows_for_retry(db_session):
    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=False):
        result = callups.run_poll_cycle(db_session)
    assert result["emailed"] == 0
    assert all(e.emailed_at is None for e in db_session.query(CallupEvent).all())


def test_stale_unemailed_events_are_not_retried(db_session):
    stale = CallupEvent(tx_id=3001, date="2026-07-01", type_desc="Selected",
                        player_name="Old News", to_team="Mets", inventory_match=False,
                        matched_card_count=0, emailed_at=None,
                        created_at=datetime.utcnow() - timedelta(hours=49))
    db_session.add(stale); db_session.commit()
    with patch.object(callups, "fetch_callup_transactions", return_value=[]), \
         patch("backend.services.callups.mailer.send_email", return_value=True) as send:
        result = callups.run_poll_cycle(db_session)
    assert result == {"new": 0, "emailed": 0}
    send.assert_not_called()
