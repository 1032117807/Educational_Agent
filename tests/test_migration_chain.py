from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_empty_sqlite_database_reaches_current_head(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "g10_tenant_not_null"
    names = set(inspect(engine).get_table_names())
    assert {"courses", "audit_events", "document_indexes"}.issubset(names)
