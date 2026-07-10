from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import create_token
from backend.models import UsageEvent


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_token_for_unconfigured_user_is_rejected():
    # A token minted for a username not in CARDLISTER_USERS (the ghost case).
    ghost = create_token("cardlister-user")
    with TestClient(app) as client:
        r = client.get("/api/analytics", headers={"Authorization": f"Bearer {ghost}"})
    assert r.status_code == 401


def test_reassign_moves_rows(db_session):
    db_session.add_all([
        UsageEvent(username="cardlister-user", model="claude-opus-4-7", input_tokens=100),
        UsageEvent(username="cardlister-user", model="claude-opus-4-7", input_tokens=200),
    ])
    db_session.commit()
    with TestClient(app) as client:
        r = client.post("/api/analytics/users/reassign",
                        json={"from_user": "cardlister-user", "to_user": "tester"},
                        headers=_auth(client))
    assert r.status_code == 200, r.text
    assert r.json()["moved"]["usage_events"] == 2
    assert db_session.query(UsageEvent).filter_by(username="cardlister-user").count() == 0
    assert db_session.query(UsageEvent).filter_by(username="tester").count() == 2


def test_reassign_rejects_unconfigured_target(db_session):
    with TestClient(app) as client:
        r = client.post("/api/analytics/users/reassign",
                        json={"from_user": "cardlister-user", "to_user": "not-a-user"},
                        headers=_auth(client))
    assert r.status_code == 400


def test_delete_user_data(db_session):
    db_session.add(UsageEvent(username="cardlister-user", model="m", input_tokens=1))
    db_session.commit()
    with TestClient(app) as client:
        r = client.delete("/api/analytics/users/cardlister-user/data", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["deleted"]["usage_events"] == 1
    assert db_session.query(UsageEvent).filter_by(username="cardlister-user").count() == 0


def test_configured_users_lists_env_users():
    with TestClient(app) as client:
        r = client.get("/api/analytics/users/configured", headers=_auth(client))
    assert r.status_code == 200
    assert r.json() == {"users": ["tester"]}
