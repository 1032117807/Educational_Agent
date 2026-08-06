from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.database import Database
from app.models import AgentHandoff, AgentMessage, AgentSession, AgentToolCall


class AgentSessionService:
    """Persistence boundary for AI-center conversations and module handoffs."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_session(self, title: str) -> AgentSession:
        with self.database.session() as db:
            item = AgentSession(title=title.strip() or "New session")
            db.add(item)
            db.flush()
            return item

    def list_sessions(self) -> list[AgentSession]:
        with self.database.session() as db:
            return list(db.scalars(
                select(AgentSession)
                .where(~AgentSession.archived)
                .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
            ))

    def search_sessions(self, query: str, *, include_archived: bool = False) -> list[AgentSession]:
        """按标题检索会话，默认不返回已归档会话。"""
        normalized = query.strip()
        with self.database.session() as db:
            statement = select(AgentSession).order_by(
                AgentSession.updated_at.desc(), AgentSession.id.desc()
            )
            if not include_archived:
                statement = statement.where(~AgentSession.archived)
            if normalized:
                statement = statement.where(AgentSession.title.contains(normalized))
            return list(db.scalars(statement))

    def archive(self, session_id: int) -> None:
        with self.database.session() as db:
            item = db.get(AgentSession, session_id)
            if item is None:
                raise ValueError("Agent session does not exist")
            item.archived = True
            item.updated_at = datetime.now()

    def restore(self, session_id: int) -> None:
        with self.database.session() as db:
            item = db.get(AgentSession, session_id)
            if item is None:
                raise ValueError("Agent session does not exist")
            item.archived = False
            item.updated_at = datetime.now()

    def load(self, session_id: int) -> tuple[AgentSession, list[AgentMessage], list[AgentToolCall]]:
        with self.database.session() as db:
            item = db.get(AgentSession, session_id)
            if item is None:
                raise ValueError("Agent session does not exist")
            messages = list(db.scalars(
                select(AgentMessage).where(AgentMessage.session_id == session_id)
                .order_by(AgentMessage.id)
            ))
            tools = list(db.scalars(
                select(AgentToolCall).where(AgentToolCall.session_id == session_id)
                .order_by(AgentToolCall.id)
            ))
            return item, messages, tools

    def list_handoffs(self, session_id: int) -> list[AgentHandoff]:
        with self.database.session() as db:
            return list(db.scalars(
                select(AgentHandoff).where(AgentHandoff.session_id == session_id)
                .order_by(AgentHandoff.id.desc())
            ))

    def append_message(self, session_id: int, role: str, content: str) -> AgentMessage:
        with self.database.session() as db:
            item = db.get(AgentSession, session_id)
            if item is None:
                raise ValueError("Agent session does not exist")
            message = AgentMessage(session_id=session_id, role=role, content=content)
            db.add(message)
            item.updated_at = datetime.now()
            db.flush()
            return message

    def rename(self, session_id: int, title: str) -> None:
        with self.database.session() as db:
            item = db.get(AgentSession, session_id)
            if item is None:
                raise ValueError("Agent session does not exist")
            item.title = title.strip()[:160] or item.title
            item.updated_at = datetime.now()

    def record_tool_call(
        self, session_id: int, tool_name: str, status: str, detail: str,
        *, input_data: dict[str, Any] | None = None, output_data: dict[str, Any] | None = None,
    ) -> AgentToolCall:
        with self.database.session() as db:
            item = AgentToolCall(
                session_id=session_id, tool_name=tool_name, status=status, detail=detail,
                input_json=json.dumps(input_data or {}, ensure_ascii=False),
                output_json=json.dumps(output_data or {}, ensure_ascii=False),
                error_message=detail if status == "failed" else "",
                finished_at=datetime.now() if status in {"completed", "failed"} else None,
            )
            db.add(item)
            session = db.get(AgentSession, session_id)
            if session is not None:
                session.updated_at = datetime.now()
            db.flush()
            return item

    def record_handoff(
        self, session_id: int, kind: str, *, target_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentHandoff:
        with self.database.session() as db:
            item = AgentHandoff(
                session_id=session_id, kind=kind, target_id=target_id,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
            )
            db.add(item)
            session = db.get(AgentSession, session_id)
            if session is not None:
                session.updated_at = datetime.now()
            db.flush()
            return item
