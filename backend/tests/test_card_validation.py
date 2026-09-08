from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import Card


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _payload(**kw):
    base = dict(player_name="Wander Franco", year=2021, brand="Bowman",
                set_name="Chrome", card_number="BCP-100", condition="NM")
    base.update(kw)
    return base


def test_ebay_listing_url_rejects_non_http_scheme(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/ebay-id",
                        json={"ebay_listing_id": "123",
                              "ebay_listing_url": "javascript:alert(document.cookie)"},
                        headers=headers)
        assert r.status_code == 422, r.text


def test_ebay_listing_url_accepts_https(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/ebay-id",
                        json={"ebay_listing_id": "123",
                              "ebay_listing_url": "https://www.ebay.com/itm/123"},
                        headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["ebay_listing_url"] == "https://www.ebay.com/itm/123"


def test_mark_sold_rejects_non_positive_price(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.post(f"/api/cards/{created['id']}/mark-sold",
                        json={"sold_price": 0}, headers=headers)
        assert r.status_code == 422, r.text
        r = client.post(f"/api/cards/{created['id']}/mark-sold",
                        json={"sold_price": -5}, headers=headers)
        assert r.status_code == 422, r.text


def test_patch_cannot_set_status_directly(db_session):
    """Status can only change via /mark-sold; PATCH must not accept it."""
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.patch(f"/api/cards/{created['id']}", json={"status": "sold"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"  # unchanged, "status" was silently ignored


def test_listed_price_rejects_negative(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post("/api/cards", json=_payload(listed_price=-10), headers=headers)
        assert r.status_code == 422, r.text


def test_quantity_rejects_zero_and_negative(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        for bad in (0, -1):
            r = client.post("/api/cards", json=_payload(quantity=bad), headers=headers)
            assert r.status_code == 422, r.text


def test_patch_quantity_rejects_zero_and_negative(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        for bad in (0, -3):
            r = client.patch(f"/api/cards/{created['id']}", json={"quantity": bad}, headers=headers)
            assert r.status_code == 422, r.text
        r = client.patch(f"/api/cards/{created['id']}", json={"quantity": 4}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["quantity"] == 4


def test_suggested_price_rejects_negative(db_session):
    """The same floor `listed_price` has had. Both are read by the Sheets price
    column, the listing text and the inventory value tile; only one was
    guarded, so a negative comp median (or a hand-crafted request) was stored
    and mirrored."""
    with TestClient(app) as client:
        headers = _auth(client)
        r = client.post("/api/cards", json=_payload(suggested_price=-10), headers=headers)
        assert r.status_code == 422, r.text

        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        r = client.patch(f"/api/cards/{created['id']}",
                         json={"suggested_price": -0.01}, headers=headers)
        assert r.status_code == 422, r.text
        # Zero is not negative and stays acceptable — the listing text already
        # treats a non-positive price as unset, which is the right place for
        # that judgment.
        r = client.patch(f"/api/cards/{created['id']}",
                         json={"suggested_price": 0}, headers=headers)
        assert r.status_code == 200, r.text


def test_a_legacy_negative_price_still_reads_back(db_session):
    """Reads report what is stored. FastAPI validates responses against
    `CardOut` too, so inheriting the input floors would turn one row saved
    before the floor existed into a 500 on the whole inventory list."""
    db = SessionLocal()
    try:
        db.add(Card(player_name="Legacy Row", suggested_price=-5, listed_price=-5))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        headers = _auth(client)
        r = client.get("/api/cards", headers=headers)
        assert r.status_code == 200, r.text
        row = next(c for c in r.json() if c["player_name"] == "Legacy Row")
        assert row["suggested_price"] == -5
        assert row["listed_price"] == -5


def _mark_sold(client, headers, card_id, **kw):
    return client.post(f"/api/cards/{card_id}/mark-sold", json=kw, headers=headers)


def test_mark_sold_rejects_a_future_sale_date(db_session):
    """A mistyped year is permanent furniture: it joins the sold-years picker
    forever, sorts to the end of every tax export, and the only way back is
    unmark-sold and redo."""
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        far = datetime.utcnow().replace(year=datetime.utcnow().year + 36)
        r = _mark_sold(client, headers, created["id"],
                       sold_price=25, sold_at=far.isoformat())
        assert r.status_code == 422, r.text
        # A day ahead is inside the skew allowance — the client builds the
        # instant from its own clock, and the two need not agree.
        soon = datetime.utcnow() + timedelta(hours=12)
        r = _mark_sold(client, headers, created["id"],
                       sold_price=25, sold_at=soon.isoformat())
        assert r.status_code == 200, r.text


def test_mark_sold_still_accepts_a_backdated_sale(db_session):
    """Backdating is deliberately unbounded — recording a sale weeks after the
    fact is ordinary, and a floor would reject it."""
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        old = datetime.utcnow() - timedelta(days=400)
        r = _mark_sold(client, headers, created["id"],
                       sold_price=25, sold_at=old.isoformat())
        assert r.status_code == 200, r.text
        assert r.json()["sold_at"].startswith(old.strftime("%Y-%m-%d"))


def test_a_future_sale_cannot_slip_through_on_a_utc_offset(db_session):
    """The bound is checked on the value as it will be *stored*.

    SQLAlchemy's SQLite dialect drops tzinfo without converting, so an aware
    instant validated as the moment it really is would then be stored as its
    wall-clock parts — landing a day past the bound that just admitted it.
    """
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        # Just under two days ahead in wall-clock terms, but a real instant
        # only ~1.4 days ahead thanks to the +14:00 offset. Both readings are
        # past the one-day allowance, so this must be refused either way.
        wall = datetime.utcnow() + timedelta(days=2)
        r = _mark_sold(client, headers, created["id"], sold_price=25,
                       sold_at=wall.replace(tzinfo=timezone(timedelta(hours=14))).isoformat())
        assert r.status_code == 422, r.text

        # And an accepted aware value is stored as UTC, not as its wall clock:
        # 23:00 at +14:00 is 09:00 UTC the same day.
        aware = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)
        r = _mark_sold(client, headers, created["id"], sold_price=25,
                       sold_at=(aware + timedelta(hours=14)).replace(
                           tzinfo=timezone(timedelta(hours=14))).isoformat())
        assert r.status_code == 200, r.text
        assert r.json()["sold_at"].startswith(aware.strftime("%Y-%m-%dT09:00"))


def test_mark_sold_refuses_to_overwrite_a_recorded_sale(db_session):
    """A second mark-sold must not silently replace the first sale's figures.

    unmark_sold has always refused to act on a card that is not sold; mark_sold
    had no mirror guard, so a double-submit on the modal, a stale second tab or
    a re-import replaced sold_price/sold_at with no warning and no way back.
    Those two columns are what the tax-year export and the Sheets "Date Sold"
    column read, so the clobbered row is wrong in the one report that has to be
    right — and it still looks like an ordinary sold card.
    """
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        first = _mark_sold(client, headers, created["id"],
                           sold_price=25.0, sold_at="2026-02-14T00:00:00")
        assert first.status_code == 200, first.text

        second = _mark_sold(client, headers, created["id"],
                            sold_price=999.0, sold_at="2026-03-01T00:00:00")
        assert second.status_code == 409, second.text

        # The original sale survives intact — the point of the guard.
        card = client.get("/api/cards", headers=headers).json()[0]
        assert card["sold_price"] == 25.0
        assert card["sold_at"].startswith("2026-02-14")


def test_a_sale_can_still_be_corrected_by_unmarking_first(db_session):
    """The guard refuses the clobber, not the correction: the existing
    reversible path (unmark, then re-mark) still records the new figures."""
    with TestClient(app) as client:
        headers = _auth(client)
        created = client.post("/api/cards", json=_payload(), headers=headers).json()
        assert _mark_sold(client, headers, created["id"],
                          sold_price=25.0).status_code == 200
        assert client.post(f"/api/cards/{created['id']}/unmark-sold",
                           headers=headers).status_code == 200
        again = _mark_sold(client, headers, created["id"], sold_price=30.0)
        assert again.status_code == 200, again.text
        assert again.json()["sold_price"] == 30.0


def test_a_sale_committed_mid_request_is_not_overwritten(db_session):
    """The endpoint itself must lose the race, not just the SQL underneath it.

    The first version of this guard read the card, checked `status`, then
    wrote — so two overlapping marks could both read it as unsold before
    either committed, and the second commit overwrote the first sale exactly
    as if there were no guard (Codex, PR #71). FastAPI runs this sync handler
    in a threadpool with a session per request, so that interleaving is real.

    Reproduced deterministically instead of with threads: the session handed
    to the handler fires a *different* session's sale in between the handler's
    own lookup and its write, which is precisely the window the old guard left
    open. A check-then-write handler passes its stale check and clobbers the
    sale; the conditional UPDATE matches no row and 409s.
    """
    from backend.database import SessionLocal
    from backend.main import app as fastapi_app
    from backend.database import get_db

    with TestClient(app) as client:
        headers = _auth(client)
        card_id = client.post("/api/cards", json=_payload(), headers=headers).json()["id"]

    def interloper():
        """A competing request that wins the race, committed and closed."""
        other = SessionLocal()
        try:
            other.query(Card).filter(Card.id == card_id).update(
                {"status": "sold", "sold_price": 25.0,
                 "sold_at": datetime(2026, 2, 14)},
                synchronize_session=False,
            )
            other.commit()
        finally:
            other.close()

    class RacingSession:
        """Delegates to a real session, firing `interloper` once — after the
        handler's 404 lookup has returned and before its write."""

        def __init__(self, inner):
            self._inner = inner
            self._queries = 0

        def query(self, *a, **kw):
            self._queries += 1
            if self._queries == 2:
                interloper()
            return self._inner.query(*a, **kw)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def racing_db():
        session = SessionLocal()
        try:
            yield RacingSession(session)
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = racing_db
    try:
        with TestClient(app) as client:
            headers = _auth(client)
            r = _mark_sold(client, headers, card_id,
                           sold_price=999.0, sold_at="2026-03-01T00:00:00")
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 409, r.text
    db_session.expire_all()
    card = db_session.query(Card).filter(Card.id == card_id).one()
    assert card.sold_price == 25.0, "the sale committed mid-request was overwritten"
    assert card.sold_at == datetime(2026, 2, 14)


def test_mark_sold_still_sells_a_card_whose_status_is_null(db_session):
    """The conditional UPDATE must not read a NULL status as 'sold'.

    `status` is nullable with a Python-side default, so `status != 'sold'`
    evaluates to NULL on such a row and matches nothing — which would 409 a
    card that has never been sold. Legacy and hand-written rows are the way a
    NULL gets in.
    """
    with TestClient(app) as client:
        headers = _auth(client)
        card_id = client.post("/api/cards", json=_payload(), headers=headers).json()["id"]

        db_session.query(Card).filter(Card.id == card_id).update(
            {"status": None}, synchronize_session=False)
        db_session.commit()

        r = _mark_sold(client, headers, card_id, sold_price=25.0)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "sold"
        assert r.json()["sold_price"] == 25.0
