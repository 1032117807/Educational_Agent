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
from ai.chains.question_generation import QuestionGenerationService, QuestionDraftService
from app.database import Database
from app.models import Course, KnowledgePoint, LearningPlanDraft, StudyGoal, StudyTask
from app.tools.registry import ToolRegistry


class AgentDecision(BaseModel):
    reply: str = Field(description="给学习者的简洁中文回复")
    action: Literal[
        "chat", "show_status", "generate_plan", "generate_questions", "navigate", "tool"
    ] = "chat"
    goal_id: int | None = None
    daily_minutes: int = Field(default=60, ge=5, le=480)
    route: Literal[
        "resources", "practice", "plan", "analytics", "review", "courses", "agent"
    ] | None = None
    tool_name: str | None = None
    tool_arguments_json: str = "{}"
    course_id: int | None = None
    question_request: str = ""
    question_count: int = Field(default=5, ge=1, le=20)
    question_difficulty: int = Field(default=3, ge=1, le=5)

    @property
    def tool_arguments(self) -> dict:
        try:
            value = json.loads(self.tool_arguments_json or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class PlanPreview:
    draft_id: int
    summary: str
    risks: tuple[str, ...]
    tasks: tuple[dict, ...]


@dataclass(frozen=True)
class GeneratedPractice:
    question_ids: tuple[int, ...]
    request: str


PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
你是桌面学习应用里的通用学习 Agent。你只能根据提供的本地学习数据回答或操作。
你的职责是解释学习状态、回答问题、调用项目工具，或把用户带到正确的功能页面。
生成计划时只能选择 active_goals 中的 goal_id，并根据用户提出的每日时长填写 daily_minutes。
生成计划只是草稿，应用会在用户确认后才写入正式任务。
如果用户只是闲聊或提问，action 使用 chat；如果要求查看学习状态，使用 show_status；
如果要求制定、安排、生成学习计划，使用 generate_plan。
如果用户要求打开或使用某个功能，action 使用 navigate，并选择 route：
resources=资料问答，practice=题库和 AI 出题/练习，plan=学习计划，analytics=学习分析和报告，
review=错题复习，courses=课程管理，agent=本窗口。
如果用户明确要求执行一个 available_tools 中的操作，action 使用 tool，填写 tool_name 和
tool_arguments_json（一个 JSON 对象字符串，例如 {{"id": 12}}）。
如果用户要求生成题目、练习题或测试题，action 使用 generate_questions，填写 question_request、
question_count、question_difficulty 和 course_id；生成后应用会把题目交给练习中心。
修改数据的工具必须等待用户确认；不要声称已经执行未确认的操作。
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
        tool_registry: ToolRegistry | None = None,
        question_factory: Callable[[], QuestionGenerationService] | None = None,
    ) -> None:
        self.database = database
        self.model = chat_model.with_structured_output(AgentDecision)
        self.plan_factory = plan_factory
        self.tool_registry = tool_registry
        self.question_factory = question_factory

    def context(self) -> dict:
        with self.database.session() as session:
            courses = list(session.scalars(select(Course).where(Course.status == "active")))
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
            "courses": [{"id": item.id, "name": item.name} for item in courses],
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
            "available_tools": [
                {"name": item.name, "description": item.description,
                 "mutates_data": item.mutates_data}
                for item in (self.tool_registry.list() if self.tool_registry else [])
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
        if decision.action == "navigate" and decision.route is None:
            decision.action = "chat"
            decision.reply = "请说明要打开资料、练习、计划、报告、复习还是课程页面。"
        if decision.action == "tool" and (
            self.tool_registry is None or not decision.tool_name
        ):
            decision.action = "chat"
            decision.reply = "我暂时无法找到对应的项目操作。"
        if decision.action == "generate_questions" and self.question_factory is None:
            decision.action = "chat"
            decision.reply = "题目生成服务尚未配置。"
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
        if decision.action == "generate_questions" and decision.course_id is None:
            courses = self.context()["courses"]
            if len(courses) == 1:
                decision.course_id = courses[0]["id"]
            elif not courses:
                decision.action = "chat"
                decision.reply = "当前没有课程，请先创建课程后再生成题目。"
            else:
                decision.action = "chat"
                decision.reply = "请告诉我为哪门课程生成题目。"
        return decision

    def execute_tool(self, name: str, arguments: dict, *, confirmed: bool = False) -> dict:
        if self.tool_registry is None:
            raise ValueError("通用工具未初始化")
        return self.tool_registry.execute(name, arguments, confirmed=confirmed)

    def generate_questions(
        self,
        *,
        course_id: int,
        request: str,
        count: int,
        difficulty: int,
        progress: Callable[[str, str, str], None] | None = None,
    ) -> GeneratedPractice:
        if self.question_factory is None:
            raise ValueError("题目生成服务未初始化")
        service = self.question_factory()
        try:
            result = service.generate(
                request,
                course_id=course_id,
                count=count,
                kinds=["单选", "判断", "填空", "简答"],
                difficulty=difficulty,
                resource_ids=None,
            )
        except ValueError as first_error:
            if progress is not None:
                progress("question_generation.retry", "running", "模型返回空结果，追加引用格式后重试")
            # Some compatible models return an empty structured list on the
            # first pass. Retry once with the required evidence format explicit.
            retry_request = (
                f"{request}\n\n必须返回 {count} 道完整题目；每题必须包含答案、解析，"
                "并在解析内引用提供的资料编号 [D1]、[D2] 等。不能返回空题目列表。"
            )
            try:
                result = service.generate(
                    retry_request,
                    course_id=course_id,
                    count=count,
                    kinds=["单选", "判断", "填空", "简答"],
                    difficulty=difficulty,
                    resource_ids=None,
                )
                if progress is not None:
                    progress("question_generation.retry", "completed", "重试成功")
            except ValueError as retry_error:
                if progress is not None:
                    progress("question_generation.retry", "failed", str(retry_error))
                raise ValueError(
                    "题目生成失败：模型没有返回符合资料引用规则的题目。"
                    "请先为该课程导入并建立资料索引，或稍后重试。"
                ) from retry_error
        draft_service = QuestionDraftService(self.database)
        question_ids = tuple(draft_service.accept(draft_id) for draft_id in result.draft_ids)
        if not question_ids:
            raise ValueError("没有生成可练习的题目")
        return GeneratedPractice(question_ids=question_ids, request=request)

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
