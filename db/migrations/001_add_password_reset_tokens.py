"""
Database migration: Add password_reset_tokens table.

This migration adds the password_reset_tokens table for password recovery functionality.
Can be run safely on existing databases (uses CREATE TABLE IF NOT EXISTS).

Usage:
    python -m db.migrations.001_add_password_reset_tokens
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

# Setup path and load environment
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR))

from db.engine import get_db_engine

logger = logging.getLogger(__name__)


def run_migration():
    """
    Run the migration to add password_reset_tokens table.
    """
    logger.info("[migration] Starting migration: Add password_reset_tokens table")
    
    engine = get_db_engine()
    
    migration_sql = text(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            
            -- Ensure token is not empty
            CHECK (LENGTH(token) > 0)
        );
        
        -- Create indexes for performance
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token ON password_reset_tokens(token);
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires ON password_reset_tokens(expires_at);
        """
    )
    
    try:
        with engine.begin() as conn:
            conn.execute(migration_sql)
        logger.info("[migration] ✓ password_reset_tokens table created/verified")
        logger.info("[migration] ✓ Indexes created/verified")
        logger.info("[migration] Migration completed successfully")
        print("[migration] Migration completed successfully!")
        return True
    except Exception as e:
        logger.error(f"[migration] Migration failed: {e}", exc_info=True)
        print(f"[migration] Migration failed: {e}")
        return False


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    success = run_migration()
    sys.exit(0 if success else 1)
