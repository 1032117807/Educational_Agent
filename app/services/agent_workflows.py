from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select

from ai.chains import KnowledgeExtractionService, QuestionDraftService, QuestionGenerationService
from ai.indexing import ResourceIndexingPipeline
from ai.reports import LearningReportService, render_learning_report
from app.database import Database
from app.models import AgentHandoff, AgentWorkflow, Course, KnowledgePointDraft, ResourceFile
from ai.agents.orchestrator import LearningOrchestrator

StepProgress = Callable[[str, str, str], None]


@dataclass(frozen=True)
class WorkflowOutcome:
    workflow_id: int
    step: str
    status: str
    summary: str
    payload: dict[str, Any]


class AgentWorkflowService:
    """Coordinates the durable resource-to-report learning workflow."""

    STEP_LABELS = {
        "analyze": "资料分析与索引",
        "extract": "知识点提炼",
        "questions": "题目生成",
        "practice": "练习",
        "report": "学习报告",
    }
    STEP_AGENTS = {
        "analyze": "资料分析 Agent",
        "extract": "知识点 Agent",
        "questions": "出题 Agent",
        "practice": "练习 Agent",
        "report": "报告 Agent",
    }

    def __init__(
        self,
        *,
        database: Database,
        indexing_factory: Callable[[], ResourceIndexingPipeline],
        extraction_factory: Callable[[], KnowledgeExtractionService],
        question_factory: Callable[[], QuestionGenerationService],
        report_factory: Callable[[], LearningReportService],
        orchestrator: LearningOrchestrator | None = None,
    ) -> None:
        self.database = database
        self.indexing_factory = indexing_factory
        self.extraction_factory = extraction_factory
        self.question_factory = question_factory
        self.report_factory = report_factory
        self.orchestrator = orchestrator or LearningOrchestrator(
            database=database,
            indexing_factory=indexing_factory,
            extraction_factory=extraction_factory,
            question_factory=question_factory,
            report_factory=report_factory,
            plan_factory=lambda: None,
        )

    def create(self, *, session_id: int, course_id: int, request: str) -> AgentWorkflow:
        with self.database.session() as db:
            if db.get(Course, course_id) is None:
                raise ValueError("课程不存在")
            resource_ids = list(db.scalars(select(ResourceFile.id).where(
                ResourceFile.course_id == course_id, ~ResourceFile.trashed
            )))
            if not resource_ids:
                raise ValueError("该课程没有可分析的资料，请先导入资料")
            item = AgentWorkflow(
                session_id=session_id,
                course_id=course_id,
                request=request.strip() or "基于课程资料完成学习闭环",
                context_json=json.dumps({"resource_ids": resource_ids}, ensure_ascii=False),
            )
            db.add(item)
            db.flush()
            return item

    def get(self, workflow_id: int) -> AgentWorkflow:
        with self.database.session() as db:
            item = db.get(AgentWorkflow, workflow_id)
            if item is None:
                raise ValueError("工作流不存在")
            return item

    def question_ids(self, workflow_id: int) -> list[int]:
        item = self.get(workflow_id)
        return [int(value) for value in self._context(item).get("question_ids", [])]

    def latest_for_session(self, session_id: int) -> AgentWorkflow | None:
        with self.database.session() as db:
            return db.scalar(select(AgentWorkflow).where(
                AgentWorkflow.session_id == session_id,
                AgentWorkflow.status.not_in(("completed", "cancelled")),
            ).order_by(AgentWorkflow.updated_at.desc(), AgentWorkflow.id.desc()))

    def cancel(self, workflow_id: int) -> AgentWorkflow:
        with self.database.session() as db:
            item = self._get_in_session(db, workflow_id)
            if item.status == "running":
                raise ValueError("当前步骤正在运行，完成后再取消")
            item.status = "cancelled"
            item.error_message = "用户取消"
            item.updated_at = datetime.now()
            return item

    def continue_workflow(self, workflow_id: int, progress: StepProgress | None = None) -> WorkflowOutcome:
        with self.database.session() as db:
            item = self._get_in_session(db, workflow_id)
            if item.status not in {"waiting_confirmation", "failed", "waiting_report"}:
                raise ValueError("当前工作流不能继续")
            if item.current_step == "practice":
                raise ValueError("请先完成练习，再生成学习报告")
            item.status = "running"
            item.error_message = ""
            item.updated_at = datetime.now()
            step, course_id, request, context = item.current_step, item.course_id, item.request, self._context(item)

        try:
            if step == "analyze":
                outcome = self._analyze(workflow_id, course_id, context, progress)
            elif step == "extract":
                outcome = self._extract(workflow_id, course_id, context, progress)
            elif step == "questions":
                outcome = self._questions(workflow_id, course_id, request, context, progress)
            elif step == "report":
                outcome = self._report(workflow_id, context, progress)
            else:
                raise ValueError(f"未知工作流步骤：{step}")
        except Exception as exc:
            self._fail(workflow_id, str(exc))
            raise
        return outcome

    def mark_practice_complete(self, workflow_id: int) -> WorkflowOutcome:
        with self.database.session() as db:
            item = self._get_in_session(db, workflow_id)
            if item.current_step != "practice":
                raise ValueError("当前工作流不在练习步骤")
            item.current_step = "report"
            item.status = "waiting_report"
            item.updated_at = datetime.now()
            context = self._context(item)
        return WorkflowOutcome(workflow_id, "report", "waiting_report", "练习已结束，可继续生成学习报告", context)

    def confirm_knowledge_review(self, workflow_id: int) -> WorkflowOutcome:
        with self.database.session() as db:
            item = self._get_in_session(db, workflow_id)
            if item.current_step != "review" or item.status != "waiting_review":
                raise ValueError("当前工作流不在知识点人工审核步骤")
            context = self._context(item)
            run_id = context.get("knowledge_ai_run_id")
            drafts = list(db.scalars(select(KnowledgePointDraft).where(
                KnowledgePointDraft.ai_run_id == run_id
            )))
            pending = [draft for draft in drafts if draft.status == "pending"]
            accepted = [draft for draft in drafts if draft.status == "accepted"]
            if pending:
                raise ValueError(f"仍有 {len(pending)} 个知识点草稿未审核")
            if not accepted:
                raise ValueError("请至少接受一个知识点草稿后再生成题目")
            context["accepted_knowledge_point_ids"] = [
                draft.accepted_knowledge_point_id for draft in accepted
                if draft.accepted_knowledge_point_id is not None
            ]
        return self._advance(
            workflow_id, "questions", "waiting_confirmation", context,
            f"人工审核已确认，接受 {len(context['accepted_knowledge_point_ids'])} 个知识点，可生成题目",
        )

    def _analyze(self, workflow_id: int, course_id: int, context: dict[str, Any], progress: StepProgress | None) -> WorkflowOutcome:
        if self.orchestrator is not None:
            result = self.orchestrator.run("analyze", {**context, "course_id": course_id}, progress)
            context.update(result.context)
            return self._advance(workflow_id, "extract", "waiting_confirmation", context, result.summary)
        resource_ids = list(context.get("resource_ids", []))
        if not resource_ids:
            raise ValueError("没有可分析的课程资料")
        pipeline = self.indexing_factory()
        for position, resource_id in enumerate(resource_ids, 1):
            self._event(progress, "workflow.analyze", "running", f"索引资料 {position}/{len(resource_ids)}")
            pipeline.index_resource(resource_id, progress=lambda value: self._event(
                progress, "workflow.analyze.progress", "running", f"资料 {position}/{len(resource_ids)}: {value}%"
            ))
        context["indexed_resource_ids"] = resource_ids
        return self._advance(workflow_id, "extract", "waiting_confirmation", context, "资料已分析，可确认提炼知识点")

    def _extract(self, workflow_id: int, course_id: int, context: dict[str, Any], progress: StepProgress | None) -> WorkflowOutcome:
        if self.orchestrator is not None:
            result = self.orchestrator.run("extract", {**context, "course_id": course_id}, progress)
            context.update(result.context)
            return self._advance(workflow_id, "review", "waiting_review", context, result.summary)
        self._event(progress, "workflow.extract", "running", "根据已索引资料提炼知识点草稿")
        result = self.extraction_factory().extract(
            course_id=course_id,
            resource_ids=list(context.get("indexed_resource_ids", context.get("resource_ids", []))),
            progress=lambda value: self._event(progress, "workflow.extract.progress", "running", f"提炼进度 {value}%"),
        )
        context.update({"knowledge_ai_run_id": result.ai_run_id, "knowledge_draft_count": result.draft_count})
        return self._advance(workflow_id, "review", "waiting_review", context, f"已生成 {result.draft_count} 个知识点草稿，等待人工审核")

    def _questions(self, workflow_id: int, course_id: int, request: str, context: dict[str, Any], progress: StepProgress | None) -> WorkflowOutcome:
        if self.orchestrator is not None:
            result = self.orchestrator.run(
                "questions", {**context, "course_id": course_id, "request": request}, progress
            )
            context.update(result.context)
            return self._advance(workflow_id, "practice", "waiting_confirmation", context, result.summary)
        self._event(progress, "workflow.questions", "running", "依据知识点和资料生成练习题草稿")
        generated = self.question_factory().generate(
            request,
            course_id=course_id,
            count=5,
            difficulty=3,
            resource_ids=list(context.get("indexed_resource_ids", context.get("resource_ids", []))),
        )
        questions = QuestionDraftService(self.database)
        question_ids = [questions.accept(draft_id) for draft_id in generated.draft_ids]
        context.update({"question_draft_ids": list(generated.draft_ids), "question_ids": question_ids})
        return self._advance(workflow_id, "practice", "waiting_confirmation", context, f"已生成 {len(question_ids)} 道练习题，可开始练习")

    def _report(self, workflow_id: int, context: dict[str, Any], progress: StepProgress | None) -> WorkflowOutcome:
        if self.orchestrator is not None:
            result = self.orchestrator.run("report", context, progress)
            context.update(result.context)
            return self._advance(workflow_id, "report", "completed", context, result.summary, complete=True)
        self._event(progress, "workflow.report", "running", "汇总练习和学习数据，生成学习报告")
        service = self.report_factory()
        report = service.generate(start_date=date.today() - timedelta(days=6), end_date=date.today())
        saved = service.save_snapshot(report, render_learning_report(report))
        context["report_snapshot_id"] = saved.id
        return self._advance(workflow_id, "report", "completed", context, "学习报告已生成", complete=True)

    def _advance(self, workflow_id: int, next_step: str, status: str, context: dict[str, Any], summary: str, *, complete: bool = False) -> WorkflowOutcome:
        with self.database.session() as db:
            item = self._get_in_session(db, workflow_id)
            completed_step = item.current_step
            specialist = self.STEP_AGENTS.get(completed_step, completed_step)
            artifact = {
                key: value for key, value in context.items()
                if key.endswith("_id") or key.endswith("_ids") or key.endswith("_count")
                or key.endswith("_date")
            }
            handoff_payload = {
                "from_agent": "总控 Agent",
                "to_agent": specialist,
                "step": completed_step,
                "input_summary": self._input_summary(item, completed_step, context),
                "output_summary": summary,
                "artifact": artifact,
                "next_step": next_step,
            }
            db.add(AgentHandoff(
                session_id=item.session_id,
                kind="agent_handoff",
                target_id=workflow_id,
                payload_json=json.dumps(handoff_payload, ensure_ascii=False),
            ))
            item.current_step = next_step
            item.status = status
            item.context_json = json.dumps(context, ensure_ascii=False)
            item.updated_at = datetime.now()
            if complete:
                item.completed_at = datetime.now()
        return WorkflowOutcome(workflow_id, next_step, status, summary, context)

    @classmethod
    def agent_for_step(cls, step: str) -> str:
        return cls.STEP_AGENTS.get(step, step)

    @staticmethod
    def _input_summary(item: AgentWorkflow, step: str, context: dict[str, Any]) -> str:
        resource_count = len(context.get("resource_ids", context.get("indexed_resource_ids", [])))
        return (
            f"步骤：{AgentWorkflowService.STEP_LABELS.get(step, step)}；"
            f"课程：#{item.course_id}；资料数：{resource_count}；"
            f"请求：{item.request[:160]}"
        )

    def _fail(self, workflow_id: int, message: str) -> None:
        with self.database.session() as db:
            item = self._get_in_session(db, workflow_id)
            item.status = "failed"
            item.error_message = message
            item.updated_at = datetime.now()

    @staticmethod
    def _event(progress: StepProgress | None, name: str, status: str, detail: str) -> None:
        if progress is not None:
            progress(name, status, detail)

    @staticmethod
    def _context(item: AgentWorkflow) -> dict[str, Any]:
        value = json.loads(item.context_json or "{}")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _get_in_session(db, workflow_id: int) -> AgentWorkflow:
        item = db.get(AgentWorkflow, workflow_id)
        if item is None:
            raise ValueError("工作流不存在")
        return item
