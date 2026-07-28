from __future__ import annotations

import logging
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config

from app.core.config import AppSettings, settings
from app.core.logging import configure_logging
from app.database import Database
from app.services.learning import LearningService


def bootstrap(config: AppSettings = settings) -> tuple[LearningService, AppSettings]:
    database_existed = (config.data_dir / "learning.db").exists()
    config.ensure_directories()
    configure_logging(config)
    database = Database(config.database_url)
    migration_candidates = [
        Path(sys.executable).resolve().parent / "alembic.ini",
        Path(__file__).resolve().parents[1] / "alembic.ini",
    ]
    migration_config = next((path for path in migration_candidates if path.exists()), None)
    if not database_existed and migration_config is not None:
        try:
            alembic = Config(str(migration_config))
            alembic.attributes["database_url"] = config.database_url
            command.upgrade(alembic, "head")
        except Exception:
            logging.getLogger(__name__).exception("Alembic migration failed; using safe schema fallback")
            database.create_schema()
    else:
        database.create_schema()
    service = LearningService(database)
    return service, config
