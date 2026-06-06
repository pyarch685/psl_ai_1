"""
Database migration: Add outcome columns to predictions table.

Adds nullable columns to support ML evaluation by recording the actual
outcome of a match alongside the original pre-match probabilities.

Existing rows remain valid (all new columns default to NULL).
Can be run safely on existing databases (uses ADD COLUMN IF NOT EXISTS).

Usage:
    python -m db.migrations.002_add_prediction_outcomes
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


def run_migration() -> None:
    """
    Add actual_outcome, actual_home_goals, actual_away_goals, is_correct,
    and resolved_at columns to the predictions table.
    """
    logger.info("[migration] Starting migration: Add prediction outcome columns")

    engine = get_db_engine()

    migration_sql = text(
        """
        ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS actual_outcome TEXT
                CHECK (actual_outcome IN ('Home', 'Draw', 'Away'));
        ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS actual_home_goals INTEGER;
        ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS actual_away_goals INTEGER;
        ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS is_correct BOOLEAN;
        ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;

        CREATE INDEX IF NOT EXISTS idx_predictions_resolved_at
            ON predictions(resolved_at);
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(migration_sql)
        logger.info("[migration] ✓ predictions outcome columns added")
        print("[migration] ✓ predictions outcome columns added")
    except Exception as exc:
        logger.error(
            f"[migration] Failed to add prediction outcome columns: {exc}",
            exc_info=True,
        )
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    run_migration()
