"""
FIFA World Cup 2026 scraper.

Phase 1 ships `scrape_groups()` only — it best-effort scrapes the public FIFA
groups page and upserts rows into `group_standings`. The frontend renders the
seeded static draw as a fallback when the scraper has no fresh data, so this
scraper is allowed to fail gracefully.

This file MUST NOT import FastAPI or ML code.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from sqlalchemy import text

from db.engine import get_db_engine
from db.seed_wc2026 import GROUPS as STATIC_GROUPS

logger = logging.getLogger(__name__)


GROUPS_URL = (
    "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/groups"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT_S = 20


# Canonical team-name set drawn from the seeded draw. Used to recognize team
# strings on the FIFA page even if they appear with extra markup nearby.
_CANONICAL_TEAMS = {
    team for teams in STATIC_GROUPS.values() for team in teams
}


def _normalize_team(raw: str) -> Optional[str]:
    """
    Map a scraped team string back to its canonical seed name.

    Returns None if the string isn't recognizable as a WC2026 participant.
    """
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", raw).strip()
    if not cleaned:
        return None
    # Direct hit.
    if cleaned in _CANONICAL_TEAMS:
        return cleaned
    # Case-insensitive hit.
    lower = cleaned.lower()
    for canonical in _CANONICAL_TEAMS:
        if canonical.lower() == lower:
            return canonical
    # Contains hit (e.g. "Korea Republic 2-1" — pick the team prefix).
    for canonical in _CANONICAL_TEAMS:
        if canonical.lower() in lower:
            return canonical
    return None


def _fetch_groups_html() -> str:
    """
    Fetch the FIFA groups page HTML.

    Raises:
        requests.RequestException on transport errors / non-2xx responses.
    """
    response = requests.get(GROUPS_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.text


def _parse_groups(html: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Best-effort parser for the FIFA groups page.

    FIFA's site is client-rendered React in places; this parser walks the
    page tokens and recognizes "Group X" headers followed by sequences of
    canonical team names with optional numeric stats. It is intentionally
    defensive — when in doubt it falls back to seeded stats (zeros) so the
    scheduler can never accidentally wipe live data with junk.

    Returns:
        Mapping from "Group A" .. "Group L" to a list of dicts with the
        team name and stat columns (played/won/drawn/lost/gf/ga/points/rank).
        Groups not detected are simply omitted.
    """
    soup = BeautifulSoup(html, "html.parser")
    tokens = [t.strip() for t in soup.stripped_strings if t.strip()]

    groups: Dict[str, List[Dict[str, Any]]] = {}
    current_group: Optional[str] = None
    current_teams_seen: set[str] = set()

    group_header_re = re.compile(r"^Group\s+([A-L])$", re.IGNORECASE)

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        m = group_header_re.match(tok)
        if m:
            current_group = f"Group {m.group(1).upper()}"
            groups.setdefault(current_group, [])
            current_teams_seen = set()
            i += 1
            continue

        if current_group is not None:
            canonical = _normalize_team(tok)
            if canonical and canonical in STATIC_GROUPS.get(current_group, []):
                # Skip duplicates within a group (e.g. crest alt-text).
                if canonical in current_teams_seen:
                    i += 1
                    continue
                # Look ahead for up to 7 integers (played, won, drawn, lost,
                # gf, ga, points). FIFA may print these as separate tokens.
                stats: List[int] = []
                j = i + 1
                while j < len(tokens) and len(stats) < 7:
                    nxt = tokens[j]
                    if nxt.lstrip("+-").isdigit():
                        stats.append(int(nxt))
                        j += 1
                        continue
                    break

                team_payload: Dict[str, Any] = {"team": canonical}
                if len(stats) >= 7:
                    (played, won, drawn, lost, gf, ga, points) = stats[:7]
                    team_payload.update(
                        {
                            "played": played,
                            "won": won,
                            "drawn": drawn,
                            "lost": lost,
                            "goals_for": gf,
                            "goals_against": ga,
                            "points": points,
                        }
                    )
                groups[current_group].append(team_payload)
                current_teams_seen.add(canonical)
                # Stop collecting once we've seen all four expected teams.
                if len(current_teams_seen) == 4:
                    current_group = None
                i = j if j > i else i + 1
                continue

        i += 1

    return groups


def _upsert_group_standings(groups: Dict[str, List[Dict[str, Any]]]) -> int:
    """
    Upsert parsed group standings into PostgreSQL.

    Only updates the stats columns for rows that already exist (the seeded
    draw). Returns the number of rows upserted.
    """
    if not groups:
        return 0

    engine = get_db_engine()
    upsert_sql = text(
        """
        INSERT INTO group_standings (
            group_name, team, played, won, drawn, lost,
            goals_for, goals_against, points, rank, updated_at
        ) VALUES (
            :group_name, :team, :played, :won, :drawn, :lost,
            :goals_for, :goals_against, :points, :rank, NOW()
        )
        ON CONFLICT (group_name, team) DO UPDATE SET
            played = EXCLUDED.played,
            won = EXCLUDED.won,
            drawn = EXCLUDED.drawn,
            lost = EXCLUDED.lost,
            goals_for = EXCLUDED.goals_for,
            goals_against = EXCLUDED.goals_against,
            points = EXCLUDED.points,
            rank = EXCLUDED.rank,
            updated_at = NOW()
        """
    )

    affected = 0
    with engine.begin() as conn:
        for group_name, rows in groups.items():
            # Compute rank within each group using points then GD then GF.
            ranked = sorted(
                rows,
                key=lambda r: (
                    -int(r.get("points", 0)),
                    -(int(r.get("goals_for", 0)) - int(r.get("goals_against", 0))),
                    -int(r.get("goals_for", 0)),
                ),
            )
            for idx, row in enumerate(ranked, start=1):
                conn.execute(
                    upsert_sql,
                    {
                        "group_name": group_name,
                        "team": row["team"],
                        "played": int(row.get("played", 0)),
                        "won": int(row.get("won", 0)),
                        "drawn": int(row.get("drawn", 0)),
                        "lost": int(row.get("lost", 0)),
                        "goals_for": int(row.get("goals_for", 0)),
                        "goals_against": int(row.get("goals_against", 0)),
                        "points": int(row.get("points", 0)),
                        "rank": idx if "points" in row else None,
                    },
                )
                affected += 1
    return affected


def scrape_groups() -> int:
    """
    Fetch the FIFA groups page, parse standings, and upsert them.

    Phase 1 entry point for the scheduler. Returns the number of rows
    upserted; logs and swallows errors so a transient FIFA outage cannot
    crash the scheduler. Returns 0 on failure.
    """
    try:
        html = _fetch_groups_html()
    except Exception as exc:
        logger.warning(f"[fifa] Failed to fetch groups page: {exc}")
        return 0

    try:
        parsed = _parse_groups(html)
    except Exception as exc:
        logger.error(f"[fifa] Failed to parse groups page: {exc}", exc_info=True)
        return 0

    if not parsed:
        logger.info("[fifa] No groups parsed (page structure changed or pre-tournament).")
        return 0

    try:
        affected = _upsert_group_standings(parsed)
    except Exception as exc:
        logger.error(f"[fifa] Failed to upsert standings: {exc}", exc_info=True)
        return 0

    logger.info(f"[fifa] ✓ Upserted {affected} group_standings rows")
    print(f"[fifa] ✓ Upserted {affected} group_standings rows")
    return affected


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    scrape_groups()
