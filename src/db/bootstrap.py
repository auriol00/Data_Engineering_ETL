"""One-time database bootstrap: create extensions and tables."""
from __future__ import annotations

from sqlalchemy import text
from src.db.session import get_engine
from src.db.models import Base


def create_all() -> None:
    """Ensure pgcrypto extension exists, then create all ORM tables."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
    Base.metadata.create_all(bind=engine)
