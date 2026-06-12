"""
FIFA World Cup 2026 scraper.

Pulls match data from FIFA's undocumented JSON API (the same backend used by
fifa.com's mobile and web apps) and:

- computes group standings from completed matches (``scrape_groups``)
- persists group-stage fixtures into ``wc_fixtures`` (``scrape_wc_fixtures``)

We previously scraped the public groups page, but that page is rendered
client-side by React and returns ~5KB of empty shell HTML to non-browser
clients — the parser had no chance.

Both functions are intentionally defensive: any error is logged and
swallowed so a transient FIFA outage cannot crash the scheduler.

This file MUST NOT import FastAPI or ML code.
"""
from __future__ import annotations

import logging
import os
import unicodedata
from datetime import date as _date, datetime
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import text

from db.engine import get_db_engine
from db.seed_wc2026 import GROUPS as STATIC_GROUPS

logger = logging.getLogger(__name__)


# FIFA's undocumented mobile/web JSON API. IDs are stable across the
# tournament; they were sourced by querying the calendar endpoint for the
# tournament start date and matching the competition name.
FIFA_API_BASE = os.getenv("FIFA_API_BASE", "https://api.fifa.com/api/v3")
WC2026_COMPETITION_ID = os.getenv("WC2026_COMPETITION_ID", "17")
WC2026_SEASON_ID = os.getenv("WC2026_SEASON_ID", "285023")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT_S = 30

# FIFA MatchStatus values we treat as "completed full-time / official result".
# Empirically 0 has meant FT in past tournaments and currently still does.
COMPLETED_STATUSES = {0}


# Aliases for the small number of teams FIFA spells differently from our
# canonical seed (the seed is the source of truth used by the frontend).
_FIFA_TO_CANONICAL: Dict[str, str] = {
    # Accented vs ASCII
    "Curaçao": "Curacao",
}

_CANONICAL_TEAMS = {team for teams in STATIC_GROUPS.values() for team in teams}


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def _localize(field: Any) -> Optional[str]:
    """Pull the English description out of FIFA's localized-string field."""
    if isinstance(field, list) and field:
        head = field[0]
        if isinstance(head, dict):
            return head.get("Description")
    if isinstance(field, str):
        return field
    return None


def _to_canonical_team(fifa_name: Optional[str]) -> Optional[str]:
    """
    Map a FIFA team name onto the canonical seed name. Returns None if the
    team isn't a recognized WC2026 participant (defensive — protects against
    typo regressions on FIFA's side).
    """
    if not fifa_name:
        return None
    name = fifa_name.strip()
    if not name:
        return None
    if name in _FIFA_TO_CANONICAL:
        return _FIFA_TO_CANONICAL[name]
    if name in _CANONICAL_TEAMS:
        return name
    # Accent-insensitive fallback in case FIFA introduces new diacritics.
    stripped = _strip_accents(name).lower()
    for canonical in _CANONICAL_TEAMS:
        if _strip_accents(canonical).lower() == stripped:
            return canonical
    return None


def _fetch_wc_matches() -> List[Dict[str, Any]]:
    """
    Fetch all WC2026 matches from FIFA's calendar API.

    Raises:
        requests.RequestException on transport errors / non-2xx responses.
    """
    url = (
        f"{FIFA_API_BASE}/calendar/matches"
        f"?language=en&count=500"
        f"&idCompetition={WC2026_COMPETITION_ID}"
        f"&idSeason={WC2026_SEASON_ID}"
    )
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    data = response.json()
    results = data.get("Results") if isinstance(data, dict) else None
    return results or []


def _compute_standings(matches: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Reduce a list of FIFA match dicts to per-group standings rows.

    Only matches with ``MatchStatus`` in :data:`COMPLETED_STATUSES` contribute
    to the stats. Groups that have no completed matches yet are still emitted
    with the seeded teams at zero so the upsert keeps draw rows fresh.
    """
    # Initialize every seeded team at zero so the table is always complete.
    table: Dict[str, Dict[str, Dict[str, int]]] = {
        group: {
            team: {
                "played": 0, "won": 0, "drawn": 0, "lost": 0,
                "goals_for": 0, "goals_against": 0, "points": 0,
            }
            for team in teams
        }
        for group, teams in STATIC_GROUPS.items()
    }

    for match in matches:
        group_name = _localize(match.get("GroupName"))
        if not group_name or not group_name.startswith("Group "):
            continue
        if group_name not in table:
            continue
        if match.get("MatchStatus") not in COMPLETED_STATUSES:
            continue

        home_raw = _localize((match.get("Home") or {}).get("TeamName"))
        away_raw = _localize((match.get("Away") or {}).get("TeamName"))
        home = _to_canonical_team(home_raw)
        away = _to_canonical_team(away_raw)
        if not home or not away:
            logger.warning(
                f"[fifa] Skipping match with unrecognized teams: "
                f"home={home_raw!r} away={away_raw!r} group={group_name!r}"
            )
            continue
        if home not in table[group_name] or away not in table[group_name]:
            continue

        try:
            home_score = int(match.get("HomeTeamScore"))
            away_score = int(match.get("AwayTeamScore"))
        except (TypeError, ValueError):
            continue

        th = table[group_name][home]
        ta = table[group_name][away]
        th["played"] += 1
        ta["played"] += 1
        th["goals_for"] += home_score
        th["goals_against"] += away_score
        ta["goals_for"] += away_score
        ta["goals_against"] += home_score
        if home_score > away_score:
            th["won"] += 1
            ta["lost"] += 1
            th["points"] += 3
        elif home_score < away_score:
            ta["won"] += 1
            th["lost"] += 1
            ta["points"] += 3
        else:
            th["drawn"] += 1
            ta["drawn"] += 1
            th["points"] += 1
            ta["points"] += 1

    output: Dict[str, List[Dict[str, Any]]] = {}
    for group_name, teams in table.items():
        rows: List[Dict[str, Any]] = []
        for team, stats in teams.items():
            row: Dict[str, Any] = {"team": team}
            row.update(stats)
            rows.append(row)
        output[group_name] = rows
    return output


def _upsert_group_standings(groups: Dict[str, List[Dict[str, Any]]]) -> int:
    """
    Upsert parsed group standings into PostgreSQL.

    Ranks rows within each group by points, then goal difference, then goals
    for. Returns the number of rows upserted.
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
            ranked = sorted(
                rows,
                key=lambda r: (
                    -int(r.get("points", 0)),
                    -(int(r.get("goals_for", 0)) - int(r.get("goals_against", 0))),
                    -int(r.get("goals_for", 0)),
                ),
            )
            any_played = any(r.get("played", 0) for r in ranked)
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
                        # Only populate rank once at least one match in the
                        # group has been played, so untouched groups keep
                        # NULL rank and the frontend can still order
                        # alphabetically or via the seeded draw.
                        "rank": idx if any_played else None,
                    },
                )
                affected += 1
    return affected


def scrape_groups() -> int:
    """
    Fetch WC2026 matches from FIFA, compute group standings, and upsert them.

    Returns the number of rows upserted; logs and swallows errors so a
    transient FIFA outage cannot crash the scheduler. Returns 0 on failure.
    """
    try:
        matches = _fetch_wc_matches()
    except Exception as exc:
        logger.warning(f"[fifa] Failed to fetch WC2026 matches: {exc}")
        return 0

    if not matches:
        logger.info("[fifa] No matches returned from FIFA API.")
        return 0

    try:
        standings = _compute_standings(matches)
    except Exception as exc:
        logger.error(f"[fifa] Failed to compute standings: {exc}", exc_info=True)
        return 0

    try:
        affected = _upsert_group_standings(standings)
    except Exception as exc:
        logger.error(f"[fifa] Failed to upsert standings: {exc}", exc_info=True)
        return 0

    played_total = sum(
        row.get("played", 0)
        for rows in standings.values()
        for row in rows
    )
    logger.info(
        f"[fifa] ✓ Upserted {affected} group_standings rows "
        f"({played_total // 2} matches counted)"
    )
    print(
        f"[fifa] ✓ Upserted {affected} group_standings rows "
        f"({played_total // 2} matches counted)"
    )
    return affected


# ---------------------------------------------------------------------------
# WC2026 FIXTURES
# ---------------------------------------------------------------------------

# Mapping from FIFA MatchStatus to our wc_fixtures.status CHECK values.
# Empirically: 0=full-time, 1=scheduled, 3=live. Anything else gets mapped to
# 'scheduled' so we never crash on a new FIFA status code, but it does mean
# postponements/cancellations would need explicit mapping if they ever appear.
_FIFA_MATCH_STATUS_TO_STATUS: Dict[int, str] = {
    0: "completed",
    1: "scheduled",
    3: "live",
}

# Stage mapping. Only "First Stage" (group) is ingested for now; knockout
# rounds reference placeholder slots ("Winner Group A", "2A", etc.) until the
# group stage finishes, and the schema CHECK constraint doesn't include
# 'round_of_16'. They can be added in a follow-up once the bracket is set.
_GROUP_STAGE_NAME = "First Stage"


def _parse_local_date_and_time(value: Optional[str]) -> tuple[Optional[_date], Optional[str]]:
    """
    Parse FIFA's ISO-8601 'LocalDate' field into a (date, "HH:MM") tuple.

    FIFA encodes the local date/time as ``2026-06-11T13:00:00Z`` even though
    it is *not* UTC (it's stadium-local). We treat the trailing 'Z' as a
    formatting artefact and just keep the wall-clock components.
    """
    if not value:
        return None, None
    s = value.rstrip("Z")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None, None
    return dt.date(), dt.strftime("%H:%M")


def _stadium_name(match: Dict[str, Any]) -> Optional[str]:
    stadium = match.get("Stadium")
    if not isinstance(stadium, dict):
        return None
    return _localize(stadium.get("Name"))


def scrape_wc_fixtures() -> int:
    """
    Fetch WC2026 matches from FIFA and upsert group-stage fixtures into
    ``wc_fixtures``.

    Only the 72 group-stage matches are ingested — knockout rounds rely on
    placeholder team slots that don't fit ``UNIQUE (match_date, home_team,
    away_team)``. Returns the number of rows inserted/updated. Errors are
    logged and swallowed; returns 0 on failure.
    """
    try:
        matches = _fetch_wc_matches()
    except Exception as exc:
        logger.warning(f"[fifa] Failed to fetch WC2026 matches for fixtures: {exc}")
        return 0

    if not matches:
        logger.info("[fifa] No matches returned from FIFA API for fixtures.")
        return 0

    engine = get_db_engine()
    upsert_sql = text(
        """
        INSERT INTO wc_fixtures (
            match_date, kickoff_time, group_name, stage,
            home_team, away_team, venue,
            home_goals, away_goals, status, updated_at
        ) VALUES (
            :match_date, :kickoff_time, :group_name, 'group',
            :home_team, :away_team, :venue,
            :home_goals, :away_goals, :status, NOW()
        )
        ON CONFLICT (match_date, home_team, away_team) DO UPDATE SET
            kickoff_time = EXCLUDED.kickoff_time,
            group_name = EXCLUDED.group_name,
            venue = EXCLUDED.venue,
            home_goals = EXCLUDED.home_goals,
            away_goals = EXCLUDED.away_goals,
            status = EXCLUDED.status,
            updated_at = NOW()
        """
    )

    affected = 0
    skipped = 0
    with engine.begin() as conn:
        for m in matches:
            stage_name = _localize(m.get("StageName"))
            if stage_name != _GROUP_STAGE_NAME:
                continue

            group_name = _localize(m.get("GroupName"))
            if not group_name or not group_name.startswith("Group "):
                skipped += 1
                continue

            home_raw = _localize((m.get("Home") or {}).get("TeamName"))
            away_raw = _localize((m.get("Away") or {}).get("TeamName"))
            home = _to_canonical_team(home_raw)
            away = _to_canonical_team(away_raw)
            if not home or not away:
                logger.warning(
                    f"[fifa] Skipping fixture with unrecognized teams: "
                    f"home={home_raw!r} away={away_raw!r} group={group_name!r}"
                )
                skipped += 1
                continue

            match_date, kickoff = _parse_local_date_and_time(m.get("LocalDate"))
            if match_date is None:
                match_date, kickoff = _parse_local_date_and_time(m.get("Date"))
            if match_date is None:
                skipped += 1
                continue

            fifa_status = m.get("MatchStatus")
            status = _FIFA_MATCH_STATUS_TO_STATUS.get(fifa_status, "scheduled")

            home_goals = m.get("HomeTeamScore") if status in ("completed", "live") else None
            away_goals = m.get("AwayTeamScore") if status in ("completed", "live") else None
            try:
                home_goals = int(home_goals) if home_goals is not None else None
                away_goals = int(away_goals) if away_goals is not None else None
            except (TypeError, ValueError):
                home_goals = None
                away_goals = None

            try:
                conn.execute(
                    upsert_sql,
                    {
                        "match_date": match_date,
                        "kickoff_time": kickoff,
                        "group_name": group_name,
                        "home_team": home,
                        "away_team": away,
                        "venue": _stadium_name(m),
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "status": status,
                    },
                )
                affected += 1
            except Exception as exc:
                logger.warning(
                    f"[fifa] Failed to upsert fixture "
                    f"({match_date} {home} vs {away}): {exc}"
                )
                skipped += 1

    logger.info(
        f"[fifa] ✓ Upserted {affected} wc_fixtures rows (skipped {skipped})"
    )
    print(
        f"[fifa] ✓ Upserted {affected} wc_fixtures rows (skipped {skipped})"
    )
    return affected


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    scrape_groups()
    scrape_wc_fixtures()
