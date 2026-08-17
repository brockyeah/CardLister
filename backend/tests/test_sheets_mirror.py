"""Sheets mirror integrity: idempotent resync, blank-on-delete, race safety.

The defining property under test is that resync is idempotent — the old
implementation nulled every sheets_row and re-synced, which took sync_card's
append branch and added a complete second copy of the inventory per press.
`test_resync_twice_is_idempotent` fails against that implementation.

Patches the module attribute `google_sheets._get_service` (not a bound import)
with a fake spreadsheet that records every call, per the repo's testing note.
"""
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import Card
from backend.services import google_sheets
from backend.services.google_sheets import END_COL, SHEET_HEADERS


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


# The Sheets API's kwarg is literally named `range`, which shadows the builtin
# inside these methods — keep a reference so the fake can still count rows.
_range = range


class FakeSheet:
    """Minimal stand-in for the Sheets API, holding rows as a dict {row_no: values}."""

    def __init__(self, rows=None, fail_on=None):
        self.rows = dict(rows or {})
        self.calls = []          # (op, range) in order
        self.fail_on = fail_on or set()

    # --- API surface used by google_sheets.py -------------------------------
    def spreadsheets(self):
        return self

    def get(self, spreadsheetId=None, fields=None, range=None):
        if fields:  # _ensure_tab metadata probe
            return _Exec(lambda: {"sheets": [{"properties": {"title": "Inventory"}}]})
        # values().get — header probe or used-range probe
        if range and range.endswith("1"):
            return _Exec(lambda: {"values": [SHEET_HEADERS]})
        last = max(self.rows) if self.rows else 1
        values = [SHEET_HEADERS] + [self.rows.get(r, []) for r in _range(2, last + 1)]
        return _Exec(lambda: {"values": values})

    def values(self):
        return self

    def batchUpdate(self, spreadsheetId=None, body=None):
        return _Exec(lambda: {})

    def clear(self, spreadsheetId=None, range=None, body=None):
        def run():
            self.calls.append(("clear", range))
            if "clear" in self.fail_on:
                raise RuntimeError("clear boom")
            first, last = _parse_range(range)
            for r in _range(first, last + 1):
                self.rows.pop(r, None)
            return {}
        return _Exec(run)

    def update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        def run():
            self.calls.append(("update", range))
            if "update" in self.fail_on:
                raise RuntimeError("update boom")
            first, _ = _parse_range(range)
            for i, row in enumerate(body["values"]):
                self.rows[first + i] = row
            return {}
        return _Exec(run)

    def append(self, spreadsheetId=None, range=None, valueInputOption=None,
               insertDataOption=None, body=None):
        def run():
            self.calls.append(("append", range))
            row_no = (max(self.rows) if self.rows else 1) + 1
            self.rows[row_no] = body["values"][0]
            return {"updates": {"updatedRange": f"Inventory!A{row_no}:{END_COL}{row_no}"}}
        return _Exec(run)

    # --- helpers ------------------------------------------------------------
    def ops(self, kind):
        return [r for (op, r) in self.calls if op == kind]

    def players(self):
        """Player column of every non-empty data row, in row order."""
        return [self.rows[r][0] for r in sorted(self.rows)
                if r >= 2 and self.rows[r] and str(self.rows[r][0]).strip()]


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


def _parse_range(rng: str):
    """'Inventory!A2:V9' -> (2, 9); 'Inventory!A2' -> (2, 2)."""
    body = rng.split("!")[1]
    parts = body.split(":")
    first = int("".join(c for c in parts[0] if c.isdigit()))
    last = int("".join(c for c in parts[1] if c.isdigit())) if len(parts) > 1 else first
    return first, last


def _install(fake):
    return patch.object(google_sheets, "_get_service", lambda: (fake, "sheet-id"))


def _mkcard(db, name, **kw):
    card = Card(player_name=name, created_at=kw.pop("created_at", datetime(2026, 1, 1)), **kw)
    db.add(card)
    db.commit()
    return card


# --- the regression test -----------------------------------------------------

def test_resync_twice_is_idempotent(db_session):
    """Two resyncs produce identical sheet contents and never append.

    Fails against the pre-fix implementation, which appended a full second copy.
    """
    for n in ("Alpha", "Bravo", "Charlie"):
        _mkcard(db_session, n)
    fake = FakeSheet()

    with _install(fake), TestClient(app) as client:
        headers = _auth(client)
        r1 = client.post("/api/sheets/resync", headers=headers)
        assert r1.status_code == 200, r1.text
        after_first = fake.players()

        r2 = client.post("/api/sheets/resync", headers=headers)
        assert r2.status_code == 200, r2.text
        after_second = fake.players()

    assert after_first == ["Alpha", "Bravo", "Charlie"]
    assert after_second == after_first          # no duplication
    assert fake.ops("append") == []             # never the append branch
    assert r2.json()["synced"] == 3


def test_resync_never_clears_the_header(db_session):
    _mkcard(db_session, "Alpha")
    fake = FakeSheet()
    with _install(fake), TestClient(app) as client:
        client.post("/api/sheets/resync", headers=_auth(client))
    assert fake.ops("clear"), "expected a clear call"
    for rng in fake.ops("clear"):
        assert _parse_range(rng)[0] == 2, f"clear must start at row 2, got {rng}"


def test_resync_clears_residue_below_the_card_block(db_session):
    """A sheet longer than the DB must not keep rows below the rewritten block."""
    _mkcard(db_session, "Alpha")
    fake = FakeSheet(rows={2: ["Old1"], 3: ["Old2"], 4: ["Old3"], 5: ["Old4"]})
    with _install(fake), TestClient(app) as client:
        client.post("/api/sheets/resync", headers=_auth(client))
    assert fake.players() == ["Alpha"]


def test_resync_clears_residue_invisible_to_a_column_a_probe(db_session):
    """Residue whose Player cell is empty but which carries stale data further
    right must still fall inside the clear range."""
    _mkcard(db_session, "Alpha")
    stale = [""] * len(SHEET_HEADERS)
    stale[6] = "Y"  # RC column set, Player empty
    fake = FakeSheet(rows={2: ["Old"], 3: stale})
    with _install(fake), TestClient(app) as client:
        client.post("/api/sheets/resync", headers=_auth(client))
    assert 3 not in fake.rows or not any(str(c).strip() for c in fake.rows.get(3, []))


def test_resync_orders_equal_timestamps_by_id(db_session):
    """created_at alone is not a total order — a CSV import stamps many rows in
    the same instant, so without the id tiebreaker two runs assign different
    rows and idempotence breaks."""
    same = datetime(2026, 5, 5, 12, 0, 0)
    for n in ("One", "Two", "Three", "Four"):
        _mkcard(db_session, n, created_at=same)
    fake = FakeSheet()
    with _install(fake), TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/sheets/resync", headers=headers)
        first = fake.players()
        client.post("/api/sheets/resync", headers=headers)
        assert fake.players() == first


# --- partial failure, both orders --------------------------------------------

def test_cleared_but_not_rewritten_nulls_every_row(db_session):
    """Sheet ends up empty, so every index must be nulled — otherwise each card
    would write into a position nothing occupies any more."""
    for n in ("Alpha", "Bravo"):
        _mkcard(db_session, n)
    fake = FakeSheet(fail_on={"update"})
    with _install(fake), TestClient(app) as client:
        r = client.post("/api/sheets/resync", headers=_auth(client))
    body = r.json()
    assert body["ok"] is False and body["reason"] == "cleared"
    assert "empty" in body["detail"].lower()
    assert [c.sheets_row for c in db_session.query(Card).all()] == [None, None]


def test_setup_failure_leaves_indices_alone(db_session):
    """Nothing was cleared, so the existing indices stay valid."""
    a = _mkcard(db_session, "Alpha")
    a.sheets_row = 2
    db_session.commit()
    fake = FakeSheet(fail_on={"clear"})
    with _install(fake), TestClient(app) as client:
        r = client.post("/api/sheets/resync", headers=_auth(client))
    body = r.json()
    assert body["ok"] is False and body["reason"] == "setup"
    db_session.refresh(a)
    assert a.sheets_row == 2


def test_unconfigured_reports_rather_than_pretending_success(db_session):
    _mkcard(db_session, "Alpha")
    with patch.object(google_sheets, "_get_service", lambda: (None, None)), TestClient(app) as client:
        r = client.post("/api/sheets/resync", headers=_auth(client))
    body = r.json()
    assert body["ok"] is False and body["reason"] == "unconfigured"


# --- delete path --------------------------------------------------------------

def test_delete_blanks_exactly_its_own_row(db_session):
    a = _mkcard(db_session, "Alpha")
    b = _mkcard(db_session, "Bravo")
    a.sheets_row, b.sheets_row = 2, 3
    db_session.commit()
    fake = FakeSheet(rows={2: ["Alpha"], 3: ["Bravo"]})

    with _install(fake), TestClient(app) as client:
        r = client.delete(f"/api/cards/{a.id}", headers=_auth(client))
        assert r.status_code == 200, r.text

    updates = fake.ops("update")
    assert updates == [f"Inventory!A2:{END_COL}2"], updates
    assert fake.players() == ["Bravo"]


def test_delete_of_never_mirrored_card_calls_nothing(db_session):
    a = _mkcard(db_session, "Alpha")  # sheets_row stays None
    fake = FakeSheet()
    with _install(fake), TestClient(app) as client:
        client.delete(f"/api/cards/{a.id}", headers=_auth(client))
    assert fake.calls == []


def test_delete_does_not_erase_a_row_a_resync_reassigned(db_session):
    """A resync landing between the delete and the background blank may hand
    row N to a live card. Row 7 looks identical either way, so the check has to
    be about ownership."""
    survivor = _mkcard(db_session, "Survivor")
    survivor.sheets_row = 2
    db_session.commit()
    fake = FakeSheet(rows={2: ["Survivor"]})

    with _install(fake):
        google_sheets.blank_row(2, lambda r: True)   # row 2 is owned now

    assert fake.ops("update") == []
    assert fake.players() == ["Survivor"]


def test_blank_failure_is_swallowed(db_session):
    """The card is gone, so there is nothing to retry from; the residue is one
    stale row that the idempotent resync sweeps away."""
    fake = FakeSheet(fail_on={"update"}, rows={2: ["Ghost"]})
    with _install(fake):
        assert google_sheets.blank_row(2, lambda r: False) is False


# --- save racing a rewrite -----------------------------------------------------

def test_sync_card_rereads_row_inside_the_lock(db_session):
    """A save that read its sheets_row before a rewrite reassigned it must land
    on the NEW row, and must not be dropped."""
    card = _mkcard(db_session, "Alpha")
    card.sheets_row = 2
    db_session.commit()
    fake = FakeSheet(rows={2: ["Other"], 9: ["Alpha-old"]})

    with _install(fake):
        # reread reports the row a concurrent rewrite just assigned
        row = google_sheets.sync_card(card, reread_row=lambda: 9)

    assert row == 9
    assert fake.ops("update") == [f"Inventory!A9:{END_COL}9"]
    assert fake.rows[2] == ["Other"]          # someone else's row untouched
    assert fake.rows[9][0] == "Alpha"         # the save landed, not dropped


def test_import_then_resync_gives_one_row_per_card(db_session):
    import io as _io
    csv_text = "Player,Year\nAlpha,2021\nBravo,2022\n"
    fake = FakeSheet()
    with _install(fake), TestClient(app) as client:
        headers = _auth(client)
        r = client.post(
            "/api/cards/import.csv",
            files={"file": ("i.csv", _io.BytesIO(csv_text.encode()), "text/csv")},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert any("Resync" in w for w in r.json()["warnings"]), r.json()["warnings"]
        client.post("/api/sheets/resync", headers=headers)

    assert sorted(fake.players()) == ["Alpha", "Bravo"]
