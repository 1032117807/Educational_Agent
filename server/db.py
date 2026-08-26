from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from server.config import ServerSettings
from server.tenant_session import attach_tenant_transaction_hook


def create_server_engine(settings: ServerSettings):
    return create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)


def session_factory(settings: ServerSettings):
    factory = sessionmaker(bind=create_server_engine(settings), expire_on_commit=False, autoflush=False)
    attach_tenant_transaction_hook(factory)
    return factory


def check_database(settings: ServerSettings) -> bool:
    engine = create_server_engine(settings)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    finally:
        engine.dispose()


def ensure_development_schema(settings: ServerSettings) -> None:
    """Make the local SQLite preview self-contained without touching prod."""
    if settings.app_env.lower() in {"production", "prod"} or not settings.database_url.startswith("sqlite"):
        return
    engine = create_server_engine(settings)
    try:
        Base.metadata.create_all(engine)
        inspector = inspect(engine)
        with engine.begin() as connection:
            # The desktop SQLite file predates the SaaS migrations. Add any
            # model columns missing from it so read-only Web pages remain
            # usable during local development. Production uses Alembic.
            for table in Base.metadata.sorted_tables:
                if not inspector.has_table(table.name):
                    continue
                existing = {column["name"] for column in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing:
                        continue
                    sql_type = column.type.compile(dialect=engine.dialect)
                    connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {sql_type}'))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_runs_user_id ON ai_runs (user_id)"))
    finally:
        engine.dispose()
