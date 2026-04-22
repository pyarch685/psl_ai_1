"""
Twitter API v2 client for fetching user tweets.

Uses OAuth 2.0 App-only (Bearer Token) authentication.
Implements in-memory caching with 15-minute TTL to reduce API calls.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

import requests

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes

# In-memory cache: {username: (tweets, timestamp)}
_tweet_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}


def _get_bearer_token() -> Optional[str]:
    """
    Read the Twitter bearer token from the environment.

    Tokens are sometimes stored URL-encoded (e.g. '%2F' for '/', '%3D' for '='),
    which causes Twitter to reject the Authorization header. We transparently
    decode such tokens so both raw and URL-encoded forms work.
    """
    raw = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    if not raw:
        return None
    if "%" in raw:
        try:
            decoded = unquote(raw)
            if decoded != raw:
                logger.info("TWITTER_BEARER_TOKEN was URL-encoded; decoded for use")
            return decoded
        except Exception:  # pragma: no cover - defensive
            return raw
    return raw


def _is_cache_valid(username: str) -> bool:
    if username not in _tweet_cache:
        return False
    _, timestamp = _tweet_cache[username]
    return (time.time() - timestamp) < CACHE_TTL_SECONDS


def _get_cached_tweets(username: str) -> Optional[List[Dict[str, Any]]]:
    if not _is_cache_valid(username):
        return None
    tweets, _ = _tweet_cache[username]
    return tweets


def _set_cache(username: str, tweets: List[Dict[str, Any]]) -> None:
    _tweet_cache[username] = (tweets, time.time())


def _describe_twitter_error(resp: requests.Response) -> str:
    """Build a concise error string from a non-200 Twitter response."""
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:200]}
    title = body.get("title") or body.get("error") or ""
    detail = body.get("detail") or body.get("message") or ""
    pieces = [p for p in (str(resp.status_code), title, detail) if p]
    return " | ".join(pieces) or f"HTTP {resp.status_code}"


def fetch_user_tweets_result(
    username: str, max_results: int = 10
) -> Dict[str, Any]:
    """
    Fetch recent tweets for a username.

    Returns a dict: {"tweets": [...], "error": Optional[str]}.
    This is the preferred entry point because it surfaces upstream
    failures rather than swallowing them.
    """
    token = _get_bearer_token()
    if not token:
        return {"tweets": [], "error": "TWITTER_BEARER_TOKEN not set"}

    cached = _get_cached_tweets(username)
    if cached is not None:
        return {"tweets": cached, "error": None}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "psl-ai/1.0",
    }

    # Step 1: Resolve username -> user id
    try:
        r = requests.get(
            f"{TWITTER_API_BASE}/users/by/username/{username}",
            headers=headers,
            timeout=10,
        )
    except requests.RequestException as exc:
        msg = f"Network error resolving @{username}: {exc}"
        logger.warning(msg)
        return {"tweets": [], "error": msg}

    if r.status_code != 200:
        msg = f"Twitter user lookup failed: {_describe_twitter_error(r)}"
        logger.warning(msg)
        return {"tweets": [], "error": msg}

    try:
        user_id = r.json().get("data", {}).get("id")
    except ValueError:
        return {"tweets": [], "error": "Invalid JSON from Twitter user lookup"}

    if not user_id:
        return {"tweets": [], "error": f"User @{username} not found"}

    # Step 2: Fetch tweets
    try:
        r = requests.get(
            f"{TWITTER_API_BASE}/users/{user_id}/tweets",
            headers=headers,
            params={
                "max_results": max(5, min(max_results, 100)),
                "tweet.fields": "created_at,public_metrics",
                "exclude": "retweets,replies",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        msg = f"Network error fetching tweets for @{username}: {exc}"
        logger.warning(msg)
        return {"tweets": [], "error": msg}

    if r.status_code != 200:
        msg = f"Twitter tweets fetch failed: {_describe_twitter_error(r)}"
        logger.warning(msg)
        return {"tweets": [], "error": msg}

    try:
        raw_tweets = r.json().get("data", []) or []
    except ValueError:
        return {"tweets": [], "error": "Invalid JSON from Twitter tweets endpoint"}

    tweets: List[Dict[str, Any]] = []
    for t in raw_tweets:
        tid = t.get("id", "")
        metrics = t.get("public_metrics", {}) or {}
        tweets.append({
            "id": tid,
            "text": t.get("text", ""),
            "created_at": t.get("created_at", ""),
            "url": f"https://x.com/{username}/status/{tid}" if tid else "",
            "metrics": {
                "like_count": metrics.get("like_count"),
                "retweet_count": metrics.get("retweet_count"),
            } if metrics else None,
        })

    _set_cache(username, tweets)
    return {"tweets": tweets, "error": None}


def fetch_user_tweets(username: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Backwards-compatible wrapper returning only the tweets list."""
    return fetch_user_tweets_result(username, max_results)["tweets"]
