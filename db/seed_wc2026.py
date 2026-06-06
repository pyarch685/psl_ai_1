"""
Seed FIFA World Cup 2026 group draw into the database.

Inserts the 12 groups × 4 teams using FIFA-canonical names. Uses INSERT ...
ON CONFLICT DO NOTHING so this is safe to run multiple times. Existing rows
(which may already contain live standings stats) are NOT overwritten.

Team-name source of truth — matches src/wc2026/pages/Groups.tsx STATIC_GROUPS.

Usage:
    python -m db.seed_wc2026
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR))

from db.engine import get_db_engine

logger = logging.getLogger(__name__)


GROUPS: Dict[str, List[str]] = {
    "Group A": ["Mexico", "Korea Republic", "Czechia", "South Africa"],
    "Group B": ["Canada", "Switzerland", "Bosnia and Herzegovina", "Qatar"],
    "Group C": ["Brazil", "Morocco", "Scotland", "Haiti"],
    "Group D": ["USA", "Türkiye", "Paraguay", "Australia"],
    "Group E": ["Germany", "Ecuador", "Côte d'Ivoire", "Curacao"],
    "Group F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "Group G": ["Belgium", "Egypt", "IR Iran", "New Zealand"],
    "Group H": ["Spain", "Uruguay", "Saudi Arabia", "Cabo Verde"],
    "Group I": ["France", "Senegal", "Norway", "Iraq"],
    "Group J": ["Argentina", "Austria", "Algeria", "Jordan"],
    "Group K": ["Portugal", "Colombia", "Congo DR", "Uzbekistan"],
    "Group L": ["England", "Croatia", "Ghana", "Panama"],
}


def seed_groups() -> int:
    """
    Insert group_standings rows for the WC2026 draw.

    Returns:
        Number of rows successfully inserted (excludes rows that already
        existed and were skipped via ON CONFLICT DO NOTHING).
    """
    engine = get_db_engine()
    insert_sql = text(
        """
        INSERT INTO group_standings (group_name, team)
        VALUES (:group_name, :team)
        ON CONFLICT (group_name, team) DO NOTHING
        """
    )

    inserted = 0
    with engine.begin() as conn:
        for group_name, teams in GROUPS.items():
            for team in teams:
                result = conn.execute(
                    insert_sql,
                    {"group_name": group_name, "team": team},
                )
                if result.rowcount:
                    inserted += 1

    return inserted


def main() -> int:
    logger.info("[seed] Seeding WC2026 group draw")
    try:
        inserted = seed_groups()
    except Exception as exc:
        logger.error(f"[seed] Seed failed: {exc}", exc_info=True)
        print(f"[seed] FAILED: {exc}")
        return 1

    total = sum(len(t) for t in GROUPS.values())
    print(
        f"[seed] ✓ WC2026 groups seeded — {inserted} new rows inserted "
        f"(existing rows preserved; {total} teams in the draw)."
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    sys.exit(main())
