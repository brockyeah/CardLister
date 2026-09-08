from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import prospect_news
from backend.models import CallupEvent


@pytest.fixture
def clean_news_cache():
    """The article cache is module-level state, so tests that exercise it have
    to leave it as they found it or they change what a later test fetches."""
    before = dict(prospect_news._cache)
    prospect_news._cache.update(at=0.0, articles=[], limit=None)
    yield prospect_news._cache
    prospect_news._cache.clear()
    prospect_news._cache.update(before)


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


def test_an_empty_result_is_still_cached(clean_news_cache):
    """The expensive case must not also be the uncached one.

    The guard used to read `if _cache["articles"] and ...`, keying freshness on
    the truthiness of the payload rather than on the timestamp stored beside
    it — so an empty result never satisfied it. Empty is the ordinary outcome
    of both feeds failing (10s timeout each, ~20s of blocked worker thread) and
    of an offseason where nothing clears the score floor, and NewsSection fires
    GET /api/news on every Scanner mount.
    """
    with patch.object(prospect_news, "_feeds", return_value=["http://feed/a", "http://feed/b"]):
        with patch.object(prospect_news, "_fetch_feed", return_value=[]) as fetch:
            assert prospect_news.fetch_articles() == []
            assert fetch.call_count == 2
            assert prospect_news.fetch_articles() == []
            assert fetch.call_count == 2, "an empty result re-fetched every feed"


def test_the_empty_result_is_held_for_a_shorter_ttl_than_a_real_one(clean_news_cache):
    """A feed outage should recover on the next page load or two, not in 15
    minutes — while a real result keeps the full TTL it always had."""
    import time

    with patch.object(prospect_news, "_feeds", return_value=["http://feed/a"]):
        with patch.object(prospect_news, "_fetch_feed", return_value=[]) as fetch:
            # Empty and older than the negative TTL: re-fetch.
            clean_news_cache.update(at=time.time() - prospect_news._EMPTY_CACHE_TTL - 1,
                                    articles=[], limit=8)
            prospect_news.fetch_articles()
            assert fetch.call_count == 1

            # A populated cache of the same age is still fresh, because the
            # long TTL applies to it.
            clean_news_cache.update(at=time.time() - prospect_news._EMPTY_CACHE_TTL - 1,
                                    articles=[{"title": "cached"}], limit=8)
            assert prospect_news.fetch_articles() == [{"title": "cached"}]
            assert fetch.call_count == 1

    assert prospect_news._EMPTY_CACHE_TTL < prospect_news._CACHE_TTL


def test_a_different_limit_is_not_served_from_the_cache(clean_news_cache):
    """`limit` shapes the payload, so it has to be part of the cache key — a
    cached top-8 handed to a caller asking for 3 is silently wrong."""
    articles = [{"title": f"a{i}", "summary": "called up", "link": "", "source": "s",
                 "published_iso": None, "age_days": None, "published_parsed": None}
                for i in range(8)]
    with patch.object(prospect_news, "_feeds", return_value=["http://feed/a"]):
        with patch.object(prospect_news, "_fetch_feed", return_value=articles):
            assert len(prospect_news.fetch_articles(limit=8)) == 8
            assert len(prospect_news.fetch_articles(limit=3)) == 3


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
    # many alerts are waiting on a retry and how many were dropped unsent.
    assert r.json() == {"new": 0, "emailed": 0, "pending": 0, "abandoned": 0}
