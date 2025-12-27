"""
Database schema creation for the predictions table.

This module can be:
- Imported and called from other apps
- Run as a standalone script
"""

from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

from db.engine import get_db_engine


def create_predictions_table() -> None:
    """
    Create the predictions table if it does not already exist.
    """
    engine = get_db_engine()

    create_table_sql = text(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id SERIAL PRIMARY KEY,
            match_date DATE NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,

            home_win_prob DOUBLE PRECISION NOT NULL 
                CHECK (home_win_prob >= 0 AND home_win_prob <= 1),
            draw_prob DOUBLE PRECISION NOT NULL 
                CHECK (draw_prob >= 0 AND draw_prob <= 1),
            away_win_prob DOUBLE PRECISION NOT NULL 
                CHECK (away_win_prob >= 0 AND away_win_prob <= 1),

            predicted_outcome TEXT 
                CHECK (predicted_outcome IN ('Home', 'Draw', 'Away')),
            confidence DOUBLE PRECISION 
                CHECK (confidence >= 0 AND confidence <= 1),

            model_version TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),

            UNIQUE (match_date, home_team, away_team),
            
            -- Ensure probabilities sum to approximately 1.0 (within tolerance)
            CHECK (
                ABS(home_win_prob + draw_prob + away_win_prob - 1.0) < 0.01
            )
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_predictions_date 
            ON predictions(match_date);
        CREATE INDEX IF NOT EXISTS idx_predictions_teams 
            ON predictions(home_team, away_team);
        """
    )

    with engine.begin() as conn:
        conn.execute(create_table_sql)

    print("[db] predictions table is ready")


# -------------------------------------------------------------------
# SCRIPT ENTRY POINT
# -------------------------------------------------------------------

if __name__ == "__main__":
    create_predictions_table()
