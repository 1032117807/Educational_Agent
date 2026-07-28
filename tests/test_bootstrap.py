from __future__ import annotations

from pathlib import Path

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
