from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import prospect_news
from backend.models import CallupEvent


def _auth(client):
    tok = client.post("/api/auth/login", json={"username": "tester", "password": "pw"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_score_article_rewards_keywords_and_recency():
    hit = {"title": "Top prospect called up to the Majors", "summary": "", "published_parsed": datetime.utcnow().timetuple()}
    miss = {"title": "Team wins game", "summary": "", "published_parsed": datetime.utcnow().timetuple()}
    assert prospect_news.score_article(hit) > prospect_news.score_article(miss)


def test_clean_summary_strips_tags_unescapes_entities_and_truncates():
    raw = "<p>Holliday &amp; the Orioles &mdash; " + ("a" * 250) + "</p>"
    cleaned = prospect_news._clean_summary(raw)
    assert "<p>" not in cleaned and "</p>" not in cleaned
    assert "&amp;" not in cleaned and "&" in cleaned
    assert cleaned.endswith("…")
    assert len(cleaned) <= 221

    short = prospect_news._clean_summary("<b>Short</b> &amp; sweet.")
    assert short == "Short & sweet."


def test_news_endpoint_returns_callups_and_articles(db_session):
    db_session.add(CallupEvent(tx_id=9001, date="2026-07-08", type_desc="Selected",
                               player_name="Jackson Holliday", to_team="Baltimore Orioles",
                               inventory_match=True, matched_card_count=3,
                               first_bowman_count=1,
                               created_at=datetime.utcnow()))
    db_session.commit()

    fake_articles = [{"title": "Jackson Holliday called up", "link": "http://x/1",
                      "source": "MLB.com", "published_iso": "2026-07-08T12:00:00", "age_days": 0,
                      "summary": "Holliday joins the Orioles roster ahead of tonight's game."}]
    with TestClient(app) as client:
        with patch.object(prospect_news, "fetch_articles", return_value=fake_articles):
            r = client.get("/api/news", headers=_auth(client))
    assert r.status_code == 200
    body = r.json()
    assert body["articles"] == fake_articles
    holliday = next(c for c in body["callups"] if c["player_name"] == "Jackson Holliday")
    assert holliday["inventory_match"]
    assert holliday["first_bowman_count"] == 1


def test_news_requires_auth():
    with TestClient(app) as client:
        assert client.get("/api/news").status_code == 401


def test_poll_now_runs_a_cycle(db_session):
    from backend.services import callups
    with TestClient(app) as client:
        with patch.object(callups, "fetch_callup_transactions", return_value=[]):
            r = client.post("/api/news/poll-now", headers=_auth(client))
    assert r.status_code == 200
    # The manual poll returns the cycle result verbatim, so it also reports how
    # many alerts are waiting on a retry, how many were dropped unsent, and
    # whether the upstream MLB fetch actually succeeded — the last one because
    # a swallowed fetch failure and a quiet day both produce zero new events.
    assert r.json() == {"new": 0, "emailed": 0, "pending": 0, "abandoned": 0,
                        "fetch_ok": True}
