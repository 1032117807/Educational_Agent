from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.database import Database
from app.models import AgentMemory


class AgentMemoryService:
    """长期记忆边界：没有 confirmed=True 就不能写入。"""

    ALLOWED_CATEGORIES = {
        "goal", "plan_preference", "weak_point", "learning_pace",
    }

    def __init__(self, database: Database) -> None:
        self.database = database

    def remember(
        self, *, scope: str, category: str, content: dict[str, Any],
        course_id: int | None = None, confirmed: bool = False,
    ) -> AgentMemory:
        # 这是隐私边界，不能只依赖 UI 按钮或模型提示词。
        if not confirmed:
            raise PermissionError("记忆必须经用户确认后才能保存")
        if scope not in {"course", "long_term"}:
            raise ValueError("记忆范围只能是 course 或 long_term")
        if category not in self.ALLOWED_CATEGORIES:
            raise ValueError("不支持的记忆类别")
        if scope == "course" and course_id is None:
            raise ValueError("课程记忆必须提供 course_id")
        with self.database.session() as session:
            item = AgentMemory(
                scope=scope, course_id=course_id, category=category,
                content_json=json.dumps(content, ensure_ascii=False),
                confirmed=True,
            )
            session.add(item)
            session.flush()
            return item

    def list_memories(self, course_id: int | None = None) -> list[AgentMemory]:
        with self.database.session() as session:
            statement = select(AgentMemory).where(
                AgentMemory.confirmed, ~AgentMemory.deleted,
            )
            if course_id is None:
                statement = statement.where(AgentMemory.course_id.is_(None))
            else:
                statement = statement.where(
                    (AgentMemory.course_id.is_(None))
                    | (AgentMemory.course_id == course_id)
                )
            return list(session.scalars(statement.order_by(AgentMemory.updated_at.desc())))

    def list_all_memories(self) -> list[AgentMemory]:
        """管理界面使用：列出全部课程和全局记忆。"""
        with self.database.session() as session:
            return list(session.scalars(select(AgentMemory).where(
                AgentMemory.confirmed, ~AgentMemory.deleted,
            ).order_by(AgentMemory.updated_at.desc())))

    def context(self, course_id: int | None = None) -> list[dict[str, Any]]:
        """只给 Agent 返回确认且未删除的最小必要数据。"""
        return [
            {
                "id": item.id,
                "scope": item.scope,
                "category": item.category,
                "content": json.loads(item.content_json or "{}"),
            }
            for item in self.list_memories(course_id)
        ]

    def context_for_courses(self, course_ids: list[int]) -> list[dict[str, Any]]:
        """合并全局偏好和当前课程记忆，并去重。"""
        items = self.context()
        seen = {item["id"] for item in items}
        for course_id in course_ids:
            for item in self.context(course_id):
                if item["id"] not in seen:
                    items.append(item)
                    seen.add(item["id"])
        return items

    def delete_memory(self, memory_id: int) -> None:
        # 软删除，避免用户误删后无法审计。
        with self.database.session() as session:
            item = session.get(AgentMemory, memory_id)
            if item is None:
                raise ValueError("记忆不存在")
            item.deleted = True
