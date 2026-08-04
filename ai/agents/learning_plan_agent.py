from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select

from ai.chains.plan_generation import PlanGenerationService
from app.database import Database
from app.models import KnowledgePoint, LearningPlanDraft, StudyGoal, StudyTask


class AgentDecision(BaseModel):
    reply: str = Field(description="给学习者的简洁中文回复")
    action: Literal["chat", "show_status", "generate_plan"] = "chat"
    goal_id: int | None = None
    daily_minutes: int = Field(default=60, ge=5, le=480)


@dataclass(frozen=True)
class PlanPreview:
    draft_id: int
    summary: str
    risks: tuple[str, ...]
    tasks: tuple[dict, ...]


PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
你是桌面学习应用里的学习计划 Agent。你只能根据提供的本地学习数据回答。
你的职责是解释学习状态、回答计划问题，或在用户明确要求时生成学习计划草稿。
生成计划时只能选择 active_goals 中的 goal_id，并根据用户提出的每日时长填写 daily_minutes。
生成计划只是草稿，应用会在用户确认后才写入正式任务。
如果用户只是闲聊或提问，action 使用 chat；如果要求查看学习状态，使用 show_status；
如果要求制定、安排、生成学习计划，使用 generate_plan。
回复简短、具体，避免声称已经完成尚未执行的操作。
""".strip()),
    ("human", """
本地学习状态：
{context}

最近对话：
{history}

用户消息：
{message}
""".strip()),
])


class LearningPlanAgentService:
    def __init__(
        self,
        *,
        database: Database,
        chat_model: BaseChatModel,
        plan_factory: Callable[[], PlanGenerationService],
    ) -> None:
        self.database = database
        self.model = chat_model.with_structured_output(AgentDecision)
        self.plan_factory = plan_factory

    def context(self) -> dict:
        with self.database.session() as session:
            goals = list(session.scalars(select(StudyGoal).where(StudyGoal.status == "active")))
            weak_points = list(session.scalars(
                select(KnowledgePoint).order_by(KnowledgePoint.mastery.asc()).limit(8)
            ))
            tasks = list(session.scalars(
                select(StudyTask)
                .where(StudyTask.planned_date >= date.today())
                .order_by(StudyTask.planned_date, StudyTask.id)
                .limit(20)
            ))
        return {
            "today": date.today().isoformat(),
            "active_goals": [
                {"id": item.id, "title": item.title, "target_date": item.target_date.isoformat(),
                 "course_id": item.course_id, "weekly_minutes": item.weekly_minutes,
                 "progress": item.progress}
                for item in goals
            ],
            "weak_points": [
                {"id": item.id, "name": item.name, "mastery": item.mastery,
                 "course_id": item.course_id}
                for item in weak_points
            ],
            "upcoming_tasks": [
                {"id": item.id, "title": item.title, "date": item.planned_date.isoformat(),
                 "completed": item.completed, "duration_minutes": item.duration_minutes}
                for item in tasks
            ],
        }

    def respond(self, message: str, history: list[dict[str, str]] | None = None) -> AgentDecision:
        if not message.strip():
            raise ValueError("消息不能为空")
        decision = self.model.invoke(PROMPT.invoke({
            "context": json.dumps(self.context(), ensure_ascii=False),
            "history": json.dumps((history or [])[-10:], ensure_ascii=False),
            "message": message.strip(),
        }))
        if decision.action == "generate_plan" and decision.goal_id is None:
            goals = self.context()["active_goals"]
            if len(goals) == 1:
                decision.goal_id = goals[0]["id"]
            elif not goals:
                decision.action = "chat"
                decision.reply = "当前没有进行中的学习目标，请先在学习计划页创建一个目标。"
            else:
                decision.action = "chat"
                decision.reply = "你有多个进行中的目标，请告诉我想为哪个目标制定计划。"
        return decision

    def generate_plan(self, *, goal_id: int, daily_minutes: int) -> PlanPreview:
        draft_id = self.plan_factory().generate(
            goal_id, start_date=date.today(), daily_minutes=daily_minutes
        )
        with self.database.session() as session:
            draft = session.get(LearningPlanDraft, draft_id)
            if draft is None:
                raise ValueError("计划草稿生成后无法读取")
            summary = draft.summary
            risks = tuple(json.loads(draft.risks_json or "[]"))
        tasks = self.plan_factory().list_tasks(draft_id)
        return PlanPreview(
            draft_id=draft_id,
            summary=summary,
            risks=risks,
            tasks=tuple({
                "title": item.title,
                "date": item.planned_date.isoformat(),
                "duration_minutes": item.duration_minutes,
                "priority": item.priority,
                "task_type": item.task_type,
                "reason": item.reason,
            } for item in tasks),
        )

    def confirm_plan(self, draft_id: int) -> int:
        return self.plan_factory().confirm(draft_id)
