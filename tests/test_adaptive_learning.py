from datetime import date, timedelta

from app.services.adaptive_learning import AdaptiveLearningService
from app.services.assessment import QuestionService, ReviewService


def test_adaptive_recommendations_layered_practice_and_confirmable_plan(service):
    course = service.create_course("Calculus", "University", "Math")
    questions = QuestionService(service.database)
    weak = questions.save_knowledge(course.id, "Derivative", mastery=25)
    related = questions.save_knowledge(course.id, "Limits", mastery=75)
    with service.database.session() as session:
        point = session.get(type(weak), weak.id)
        point.related_points_json = f"[{related.id}]"
    wrong = questions.save_question("Derivative meaning?", "Rate", course_id=course.id, knowledge_point_id=weak.id)
    variant = questions.save_question("Derivative at a point?", "Rate", course_id=course.id, knowledge_point_id=weak.id)
    transfer = questions.save_question("Limit connection?", "Rate", course_id=course.id, knowledge_point_id=related.id, difficulty=4)
    practice, _ = questions.create_practice_for_questions([wrong.id])
    questions.submit(practice.id, wrong.id, "wrong")
    questions.finish(practice.id, 20)
    review = ReviewService(service.database).list_items()[0]
    ReviewService(service.database).update_notes(review.id, "concept confusion", "separate limit from derivative")
    with service.database.session() as session:
        item = session.get(type(review), review.id)
        item.next_review = date.today() - timedelta(days=2)

    adaptive = AdaptiveLearningService(service.database)
    recommendations = adaptive.recommendations(course.id)
    assert recommendations[0].knowledge_point_id == weak.id
    assert recommendations[0].layer == "foundation"
    assert recommendations[0].overdue_days == 2
    foundation, chosen = adaptive.create_layered_practice(course.id, "foundation", count=2)
    assert foundation.total >= 1 and chosen[0].knowledge_point_id == weak.id
    transfer_practice, transfer_questions = adaptive.create_error_transfer_practice(wrong.id)
    assert transfer_practice.total == 2
    assert {item.id for item in transfer_questions} == {variant.id, transfer.id}

    draft = adaptive.create_next_week_draft(course.id)
    assert draft.status == "pending" and draft.tasks
    assert adaptive.confirm_draft(draft.id) == len(draft.tasks)
    assert adaptive.confirm_draft(draft.id) == 0
    created = service.list_tasks(date.today(), date.today() + timedelta(days=14))
    assert any(item.source == "adaptive_plan" for item in created)
