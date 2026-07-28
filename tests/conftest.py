from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import AppSettings
from app.database import Database
from app.services.learning import LearningService


@pytest.fixture
def tmp_path(pytestconfig: pytest.Config) -> Path:
    """Return a unique writable directory without deleting an older test run.

    Some Windows environments allow directory creation but deny recursive
    deletion.  Pytest's built-in tmp_path fixture cleans a shared base
    directory at startup, which makes the whole suite fail in that situation.
    """
    path = Path(pytestconfig.rootpath) / ".test-artifacts" / uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture
def service(tmp_path):
    config = AppSettings(data_dir=tmp_path)
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    return LearningService(database)
