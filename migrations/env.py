from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base
from app.core.config import settings
import app.models  # noqa: F401

config = context.config
database_url = config.attributes.get("database_url")
if database_url is None:
    # SaaS deployments must set DATABASE_URL explicitly. Fall back to the
    # desktop SQLite database only when no SaaS URL is provided.
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        settings.ensure_directories()
        database_url = settings.database_url
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
