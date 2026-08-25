"""Translate application PostgreSQL URLs for PostgreSQL command-line tools."""
from __future__ import annotations

import re


def postgres_client_url(database_url: str) -> str:
    """Return a libpq-compatible URL from an application DATABASE_URL.

    SQLAlchemy commonly stores URLs as ``postgresql+psycopg://...`` while the
    PostgreSQL CLI only understands ``postgresql://...``.  Passing the former
    to ``pg_dump`` silently loses its host information on some platforms, so
    conversion must happen before backup or restore commands are invoked.
    """
    if not database_url.startswith("postgresql"):
        raise ValueError("DATABASE_URL must point to PostgreSQL")
    return re.sub(r"^postgresql\+[a-zA-Z0-9_]+://", "postgresql://", database_url, count=1)
