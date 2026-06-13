"""
Database migration: Add WC2026 model-prediction storage.

Creates ``wc_predictions``: an insert-only audit trail of the
Davidson-Bradley-Terry model's prediction for each WC2026 fixture, plus
the actual result once the match is played.

Schema highlights:

- ``UNIQUE(fixture_id)`` enforces the insert-only contract at the DB
  layer. Once a row exists for a fixture it is never overwritten by the
  snapshot job, preserving honest pre-kickoff probabilities.

- ``snapshot_kind`` distinguishes:
    * ``'pre_match'``   - inserted before the fixture's kickoff time.
    * ``'retroactive'`` - inserted after kickoff using the un-retrained
      pre-tournament artifact. The WC2026 model is trained offline only
      (no scheduled retrain), so a retroactive prediction is identical
      to one made before the match. Surfacing the kind lets the UI
      isolate the honest pre-match subset.

Idempotent - safe to run multiple times.

Usage:
    python -m db.migrations.005_add_wc_predictions
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
CREATE TABLE IF NOT EXISTS wc_predictions (
    id SERIAL PRIMARY KEY,
    fixture_id INTEGER NOT NULL UNIQUE
        REFERENCES wc_fixtures(id) ON DELETE CASCADE,
    predicted_outcome TEXT NOT NULL
        CHECK (predicted_outcome IN ('Home','Draw','Away')),
    prob_home REAL NOT NULL,
    prob_draw REAL NOT NULL,
    prob_away REAL NOT NULL,
    confidence REAL NOT NULL,
    model_version TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL
        CHECK (snapshot_kind IN ('pre_match','retroactive')),
    predicted_at TIMESTAMP NOT NULL DEFAULT NOW(),

    actual_outcome TEXT
        CHECK (actual_outcome IN ('Home','Draw','Away')),
    actual_home_goals INTEGER,
    actual_away_goals INTEGER,
    is_correct BOOLEAN,
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wc_predictions_resolved
    ON wc_predictions(resolved_at) WHERE resolved_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wc_predictions_kind
    ON wc_predictions(snapshot_kind);
"""


def run_migration() -> bool:
    logger.info("[migration] Starting migration 005: Add wc_predictions")
    engine = get_db_engine()
    try:
        with engine.begin() as conn:
            conn.execute(text(MIGRATION_SQL))
        logger.info("[migration] ✓ wc_predictions created/verified")
        print("[migration] ✓ wc_predictions created/verified")
        return True
    except Exception as exc:
        logger.error(
            f"[migration] Failed to create wc_predictions: {exc}",
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
