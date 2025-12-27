"""
PSL match data scraper and database updater.

This module is responsible for:
- Fetching PSL match results / fixtures from web
- Normalizing data
- Writing safely to PostgreSQL
- Being callable by a scheduler without crashing the app

This file MUST NOT import FastAPI or ML code.
"""
import logging
import re
from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from bs4 import BeautifulSoup
from sqlalchemy import text

from db.engine import get_db_engine

# Configure logging
logger = logging.getLogger(__name__)

# Timezone for South Africa
TZ = ZoneInfo("Africa/Johannesburg")

# -------------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------------

MATCHES_TABLE = "matches"
FIXTURES_TABLE = "fixtures"

MATCH_CENTRE_URL = "https://www.psl.co.za/MatchCentre"
RESULTS_URL = "https://www.psl.co.za/MatchCentre"
FIXTURES_URL = "https://www.psl.co.za/MatchCentre"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PSLBot/1.0)"
}


def _clean(s: str) -> str:
    """
    Clean and normalize string by removing extra whitespace.

    Args:
        s: String to clean.

    Returns:
        Cleaned string with normalized whitespace.
    """
    return re.sub(r"\s+", " ", s).strip()


# -------------------------------------------------------------------
# DATA FETCHING
# -------------------------------------------------------------------


def fetch_latest_matches() -> List[Dict]:
    """
    Scrape completed match results from PSL Match Centre using token-based parsing.

    Returns:
        List of dictionaries containing match data with keys:
        date, home_team, away_team, home_goals, away_goals, venue.

    Raises:
        requests.RequestException: If HTTP request fails.
    """
    try:
        response = requests.get(RESULTS_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch match results: {e}")
        raise

    try:
        soup = BeautifulSoup(response.text, "html.parser")

        # Flatten all visible strings (keeps order the site renders)
        tokens = [t.strip() for t in soup.stripped_strings if t.strip()]

        matches: List[Dict] = []
        section_date = None  # e.g. "17 Sep 2025"

        i = 0
        while i < len(tokens):
            t = tokens[i]

            # Section date header like "17 Sep 2025"
            if re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$", t):
                section_date = t
                i += 1
                continue

            # Pattern for completed matches: <Home> , "VS" , <Away> , <Score> , <Venue>
            # Look for pattern: Team VS Team followed by score (e.g., "2 - 1")
            if t != "VS" and i + 2 < len(tokens) and tokens[i+1] == "VS":
                home = _clean(t)
                away = _clean(tokens[i+2])

                # Look for score pattern after away team
                # Score could be: "2 - 1" or "2-1" or just "2" "1"
                j = i + 3
                score_found = False
                home_goals = None
                away_goals = None
                venue = None

                # Try to find score in next few tokens
                while j < len(tokens) and j < i + 10:
                    token = tokens[j]

                    # Check for score pattern like "2 - 1" or "2-1"
                    score_match = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", token)
                    if score_match:
                        home_goals = int(score_match.group(1))
                        away_goals = int(score_match.group(2))
                        score_found = True
                        j += 1
                        break

                    # Check if next two tokens are numbers (score)
                    if j + 1 < len(tokens):
                        try:
                            home_goals = int(token)
                            away_goals = int(tokens[j + 1])
                            score_found = True
                            j += 2
                            break
                        except ValueError:
                            pass

                    j += 1

                if not score_found:
                    i += 1
                    continue

                # Find venue after score (look for pattern with dash or comma)
                while j < len(tokens) and j < i + 15:
                    token = tokens[j]

                    # Venue might be after a dash or standalone
                    # Pattern: "14 Sep 19:30 - Venue" or just "Venue"
                    venue_match = re.match(
                        r"^(\d{1,2}\s+[A-Za-z]{3})(?:\s+(\d{2}:\d{2}))?\s*-\s*(.+)$",
                        token
                    )
                    if venue_match:
                        venue = _clean(venue_match.group(3))
                        break

                    # If token contains venue-like words (Stadium, Park, etc.)
                    if any(word in token for word in ["Stadium", "Park", "Arena", "Ground"]):
                        venue = _clean(token)
                        # Check if next token is part of venue (city name)
                        if j + 1 < len(tokens) and len(tokens[j + 1]) > 2:
                            next_token = tokens[j + 1]
                            if not re.match(r"^\d", next_token):  # Not a number
                                venue += ", " + _clean(next_token)
                        break

                    j += 1

                # Parse date
                dt_local = None
                if section_date:
                    try:
                        dt_local = datetime.strptime(
                            section_date + " 15:00",
                            "%d %b %Y %H:%M"
                        ).replace(tzinfo=TZ)
                    except ValueError:
                        logger.warning(f"Failed to parse date: {section_date}")

                if dt_local and home_goals is not None and away_goals is not None:
                    matches.append({
                        "date": dt_local.date(),
                        "home_team": home,
                        "away_team": away,
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "venue": venue or "",
                    })

                i = j + 1
                continue

            i += 1

        logger.info(f"Successfully scraped {len(matches)} match results")
        return matches

    except Exception as e:
        logger.error(f"Error parsing match results: {e}", exc_info=True)
        raise


def fetch_all_fixtures_with_results() -> List[Dict]:
    """
    Scrape all fixtures for current season with results from PSL Match Centre.

    Returns fixtures with scores for completed matches and None for upcoming matches.
    Uses token-based parsing to detect both completed and upcoming fixtures.

    Returns:
        List of dictionaries containing fixture data with keys:
        date, home_team, away_team, venue, status, home_goals, away_goals.
        - home_goals/away_goals are integers for completed matches
        - home_goals/away_goals are None for upcoming matches

    Raises:
        requests.RequestException: If HTTP request fails.
    """
    try:
        response = requests.get(MATCH_CENTRE_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch fixtures with results: {e}")
        raise

    try:
        soup = BeautifulSoup(response.text, "html.parser")

        # Flatten all visible strings (keeps order the site renders)
        tokens = [t.strip() for t in soup.stripped_strings if t.strip()]

        fixtures: List[Dict] = []
        section_date = None  # e.g. "17 Sep 2025"

        i = 0
        while i < len(tokens):
            t = tokens[i]

            # Section date header like "17 Sep 2025"
            if re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$", t):
                section_date = t
                i += 1
                continue

            # Pattern for COMPLETED matches: <Team1> <Score> <Team2>
            # e.g., "TS Galaxy 0 - 0 Kaizer Chiefs"
            if i + 2 < len(tokens):
                score_match = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", tokens[i + 1])
                if score_match:
                    # Check if tokens[i] and tokens[i+2] look like team names
                    # (not dates, not "VS", not numbers)
                    team1 = tokens[i]
                    team2 = tokens[i + 2]
                    if (not re.match(r"^\d", team1) and 
                        not re.match(r"^\d", team2) and
                        team1 != "VS" and team2 != "VS" and
                        len(team1) > 2 and len(team2) > 2):
                        
                        home_goals = int(score_match.group(1))
                        away_goals = int(score_match.group(2))
                        home = _clean(team1)
                        away = _clean(team2)
                        
                        # Look for venue after "Match Summary"
                        venue = None
                        dt_local = None
                        match_date = section_date
                        
                        # Look ahead for "Match Summary" and venue
                        k = i + 3
                        while k < len(tokens) and k < i + 10:
                            if tokens[k] == "Match Summary" and k + 1 < len(tokens):
                                # Next token should be date - venue
                                venue_match = re.match(
                                    r"^(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s*-\s*(.+)$",
                                    tokens[k + 1]
                                )
                                if venue_match:
                                    match_date = venue_match.group(1)
                                    venue = _clean(venue_match.group(2))
                                break
                            k += 1
                        
                        # Parse date
                        if match_date:
                            try:
                                dt_local = datetime.strptime(
                                    match_date + " 15:00",
                                    "%d %b %Y %H:%M"
                                ).replace(tzinfo=TZ)
                            except ValueError as e:
                                logger.warning(f"Failed to parse completed match date: {match_date}: {e}")
                        
                        if dt_local:
                            fixtures.append({
                                "date": dt_local.date(),
                                "home_team": home,
                                "away_team": away,
                                "venue": venue or "",
                                "status": "completed",
                                "home_goals": home_goals,
                                "away_goals": away_goals,
                            })
                            # Skip past this match
                            i = k + 1 if k < len(tokens) else i + 3
                            continue

            # Pattern: <Home> , "VS" , <Away> , <Score | Date/Venue | Postponed>
            if t != "VS" and i + 2 < len(tokens) and tokens[i+1] == "VS":
                home = _clean(t)
                away = _clean(tokens[i+2])

                # Look ahead to determine if this is a completed match or upcoming fixture
                j = i + 3
                score_found = False
                home_goals = None
                away_goals = None
                venue = None
                status = "on schedule"
                dt_local = None

                # Check next few tokens for score pattern (completed match)
                while j < len(tokens) and j < i + 15:
                    token = tokens[j]

                    # Check for score pattern like "2 - 1" or "2-1" (completed match)
                    score_match = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", token)
                    if score_match:
                        home_goals = int(score_match.group(1))
                        away_goals = int(score_match.group(2))
                        score_found = True
                        status = "completed"
                        j += 1
                        break

                    # Check if next two tokens are numbers (score)
                    if j + 1 < len(tokens):
                        try:
                            potential_home = int(token)
                            potential_away = int(tokens[j + 1])
                            # Verify these look like scores (reasonable range)
                            if 0 <= potential_home <= 20 and 0 <= potential_away <= 20:
                                home_goals = potential_home
                                away_goals = potential_away
                                score_found = True
                                status = "completed"
                                j += 2
                                break
                        except ValueError:
                            pass

                    # Check for "none - none" or "none-none" (explicit upcoming match)
                    if re.match(r"^none\s*[-–]\s*none$", token, re.IGNORECASE):
                        home_goals = None
                        away_goals = None
                        score_found = True  # Mark as processed
                        j += 1
                        break

                    # Check for date/venue pattern (upcoming fixture)
                    date_venue_match = re.match(
                        r"^(\d{1,2}\s+[A-Za-z]{3})(?:\s+(\d{2}:\d{2}))?\s*-\s*(.+)$",
                        token
                    )
                    if date_venue_match:
                        # This is an upcoming fixture
                        daymon, timepart, venue = (
                            date_venue_match.group(1),
                            date_venue_match.group(2) or "15:00",
                            _clean(date_venue_match.group(3))
                        )
                        year = (
                            section_date.split()[-1]
                            if section_date
                            else str(datetime.now(TZ).year)
                        )
                        try:
                            dt_local = datetime.strptime(
                                f"{daymon} {year} {timepart}",
                                "%d %b %Y %H:%M"
                            ).replace(tzinfo=TZ)
                        except ValueError as e:
                            logger.warning(
                                f"Failed to parse date: {daymon} {year} {timepart}: {e}"
                            )
                        j += 1
                        break

                    # Check for postponed/delayed status
                    if "Postponed" in token:
                        status = "postponed"
                        if section_date:
                            try:
                                dt_local = datetime.strptime(
                                    section_date + " 15:00",
                                    "%d %b %Y %H:%M"
                                ).replace(tzinfo=TZ)
                            except ValueError as e:
                                logger.warning(
                                    f"Failed to parse postponed date: {section_date}: {e}"
                                )
                        j += 1
                        break

                    if "Delayed" in token:
                        status = "delayed"
                        if section_date:
                            try:
                                dt_local = datetime.strptime(
                                    section_date + " 15:00",
                                    "%d %b %Y %H:%M"
                                ).replace(tzinfo=TZ)
                            except ValueError as e:
                                logger.warning(
                                    f"Failed to parse delayed date: {section_date}: {e}"
                                )
                        j += 1
                        break

                    j += 1

                # If we found a score, look for venue after the score
                if score_found and home_goals is not None:
                    # Look for venue in next few tokens
                    k = j
                    while k < len(tokens) and k < j + 5:
                        venue_token = tokens[k]
                        # Venue might be after score, look for common patterns
                        if any(word in venue_token for word in ["Stadium", "Park", "Arena", "Ground"]):
                            venue = _clean(venue_token)
                            # Check if next token is part of venue (city name)
                            if k + 1 < len(tokens) and len(tokens[k + 1]) > 2:
                                next_token = tokens[k + 1]
                                if not re.match(r"^\d", next_token):  # Not a number
                                    venue += ", " + _clean(next_token)
                            break
                        k += 1

                    # Parse date for completed match
                    if section_date:
                        try:
                            dt_local = datetime.strptime(
                                section_date + " 15:00",
                                "%d %b %Y %H:%M"
                            ).replace(tzinfo=TZ)
                        except ValueError as e:
                            logger.warning(f"Failed to parse date: {section_date}: {e}")

                # If no date parsed yet and we have section_date, use it
                if not dt_local and section_date:
                    try:
                        dt_local = datetime.strptime(
                            section_date + " 15:00",
                            "%d %b %Y %H:%M"
                        ).replace(tzinfo=TZ)
                    except ValueError as e:
                        logger.warning(f"Failed to parse date: {section_date}: {e}")

                # Add fixture if we have a valid date
                if dt_local:
                    fixtures.append({
                        "date": dt_local.date(),
                        "home_team": home,
                        "away_team": away,
                        "venue": venue or "",
                        "status": status,
                        "home_goals": home_goals,  # None for upcoming, int for completed
                        "away_goals": away_goals,  # None for upcoming, int for completed
                    })

                i = j + 1
                continue

            i += 1

        logger.info(
            f"Successfully scraped {len(fixtures)} fixtures "
            f"({sum(1 for f in fixtures if f.get('home_goals') is not None)} completed, "
            f"{sum(1 for f in fixtures if f.get('home_goals') is None)} upcoming)"
        )
        return fixtures

    except Exception as e:
        logger.error(f"Error parsing fixtures with results: {e}", exc_info=True)
        raise


def fetch_upcoming_fixtures() -> List[Dict]:
    """
    Scrape upcoming PSL fixtures using token-based parsing.

    Returns:
        List of dictionaries containing fixture data with keys:
        date, home_team, away_team, venue, status.

    Raises:
        requests.RequestException: If HTTP request fails.
    """
    try:
        response = requests.get(FIXTURES_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch fixtures: {e}")
        raise

    try:
        soup = BeautifulSoup(response.text, "html.parser")

        # Flatten all visible strings (keeps order the site renders)
        tokens = [t.strip() for t in soup.stripped_strings if t.strip()]

        fixtures: List[Dict] = []
        section_date = None  # e.g. "17 Sep 2025"

        i = 0
        while i < len(tokens):
            t = tokens[i]

            # Section date header like "17 Sep 2025"
            if re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$", t):
                section_date = t
                i += 1
                continue

            # Pattern: <Home> , "VS" , <Away> , <"14 Sep 19:30 - Venue" | "Postponed">
            if t != "VS" and i + 2 < len(tokens) and tokens[i+1] == "VS":
                home = _clean(t)
                away = _clean(tokens[i+2])

                # Find the next informative line after away
                j = i + 3
                while j < len(tokens) and not tokens[j]:
                    j += 1
                info = tokens[j] if j < len(tokens) else ""

                status = "on schedule"
                venue = None
                dt_local = None

                # Typical line: "14 Sep 19:30 - Moses Mabhida Stadium, Durban"
                m = re.match(
                    r"^(\d{1,2}\s+[A-Za-z]{3})(?:\s+(\d{2}:\d{2}))?\s*-\s*(.+)$",
                    info
                )
                if m:
                    daymon, timepart, venue = (
                        m.group(1),
                        m.group(2) or "15:00",
                        _clean(m.group(3))
                    )
                    year = (
                        section_date.split()[-1]
                        if section_date
                        else str(datetime.now(TZ).year)
                    )
                    try:
                        dt_local = datetime.strptime(
                            f"{daymon} {year} {timepart}",
                            "%d %b %Y %H:%M"
                        ).replace(tzinfo=TZ)
                    except ValueError as e:
                        logger.warning(f"Failed to parse date: {daymon} {year} {timepart}: {e}")
                elif "Postponed" in info:
                    status = "postponed"
                    # If postponed, keep section_date at a default time
                    if section_date:
                        try:
                            dt_local = datetime.strptime(
                                section_date + " 15:00",
                                "%d %b %Y %H:%M"
                            ).replace(tzinfo=TZ)
                        except ValueError as e:
                            logger.warning(f"Failed to parse postponed date: {section_date}: {e}")
                elif "Delayed" in info:
                    status = "delayed"
                    if section_date:
                        try:
                            dt_local = datetime.strptime(
                                section_date + " 15:00",
                                "%d %b %Y %H:%M"
                            ).replace(tzinfo=TZ)
                        except ValueError as e:
                            logger.warning(f"Failed to parse delayed date: {section_date}: {e}")

                if dt_local:
                    fixtures.append({
                        "date": dt_local.date(),  # Convert to date for database
                        "home_team": home,
                        "away_team": away,
                        "venue": venue or "",
                        "status": status,
                    })

                i = j + 1
                continue

            i += 1

        logger.info(f"Successfully scraped {len(fixtures)} fixtures")
        return fixtures

    except Exception as e:
        logger.error(f"Error parsing fixtures: {e}", exc_info=True)
        raise


# -------------------------------------------------------------------
# DATABASE HELPERS
# -------------------------------------------------------------------


def _normalize_matches(rows: List[Dict]) -> pd.DataFrame:
    """
    Normalize match data into DataFrame format.

    Args:
        rows: List of match dictionaries.

    Returns:
        DataFrame with normalized match data including venue.
    """
    if not rows:
        return pd.DataFrame(columns=["date", "home_team", "away_team", "home_goals", "away_goals", "venue"])

    df = pd.DataFrame(rows)

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)

    # Ensure venue column exists and is string type
    if "venue" not in df.columns:
        df["venue"] = ""
    df["venue"] = df["venue"].astype(str).fillna("")

    return df


def _normalize_fixtures(rows: List[Dict]) -> pd.DataFrame:
    """
    Normalize fixture data into DataFrame format.

    Args:
        rows: List of fixture dictionaries.

    Returns:
        DataFrame with normalized fixture data including venue, status,
        home_goals, and away_goals.
    """
    if not rows:
        return pd.DataFrame(
            columns=["date", "home_team", "away_team", "venue", "status", "home_goals", "away_goals"]
        )

    df = pd.DataFrame(rows)

    # Ensure date is date type (not datetime)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date

    # Ensure venue column exists and is string type
    if "venue" not in df.columns:
        df["venue"] = ""
    df["venue"] = df["venue"].astype(str).fillna("")

    # Ensure status column exists and normalize values
    if "status" not in df.columns:
        df["status"] = "on schedule"
    df["status"] = df["status"].astype(str).fillna("on schedule")

    # Normalize status values to standard format
    df["status"] = df["status"].str.lower().str.strip()
    df["status"] = df["status"].replace({
        "scheduled": "on schedule",
        "on-schedule": "on schedule",
        "onschedule": "on schedule",
        "completed": "completed",
    })

    # Handle goals columns (nullable integers)
    if "home_goals" not in df.columns:
        df["home_goals"] = None
    if "away_goals" not in df.columns:
        df["away_goals"] = None

    # Convert goals to nullable integer type
    # Use pd.NA for proper nullable integer support
    df["home_goals"] = df["home_goals"].apply(
        lambda x: int(x) if pd.notna(x) and x is not None and str(x).lower() != "nan" else pd.NA
    )
    df["away_goals"] = df["away_goals"].apply(
        lambda x: int(x) if pd.notna(x) and x is not None and str(x).lower() != "nan" else pd.NA
    )
    
    # Convert to nullable integer dtype (Int64)
    df["home_goals"] = df["home_goals"].astype("Int64")
    df["away_goals"] = df["away_goals"].astype("Int64")

    return df


# -------------------------------------------------------------------
# MAIN UPDATE FUNCTIONS (CALLED BY SCHEDULER)
# -------------------------------------------------------------------


def update_match_results() -> None:
    """
    Insert new match results into the database.

    Safe to run repeatedly:
    - Prevents duplicates
    - Uses transactions
    - Handles errors gracefully

    Prints status messages to stdout and logs to logger.
    """
    try:
        logger.info("[scraper] Starting match results update")
        engine = get_db_engine()
    except Exception as e:
        logger.error(f"[scraper] Failed to get database engine: {e}", exc_info=True)
        return

    try:
        matches = fetch_latest_matches()
    except requests.RequestException as e:
        logger.error(f"[scraper] Network error fetching match results: {e}")
        return
    except Exception as e:
        logger.error(f"[scraper] Error fetching match results: {e}", exc_info=True)
        return

    if not matches:
        logger.info("[scraper] No new match results found")
        return

    try:
        df = _normalize_matches(matches)
    except Exception as e:
        logger.error(f"[scraper] Error normalizing match data: {e}", exc_info=True)
        return

    try:
        inserted_count = 0
        skipped_count = 0

        with engine.begin() as conn:
            for _, row in df.iterrows():
                try:
                    exists = conn.execute(
                        text(
                            f"""
                            SELECT 1 FROM {MATCHES_TABLE}
                            WHERE date = :date
                              AND home_team = :home_team
                              AND away_team = :away_team
                            """
                        ),
                        {
                            "date": row["date"],
                            "home_team": row["home_team"],
                            "away_team": row["away_team"],
                        },
                    ).fetchone()

                    if exists:
                        skipped_count += 1
                        continue

                    conn.execute(
                        text(
                            f"""
                            INSERT INTO {MATCHES_TABLE}
                            (date, home_team, away_team, home_goals, away_goals, venue)
                            VALUES
                            (:date, :home_team, :away_team, :home_goals, :away_goals, :venue)
                            """
                        ),
                        row.to_dict(),
                    )
                    inserted_count += 1

                except Exception as e:
                    logger.warning(
                        f"[scraper] Failed to insert match "
                        f"({row.get('date')}, {row.get('home_team')} vs {row.get('away_team')}): {e}"
                    )
                    continue

        logger.info(
            f"[scraper] Match results updated "
            f"({inserted_count} inserted, {skipped_count} skipped, {len(df)} total)"
        )
        print(f"[scraper] Match results updated ({inserted_count} inserted, {skipped_count} skipped)")

    except Exception as e:
        logger.error(f"[scraper] Database error updating match results: {e}", exc_info=True)
        return


def update_fixtures() -> None:
    """
    Update fixtures table with all fixtures for current season, including results.

    Scrapes PSL Match Centre for all fixtures (completed and upcoming) and updates
    the fixtures table. Uses INSERT for new fixtures and UPDATE for existing fixtures
    when scores become available.

    Safe to run repeatedly:
    - Prevents duplicates
    - Updates existing fixtures with scores
    - Uses transactions
    - Handles errors gracefully

    Prints status messages to stdout and logs to logger.
    """
    try:
        logger.info("[scraper] Starting fixtures update with results")
        engine = get_db_engine()
    except Exception as e:
        logger.error(f"[scraper] Failed to get database engine: {e}", exc_info=True)
        return

    try:
        fixtures = fetch_all_fixtures_with_results()
    except requests.RequestException as e:
        logger.error(f"[scraper] Network error fetching fixtures: {e}")
        return
    except Exception as e:
        logger.error(f"[scraper] Error fetching fixtures: {e}", exc_info=True)
        return

    if not fixtures:
        logger.info("[scraper] No fixtures found")
        return

    try:
        df = _normalize_fixtures(fixtures)
    except Exception as e:
        logger.error(f"[scraper] Error normalizing fixture data: {e}", exc_info=True)
        return

    try:
        inserted_count = 0
        updated_count = 0
        skipped_count = 0

        # Process each row in its own transaction to prevent cascading failures
        for _, row in df.iterrows():
            try:
                with engine.begin() as conn:
                    # Check if fixture exists
                    existing = conn.execute(
                        text(
                            f"""
                            SELECT id, home_goals, away_goals FROM {FIXTURES_TABLE}
                            WHERE date = :date
                              AND home_team = :home_team
                              AND away_team = :away_team
                            """
                        ),
                        {
                            "date": row["date"],
                            "home_team": row["home_team"],
                            "away_team": row["away_team"],
                        },
                    ).fetchone()

                    if existing:
                        # Fixture exists - update if scores are available and different
                        existing_home_goals = existing[1]
                        existing_away_goals = existing[2]
                        new_home_goals = row.get("home_goals")
                        new_away_goals = row.get("away_goals")

                        # Update if we have new scores and they're different
                        if (
                            new_home_goals is not None
                            and new_away_goals is not None
                            and (
                                existing_home_goals != new_home_goals
                                or existing_away_goals != new_away_goals
                            )
                        ):
                            conn.execute(
                                text(
                                    f"""
                                    UPDATE {FIXTURES_TABLE}
                                    SET venue = :venue,
                                        status = :status,
                                        home_goals = :home_goals,
                                        away_goals = :away_goals,
                                        updated_at = NOW()
                                    WHERE date = :date
                                      AND home_team = :home_team
                                      AND away_team = :away_team
                                    """
                                ),
                                {
                                    "date": row["date"],
                                    "home_team": row["home_team"],
                                    "away_team": row["away_team"],
                                    "venue": row.get("venue", ""),
                                    "status": row.get("status", "on schedule"),
                                    "home_goals": (
                                        int(new_home_goals)
                                        if pd.notna(new_home_goals) and new_home_goals is not None
                                        else None
                                    ),
                                    "away_goals": (
                                        int(new_away_goals)
                                        if pd.notna(new_away_goals) and new_away_goals is not None
                                        else None
                                    ),
                                },
                            )
                            updated_count += 1
                        else:
                            # Update venue/status even if scores haven't changed
                            conn.execute(
                                text(
                                    f"""
                                    UPDATE {FIXTURES_TABLE}
                                    SET venue = :venue,
                                        status = :status,
                                        updated_at = NOW()
                                    WHERE date = :date
                                      AND home_team = :home_team
                                      AND away_team = :away_team
                                    """
                                ),
                                {
                                    "date": row["date"],
                                    "home_team": row["home_team"],
                                    "away_team": row["away_team"],
                                    "venue": row.get("venue", ""),
                                    "status": row.get("status", "on schedule"),
                                },
                            )
                            skipped_count += 1
                    else:
                        # New fixture - insert
                        conn.execute(
                            text(
                                f"""
                                INSERT INTO {FIXTURES_TABLE}
                                (date, home_team, away_team, venue, status, home_goals, away_goals)
                                VALUES
                                (:date, :home_team, :away_team, :venue, :status, :home_goals, :away_goals)
                                """
                            ),
                            {
                                "date": row["date"],
                                "home_team": row["home_team"],
                                "away_team": row["away_team"],
                                "venue": row.get("venue", ""),
                                "status": row.get("status", "on schedule"),
                                "home_goals": (
                                    int(row.get("home_goals"))
                                    if pd.notna(row.get("home_goals"))
                                    and row.get("home_goals") is not None
                                    else None
                                ),
                                "away_goals": (
                                    int(row.get("away_goals"))
                                    if pd.notna(row.get("away_goals"))
                                    and row.get("away_goals") is not None
                                    else None
                                ),
                            },
                        )
                        inserted_count += 1

            except Exception as e:
                logger.warning(
                    f"[scraper] Failed to process fixture "
                    f"({row.get('date')}, {row.get('home_team')} vs {row.get('away_team')}): {e}"
                )
                continue

        logger.info(
            f"[scraper] Fixtures updated "
            f"({inserted_count} inserted, {updated_count} updated, "
            f"{skipped_count} unchanged, {len(df)} total)"
        )
        print(
            f"[scraper] Fixtures updated "
            f"({inserted_count} inserted, {updated_count} updated, {skipped_count} unchanged)"
        )

    except Exception as e:
        logger.error(f"[scraper] Database error updating fixtures: {e}", exc_info=True)
        return


# -------------------------------------------------------------------
# MANUAL TEST ENTRYPOINT
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Configure logging for manual execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    print("[scraper] Running manual update...")
    update_match_results()
    update_fixtures()
    print("[scraper] Done.")
