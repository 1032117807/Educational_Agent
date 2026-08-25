from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.bootstrap import bootstrap
from app.core.config import AppSettings


def test_fresh_bootstrap_uses_alembic_head(tmp_path):
    config = AppSettings(data_dir=tmp_path / "new-user")
    service, _ = bootstrap(config)
    alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    expected_revision = ScriptDirectory.from_config(alembic_config).get_current_head()

    with service.database.engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert revision == expected_revision


def test_existing_versioned_database_is_upgraded_to_head(tmp_path):
    config = AppSettings(data_dir=tmp_path / "existing-user")
    config.ensure_directories()
    alembic_config = Config(
        str(Path(__file__).resolve().parents[1] / "alembic.ini")
    )
    alembic_config.attributes["database_url"] = config.database_url
    command.upgrade(alembic_config, "c3f9a821d104")

    service, _ = bootstrap(config)
    expected_revision = ScriptDirectory.from_config(
        alembic_config
    ).get_current_head()

    with service.database.engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(knowledge_points)"
            )
        }

    assert revision == expected_revision
    assert {"vector_id", "embedding_model"} <= columns


def test_existing_unversioned_database_uses_compatibility_path(tmp_path, monkeypatch):
    config = AppSettings(data_dir=tmp_path / "legacy-user")
    config.ensure_directories()
    database = __import__("app.database", fromlist=["Database"]).Database(config.database_url)
    database.create_schema()
    with database.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.exec_driver_sql("DELETE FROM alembic_version")
    database.close()

    def fail_if_migrations_run(*args, **kwargs):
        raise AssertionError("legacy unversioned databases must not replay all migrations")

    monkeypatch.setattr("app.bootstrap.command.upgrade", fail_if_migrations_run)
    service, _ = bootstrap(config)
    with service.database.engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(knowledge_points)")}
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    service.database.close()
    assert {"practice_count", "correct_count", "wrong_count", "last_studied_at", "next_review_at"} <= columns
    assert "learning_events" in tables
