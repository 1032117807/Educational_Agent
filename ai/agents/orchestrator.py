from __future__ import annotations

from typing import Any, Callable

from ai.agents.specialists import (
    LearningPlanSpecialist,
    QuestionSpecialist,
    ReportSpecialist,
    ResourceAnalysisSpecialist,
    SpecialistResult,
)

Progress = Callable[[str, str, str], None]


class LearningOrchestrator:
    """Deterministic supervisor that can call several specialists in one workflow."""

    def __init__(self, *, database, indexing_factory, extraction_factory,
                 question_factory, report_factory, plan_factory):
        self.resource = ResourceAnalysisSpecialist(indexing_factory, extraction_factory)
        self.questions = QuestionSpecialist(question_factory, database)
        self.plan = LearningPlanSpecialist(plan_factory)
        self.report = ReportSpecialist(report_factory)

    def run(
        self, step: str, context: dict[str, Any], progress: Progress | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpecialistResult:
        if step == "analyze":
            return self.resource.index(
                resource_ids=list(context.get("resource_ids", [])), progress=progress,
                should_cancel=should_cancel,
            )
        if step == "extract":
            return self.resource.extract(
                course_id=int(context["course_id"]),
                resource_ids=list(context.get("indexed_resource_ids", context.get("resource_ids", []))),
                progress=progress, should_cancel=should_cancel,
            )
        if step == "questions":
            return self.questions.run(
                course_id=int(context["course_id"]),
                request=str(context.get("request", "Generate practice questions")),
                resource_ids=list(context.get("indexed_resource_ids", context.get("resource_ids", []))),
                count=int(context.get("question_count", 5)),
                difficulty=int(context.get("difficulty", 3)),
                progress=progress, should_cancel=should_cancel,
            )
        if step == "plan":
            return self.plan.run(
                goal_id=int(context["goal_id"]),
                daily_minutes=int(context.get("daily_minutes", 60)),
                progress=progress,
            )
        if step == "report":
            return self.report.run(
                days=int(context.get("report_days", 7)), progress=progress,
                should_cancel=should_cancel,
            )
        raise ValueError(f"Unsupported specialist step: {step}")
