# psl_fetcher.py
import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+; else use pytz
TZ = ZoneInfo("Africa/Johannesburg")

MATCH_CENTRE_URL = "https://www.psl.co.za/MatchCentre"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PSL-Fixture-Fetch/1.0)"}

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def fetch_psl_fixtures() -> pd.DataFrame:
    """
    Scrape fixtures shown on the PSL Match Centre.
    Returns columns: date, home_team, away_team, venue, status.
    """
    html = requests.get(MATCH_CENTRE_URL, headers=HEADERS, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    # Flatten all visible strings (keeps order the site renders)
    tokens = [t.strip() for t in soup.stripped_strings if t.strip()]

    fixtures = []
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

            status = "Scheduled"
            venue = None
            dt_local = None

            # Typical line: "14 Sep 19:30 - Moses Mabhida Stadium, Durban"
            m = re.match(r"^(\d{1,2}\s+[A-Za-z]{3})(?:\s+(\d{2}:\d{2}))?\s*-\s*(.+)$", info)
            if m:
                daymon, timepart, venue = m.group(1), m.group(2) or "15:00", _clean(m.group(3))
                year = section_date.split()[-1] if section_date else str(datetime.now(TZ).year)
                dt_local = datetime.strptime(f"{daymon} {year} {timepart}", "%d %b %Y %H:%M").replace(tzinfo=TZ)
            elif "Postponed" in info:
                status = "Postponed"
                # If postponed, keep section_date at a default time (optional)
                if section_date:
                    dt_local = datetime.strptime(section_date + " 15:00", "%d %b %Y %H:%M").replace(tzinfo=TZ)

            fixtures.append({
                "date": dt_local,              # timezone-aware (Africa/Johannesburg)
                "home_team": home,
                "away_team": away,
                "venue": venue,
                "status": status,
            })

            i = j + 1
            continue

        i += 1

    df = pd.DataFrame(fixtures)
    
    return df
