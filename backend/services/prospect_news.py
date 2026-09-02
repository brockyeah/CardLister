"""Prospect-news RSS aggregation (ported from Daryls-Digest). Fetches MLB feeds,
scores by call-up keywords + recency, caches in-process for 15 minutes."""
import html
import logging
import os
import re
import time
from datetime import datetime

import feedparser
import httpx

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://www.mlb.com/feeds/news/rss.xml",
    "https://www.mlb.com/orioles/feeds/news/rss.xml",
]
KEYWORDS = ["called up", "call-up", "call up", "contract selected", "selected the contract",
            "promoted", "top prospect", "debut", "recalled", "roster move"]
_CACHE_TTL = 900  # 15 min

# Separate, shorter TTL for a result that came back empty. Empty is not the
# rare case: both feeds failing (10s timeout each, so ~20s of blocked worker
# thread per request) produces one, and so does any stretch — most of the
# winter — where no MLB headline clears the `score_article(a) > 0` floor.
# NewsSection fires GET /api/news on every Scanner mount, so without caching
# the empty result the app re-fetches both feeds on every page load, precisely
# when fetching is most expensive and least likely to work. Holding it for the
# full 15 minutes would be the other error: a transient feed outage would keep
# the panel blank long after the feeds recovered. Two minutes collapses a burst
# of page loads while letting a recovery show up on the next one.
_EMPTY_CACHE_TTL = 120  # 2 min

# `limit` is part of the key because it shapes the payload: a cached top-8
# served to a caller asking for 3 would be silently wrong. Only the router
# calls this today, always with the default, so this costs nothing and closes
# the hole rather than relying on that staying true.
_cache = {"at": 0.0, "articles": [], "limit": None}


def _feeds() -> list[str]:
    raw = os.getenv("NEWS_FEEDS", "").strip()
    return [u.strip() for u in raw.split(",") if u.strip()] or DEFAULT_FEEDS


def _clean_summary(raw: str, limit: int = 220) -> str:
    """Feed summaries arrive as HTML — strip tags/entities, collapse whitespace, truncate."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    text = " ".join(text.split())
    return text[:limit].rsplit(" ", 1)[0] + "…" if len(text) > limit else text


def score_article(article: dict) -> int:
    score = 0
    text = f"{article.get('title','')} {article.get('summary','')}".lower()
    for kw in KEYWORDS:
        if kw in text:
            score += 10
            if kw in article.get("title", "").lower():
                score += 5
    published = article.get("published_parsed")
    if published:
        days = (datetime.utcnow() - datetime(*published[:6])).days
        score += 20 if days == 0 else 10 if days == 1 else 5 if days <= 3 else 0
    return score


def _fetch_feed(url: str) -> list[dict]:
    try:
        resp = httpx.get(url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0 CardLister"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        source = parsed.feed.get("title", url)
        out = []
        for e in parsed.entries:
            published = e.get("published_parsed")
            age = (datetime.utcnow() - datetime(*published[:6])).days if published else None
            out.append({
                "title": e.get("title", ""), "summary": e.get("summary", ""),
                "link": e.get("link", ""), "source": source,
                "published_parsed": published,
                "published_iso": datetime(*published[:6]).isoformat() if published else None,
                "age_days": age,
            })
        return out
    except Exception as ex:
        logger.warning("Feed fetch failed (%s): %s", url, ex)
        return []


def fetch_articles(limit: int = 8) -> list[dict]:
    """Top scored articles across all feeds. Cached 15 min (2 min when empty)."""
    now = time.time()
    # Freshness is keyed on the timestamp stored beside the payload, never on
    # the payload's truthiness: the earlier `if _cache["articles"] and ...`
    # form meant an empty result could never satisfy the guard, so the one
    # case where fetching costs the most — both feeds timing out — was also
    # the one case that re-fetched on every single request.
    ttl = _CACHE_TTL if _cache["articles"] else _EMPTY_CACHE_TTL
    if _cache["at"] and now - _cache["at"] < ttl and _cache["limit"] == limit:
        return _cache["articles"]
    all_articles = []
    for url in _feeds():
        all_articles.extend(_fetch_feed(url))
    scored = sorted(all_articles, key=score_article, reverse=True)
    top = [{"title": a["title"], "link": a["link"], "source": a["source"],
            "published_iso": a["published_iso"], "age_days": a["age_days"],
            "summary": _clean_summary(a.get("summary", ""))}
           for a in scored[:limit] if score_article(a) > 0]
    _cache.update(at=now, articles=top, limit=limit)
    return top
