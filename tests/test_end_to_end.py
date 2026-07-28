from __future__ import annotations

from datetime import date, timedelta

from app.core.config import AppSettings
from app.database import Database
from app.services.domain import (
    AnalyticsService,
    MaintenanceService,
    QuestionService,
    ResourceService,
    ReviewService,
)
from app.services.learning import LearningService


def test_complete_local_user_workflow(tmp_path):
    config = AppSettings(data_dir=tmp_path / "fresh-user")
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    learning = LearningService(database)
    resources = ResourceService(database, config)
    questions = QuestionService(database)
    reviews = ReviewService(database)
    analytics = AnalyticsService(database)
    maintenance = MaintenanceService(database, config)

    course = learning.create_course(
        "高等数学", "大学", "数学", "微积分完整复习",
        grade_level="大一", exam_type="期末考试", textbook_version="同济版",
        target_date=date.today() + timedelta(days=60), target_score=90, progress=10,
    )
    notes = tmp_path / "导数笔记.md"
    notes.write_text("# 导数\n导数表示瞬时变化率。", encoding="utf-8")
    resource = resources.import_file(notes, course.id)
    resources.set_metadata(resource.id, course.id, "重点,导数")

    task = learning.create_task(
        "复习导数", 45, "高", date.today(), note="完成第一章"
        , course_id=course.id
    )
    goal = learning.create_goal("期末达到 90 分", date.today() + timedelta(days=60), 420, 90, course.id)
    study = learning.start_study_session(task.id, course.id)
    learning.finish_study_session(study.id, 45, "完成导数定义")
    learning.complete_task(task.id)

    knowledge = questions.save_knowledge(course.id, "导数定义", 40)
    question = questions.save_question(
        "函数在一点的导数表示什么？", "瞬时变化率", "填空", 2, course.id,
        options="", explanation="导数是差商极限。", tags="导数,基础",
        knowledge_point_id=knowledge.id,
    )
    practice, chosen = questions.create_practice(1, course.id, seed=2026)
    assert chosen[0].id == question.id
    questions.submit(practice.id, question.id, "平均变化率")
    result = questions.finish(practice.id, 90)
    assert result.correct == 0
    wrong = reviews.list_items()[0]
    reviews.update_notes(wrong.id, "概念混淆", "区分平均与瞬时变化率")
    reviews.review(wrong.id, "correct")

    summary = analytics.summary(date.today(), date.today(), course.id)
    assert summary["study_minutes"] == 45
    assert summary["tasks_done"] == 1
    assert summary["practice_questions"] == 1
    assert maintenance.search("导数")

    exported = maintenance.export_user_data(tmp_path / "exports")
    assert exported["courses"] == 1 and exported["tasks"] == 1
    backup = maintenance.backup(tmp_path / "complete-backup.zip")
    learning.update_course(course.id, name="临时修改")
    maintenance.restore(backup)
    assert learning.get_course(course.id).name == "高等数学"
    assert resources.content_path(resource.id).read_text(encoding="utf-8").startswith("# 导数")
    assert goal.id in {item.id for item in learning.list_goals()}
