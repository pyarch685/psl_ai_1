"""
Production-specific configuration settings.

This module contains settings and validations specific to production environments.
"""
import os
import secrets
from typing import List


def get_allowed_origins() -> List[str]:
    """
    Get allowed CORS origins from environment variable.

    Returns:
        List of allowed origins. Defaults to empty list if not set.
    """
    origins_str = os.getenv("CORS_ORIGINS", "")
    if not origins_str:
        return []
    
    # Split by comma and strip whitespace
    origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]
    return origins


def is_production() -> bool:
    """
    Check if running in production environment.

    Returns:
        True if ENVIRONMENT is set to 'production', False otherwise.
    """
    return os.getenv("ENVIRONMENT", "").lower() == "production"


def get_jwt_expiration_minutes() -> int:
    """
    Get JWT token expiration time in minutes based on environment.

    Returns:
        Token expiration in minutes. Shorter in production (24 hours) vs development (7 days).
    """
    if is_production():
        return 60 * 24  # 24 hours in production
    return 60 * 24 * 7  # 7 days in development


def validate_production_secrets() -> None:
    """
    Validate that all required production secrets are set.

    Raises:
        RuntimeError: If any required production secrets are missing.
    """
    required_secrets = [
        "JWT_SECRET_KEY",
        "DATABASE_URL",  # Or DB_USER/DB_PASSWORD combo
    ]
    
    missing = []
    
    # Check JWT_SECRET_KEY
    jwt_secret = os.getenv("JWT_SECRET_KEY")
    if not jwt_secret or jwt_secret == "your-secret-key-change-in-production":
        missing.append("JWT_SECRET_KEY")
    
    # Check database credentials (either DATABASE_URL or individual vars)
    if not os.getenv("DATABASE_URL"):
        if not os.getenv("DB_USER") or not os.getenv("DB_PASSWORD"):
            missing.append("DATABASE_URL or (DB_USER and DB_PASSWORD)")
    
    if missing and is_production():
        raise RuntimeError(
            f"Missing required production secrets: {', '.join(missing)}. "
            "Please set these environment variables before deploying to production."
        )


def generate_secret_key() -> str:
    """
    Generate a secure random secret key for JWT.

    Returns:
        A URL-safe base64-encoded random string suitable for use as a secret key.
    """
    return secrets.token_urlsafe(32)

