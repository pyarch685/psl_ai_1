"""
Database migration: Add WC2026 per-user prediction storage.

Creates `wc_user_predictions` which records each logged-in user's saved
Home / Draw / Away pick for individual WC2026 fixtures. Predictions are
constrained to actual fixtures via a foreign key and limited to one per
(user, fixture) pair via a unique index. Editing is allowed up until the
match kicks off (enforced by the route handler, not the schema).

Idempotent — safe to run multiple times.

Usage:
    python -m db.migrations.004_add_wc_user_predictions
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

from db.engine import get_db_engine  # noqa: E402

logger = logging.getLogger(__name__)


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS wc_user_predictions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fixture_id INTEGER NOT NULL REFERENCES wc_fixtures(id) ON DELETE CASCADE,
    predicted_outcome TEXT NOT NULL
        CHECK (predicted_outcome IN ('Home','Draw','Away')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, fixture_id)
);

CREATE INDEX IF NOT EXISTS idx_wc_user_predictions_user
    ON wc_user_predictions(user_id);
CREATE INDEX IF NOT EXISTS idx_wc_user_predictions_fixture
    ON wc_user_predictions(fixture_id);
"""


def run_migration() -> bool:
    logger.info("[migration] Starting migration 004: Add wc_user_predictions")
    engine = get_db_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATION_SQL))
        logger.info("[migration] ✓ wc_user_predictions created/verified")
        print("[migration] ✓ wc_user_predictions created/verified")
        return True
    except Exception as exc:
        logger.error(
            f"[migration] Failed to create wc_user_predictions: {exc}",
            exc_info=True,
        )
        print(f"[migration] FAILED: {exc}")
        return False


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return 0 if run_migration() else 1


if __name__ == "__main__":
    sys.exit(main())
