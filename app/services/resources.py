from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import sqlite3
import uuid
import zipfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import func, or_, select

from app.core.config import AppSettings
from app.database import Base, Database
from app.models import (
    AppSetting, BackgroundJob,
    Course,
    KnowledgePoint,
    PracticeSession, PracticeSessionQuestion,
    Question,
    QuestionAttempt,
    ResourceFile,
    ReviewAttempt,
    ReviewItem,
    StudySession,
    StudyTask,
    ToolCallLog,
)


def _inside(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("路径超出受管 workspace")
    return candidate


class ResourceService:
    def __init__(self, database: Database, config: AppSettings) -> None:
        self.database = database
        self.root = config.workspace_dir
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".trash").mkdir(exist_ok=True)

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def list_files(self, search: str = "", trashed: bool = False) -> list[ResourceFile]:
        with self.database.session() as session:
            stmt = select(ResourceFile).where(ResourceFile.trashed == trashed)
            if search:
                stmt = stmt.where(ResourceFile.name.ilike(f"%{search}%"))
            return list(session.scalars(stmt.order_by(ResourceFile.created_at.desc())))

    def import_file(
        self, source: Path, course_id: int | None = None, relative_parent: Path | None = None
    ) -> ResourceFile:
        source = source.resolve()
        if not source.is_file():
            raise ValueError("请选择有效文件")
        digest = self._digest(source)
        with self.database.session() as session:
            duplicate = session.scalar(select(ResourceFile).where(ResourceFile.sha256 == digest, ~ResourceFile.trashed))
            if duplicate:
                raise ValueError(f"文件内容已存在：{duplicate.name}")
            parent = self.root / (relative_parent or Path())
            destination = _inside(self.root, parent / source.name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            counter = 1
            while destination.exists():
                destination = destination.with_name(f"{source.stem}_{counter}{source.suffix}")
                counter += 1
            shutil.copy2(source, destination)
            item = ResourceFile(
                name=destination.name,
                original_name=source.name,
                source_path=str(source),
                relative_path=destination.relative_to(self.root).as_posix(),
                sha256=digest,
                size=destination.stat().st_size,
                course_id=course_id,
            )
            session.add(item)
            session.flush()
            return item

    def import_directory(
        self, source: Path, course_id: int | None = None,
        should_cancel: Any = None, progress: Any = None
    ) -> tuple[int, list[str]]:
        source = source.resolve()
        if not source.is_dir():
            raise ValueError("请选择有效目录")
        imported, errors = 0, []
        files = [path for path in source.rglob("*") if path.is_file()]
        for index, path in enumerate(files, 1):
            if should_cancel and should_cancel():
                raise InterruptedError("用户取消了导入")
            if path.is_file():
                try:
                    self.import_file(path, course_id, path.parent.relative_to(source))
                    imported += 1
                except ValueError as error:
                    errors.append(f"{path.name}: {error}")
            if progress:
                progress(int(index * 100 / max(1, len(files))))
        return imported, errors

    def set_metadata(self, item_id: int, course_id: int | None, tags: str) -> None:
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item:
                raise ValueError("资料不存在")
            if course_id and not session.get(Course, course_id):
                raise ValueError("课程不存在")
            item.course_id = course_id
            item.tags = ",".join(dict.fromkeys(tag.strip() for tag in tags.replace("，", ",").split(",") if tag.strip()))

    def list_courses(self) -> list[Course]:
        with self.database.session() as session:
            return list(session.scalars(select(Course).where(Course.status == "active").order_by(Course.name)))

    def create_folder(self, relative: str) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts or not relative.strip():
            raise ValueError("文件夹路径无效")
        destination = _inside(self.root, self.root / relative_path)
        destination.mkdir(parents=True, exist_ok=False)
        return destination

    def move(self, item_id: int, relative_folder: str) -> None:
        folder = Path(relative_folder)
        if folder.is_absolute() or ".." in folder.parts:
            raise ValueError("目标文件夹无效")
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item:
                raise ValueError("资料不存在")
            source = _inside(self.root, self.root / item.relative_path)
            destination_folder = _inside(self.root, self.root / folder)
            if not destination_folder.is_dir():
                raise ValueError("目标文件夹不存在")
            destination = destination_folder / source.name
            if destination.exists():
                raise ValueError("目标位置已有同名文件")
            shutil.move(source, destination)
            item.relative_path = destination.relative_to(self.root).as_posix()

    def list_folders(self) -> list[str]:
        return [
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_dir() and ".trash" not in path.parts and ".versions" not in path.parts
        ]

    def content_path(self, item_id: int) -> Path:
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item:
                raise ValueError("资料不存在")
            return _inside(self.root, self.root / item.relative_path)

    def rename(self, item_id: int, new_name: str) -> None:
        if not new_name.strip() or Path(new_name).name != new_name:
            raise ValueError("文件名无效")
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item:
                raise ValueError("资料不存在")
            source = _inside(self.root, self.root / item.relative_path)
            destination = _inside(self.root, source.with_name(new_name))
            if destination.exists():
                raise ValueError("目标文件已存在")
            source.rename(destination)
            item.name = destination.name
            item.relative_path = destination.relative_to(self.root).as_posix()

    def move_to_trash(self, item_id: int) -> None:
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item or item.trashed:
                return
            source = _inside(self.root, self.root / item.relative_path)
            destination = self.root / ".trash" / f"{item.id}_{source.name}"
            if source.exists():
                shutil.move(source, destination)
            item.relative_path = destination.relative_to(self.root).as_posix()
            item.trashed = True

    def restore(self, item_id: int) -> None:
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item or not item.trashed:
                return
            source = _inside(self.root, self.root / item.relative_path)
            original = item.name.split("_", 1)[-1] if item.name.startswith(f"{item.id}_") else item.name
            destination = self.root / original
            if destination.exists():
                destination = self.root / f"restored_{item.id}_{original}"
            if source.exists():
                shutil.move(source, destination)
            item.name = destination.name
            item.relative_path = destination.relative_to(self.root).as_posix()
            item.trashed = False

    def delete_permanently(self, item_id: int) -> None:
        with self.database.session() as session:
            item = session.get(ResourceFile, item_id)
            if not item or not item.trashed:
                raise ValueError("只有回收站内的资料可以彻底删除")
            path = _inside(self.root, self.root / item.relative_path)
            if path.exists():
                path.unlink()
            session.delete(item)


