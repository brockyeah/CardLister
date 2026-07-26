import sqlite3
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_backup_requires_auth(db_session):
    with TestClient(app) as client:
        assert client.get("/api/analytics/backup.db").status_code == 401


def test_backup_is_a_valid_snapshot(db_session):
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/cards", json=dict(
            player_name="Jackson Holliday", year=2023, brand="Bowman",
            set_name="Chrome", card_number="BCP-19",
        ), headers=headers)
        r = client.get("/api/analytics/backup.db", headers=headers)
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers["content-disposition"]
        assert "cardlister-backup-" in r.headers["content-disposition"]

        # The download must itself be a readable SQLite DB containing the card.
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / "snap.db"
            snap.write_bytes(r.content)
            conn = sqlite3.connect(snap)
            try:
                players = [row[0] for row in conn.execute("SELECT player_name FROM cards")]
            finally:
                conn.close()
        assert "Jackson Holliday" in players
