from __future__ import annotations

import json
import zipfile
from datetime import date

import pytest

from app.core.config import AppSettings
from app.database import Database
from app.services.domain import (
    AnalyticsService,
    JobService,
    MaintenanceService,
    QuestionService,
    ResourceService,
    ReviewService,
)


@pytest.fixture
def domain(tmp_path):
    config = AppSettings(data_dir=tmp_path / "appdata")
    config.ensure_directories()
    database = Database(config.database_url)
    database.create_schema()
    return database, config


def test_resource_import_deduplicate_rename_trash_restore(domain, tmp_path):
    database, config = domain
    service = ResourceService(database, config)
    source = tmp_path / "notes.txt"
    source.write_text("函数与导数", encoding="utf-8")
    item = service.import_file(source)
    assert service.content_path(item.id).read_text(encoding="utf-8") == "函数与导数"
    with pytest.raises(ValueError, match="已存在"):
        service.import_file(source)
    service.rename(item.id, "数学笔记.txt")
    assert service.content_path(item.id).name == "数学笔记.txt"
    service.move_to_trash(item.id)
    assert service.list_files(trashed=True)[0].id == item.id
    service.restore(item.id)
    assert service.list_files()[0].id == item.id
    service.move_to_trash(item.id)
    service.delete_permanently(item.id)
    assert service.list_files(trashed=True) == []


def test_resource_rejects_path_escape(domain):
    database, config = domain
    service = ResourceService(database, config)
    with pytest.raises(ValueError, match="不存在"):
        service.content_path(999)


def test_directory_import_preserves_structure_and_metadata(domain, tmp_path):
    database, config = domain
    from app.services.learning import LearningService

    course = LearningService(database).create_course("资料课程", "大学", "计算机")
    source = tmp_path / "folder"
    nested = source / "chapter1"
    nested.mkdir(parents=True)
    (nested / "intro.md").write_text("# 入门", encoding="utf-8")
    resources = ResourceService(database, config)
    imported, errors = resources.import_directory(source)
    assert imported == 1 and not errors
    item = resources.list_files()[0]
    assert item.relative_path == "chapter1/intro.md"
    assert item.original_name == "intro.md"
    resources.set_metadata(item.id, course.id, "重点，复习,重点")
    updated = resources.list_files()[0]
    assert updated.course_id == course.id
    assert updated.tags == "重点,复习"
    resources.create_folder("归档/第一章")
    resources.move(item.id, "归档/第一章")
    assert resources.content_path(item.id).relative_to(config.workspace_dir).as_posix() == "归档/第一章/intro.md"


def test_question_grading_practice_and_wrong_review(domain):
    database, _ = domain
    questions = QuestionService(database)
    single = questions.save_question("1+1=?", "2", "单选")
    multiple = questions.save_question("选择偶数", "A,C", "多选")
    assert questions.grade("多选", "A,C", "c,a")
    assert not questions.grade("单选", "2", "3")
    practice, chosen = questions.create_practice(10, seed=42)
    assert {item.id for item in chosen} == {single.id, multiple.id}
    questions.submit(practice.id, single.id, "3")
    questions.submit(practice.id, multiple.id, "C,A")
    result = questions.finish(practice.id, 60)
    assert (result.total, result.correct) == (2, 1)
    due = ReviewService(database).list_items()
    assert len(due) == 1
    assert due[0].question_id == single.id


def test_review_scheduler_records_all_transitions(domain):
    database, _ = domain
    questions = QuestionService(database)
    question = questions.save_question("定义域", "x>0", "填空")
    practice, _ = questions.create_practice(1)
    questions.submit(practice.id, question.id, "x<0")
    reviews = ReviewService(database)
    item = reviews.list_items()[0]
    updated = reviews.review(item.id, "correct")
    assert updated.streak == 1
    assert updated.next_review > date.today()
    reset = reviews.review(item.id, "wrong")
    assert reset.streak == 0


def test_question_json_roundtrip(domain, tmp_path):
    database, _ = domain
    service = QuestionService(database)
    source = tmp_path / "questions.json"
    source.write_text(json.dumps([
        {"prompt": "地球是圆的吗？", "answer": "是", "kind": "判断", "difficulty": 1}
    ], ensure_ascii=False), encoding="utf-8")
    count, errors = service.import_json(source)
    assert count == 1 and not errors
    target = tmp_path / "export.json"
    assert service.export_json(target) == 1
    assert json.loads(target.read_text(encoding="utf-8"))[0]["kind"] == "判断"


def test_csv_import_and_practice_resume(domain, tmp_path):
    database, _ = domain
    service = QuestionService(database)
    source = tmp_path / "questions.csv"
    source.write_text(
        "prompt,answer,kind,difficulty,options,explanation,tags\n"
        "2+2=?,4,单选,1,\"A. 3|B. 4\",基础加法,数学\n",
        encoding="utf-8-sig",
    )
    count, errors = service.import_csv(source)
    assert count == 1 and not errors
    practice, questions = service.create_practice(1, seed=7)
    service.save_draft(practice.id, questions[0].id, "B")
    resumed = service.resume_latest()
    assert resumed is not None
    assert resumed[0].id == practice.id
    assert resumed[1][0].id == questions[0].id
    assert service.saved_responses(practice.id) == {questions[0].id: "B"}


def test_attempt_updates_knowledge_mastery(domain):
    database, _ = domain
    from app.services.learning import LearningService

    course = LearningService(database).create_course("化学", "高中", "化学")
    service = QuestionService(database)
    knowledge = service.save_knowledge(course.id, "氧化还原", 50)
    question = service.save_question(
        "氧化数升高表示？", "氧化", "填空", course_id=course.id,
        knowledge_point_id=knowledge.id
    )
    practice, _ = service.create_practice(1, course_id=course.id)
    service.submit(practice.id, question.id, "氧化")
    assert service.list_knowledge(course.id)[0].mastery == 60


def test_create_practice_for_specific_accepted_questions(domain):
    database, _ = domain
    service = QuestionService(database)
    first = service.save_question("第一题", "A")
    second = service.save_question("第二题", "B")
    practice, questions = service.create_practice_for_questions([second.id, first.id])
    assert practice.total == 2
    assert [question.id for question in questions] == [second.id, first.id]


def test_analytics_empty_and_backup_manifest(domain, tmp_path):
    database, config = domain
    summary = AnalyticsService(database).summary(date.today(), date.today())
    assert summary["accuracy"] == 0
    maintenance = MaintenanceService(database, config)
    archive = maintenance.backup(tmp_path / "backup")
    assert archive.exists()
    with zipfile.ZipFile(archive) as bundle:
        assert {"learning.db", "manifest.json"} <= set(bundle.namelist())
        manifest = json.loads(bundle.read("manifest.json"))
        assert len(manifest["database_sha256"]) == 64


def test_search_finds_real_user_data(domain):
    database, config = domain
    from app.services.learning import LearningService

    LearningService(database).create_course("概率论", "大学", "数学")
    results = MaintenanceService(database, config).search("概率")
    assert results == [{"type": "课程", "id": results[0]["id"], "title": "概率论"}]


def test_backup_restore_roundtrip(domain, tmp_path):
    database, config = domain
    from app.services.learning import LearningService

    learning = LearningService(database)
    course = learning.create_course("恢复前课程", "大学", "数学")
    maintenance = MaintenanceService(database, config)
    backup = maintenance.backup(tmp_path / "roundtrip.zip")
    learning.update_course(course.id, name="已被修改")
    maintenance.restore(backup)
    assert learning.get_course(course.id).name == "恢复前课程"


def test_restore_rejects_corrupted_workspace_file(domain, tmp_path):
    database, config = domain
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    ResourceService(database, config).import_file(source)
    maintenance = MaintenanceService(database, config)
    backup = maintenance.backup(tmp_path / "valid.zip")
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(backup) as original, zipfile.ZipFile(corrupt, "w") as target:
        for name in original.namelist():
            data = b"corrupted" if name == "workspace/source.txt" else original.read(name)
            target.writestr(name, data)
    with pytest.raises(ValueError, match="资料哈希"):
        maintenance.restore(corrupt)


def test_jobs_recover_running_and_clear(domain):
    database, _ = domain
    jobs = JobService(database)
    item = jobs.create("file_import", "notes.txt")
    jobs.update(item.id, "running", 50)
    assert jobs.recover_interrupted() == 1
    assert jobs.list()[0].status == "interrupted"
    assert jobs.clear_history() == 1


def test_job_cancel_and_retry_preserve_payload(domain):
    database, _ = domain
    jobs = JobService(database)
    item = jobs.create("directory_import", "C:/notes")
    jobs.update(item.id, "running", 20, "正在导入")
    jobs.cancel(item.id)
    assert jobs.is_cancelled(item.id)
    retry = jobs.retry(item.id)
    assert retry.status == "queued"
    assert retry.payload == "C:/notes"


def test_directory_import_cooperatively_cancels(domain, tmp_path):
    database, config = domain
    source = tmp_path / "many"
    source.mkdir()
    for index in range(3):
        (source / f"{index}.txt").write_text(str(index), encoding="utf-8")
    service = ResourceService(database, config)
    with pytest.raises(InterruptedError):
        service.import_directory(source, should_cancel=lambda: True)
    assert service.list_files() == []


def test_real_study_session_drives_analytics(domain):
    database, _ = domain
    from app.services.learning import LearningService

    learning = LearningService(database)
    record = learning.start_study_session()
    learning.finish_study_session(record.id, 35, "复习矩阵")
    summary = AnalyticsService(database).summary(date.today(), date.today())
    assert summary["study_minutes"] == 35
    assert learning.dashboard()["stats"]["week_minutes"] == 35


def test_demo_data_can_be_removed_without_user_data(domain):
    database, _ = domain
    from app.services.learning import LearningService

    learning = LearningService(database)
    user = learning.create_course("用户课程", "大学", "物理")
    learning.seed_demo()
    assert len(learning.list_courses()) == 4
    assert learning.clear_demo() >= 5
    assert [course.id for course in learning.list_courses()] == [user.id]


def test_export_and_integrity_check(domain, tmp_path):
    database, config = domain
    from app.services.learning import LearningService

    learning = LearningService(database)
    learning.create_course("导出课程", "高中", "数学")
    learning.create_task("导出任务", 20)
    maintenance = MaintenanceService(database, config)
    output = tmp_path / "export"
    counts = maintenance.export_user_data(output)
    assert counts["courses"] == 1
    assert counts["tasks"] == 1
    assert {
        "courses.json", "tasks.csv", "practices.csv", "wrong_questions.json",
        "questions.json", "analytics.csv",
    } <= {path.name for path in output.iterdir()}
    result = maintenance.integrity_check()
    assert result["database"] == "ok"
    assert not result["missing_files"]


def test_reset_requires_exact_confirmation_and_preserves_files_in_trash(domain, tmp_path):
    database, config = domain
    from app.services.learning import LearningService

    LearningService(database).create_course("待重置", "大学", "数学")
    source = tmp_path / "keep.txt"
    source.write_text("recoverable", encoding="utf-8")
    ResourceService(database, config).import_file(source)
    maintenance = MaintenanceService(database, config)
    with pytest.raises(ValueError, match="确认文本"):
        maintenance.reset_all("reset")
    assert maintenance.reset_all("RESET") >= 2
    assert LearningService(database).list_courses() == []
    assert any(path.name == "keep.txt" for path in (config.workspace_dir / ".trash").rglob("*"))
