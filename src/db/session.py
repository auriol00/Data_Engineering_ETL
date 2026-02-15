"""Database session management.

The engine and session factory are created lazily on first use,
so importing this module never triggers a database connection.
"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _build_db_url() -> str:
    """Build the PostgreSQL connection URL from environment variables."""
    direct = os.getenv("DATABASE_URL")
    if direct:
        return direct

    host = os.getenv("DB_HOST", "postgres_heycar")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "heycar")
    user = os.getenv("DB_USER", "heycar")
    pwd = os.getenv("DB_PASSWORD", "heycar")
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}"


@lru_cache(maxsize=1)
def get_engine():
    """Return a singleton engine (created on first call, not at import time)."""
    return create_engine(_build_db_url(), pool_pre_ping=True, future=True)


def get_session():
    """Return a new database session bound to the singleton engine."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return factory()
