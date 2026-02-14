"""
Unified database schema creation for PSL AI application.

Creates all three tables:
- matches: Historical match results
- fixtures: Upcoming matches
- predictions: ML model predictions

This script is idempotent and can be run multiple times safely.
"""
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# Add project root to Python path so db module can be imported
sys.path.insert(0, str(BASE_DIR))

from db.engine import get_db_engine

logger = logging.getLogger(__name__)


def create_matches_table() -> None:
    """
    Create the matches table for historical match results.

    Columns:
    - id: Primary key
    - date: Match date
    - home_team: Home team name
    - away_team: Away team name
    - home_goals: Home team goals scored
    - away_goals: Away team goals scored
    - venue: Match venue (nullable)
    - capacity: Stadium capacity/attendance (nullable)
    - referee: Match referee (nullable)
    - created_at: Record creation timestamp
    - updated_at: Record update timestamp
    """
    engine = get_db_engine()

    create_table_sql = text(
        """
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_goals INTEGER NOT NULL CHECK (home_goals >= 0),
            away_goals INTEGER NOT NULL CHECK (away_goals >= 0),
            venue TEXT,
            capacity INTEGER,
            referee TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            
            UNIQUE (date, home_team, away_team)
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
        CREATE INDEX IF NOT EXISTS idx_matches_teams 
            ON matches(home_team, away_team);
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(create_table_sql)
        logger.info("[db] matches table created/verified")
    except Exception as e:
        logger.error(f"[db] Failed to create matches table: {e}", exc_info=True)
        raise


def create_fixtures_table() -> None:
    """
    Create the fixtures table for upcoming matches.

    Columns:
    - id: Primary key
    - date: Fixture date
    - home_team: Home team name
    - away_team: Away team name
    - venue: Match venue (nullable)
    - home_goals: Home team goals (nullable, populated when match completed)
    - away_goals: Away team goals (nullable, populated when match completed)
    - status: Match status (on schedule, postponed, delayed, completed, scheduled)
    - created_at: Record creation timestamp
    - updated_at: Record update timestamp
    """
    engine = get_db_engine()

    create_table_sql = text(
        """
        CREATE TABLE IF NOT EXISTS fixtures (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            venue TEXT,
            home_goals INTEGER,
            away_goals INTEGER,
            status TEXT NOT NULL DEFAULT 'on schedule' 
                CHECK (status IN ('on schedule', 'postponed', 'delayed', 'completed', 'scheduled')),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            
            UNIQUE (date, home_team, away_team)
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(date);
        CREATE INDEX IF NOT EXISTS idx_fixtures_status ON fixtures(status);
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(create_table_sql)
            # Migration: add home_goals/away_goals to existing fixtures tables
            conn.execute(text(
                "ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS home_goals INTEGER"
            ))
            conn.execute(text(
                "ALTER TABLE fixtures ADD COLUMN IF NOT EXISTS away_goals INTEGER"
            ))
        logger.info("[db] fixtures table created/verified")
    except Exception as e:
        logger.error(f"[db] Failed to create fixtures table: {e}", exc_info=True)
        raise


def create_predictions_table() -> None:
    """
    Create the predictions table for ML model predictions.

    Columns:
    - id: Primary key
    - match_date: Match date
    - home_team: Home team name
    - away_team: Away team name
    - home_win_prob: Probability of home win
    - draw_prob: Probability of draw
    - away_win_prob: Probability of away win
    - predicted_outcome: Predicted outcome (Home, Draw, Away)
    - confidence: Highest probability value
    - model_version: Model version identifier
    - created_at: Prediction creation timestamp
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

    try:
        with engine.begin() as conn:
            conn.execute(create_table_sql)
        logger.info("[db] predictions table created/verified")
    except Exception as e:
        logger.error(
            f"[db] Failed to create predictions table: {e}",
            exc_info=True
        )
        raise


def create_user_feedback_table() -> None:
    """
    Create the user_feedback table for storing user predictions/feedback.

    Columns:
    - id: Primary key
    - fixture_id: Reference to fixture (optional, can be 0 if not available)
    - home_team: Home team name
    - away_team: Away team name
    - user_prediction: User's prediction (home_win, draw, away_win)
    - user_email: User email (optional)
    - created_at: Feedback creation timestamp
    """
    engine = get_db_engine()

    create_table_sql = text(
        """
        CREATE TABLE IF NOT EXISTS user_feedback (
            id SERIAL PRIMARY KEY,
            fixture_id INTEGER DEFAULT 0,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            user_prediction TEXT NOT NULL 
                CHECK (user_prediction IN ('home_win', 'draw', 'away_win')),
            user_email TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_user_feedback_fixture ON user_feedback(fixture_id);
        CREATE INDEX IF NOT EXISTS idx_user_feedback_teams ON user_feedback(home_team, away_team);
        CREATE INDEX IF NOT EXISTS idx_user_feedback_created ON user_feedback(created_at);
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(create_table_sql)
        logger.info("[db] user_feedback table created/verified")
    except Exception as e:
        logger.error(f"[db] Failed to create user_feedback table: {e}", exc_info=True)
        raise


def create_users_table() -> None:
    """
    Create the users table for authentication.

    Columns:
    - id: Primary key
    - email: User email address (used as username, must be unique and valid email)
    - password_hash: Hashed password using bcrypt (never store plain text)
    - created_at: Account creation timestamp
    - last_login: Last login timestamp (nullable)
    - is_active: Account active status (default: true)

    Password requirements (enforced in application):
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    """
    engine = get_db_engine()

    create_table_sql = text(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            
            -- Ensure email is a valid email format (basic check)
            CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$')
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
        CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(create_table_sql)
        logger.info("[db] users table created/verified")
    except Exception as e:
        logger.error(f"[db] Failed to create users table: {e}", exc_info=True)
        raise


def create_all_tables() -> None:
    """
    Create all database tables in the correct order.

    Order matters if there are foreign key relationships.
    Currently, tables are independent, so order doesn't matter.
    """
    logger.info("[db] Starting database schema creation...")
    
    try:
        create_matches_table()
        create_fixtures_table()
        create_predictions_table()
        create_user_feedback_table()
        create_users_table()
        
        logger.info("[db] All tables created successfully")
        print("[db] Database schema ready!")
        
    except Exception as e:
        logger.error(f"[db] Schema creation failed: {e}", exc_info=True)
        raise


# -------------------------------------------------------------------
# SCRIPT ENTRY POINT
# -------------------------------------------------------------------

if __name__ == "__main__":
    # Configure logging for manual execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    create_all_tables()

