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

    # Selected + owned Recalled(x2); Nobody skipped. pending is 0, not 3: it
    # counts what is still awaiting a retry, and a successful send stamps every
    # candidate — reporting the pre-send count would say three alerts are
    # waiting on the very cycle that just delivered them.
    assert result == {"new": 4, "emailed": 3, "pending": 0, "abandoned": 0}
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
    assert second == {"new": 0, "emailed": 0, "pending": 0, "abandoned": 0}
    assert db_session.query(CallupEvent).count() == 4


def test_email_failure_leaves_rows_for_retry(db_session):
    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=False), \
         patch.object(callups.billing_alerts, "notify_callup_alerts_undelivered"):
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
         patch("backend.services.callups.mailer.send_email", return_value=True) as send, \
         patch.object(callups.billing_alerts, "notify_callup_alerts_undelivered"):
        result = callups.run_poll_cycle(db_session)
    assert result == {"new": 0, "emailed": 0, "pending": 0, "abandoned": 1}
    send.assert_not_called()


def test_failing_mailer_alerts_the_owner_out_of_band(db_session):
    # The mailer failing is the *start* of the problem, and it used to be
    # completely silent: the poller retries, stamps its heartbeat after the
    # failure too — so /api/health keeps reporting the poller fresh — and the
    # owner finds out only by noticing an email that never came.
    db_session.add(Card(player_name="Owned Guy", quantity=2, is_first_bowman=True))
    db_session.add(Card(player_name="Plain Match", quantity=1))
    db_session.commit()

    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=False), \
         patch.object(callups.billing_alerts, "notify_callup_alerts_undelivered") as notify:
        result = callups.run_poll_cycle(db_session)

    assert result == {"new": 4, "emailed": 0, "pending": 3, "abandoned": 0}
    notify.assert_called_once_with(3, 0, callups.ALERT_MAX_AGE_HOURS)


def test_alerts_aging_out_unsent_are_counted_and_reported(db_session):
    # The end of the same problem: a mailer that stayed broken for two days.
    # These events leave the retry window permanently, unemailed — the window
    # is right, but nothing used to record that an alert had been dropped.
    db_session.add(Card(player_name="Owned Guy", quantity=1))
    for i, hours in enumerate((49, 60)):
        db_session.add(CallupEvent(
            tx_id=4000 + i, date="2026-07-01", type_desc="Selected",
            player_name=f"Missed Guy {i}", to_team="Mets", inventory_match=False,
            matched_card_count=0, emailed_at=None,
            created_at=datetime.utcnow() - timedelta(hours=hours),
        ))
    # Not alertable — a Recalled for a player the owner does not own is
    # un-emailed on purpose, so counting it would make the figure meaningless.
    db_session.add(CallupEvent(
        tx_id=4100, date="2026-07-01", type_desc="Recalled",
        player_name="Nobody Special", to_team="Reds", inventory_match=False,
        matched_card_count=0, emailed_at=None,
        created_at=datetime.utcnow() - timedelta(hours=49),
    ))
    # Already delivered, and older than the cutoff — not abandoned.
    db_session.add(CallupEvent(
        tx_id=4101, date="2026-07-01", type_desc="Selected",
        player_name="Sent Fine", to_team="Cubs", inventory_match=False,
        matched_card_count=0, emailed_at=datetime.utcnow(),
        created_at=datetime.utcnow() - timedelta(hours=49),
    ))
    db_session.commit()

    with patch.object(callups, "fetch_callup_transactions", return_value=[]), \
         patch("backend.services.callups.mailer.send_email", return_value=True), \
         patch.object(callups.billing_alerts, "notify_callup_alerts_undelivered") as notify:
        result = callups.run_poll_cycle(db_session)

    assert result == {"new": 0, "emailed": 0, "pending": 0, "abandoned": 2}
    # pending is 0: there is nothing left to retry, which is the whole point.
    notify.assert_called_once_with(0, 2, callups.ALERT_MAX_AGE_HOURS)


def test_events_older_than_the_reporting_band_are_not_re_reported(db_session):
    # Without a lower bound the count would grow forever, so a run months
    # later would keep alerting about call-ups from last season.
    db_session.add(CallupEvent(
        tx_id=4200, date="2026-01-01", type_desc="Selected",
        player_name="Ancient History", to_team="Mets", inventory_match=False,
        matched_card_count=0, emailed_at=None,
        created_at=datetime.utcnow() - timedelta(hours=200),
    ))
    db_session.commit()

    with patch.object(callups, "fetch_callup_transactions", return_value=[]), \
         patch("backend.services.callups.mailer.send_email", return_value=True), \
         patch.object(callups.billing_alerts, "notify_callup_alerts_undelivered") as notify:
        result = callups.run_poll_cycle(db_session)

    assert result == {"new": 0, "emailed": 0, "pending": 0, "abandoned": 0}
    notify.assert_not_called()


def test_healthy_cycle_does_not_alert(db_session):
    with patch.object(callups, "fetch_callup_transactions", return_value=TX), \
         patch("backend.services.callups.mailer.send_email", return_value=True), \
         patch.object(callups.billing_alerts, "notify_callup_alerts_undelivered") as notify:
        callups.run_poll_cycle(db_session)
    notify.assert_not_called()


def _reset_callup_throttle():
    callups.billing_alerts._last_callup_alert_at = 0.0


def test_undelivered_alert_pushes_and_names_a_missing_mail_config(monkeypatch):
    # A permanent misconfiguration and a provider outage produce the same
    # symptom — no email — and the fix for each is entirely different, so the
    # alert has to say which one it is.
    _reset_callup_throttle()
    sent = {}

    def record(channel):
        def _send(subject, body):
            sent[channel] = (subject, body)
            return True
        return _send

    monkeypatch.setattr(callups.billing_alerts, "send_email", record("email"))
    monkeypatch.setattr(callups.billing_alerts, "_push_via_ntfy", record("push"))
    monkeypatch.setattr(callups.billing_alerts.mailer, "is_configured", lambda: False)

    assert callups.billing_alerts.notify_callup_alerts_undelivered(3, 0, 48) is True
    subject, body = sent["push"]
    assert "not being delivered" in subject
    assert "3 call-up alert(s) could not be emailed" in body
    assert "ALERT_EMAILS" in body           # says how to fix it
    assert sent["email"][0] == subject      # both channels carry the same alert


def _capture_body(monkeypatch, configured=True):
    bodies = []
    monkeypatch.setattr(callups.billing_alerts, "send_email", lambda s, b: True)
    monkeypatch.setattr(callups.billing_alerts, "_push_via_ntfy",
                        lambda s, b: bodies.append(b) or True)
    monkeypatch.setattr(callups.billing_alerts.mailer, "is_configured", lambda: configured)
    return bodies


def test_undelivered_alert_distinguishes_an_outage_from_no_config(monkeypatch):
    _reset_callup_throttle()
    bodies = _capture_body(monkeypatch, configured=True)

    # A send failed on this cycle, so a live provider problem is the diagnosis.
    callups.billing_alerts.notify_callup_alerts_undelivered(1, 2, 48)
    body = bodies[0]
    assert "passed 48h unsent" in body
    assert "never be retried" in body
    assert "ALERT_EMAILS" not in body       # configured — do not misdiagnose it
    assert "provider credentials" in body


def test_abandoned_only_alert_does_not_claim_a_live_provider_failure(monkeypatch):
    # Nothing failed on this cycle — the sends that lost these alerts may have
    # been days ago and may since have cleared. Claiming a current outage is a
    # diagnosis of something that is not happening, and this very alert can go
    # out *by email* while its body tells the owner email is down.
    _reset_callup_throttle()
    bodies = _capture_body(monkeypatch, configured=True)

    callups.billing_alerts.notify_callup_alerts_undelivered(0, 2, 48)
    body = bodies[0]
    assert "passed 48h unsent" in body
    assert "provider credentials" not in body
    assert "nothing failed on this cycle" in body
    assert "could not be emailed just now" not in body   # no live failure to report


def test_missing_mail_config_is_reported_even_with_no_failed_send(monkeypatch):
    # Unlike a provider outage, this is a standing condition rather than an
    # event, so it holds whether or not a send was attempted this cycle.
    _reset_callup_throttle()
    bodies = _capture_body(monkeypatch, configured=False)

    callups.billing_alerts.notify_callup_alerts_undelivered(0, 2, 48)
    assert "ALERT_EMAILS" in bodies[0]
    assert "provider credentials" not in bodies[0]


def test_undelivered_alert_is_throttled(monkeypatch):
    # run_poll_cycle calls this every cycle for as long as the outage lasts —
    # at 15-minute polling that is 96 pushes a day without the throttle.
    _reset_callup_throttle()
    pushes = []
    monkeypatch.setattr(callups.billing_alerts, "send_email", lambda s, b: True)
    monkeypatch.setattr(callups.billing_alerts, "_push_via_ntfy",
                        lambda s, b: pushes.append(b) or True)
    monkeypatch.setattr(callups.billing_alerts.mailer, "is_configured", lambda: True)

    assert callups.billing_alerts.notify_callup_alerts_undelivered(1, 0, 48) is True
    assert callups.billing_alerts.notify_callup_alerts_undelivered(1, 0, 48) is False
    assert len(pushes) == 1


def test_callup_and_billing_alerts_do_not_share_a_throttle_clock(monkeypatch):
    # Two unrelated outages can be live at once; one must not silence the other.
    _reset_callup_throttle()
    callups.billing_alerts._last_alert_at = 0.0
    monkeypatch.setattr(callups.billing_alerts, "send_email", lambda s, b: True)
    monkeypatch.setattr(callups.billing_alerts, "_push_via_ntfy", lambda s, b: True)
    monkeypatch.setattr(callups.billing_alerts.mailer, "is_configured", lambda: True)

    assert callups.billing_alerts.notify_callup_alerts_undelivered(1, 0, 48) is True
    assert callups.billing_alerts.notify_credits_exhausted("credit balance too low") is True
