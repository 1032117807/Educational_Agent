from pathlib import Path

from app.core.config import AppSettings
from app.database import Database
from app.models import Course
from app.services.research_curation import ResearchCurationService


class FakeModel:
    def with_structured_output(self, _schema, **_kwargs):
        return self

    def invoke(self, _prompt):
        return {
            "relevance_score": 91, "quality_score": 82, "decision": "accept",
            "reason": "Matches the course topic and has usable worked examples.",
            "learning_uses": ["concept review", "practice examples"],
        }


class FakeIndex:
    def __init__(self):
        self.resource_ids: list[int] = []

    def index_resource(self, resource_id: int):
        self.resource_ids.append(resource_id)


def test_research_candidates_are_assessed_then_imported_after_confirmation(tmp_path):
    config = AppSettings(data_dir=tmp_path)
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    with database.session() as session:
        course = Course(name="Calculus", status="active")
        session.add(course)
        session.flush()
        course_id = course.id

    index = FakeIndex()

    def download(_url: str, target: Path) -> None:
        target.with_suffix(".txt").write_text("Derivative rules and examples", encoding="utf-8")

    service = ResearchCurationService(
        database=database, app_settings=config, chat_model=FakeModel(),
        indexing_factory=lambda: index,
        search_client=lambda _query, _limit: [{
            "title": "Derivative examples", "url": "https://example.com/calculus",
            "description": "Worked derivative examples",
        }],
        downloader=download,
    )
    candidates = service.collect(course_id=course_id, query="derivative materials")
    assert candidates[0]["status"] == "pending"

    imported = service.import_candidate(int(candidates[0]["candidate_id"]), confirmed=True)
    assert imported["status"] == "imported"
    assert imported["resource_id"] == index.resource_ids[0]
    database.close()
