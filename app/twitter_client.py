"""
Twitter API v2 client for fetching user tweets.

Uses OAuth 2.0 App-only (Bearer Token) authentication.
Implements in-memory caching with 15-minute TTL to reduce API calls.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

TWITTER_API_BASE = "https://api.twitter.com/2"
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes

# In-memory cache: {username: (tweets, timestamp)}
_tweet_cache: Dict[str, tuple[List[Dict[str, Any]], float]] = {}


def _get_bearer_token() -> Optional[str]:
    """Get Bearer Token from environment."""
    token = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    return token if token else None


def _is_cache_valid(username: str) -> bool:
    """Check if cached tweets for username are still valid."""
    if username not in _tweet_cache:
        return False
    _, timestamp = _tweet_cache[username]
    return (time.time() - timestamp) < CACHE_TTL_SECONDS


def _get_cached_tweets(username: str) -> Optional[List[Dict[str, Any]]]:
    """Return cached tweets if valid."""
    if not _is_cache_valid(username):
        return None
    tweets, _ = _tweet_cache[username]
    return tweets


def _set_cache(username: str, tweets: List[Dict[str, Any]]) -> None:
    """Store tweets in cache."""
    _tweet_cache[username] = (tweets, time.time())


def fetch_user_tweets(username: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch recent tweets from a Twitter user by username.

    Uses Twitter API v2:
    1. GET /2/users/by/username/:username -> user id
    2. GET /2/users/:id/tweets -> tweets

    Returns:
        List of dicts with keys: id, text, created_at, url, metrics (optional)
    """
    token = _get_bearer_token()
    if not token:
        return []

    # Check cache
    cached = _get_cached_tweets(username)
    if cached is not None:
        return cached

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Step 1: Resolve username to user ID
    try:
        r = requests.get(
            f"{TWITTER_API_BASE}/users/by/username/{username}",
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        user_id = data.get("data", {}).get("id")
        if not user_id:
            return []
    except (requests.RequestException, KeyError):
        return []

    # Step 2: Fetch tweets
    try:
        r = requests.get(
            f"{TWITTER_API_BASE}/users/{user_id}/tweets",
            headers=headers,
            params={
                "max_results": min(max_results, 100),
                "tweet.fields": "created_at,public_metrics",
                "exclude": "retweets,replies",
            },
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        raw_tweets = data.get("data", [])
    except (requests.RequestException, KeyError):
        return []

    # Parse into simple shape
    tweets: List[Dict[str, Any]] = []
    for t in raw_tweets:
        tid = t.get("id", "")
        text = t.get("text", "")
        created_at = t.get("created_at", "")
        metrics = t.get("public_metrics", {})
        url = f"https://twitter.com/{username}/status/{tid}" if tid else ""
        tweets.append({
            "id": tid,
            "text": text,
            "created_at": created_at,
            "url": url,
            "metrics": {
                "like_count": metrics.get("like_count"),
                "retweet_count": metrics.get("retweet_count"),
            } if metrics else None,
        })

    _set_cache(username, tweets)
    return tweets
