from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.core.config import AppSettings
from app.database import Database
from app.services.domain import MaintenanceService, QuestionService, ResourceService, ReviewService
from app.services.learning import LearningService
from app.agent_runtime.observations import observe_failure, observe_success


class PathInput(BaseModel):
    path: str = Field(".", description="workspace 内相对路径")


class TextInput(PathInput):
    content: str


class IdInput(BaseModel):
    id: int


class RenameInput(PathInput):
    new_name: str


class EmptyInput(BaseModel):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    mutates_data: bool
    risk: str
    handler: Callable[[BaseModel], Any]

    def schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


class ToolRegistry:
    def __init__(self, database: Database, config: AppSettings) -> None:
        self.database = database
        self.config = config
        self.learning = LearningService(database)
        self.resources = ResourceService(database, config)
        self.questions = QuestionService(database)
        self.reviews = ReviewService(database)
        self.maintenance = MaintenanceService(database, config)
        self._tools: dict[str, ToolDefinition] = {}
        self._register_defaults()

    def _safe(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("只接受 workspace 内的相对路径")
        resolved = (self.config.workspace_dir / path).resolve()
        root = self.config.workspace_dir.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("路径越界")
        return resolved

    def _add(self, name: str, description: str, model: type[BaseModel], mutates: bool, risk: str, handler: Callable[[BaseModel], Any]) -> None:
        self._tools[name] = ToolDefinition(name, description, model, mutates, risk, handler)

    def _register_defaults(self) -> None:
        self._add("filesystem.list_directory", "列出 workspace 目录", PathInput, False, "low",
                  lambda args: [item.name for item in self._safe(args.path).iterdir()])
        self._add("filesystem.read_text", "读取 workspace 文本", PathInput, False, "low",
                  lambda args: self._safe(args.path).read_text(encoding="utf-8", errors="replace"))
        self._add("filesystem.create_directory", "创建 workspace 目录", PathInput, True, "medium",
                  lambda args: self._mkdir(args.path))
        self._add("filesystem.create_text_file", "创建文本文件", TextInput, True, "medium",
                  lambda args: self._write(args.path, args.content, False))
        self._add("filesystem.update_text_file", "更新文本文件", TextInput, True, "medium",
                  lambda args: self._write(args.path, args.content, True))
        self._add("filesystem.rename", "重命名 workspace 文件", RenameInput, True, "medium",
                  lambda args: self._rename(args.path, args.new_name))
        self._add("filesystem.move_to_trash", "移动文件到回收站", PathInput, True, "high",
                  lambda args: self._trash(args.path))
        self._add("filesystem.restore_from_trash", "从回收站恢复文件", PathInput, True, "medium",
                  lambda args: self._restore(args.path))
        self._add("course.list", "列出课程", EmptyInput, False, "low",
                  lambda _: [{"id": c.id, "name": c.name, "subject": c.subject} for c in self.learning.list_courses()])
        self._add("course.get", "获取课程", IdInput, False, "low",
                  lambda args: self._course(args.id))
        self._add("study_task.list_today", "列出今日任务", EmptyInput, False, "low",
                  lambda _: [{"id": t.id, "title": t.title, "completed": t.completed} for t in self.learning.list_today_tasks()])
        self._add("study_task.complete", "完成任务", IdInput, True, "medium",
                  lambda args: self.learning.complete_task(args.id))
        self._add("review.list_due", "列出到期复习", EmptyInput, False, "low",
                  lambda _: [{"id": r.id, "title": r.title, "next_review": r.next_review.isoformat()} for r in self.reviews.list_items(True)])
        self._add("question.export_json", "导出题库", PathInput, True, "medium",
                  lambda args: self.questions.export_json(self._safe(args.path)))
        self._add("database.backup", "创建完整备份", PathInput, True, "medium",
                  lambda args: str(self.maintenance.backup(self._safe(args.path))))

    def _mkdir(self, relative: str) -> str:
        path = self._safe(relative)
        path.mkdir(parents=True, exist_ok=False)
        return str(path.relative_to(self.config.workspace_dir))

    def _write(self, relative: str, content: str, must_exist: bool) -> str:
        import shutil
        from datetime import datetime

        path = self._safe(relative)
        if must_exist and not path.is_file():
            raise ValueError("目标文件不存在")
        if not must_exist and path.exists():
            raise ValueError("目标文件已存在")
        if must_exist:
            version = (
                self.config.workspace_dir / ".versions" / f"{datetime.now():%Y%m%d-%H%M%S-%f}"
                / path.relative_to(self.config.workspace_dir)
            )
            version.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.config.workspace_dir))

    def _rename(self, relative: str, new_name: str) -> str:
        source = self._safe(relative)
        if Path(new_name).name != new_name or not new_name.strip():
            raise ValueError("新名称无效")
        destination = source.with_name(new_name)
        if destination.exists():
            raise ValueError("目标已存在")
        source.rename(destination)
        return str(destination.relative_to(self.config.workspace_dir))

    def _trash(self, relative: str) -> str:
        import shutil

        source = self._safe(relative)
        if not source.exists():
            raise ValueError("目标不存在")
        trash = self.config.workspace_dir / ".trash"
        trash.mkdir(exist_ok=True)
        destination = trash / source.name
        counter = 1
        while destination.exists():
            destination = trash / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        shutil.move(source, destination)
        return str(destination.relative_to(self.config.workspace_dir))

    def _restore(self, relative: str) -> str:
        import shutil

        source = self._safe(relative)
        trash = (self.config.workspace_dir / ".trash").resolve()
        if trash not in source.parents:
            raise ValueError("只能恢复回收站内的文件")
        destination = self.config.workspace_dir / source.name
        if destination.exists():
            raise ValueError("恢复目标已存在")
        shutil.move(source, destination)
        return str(destination.relative_to(self.config.workspace_dir))

    def _course(self, course_id: int) -> dict[str, Any]:
        item = self.learning.get_course(course_id)
        if not item:
            raise ValueError("课程不存在")
        return {"id": item.id, "name": item.name, "subject": item.subject, "progress": item.progress}

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise ValueError(f"未知工具：{name}")
        return self._tools[name]

    def execute(self, name: str, arguments: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        tool = self.get(name)
        if tool.mutates_data and not confirmed:
            return {"success": False, "confirmation_required": True, "tool": name}
        return self.maintenance.log_tool(
            name, arguments, lambda: tool.handler(tool.input_model.model_validate(arguments))
        )

    def execute_observed(self, name: str, arguments: dict[str, Any], confirmed: bool = False) -> dict[str, Any]:
        """Execute through the legacy handler and expose the shared result envelope."""
        try:
            return observe_success(name, self.execute(name, arguments, confirmed), source="local")
        except Exception as exc:
            return observe_failure(name, exc, suggestion="check arguments or ask the learner for clarification")

    def recent_logs(self, limit: int = 100) -> list[Any]:
        return self.maintenance.list_tool_logs(limit)
