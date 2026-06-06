"""
Database migration: Add WC2026 (FIFA World Cup 2026) tables.

Adds four additive, independent tables for the WC2026 surface:

- group_standings   : current standings per group, refreshed by FIFA scraper
- wc_fixtures       : tournament fixtures (group + knockout stages)
- unlocks           : per-user paid unlocks for predictions
- paystack_payments : Paystack init/verify ledger

Idempotent — safe to run multiple times.

Usage:
    python -m db.migrations.003_add_wc2026_tables
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR))

from db.engine import get_db_engine

logger = logging.getLogger(__name__)


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS group_standings (
    id SERIAL PRIMARY KEY,
    group_name TEXT NOT NULL,
    team TEXT NOT NULL,
    played INTEGER NOT NULL DEFAULT 0,
    won INTEGER NOT NULL DEFAULT 0,
    drawn INTEGER NOT NULL DEFAULT 0,
    lost INTEGER NOT NULL DEFAULT 0,
    goals_for INTEGER NOT NULL DEFAULT 0,
    goals_against INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    rank INTEGER,
    fifa_rank INTEGER,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (group_name, team)
);

CREATE INDEX IF NOT EXISTS idx_group_standings_group
    ON group_standings(group_name);
CREATE INDEX IF NOT EXISTS idx_group_standings_team
    ON group_standings(team);

CREATE TABLE IF NOT EXISTS wc_fixtures (
    id SERIAL PRIMARY KEY,
    match_date DATE NOT NULL,
    kickoff_time TEXT,
    group_name TEXT,
    stage TEXT NOT NULL DEFAULT 'group'
        CHECK (stage IN ('group','round_of_32','quarter','semi','third_place','final')),
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    venue TEXT,
    home_goals INTEGER,
    away_goals INTEGER,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled','live','completed','postponed','cancelled')),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (match_date, home_team, away_team)
);

CREATE INDEX IF NOT EXISTS idx_wc_fixtures_date
    ON wc_fixtures(match_date);
CREATE INDEX IF NOT EXISTS idx_wc_fixtures_group
    ON wc_fixtures(group_name);
CREATE INDEX IF NOT EXISTS idx_wc_fixtures_stage
    ON wc_fixtures(stage);

CREATE TABLE IF NOT EXISTS unlocks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    paystack_reference TEXT,
    amount_usd NUMERIC(8,2),
    paid_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_unlocks_user
    ON unlocks(user_id);
CREATE INDEX IF NOT EXISTS idx_unlocks_item
    ON unlocks(item_key);

CREATE TABLE IF NOT EXISTS paystack_payments (
    id SERIAL PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_usd NUMERIC(8,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','success','failed')),
    initialized_at TIMESTAMP DEFAULT NOW(),
    verified_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paystack_payments_user
    ON paystack_payments(user_id);
CREATE INDEX IF NOT EXISTS idx_paystack_payments_status
    ON paystack_payments(status);
"""


def run_migration() -> bool:
    logger.info("[migration] Starting migration 003: Add WC2026 tables")
    engine = get_db_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATION_SQL))
        logger.info("[migration] ✓ WC2026 tables created/verified")
        print("[migration] ✓ WC2026 tables created/verified")
        return True
    except Exception as exc:
        logger.error(
            f"[migration] Failed to create WC2026 tables: {exc}",
            exc_info=True,
        )
        print(f"[migration] FAILED: {exc}")
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    success = run_migration()
    sys.exit(0 if success else 1)
