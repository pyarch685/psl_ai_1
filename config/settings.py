"""
Application configuration settings.

Loads and validates environment variables for database and app configuration.
"""
from __future__ import annotations

import os
from typing import List

from config.production import is_production, validate_production_secrets

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "psl_db")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Required environment variables (when DATABASE_URL is not supplied)
REQUIRED_ENV_VARS: List[str] = ["DB_USER", "DB_PASSWORD"]


def validate_environment() -> None:
    """
    Validate required runtime environment variables.

    In production this also validates required secrets.
    """
    if not DATABASE_URL:
        missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Set DATABASE_URL or configure individual DB variables."
            )

    if is_production():
        validate_production_secrets()


# Validate on import (but allow test override).
if os.getenv("SKIP_ENV_VALIDATION", "").lower() != "true":
    try:
        validate_environment()
    except RuntimeError:
        if is_production():
            raise
