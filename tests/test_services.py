from datetime import date
from collections import Counter
from datetime import timedelta


def test_course_crud_and_search(service):
    course = service.create_course("线性代数", "大学", "数学")
    assert course.id
    assert [item.name for item in service.list_courses("线性")] == ["线性代数"]
    service.archive_course(course.id)
    assert service.list_courses() == []


def test_task_completion_updates_dashboard(service):
    task = service.create_task("矩阵练习", 35, "高")
    before = service.dashboard()
    assert before["stats"]["today"] == 1
    assert before["stats"]["done"] == 0
    service.complete_task(task.id)
    after = service.dashboard()
    assert after["stats"]["done"] == 1


def test_empty_dashboard_has_stable_shape(service):
    data = service.dashboard()
    assert set(data) == {"stats", "tasks", "courses", "weak", "daily"}
    assert data["stats"]["due"] == 0
    assert len(data["daily"]) == 7


def test_balanced_schedule_respects_daily_limit(service):
    start = date.today()
    schedule = service.distribute_schedule(start, start + timedelta(days=4), 9, 30, 60)
    counts = Counter(schedule)
    assert len(schedule) == 9
    assert max(counts.values()) * 30 <= 60
    assert max(counts.values()) - min(counts.values()) <= 1


def test_balanced_schedule_rejects_insufficient_capacity(service):
    start = date.today()
    import pytest

    with pytest.raises(ValueError, match="不足"):
        service.distribute_schedule(start, start + timedelta(days=1), 10, 30, 60)


def test_recurring_tasks_are_idempotent(service):
    start = date.today()
    first = service.create_recurring_tasks("每日背诵", start, "daily", 5, 20)
    second = service.create_recurring_tasks("每日背诵", start, "daily", 5, 20)
    assert len(first) == 5
    assert second == []
    tasks = service.list_tasks(start, start + timedelta(days=4))
    assert len(tasks) == 5


def test_study_goal_update_and_archive(service):
    goal = service.create_goal("期末目标", date.today() + timedelta(days=30), 300)
    service.update_study_goal(goal.id, "期末数学", goal.target_date, 420, 35)
    updated = service.get_goal(goal.id)
    assert updated.title == "期末数学" and updated.progress == 35
    service.archive_goal(goal.id)
    assert service.list_goals() == []
