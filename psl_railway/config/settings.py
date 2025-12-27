"""
Application configuration settings.

Loads and validates environment variables for database and application configuration.
"""
import os
from typing import List

# Import production-specific functions
try:
    from config.production import (
        is_production,
        validate_production_secrets,
        get_allowed_origins,
    )
except ImportError:
    # Fallback if production module doesn't exist
    def is_production() -> bool:
        return os.getenv("ENVIRONMENT", "").lower() == "production"
    
    def validate_production_secrets() -> None:
        pass
    
    def get_allowed_origins() -> List[str]:
        return []


# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "psl_db")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Required environment variables
REQUIRED_ENV_VARS = ["DB_USER", "DB_PASSWORD"]


def validate_environment() -> None:
    """
    Validate that all required environment variables are set.
    
    In production, also validates that secrets are properly configured.
    
    Raises:
        RuntimeError: If required environment variables are missing.
    """
    # Check if using DATABASE_URL (Railway provides this)
    if DATABASE_URL:
        # DATABASE_URL takes precedence, skip individual var checks
        pass
    else:
        # Check individual database variables
        missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Please set DATABASE_URL or configure individual database variables."
            )
    
    # Validate production secrets if in production mode
    if is_production():
        validate_production_secrets()


# Validate on import (but allow override in tests)
if os.getenv("SKIP_ENV_VALIDATION", "").lower() != "true":
    try:
        validate_environment()
    except RuntimeError:
        # In development, we might not have all vars set yet
        # This is acceptable as long as we're not in production
        if is_production():
            raise

