from __future__ import annotations

from app.core.config import AppSettings
from app.database import Database
from app.tools.registry import ToolRegistry


def test_tool_registry_schema_confirmation_and_audit(tmp_path):
    config = AppSettings(data_dir=tmp_path)
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    registry = ToolRegistry(database, config)
    names = {item.name for item in registry.list()}
    assert "filesystem.list_directory" in names
    assert "database.backup" in names
    denied = registry.execute("filesystem.create_directory", {"path": "notes"})
    assert denied["confirmation_required"]
    created = registry.execute("filesystem.create_directory", {"path": "notes"}, confirmed=True)
    assert created["success"]
    listing = registry.execute("filesystem.list_directory", {"path": "."})
    assert "notes" in listing["result"]
    registry.execute(
        "filesystem.create_text_file", {"path": "notes/a.txt", "content": "hello"}, confirmed=True
    )
    renamed = registry.execute(
        "filesystem.rename", {"path": "notes/a.txt", "new_name": "b.txt"}, confirmed=True
    )
    assert renamed["result"] == "notes\\b.txt" or renamed["result"] == "notes/b.txt"
    trashed = registry.execute("filesystem.move_to_trash", {"path": "notes/b.txt"}, confirmed=True)
    restored = registry.execute(
        "filesystem.restore_from_trash", {"path": trashed["result"]}, confirmed=True
    )
    assert restored["result"] == "b.txt"


def test_tool_registry_rejects_path_traversal(tmp_path):
    config = AppSettings(data_dir=tmp_path)
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    result = ToolRegistry(database, config).execute(
        "filesystem.read_text", {"path": "../secret.txt"}
    )
    assert not result["success"]
    assert "相对路径" in result["error"]
