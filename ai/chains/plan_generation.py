from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import Database
from app.models import (
    AIRun, ErrorAnalysisResult, KnowledgePoint, LearningPlanDraft,
    LearningPlanDraftTask, StudyGoal, StudyTask,
)


class GeneratedPlanTask(BaseModel):
    title: str
    planned_date: date
    duration_minutes: int = Field(ge=5, le=480)
    priority: str
    task_type: str
    course_id: int | None = None
    knowledge_point_id: int | None = None
    reason: str


class PlanGenerationOutput(BaseModel):
    summary: str
    risks: list[str] = Field(default_factory=list)
    tasks: list[GeneratedPlanTask]

PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
你是个性化学习计划助手。你只能生成计划草稿，不能修改已有任务。
必须满足：
1. 任务日期不得晚于目标日期。
2. 每周总时长不得超过目标的 weekly_minutes。
3. 同一天任务总时长不得超过 daily_minutes。
4. 优先安排低掌握度知识点和人工确认的错误分析。
5. priority 只能是 high、medium、low。
6. task_type 只能是 study、practice、review。
7. 不得生成与已有任务重复的任务。
""".strip()),
    ("human", """
目标：
{goal}

每日可用分钟：
{daily_minutes}

薄弱知识点：
{knowledge}

已确认错误分析：
{errors}

已有任务：
{existing_tasks}

请生成从 {start_date} 到 {target_date} 的学习计划草稿。
""".strip()),
])


class PlanGenerationService:
    def __init__(
        self,
        *,
        database: Database,
        chat_model: BaseChatModel,
        provider: str,
        model_name: str,
    ) -> None:
        self.database = database
        self.provider = provider
        self.model_name = model_name
        self.model = chat_model.with_structured_output(PlanGenerationOutput)

    def generate(
        self,
        goal_id: int,
        *,
        start_date: date | None = None,
        daily_minutes: int = 120,
    ) -> int:
        start_date = start_date or date.today()
        if daily_minutes < 5:
            raise ValueError("每日可用时间至少为 5 分钟")

        with self.database.session() as session:
            goal = session.get(StudyGoal, goal_id)
            if goal is None or goal.status != "active":
                raise ValueError("学习目标不存在或已归档")
            if goal.target_date < start_date:
                raise ValueError("目标日期已经过去")

            knowledge = list(session.scalars(
                select(KnowledgePoint)
                .where(
                    KnowledgePoint.course_id == goal.course_id
                    if goal.course_id else True
                )
                .order_by(KnowledgePoint.mastery)
                .limit(20)
            ))
            errors = list(session.scalars(
                select(ErrorAnalysisResult)
                .where(ErrorAnalysisResult.human_confirmed.is_(True))
                .order_by(ErrorAnalysisResult.created_at.desc())
                .limit(20)
            ))
            existing = list(session.scalars(
                select(StudyTask).where(
                    StudyTask.planned_date >= start_date,
                    StudyTask.planned_date <= goal.target_date,
                )
            ))

            run = AIRun(
                run_uuid=str(uuid4()),
                feature="plan_generation",
                status="running",
                provider=self.provider,
                model_name=self.model_name,
                prompt_version="plan-generation-v1",
                input_json=json.dumps({"goal_id": goal_id}),
            )
            session.add(run)
            session.flush()

            try:
                output = self.model.invoke(PROMPT.invoke({
                    "goal": json.dumps({
                        "title": goal.title,
                        "course_id": goal.course_id,
                        "target_date": goal.target_date.isoformat(),
                        "target_score": goal.target_score,
                        "weekly_minutes": goal.weekly_minutes,
                        "progress": goal.progress,
                    }, ensure_ascii=False),
                    "daily_minutes": daily_minutes,
                    "knowledge": json.dumps([
                        {"id": item.id, "name": item.name, "mastery": item.mastery}
                        for item in knowledge
                    ], ensure_ascii=False),
                    "errors": json.dumps([
                        {
                            "question_id": item.question_id,
                            "types": json.loads(item.error_types_json),
                            "explanation": item.explanation,
                        }
                        for item in errors
                    ], ensure_ascii=False),
                    "existing_tasks": json.dumps([
                        {
                            "title": item.title,
                            "date": item.planned_date.isoformat(),
                            "duration": item.duration_minutes,
                        }
                        for item in existing
                    ], ensure_ascii=False),
                    "start_date": start_date.isoformat(),
                    "target_date": goal.target_date.isoformat(),
                }))

                self._validate(
                    output, goal, start_date, daily_minutes, existing
                )

                draft = LearningPlanDraft(
                    ai_run_id=run.id,
                    goal_id=goal.id,
                    summary=output.summary,
                    risks_json=json.dumps(output.risks, ensure_ascii=False),
                    daily_minutes=daily_minutes,
                    status="pending",
                )
                session.add(draft)
                session.flush()

                for position, task in enumerate(output.tasks, 1):
                    session.add(LearningPlanDraftTask(
                        draft_id=draft.id,
                        position=position,
                        title=task.title.strip(),
                        planned_date=task.planned_date,
                        duration_minutes=task.duration_minutes,
                        priority=task.priority,
                        task_type=task.task_type,
                        course_id=task.course_id,
                        knowledge_point_id=task.knowledge_point_id,
                        reason=task.reason.strip(),
                    ))

                run.status = "completed"
                run.output_json = output.model_dump_json()
                run.finished_at = datetime.now()
                return draft.id
            except Exception as exc:
                run.status = "failed"
                run.error_message = str(exc)[:4000]
                run.finished_at = datetime.now()
                raise

    @staticmethod
    def _validate(output, goal, start_date, daily_minutes, existing) -> None:
        if not output.tasks:
            raise ValueError("模型没有生成任务")

        existing_keys = {
            (item.title.strip().casefold(), item.planned_date)
            for item in existing
        }
        generated_keys = set()
        daily_totals = {}
        weekly_totals = {}

        for task in output.tasks:
            if not task.title.strip():
                raise ValueError("任务名称不能为空")
            if not start_date <= task.planned_date <= goal.target_date:
                raise ValueError("任务日期超出计划范围")
            if task.priority not in {"high", "medium", "low"}:
                raise ValueError("任务优先级无效")
            if task.task_type not in {"study", "practice", "review"}:
                raise ValueError("任务类型无效")

            key = (task.title.strip().casefold(), task.planned_date)
            if key in existing_keys or key in generated_keys:
                raise ValueError("计划包含重复任务")
            generated_keys.add(key)

            daily_totals[task.planned_date] = (
                daily_totals.get(task.planned_date, 0)
                + task.duration_minutes
            )
            monday = task.planned_date - timedelta(
                days=task.planned_date.weekday()
            )
            weekly_totals[monday] = (
                weekly_totals.get(monday, 0)
                + task.duration_minutes
            )

        if any(value > daily_minutes for value in daily_totals.values()):
            raise ValueError("某日任务时长超过每日可用时间")
        if any(value > goal.weekly_minutes for value in weekly_totals.values()):
            raise ValueError("某周任务时长超过每周可用时间")

    def list_tasks(self, draft_id: int):
        with self.database.session() as session:
            return list(session.scalars(
                select(LearningPlanDraftTask)
                .where(LearningPlanDraftTask.draft_id == draft_id)
                .order_by(LearningPlanDraftTask.position)
            ))

    def confirm(self, draft_id: int) -> int:
        with self.database.session() as session:
            draft = session.get(LearningPlanDraft, draft_id)
            if draft is None or draft.status != "pending":
                raise ValueError("计划草稿不存在或已经处理")

            tasks = list(session.scalars(
                select(LearningPlanDraftTask)
                .where(LearningPlanDraftTask.draft_id == draft_id)
                .order_by(LearningPlanDraftTask.position)
            ))
            for item in tasks:
                session.add(StudyTask(
                    title=item.title,
                    planned_date=item.planned_date,
                    duration_minutes=item.duration_minutes,
                    priority={
                        "high": "高", "medium": "中", "low": "低"
                    }[item.priority],
                    task_type={
                        "study": "学习", "practice": "练习", "review": "复习",
                    }[item.task_type],
                    course_id=item.course_id,
                    source="ai",
                    note=item.reason,
                ))

            draft.status = "accepted"
            draft.confirmed_at = datetime.now()
            run = session.get(AIRun, draft.ai_run_id)
            if run:
                run.user_confirmed = True
            return len(tasks)

    def reject(self, draft_id: int) -> None:
        with self.database.session() as session:
            draft = session.get(LearningPlanDraft, draft_id)
            if draft is None:
                raise ValueError("计划草稿不存在")
            draft.status = "rejected"
