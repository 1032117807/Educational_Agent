from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    BackgroundJob, Course, CourseNote, DocumentChunk, KnowledgePoint, KnowledgePointDraft, LearningEvent, QuestionDraft,
    KnowledgePointDraftCitation, Question, QuestionAttempt, ResourceFile,
    QuestionDraftCitation, ReviewItem, StudyGoal, StudyTask,
)
from server.deps import RequestContext
from server.routers import (
    PracticeRecommendationRequest,
    PracticeAttemptRequest,
    PracticeStartRequest,
    TaskActionRequest,
    TaskUpdateRequest,
    QuestionRequest,
    act_on_task,
    course_workspace,
    create_question,
    learning_analytics,
    list_mistakes,
    list_reminders,
    list_questions,
    list_knowledge_drafts,
    list_question_drafts,
    recommend_practice,
    KnowledgeDraftReviewRequest,
    review_knowledge_draft,
    review_question_draft,
    start_practice_session,
    submit_practice_attempt,
    complete_practice_session,
    QuestionDraftReviewRequest,
    today_learning_center,
    update_task,
    weekly_learning_report,
    AiFeatureRequest,
    queue_ai_feature_job,
    CourseNoteRequest,
    CourseNoteUpdateRequest,
    create_course_note,
    list_course_notes,
    list_knowledge_points,
    update_course_note,
    delete_course_note,
)


def test_learning_center_aggregates_real_records_and_task_actions(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'learning-center.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="English")
        session.add(course)
        session.flush()
        point = KnowledgePoint(tenant_id="tenant-a", course_id=course.id, name="Main idea", mastery=42)
        task = StudyTask(tenant_id="tenant-a", course_id=course.id, title="Reading", planned_date=date.today(), duration_minutes=30)
        question = Question(tenant_id="tenant-a", course_id=course.id, knowledge_point_id=point.id, prompt="p", answer="D")
        session.add_all([task, point])
        session.flush()
        task.knowledge_point_id = point.id
        question.knowledge_point_id = point.id
        session.add(question)
        session.flush()
        review = ReviewItem(tenant_id="tenant-a", question_id=question.id, title="p", next_review=date.today(), wrong_count=2, error_reason="主旨题")
        session.add(review)
        session.flush()
        session.add(QuestionAttempt(tenant_id="tenant-a", session_id=1, question_id=question.id, response="B", correct=False))
        session.commit()

        today = today_learning_center(context, session)
        assert today["summary"]["planned_minutes"] == 30
        assert today["reviews"]["due"] == 1
        assert today["weak_points"][0]["name"] == "Main idea"
        assert today["insight"]["focus_areas"] == ["主旨题"]
        assert today["insight"]["recommended_minutes"] > 0
        assert today["tasks"][0]["course_name"] == "English"
        assert today["tasks"][0]["knowledge_point_name"] == "Main idea"
        started = act_on_task(task.id, TaskActionRequest(action="start"), context, session)
        assert started["status"] == "in_progress"
        updated = update_task(task.id, TaskUpdateRequest(title="Reading adjusted"), context, session)
        assert updated["updated"] == ["title"]
        analytics = learning_analytics(context, session, days=7, course_id=course.id)
        assert analytics["summary"]["questions"] == 1
        assert analytics["summary"]["accuracy"] == 0.0
        all_time = learning_analytics(context, session, days="all", course_id=course.id)
        assert all_time["range"]["days"] == "all"
        assert all_time["summary"]["questions"] == 1
        weekly = weekly_learning_report(context, session, course_id=course.id)
        assert weekly["summary"]["tasks_total"] == 1
        assert weekly["weak_points"][0]["name"] == "Main idea"
        recommended = recommend_practice(
            PracticeRecommendationRequest(course_id=course.id, limit=5), context, session
        )
        assert recommended["items"][0]["id"] == question.id
        assert recommended["items"][0]["due"] is True

        workspace = course_workspace(course.id, context, session)
        assert workspace["question_count"] == 1
        assert workspace["recent_tasks"][0]["knowledge_point_name"] == "Main idea"
        assert workspace["resource_count"] == 0
        assert workspace["mistake_count"] == 1
        assert workspace["practice"]["questions"] == 0
        mistakes = list_mistakes(context, session)
        assert mistakes[0]["user_answer"] == "B"
        assert mistakes[0]["knowledge_point"] == "Main idea"

        result = act_on_task(task.id, TaskActionRequest(action="postpone"), context, session)
        assert result["planned_date"] == (date.today() + timedelta(days=1)).isoformat()


def test_course_notes_are_crud_and_tenant_scoped(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'course-notes.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    other_context = RequestContext(user_id="user-b", tenant_id="tenant-b", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="English")
        other_course = Course(tenant_id="tenant-b", name="Other")
        session.add_all([course, other_course])
        session.commit()

        created = create_course_note(course.id, CourseNoteRequest(title="重点", content="Keep the evidence."), context, session)
        assert created["title"] == "重点"
        assert list_course_notes(course.id, context, session)[0]["content"] == "Keep the evidence."
        changed = update_course_note(created["id"], CourseNoteUpdateRequest(content="Review tomorrow."), context, session)
        assert changed["content"] == "Review tomorrow."
        assert list_course_notes(other_course.id, other_context, session) == []
        delete_course_note(created["id"], context, session)
        assert list_course_notes(course.id, context, session) == []


def test_question_api_links_a_question_to_its_knowledge_point(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'question-link.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="English")
        session.add(course)
        session.flush()
        point = KnowledgePoint(tenant_id="tenant-a", course_id=course.id, name="Main idea")
        session.add(point)
        session.commit()

        created = create_question(
            QuestionRequest(
                prompt="Which option states the main idea?",
                answer="D",
                course_id=course.id,
                knowledge_point_id=point.id,
            ),
            context,
            session,
        )

        assert created["knowledge_point_id"] == point.id
        assert list_questions(context, session, course.id)[0]["knowledge_point_id"] == point.id


def test_practice_accepts_order_independent_multiple_choice_answers(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'multiple-choice.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="Chemistry")
        session.add(course)
        session.commit()
        question = create_question(
            QuestionRequest(
                prompt="Choose all noble gases.", answer="A, C", kind="multiple_choice",
                options="A. Helium\nB. Oxygen\nC. Neon", course_id=course.id,
            ),
            context,
            session,
        )
        practice = start_practice_session(
            PracticeStartRequest(question_ids=[question["id"]], course_id=course.id), context, session
        )
        attempt = submit_practice_attempt(
            practice["id"], question["id"], PracticeAttemptRequest(response="C. Neon\nA. Helium"), context, session
        )
        assert attempt["correct"] is True


def test_knowledge_endpoint_exposes_mastery_and_graph_metadata(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'knowledge-view.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="Calculus")
        session.add(course)
        session.flush()
        point = KnowledgePoint(
            tenant_id="tenant-a", course_id=course.id, name="Derivatives", mastery=42,
            definition="Rate of change", prerequisites_json='["Limits"]', related_points_json='["Integrals"]',
        )
        session.add(point)
        session.commit()
        response = list_knowledge_points(context, session, course.id)
        assert response[0]["mastery"] == 42
        assert response[0]["prerequisites"] == ["Limits"]
        assert response[0]["related_points"] == ["Integrals"]


def test_knowledge_extraction_job_is_scoped_to_the_selected_resource(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'resource-extraction-job.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="Physics")
        resource = ResourceFile(
            tenant_id="tenant-a", course_id=None, name="mechanics.pdf", relative_path="mechanics.pdf",
            sha256="e" * 64, size=10,
        )
        session.add(course)
        session.flush()
        resource.course_id = course.id
        session.add(resource)
        session.commit()

        queued = queue_ai_feature_job(
            AiFeatureRequest(
                feature="knowledge_extraction", course_id=course.id,
                resource_ids=[resource.id], request="提取力学知识点",
            ),
            context,
            session,
        )
        job = session.get(BackgroundJob, int(queued["job_id"]))
        assert job is not None
        assert '"resource_ids": [1]' in job.payload


def test_knowledge_drafts_are_tenant_scoped_and_require_review_before_acceptance(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'knowledge-draft.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="English")
        resource = ResourceFile(
            tenant_id="tenant-a", name="notes.pdf", relative_path="notes.pdf", sha256="a" * 64, size=10,
        )
        session.add_all([course, resource])
        session.flush()
        chunk = DocumentChunk(
            tenant_id="tenant-a", document_index_id=1, resource_id=resource.id, course_id=course.id,
            chunk_number=1, content="Main ideas summarize a passage.", content_sha256="b" * 64,
        )
        session.add(chunk)
        session.flush()
        draft = KnowledgePointDraft(
            tenant_id="tenant-a", ai_run_id=1, course_id=course.id, name="Main idea",
            definition="The central message of a passage.", difficulty=2, importance=4, confidence=0.8,
        )
        session.add(draft)
        session.flush()
        session.add(KnowledgePointDraftCitation(draft_id=draft.id, chunk_id=chunk.id, quote_text="Main ideas"))
        session.commit()

        drafts = list_knowledge_drafts(context, session, course.id)
        assert drafts[0]["citations"][0]["source_name"] == "notes.pdf"
        accepted = review_knowledge_draft(
            draft.id, KnowledgeDraftReviewRequest(action="accept", review_note="Reviewed"), context, session
        )
        assert accepted["status"] == "accepted"
        point = session.get(KnowledgePoint, accepted["knowledge_point_id"])
        assert point is not None and point.tenant_id == "tenant-a" and point.source == "ai"


def test_question_drafts_are_tenant_scoped_and_require_review_before_practice(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'question-draft.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="Calculus")
        resource = ResourceFile(tenant_id="tenant-a", name="limits.pdf", relative_path="limits.pdf", sha256="c" * 64, size=12)
        session.add_all([course, resource])
        session.flush()
        chunk = DocumentChunk(
            tenant_id="tenant-a", document_index_id=1, resource_id=resource.id, course_id=course.id,
            chunk_number=1, content="A limit describes the value approached by a function.", content_sha256="d" * 64,
        )
        draft = QuestionDraft(
            tenant_id="tenant-a", ai_run_id=1, course_id=course.id, kind="single_choice",
            prompt="What does a limit describe?", answer="A", explanation="It describes the approached value [1].",
            options_json='["A", "B"]', tags_json='["limits"]', difficulty=2,
        )
        session.add_all([chunk, draft])
        session.flush()
        session.add(QuestionDraftCitation(question_draft_id=draft.id, chunk_id=chunk.id, citation_number=1, quote_text=chunk.content))
        session.commit()

        drafts = list_question_drafts(context, session, course.id)
        assert drafts[0]["citations"][0]["source_name"] == "limits.pdf"
        assert session.scalar(select(Question).where(Question.tenant_id == "tenant-a")) is None
        accepted = review_question_draft(
            draft.id, QuestionDraftReviewRequest(action="accept", review_note="Checked"), context, session
        )
        assert accepted["status"] == "accepted"
        question = session.get(Question, accepted["question_id"])
        assert question is not None and question.tenant_id == "tenant-a" and question.source == "ai"


def test_reminders_are_derived_from_tasks_reviews_and_goals(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'reminders.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="English")
        session.add(course)
        session.flush()
        session.add_all([
            StudyTask(tenant_id="tenant-a", course_id=course.id, title="Fixed study", planned_date=date.today(),
                      scheduled_time="19:00", duration_minutes=20),
            StudyTask(tenant_id="tenant-a", course_id=course.id, title="Overdue study", planned_date=date.today() - timedelta(days=1),
                      duration_minutes=15),
            StudyGoal(tenant_id="tenant-a", course_id=course.id, title="Exam goal", target_date=date.today() + timedelta(days=3), weekly_minutes=120),
            ReviewItem(tenant_id="tenant-a", title="Review item", next_review=date.today(), wrong_count=1),
        ])
        session.commit()
        reminders = list_reminders(context, session)
        types = {item["type"] for item in reminders}
        assert {"fixed", "incomplete", "deadline", "review"} <= types


def test_goal_task_practice_mistake_mastery_today_loop(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'full-learning-loop.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with factory() as session:
        course = Course(tenant_id="tenant-a", name="Calculus")
        session.add(course)
        session.flush()
        goal = StudyGoal(tenant_id="tenant-a", course_id=course.id, title="Pass calculus", target_date=date.today() + timedelta(days=30), weekly_minutes=180)
        task = StudyTask(tenant_id="tenant-a", course_id=course.id, title="Limits practice", planned_date=date.today(), duration_minutes=30)
        point = KnowledgePoint(tenant_id="tenant-a", course_id=course.id, name="Limits", mastery=50)
        session.add_all([goal, task, point])
        session.flush()
        question = create_question(QuestionRequest(
            prompt="What is the limit?", answer="A", kind="single_choice", course_id=course.id,
            knowledge_point_id=point.id, options="A\nB",
        ), context, session)
        practice = start_practice_session(PracticeStartRequest(question_ids=[question["id"]], course_id=course.id), context, session)
        attempt = submit_practice_attempt(
            practice["id"], question["id"], PracticeAttemptRequest(response="B"), context, session
        )
        assert attempt["correct"] is False
        summary = complete_practice_session(practice["id"], context, session)
        assert summary["total"] == 1 and summary["correct"] == 0
        mistake = session.scalar(select(ReviewItem).where(ReviewItem.tenant_id == "tenant-a", ReviewItem.question_id == question["id"]))
        refreshed_point = session.get(KnowledgePoint, point.id)
        assert mistake is not None and mistake.next_review <= date.today() + timedelta(days=1)
        assert refreshed_point.practice_count == 1 and refreshed_point.mastery < 50
        today = today_learning_center(context, session)
        assert today["reviews"]["due"] == 0
        mistake_details = list_mistakes(context, session)[0]
        assert mistake_details["question_id"] == question["id"]
        assert mistake_details["created_at"] is not None and mistake_details["ai_analysis"]
        assert today["tasks"][0]["title"] == "Limits practice"
        completed = act_on_task(task.id, TaskActionRequest(action="complete"), context, session)
        assert completed["completed"] is True
        events = session.scalars(
            select(LearningEvent.event_type).where(LearningEvent.tenant_id == context.tenant_id)
        ).all()
        assert {"question_answered", "study_completed", "task_completed"} <= set(events)
