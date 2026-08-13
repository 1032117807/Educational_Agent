from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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
