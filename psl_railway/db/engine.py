"""
Database engine module for PostgreSQL connection management.

Creates a single, standard way for the app to connect to PostgreSQL.
The API, scraper, scheduler, and ML logic use this function so that:
- Credentials are consistent
- Connections are reliable
- Database logic is not repeated throughout the code
"""
import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine


def get_db_engine():
    """
    Create and return a SQLAlchemy engine for PostgreSQL.

    Reads database credentials from environment variables:
    - DATABASE_URL: Full connection URL (takes precedence)
    - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD: Individual settings

    Returns:
        SQLAlchemy engine with connection pooling enabled.

    Raises:
        RuntimeError: If DB_PASSWORD is not set when using individual vars.
    """
    if os.getenv("DATABASE_URL"):
        return create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)

    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD environment variable is not set")

    password = quote_plus(password)

    return create_engine(
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{password}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/"
        f"{os.getenv('DB_NAME')}",
        pool_pre_ping=True,
    )
