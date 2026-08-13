from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models
from app.database import Base
from app.models import (
    Course,
    AuditEvent,
    AICitation,
    AIRun,
    PracticeSession,
    PracticeSessionQuestion,
    Question,
    QuestionAttempt,
    ReviewAttempt,
    ReviewItem,
    StudySession,
    StudyTask,
)
from server.backfill import backfill_legacy_rows
from server.deps import RequestContext, require_org_admin
from fastapi import HTTPException


def test_task_lookup_is_scoped_to_tenant(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'tenant.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        task = StudyTask(tenant_id="tenant-a", title="private", planned_date=date.today(), duration_minutes=10)
        session.add(task)
        session.commit()
        task_id = task.id
    with factory() as session:
        foreign = session.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == "tenant-b"))
        own = session.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == "tenant-a"))
        assert foreign is None
        assert own is not None


def test_question_and_course_keep_same_tenant_scope(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'questions.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="course")
        question = Question(tenant_id="tenant-a", course_id=None, prompt="p", answer="a")
        session.add_all([course, question])
        session.commit()
        question.course_id = course.id
        session.commit()
        foreign_questions = session.scalars(select(Question).where(Question.tenant_id == "tenant-b")).all()
        own_questions = session.scalars(select(Question).where(Question.tenant_id == "tenant-a", Question.course_id == course.id)).all()
        assert foreign_questions == []
        assert len(own_questions) == 1


def test_practice_records_are_scoped_to_the_session_tenant(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'practice.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        question = Question(tenant_id="tenant-a", prompt="p", answer="a")
        practice = PracticeSession(tenant_id="tenant-a", total=1)
        session.add_all([question, practice])
        session.flush()
        link = PracticeSessionQuestion(
            tenant_id="tenant-a", session_id=practice.id, question_id=question.id, position=1
        )
        attempt = QuestionAttempt(
            tenant_id="tenant-a", session_id=practice.id, question_id=question.id, response="a", correct=True
        )
        session.add_all([link, attempt])
        session.commit()
        assert session.scalars(
            select(PracticeSession).where(PracticeSession.id == practice.id, PracticeSession.tenant_id == "tenant-b")
        ).all() == []
        assert session.scalars(
            select(PracticeSessionQuestion).where(PracticeSessionQuestion.tenant_id == "tenant-b")
        ).all() == []
        assert session.scalars(
            select(QuestionAttempt).where(QuestionAttempt.tenant_id == "tenant-b")
        ).all() == []


def test_review_and_study_history_are_scoped_to_tenant(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'history.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        review = ReviewItem(tenant_id="tenant-a", title="private review")
        study = StudySession(tenant_id="tenant-a", duration_minutes=30)
        session.add_all([review, study])
        session.flush()
        session.add(ReviewAttempt(
            tenant_id="tenant-a", review_item_id=review.id, result="correct", next_review=date.today()
        ))
        session.commit()
        assert session.scalars(select(ReviewItem).where(ReviewItem.tenant_id == "tenant-b")).all() == []
        assert session.scalars(select(ReviewAttempt).where(ReviewAttempt.tenant_id == "tenant-b")).all() == []
        assert session.scalars(select(StudySession).where(StudySession.tenant_id == "tenant-b")).all() == []


def test_dashboard_aggregations_can_be_limited_to_a_tenant(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'dashboard.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        today = datetime.now()
        own_task = StudyTask(tenant_id="tenant-a", title="own", planned_date=today.date(), duration_minutes=20)
        foreign_task = StudyTask(tenant_id="tenant-b", title="foreign", planned_date=today.date(), duration_minutes=90)
        own_study = StudySession(tenant_id="tenant-a", started_at=today, duration_minutes=20)
        foreign_study = StudySession(tenant_id="tenant-b", started_at=today, duration_minutes=90)
        session.add_all([own_task, foreign_task, own_study, foreign_study])
        session.commit()
        own_minutes = session.scalar(select(StudySession.duration_minutes).where(
            StudySession.tenant_id == "tenant-a", StudySession.started_at >= datetime.combine(today.date(), datetime.min.time())
        ))
        foreign_tasks = session.scalars(select(StudyTask).where(StudyTask.tenant_id == "tenant-b")).all()
        assert own_minutes == 20
        assert len(foreign_tasks) == 1


def test_audit_events_are_scoped_to_tenant(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        session.add_all([
            AuditEvent(tenant_id="tenant-a", user_id="user-a", action="task.create", target_type="study_task", target_id="1"),
            AuditEvent(tenant_id="tenant-b", user_id="user-b", action="task.create", target_type="study_task", target_id="2"),
        ])
        session.commit()
        events = session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == "tenant-a")).all()
        assert len(events) == 1
        assert events[0].target_id == "1"


def test_legacy_backfill_is_dry_run_and_idempotent(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'backfill.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        session.add_all([
            Course(name="legacy"),
            Course(tenant_id="tenant-existing", name="already scoped"),
        ])
        session.commit()
    tenant = "12345678-1234-5678-1234-567812345678"
    dry = backfill_legacy_rows(engine, tenant_id=tenant)
    assert dry.applied is False
    assert dry.pending_rows["courses"] == 1
    with factory() as session:
        assert session.scalar(select(Course).where(Course.tenant_id.is_(None))).name == "legacy"
    applied = backfill_legacy_rows(engine, tenant_id=tenant, apply=True)
    assert applied.applied is True
    assert applied.changed_rows == 1
    second = backfill_legacy_rows(engine, tenant_id=tenant, apply=True)
    assert second.changed_rows == 0
    with factory() as session:
        rows = session.scalars(select(Course).order_by(Course.id)).all()
        assert [row.tenant_id for row in rows] == [tenant, "tenant-existing"]


def test_organization_admin_guard_rejects_regular_members() -> None:
    try:
        require_org_admin(RequestContext(user_id="u", tenant_id="t", role="member"))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("regular members must not manage organization membership")
    assert require_org_admin(RequestContext(user_id="u", tenant_id="t", role="admin")).role == "admin"


def test_member_lifecycle_rules_protect_self_and_owner() -> None:
    from app.models import OrganizationMember
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        session.add_all([
            OrganizationMember(organization_id="tenant-a", user_id="owner", role="owner"),
            OrganizationMember(organization_id="tenant-a", user_id="member", role="member"),
        ])
        session.commit()
        owner = session.scalar(select(OrganizationMember).where(
            OrganizationMember.organization_id == "tenant-a", OrganizationMember.user_id == "owner"
        ))
        assert owner is not None and owner.role == "owner"
        assert session.scalar(select(OrganizationMember).where(
            OrganizationMember.organization_id == "tenant-a", OrganizationMember.user_id == "member"
        )) is not None


def test_ai_run_and_citations_are_scoped_to_tenant(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'ai-run.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        run = AIRun(
            tenant_id="tenant-a", run_uuid="run-a", feature="document_qa_retrieval", status="completed",
            provider="pgvector", model_name="embedding", prompt_version="v1",
        )
        session.add(run)
        session.flush()
        session.add(AICitation(tenant_id="tenant-a", ai_run_id=run.id, chunk_id=1, citation_number=1))
        session.commit()
        assert session.scalar(select(AIRun).where(AIRun.id == run.id, AIRun.tenant_id == "tenant-b")) is None
        assert session.scalars(select(AICitation).where(AICitation.tenant_id == "tenant-b")).all() == []
