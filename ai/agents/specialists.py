from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from ai.chains import QuestionDraftService
from ai.reports import render_learning_report

Progress = Callable[[str, str, str], None]


@dataclass(frozen=True)
class SpecialistResult:
    agent_name: str
    summary: str
    context: dict[str, Any]


class ResourceAnalysisSpecialist:
    name = "resource_analysis_agent"

    def __init__(self, indexing_factory, extraction_factory):
        self.indexing_factory = indexing_factory
        self.extraction_factory = extraction_factory

    def index(
        self, *, resource_ids: list[int], progress: Progress | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpecialistResult:
        pipeline = self.indexing_factory()
        for position, resource_id in enumerate(resource_ids, 1):
            if progress:
                progress(self.name, "running", f"indexing resource {position}/{len(resource_ids)}")
            pipeline.index_resource(
                resource_id,
                progress=lambda value, resource_id=resource_id: progress(
                    self.name, "running", f"resource {resource_id}: {value}%"
                ) if progress else None,
                should_cancel=should_cancel,
            )
        return SpecialistResult(self.name, f"Indexed {len(resource_ids)} resources.", {
            "indexed_resource_ids": resource_ids,
        })

    def extract(
        self, *, course_id: int, resource_ids: list[int], progress: Progress | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpecialistResult:
        result = self.extraction_factory().extract(
            course_id=course_id,
            resource_ids=resource_ids,
            progress=lambda value: progress(
                self.name, "running", f"knowledge extraction: {value}%"
            ) if progress else None,
            should_cancel=should_cancel,
        )
        return SpecialistResult(self.name, f"Generated {result.draft_count} knowledge point drafts.", {
            "knowledge_ai_run_id": result.ai_run_id,
            "knowledge_draft_count": result.draft_count,
        })


class QuestionSpecialist:
    name = "question_agent"

    def __init__(self, question_factory, database):
        self.question_factory = question_factory
        self.database = database

    def run(self, *, course_id: int, request: str, resource_ids: list[int], count: int = 5,
            difficulty: int = 3, progress: Progress | None = None,
            should_cancel: Callable[[], bool] | None = None) -> SpecialistResult:
        if should_cancel and should_cancel():
            raise InterruptedError("Question generation cancelled")
        generated = self.question_factory().generate(
            request, course_id=course_id, count=count, difficulty=difficulty,
            resource_ids=resource_ids,
        )
        drafts = QuestionDraftService(self.database)
        if should_cancel and should_cancel():
            raise InterruptedError("Question generation cancelled")
        question_ids = [drafts.accept(item) for item in generated.draft_ids]
        return SpecialistResult(self.name, f"Generated {len(question_ids)} practice questions.", {
            "question_draft_ids": list(generated.draft_ids), "question_ids": question_ids,
        })


class LearningPlanSpecialist:
    name = "learning_plan_agent"

    def __init__(self, plan_factory):
        self.plan_factory = plan_factory

    def run(self, *, goal_id: int, daily_minutes: int, progress: Progress | None = None) -> SpecialistResult:
        draft_id = self.plan_factory().generate(
            goal_id, start_date=date.today(), daily_minutes=daily_minutes
        )
        return SpecialistResult(self.name, f"Generated learning plan draft {draft_id}.", {
            "plan_draft_id": draft_id,
        })


class ReportSpecialist:
    name = "report_agent"

    def __init__(self, report_factory):
        self.report_factory = report_factory

    def run(
        self, *, days: int = 7, progress: Progress | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpecialistResult:
        if should_cancel and should_cancel():
            raise InterruptedError("Report generation cancelled")
        end_date = date.today()
        start_date = end_date - timedelta(days=days - 1)
        service = self.report_factory()
        report = service.generate(start_date=start_date, end_date=end_date)
        if should_cancel and should_cancel():
            raise InterruptedError("Report generation cancelled")
        saved = service.save_snapshot(report, render_learning_report(report))
        return SpecialistResult(self.name, f"Generated learning report {saved.id}.", {
            "report_snapshot_id": saved.id,
            "report_markdown": saved.markdown,
            "start_date": str(saved.start_date),
            "end_date": str(saved.end_date),
        })
