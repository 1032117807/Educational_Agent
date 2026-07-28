from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import sqlite3
import uuid
import zipfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import func, or_, select

from app.core.config import AppSettings
from app.database import Base, Database
from app.models import (
    AppSetting, BackgroundJob,
    Course,
    KnowledgePoint,
    PracticeSession, PracticeSessionQuestion,
    Question,
    QuestionAttempt,
    ResourceFile,
    ReviewAttempt,
    ReviewItem,
    StudySession,
    StudyTask,
    ToolCallLog,
)
from app.services.assessment import QuestionService
from app.services.analytics import AnalyticsService


class MaintenanceService:
    def __init__(self, database: Database, config: AppSettings) -> None:
        self.database = database
        self.config = config

    def get_setting(self, key: str, default: str = "") -> str:
        with self.database.session() as session:
            item = session.get(AppSetting, key)
            return item.value if item else default

    def set_setting(self, key: str, value: str) -> None:
        with self.database.session() as session:
            item = session.get(AppSetting, key) or AppSetting(key=key)
            item.value = value
            session.add(item)

    def backup(self, destination: Path) -> Path:
        destination = destination.with_suffix(".zip")
        temp = destination.with_suffix(".tmp")
        db_path = self.config.data_dir / "learning.db"
        snapshot = self.config.data_dir / "learning.snapshot.db"
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        workspace_files = [
            path for path in self.config.workspace_dir.rglob("*") if path.is_file()
        ] if self.config.workspace_dir.exists() else []
        manifest = {
            "format": 1, "created_at": datetime.now().isoformat(),
            "database_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "files": [{
                "path": path.relative_to(self.config.workspace_dir).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            } for path in workspace_files],
        }
        try:
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "learning.db")
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                for path in workspace_files:
                    archive.write(path, f"workspace/{path.relative_to(self.config.workspace_dir).as_posix()}")
            temp.replace(destination)
            return destination
        finally:
            snapshot.unlink(missing_ok=True)
            temp.unlink(missing_ok=True)

    def restore(self, archive_path: Path) -> None:
        if not zipfile.is_zipfile(archive_path):
            raise ValueError("不是有效的 ZIP 备份")
        safety_backup = self.backup(self.config.data_dir / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}")
        with tempfile.TemporaryDirectory(dir=self.config.data_dir) as temp_name:
            temp_dir = Path(temp_name)
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                if "learning.db" not in names or "manifest.json" not in names:
                    raise ValueError("备份缺少数据库或 manifest")
                for name in names:
                    candidate = (temp_dir / name).resolve()
                    if temp_dir.resolve() not in candidate.parents and candidate != temp_dir.resolve():
                        raise ValueError("备份包含不安全路径")
                archive.extractall(temp_dir)
            manifest = json.loads((temp_dir / "manifest.json").read_text(encoding="utf-8"))
            source_db = temp_dir / "learning.db"
            actual = hashlib.sha256(source_db.read_bytes()).hexdigest()
            if actual != manifest.get("database_sha256"):
                raise ValueError("数据库哈希校验失败")
            for item in manifest.get("files", []):
                relative = Path(str(item["path"]))
                file_path = (temp_dir / "workspace" / relative).resolve()
                workspace_root = (temp_dir / "workspace").resolve()
                if workspace_root not in file_path.parents:
                    raise ValueError("manifest 包含不安全路径")
                if not file_path.is_file():
                    raise ValueError(f"备份缺少资料：{relative}")
                if hashlib.sha256(file_path.read_bytes()).hexdigest() != item.get("sha256"):
                    raise ValueError(f"资料哈希校验失败：{relative}")
            try:
                workspace_stash = temp_dir / "current-workspace"
                workspace_stash.mkdir()
                for child in list(self.config.workspace_dir.iterdir()):
                    shutil.move(child, workspace_stash / child.name)
                source = sqlite3.connect(source_db)
                target = sqlite3.connect(self.config.data_dir / "learning.db")
                source.backup(target)
                source.close()
                target.close()
                restored_workspace = temp_dir / "workspace"
                if restored_workspace.exists():
                    for path in restored_workspace.rglob("*"):
                        if path.is_file():
                            destination = self.config.workspace_dir / path.relative_to(restored_workspace)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(path, destination)
            except Exception:
                # 数据库恢复失败时，从安全备份恢复当前状态。
                with zipfile.ZipFile(safety_backup) as backup:
                    rollback_db = temp_dir / "rollback.db"
                    rollback_db.write_bytes(backup.read("learning.db"))
                source = sqlite3.connect(rollback_db)
                target = sqlite3.connect(self.config.data_dir / "learning.db")
                source.backup(target)
                source.close()
                target.close()
                for child in list(self.config.workspace_dir.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                if "workspace_stash" in locals():
                    for child in workspace_stash.iterdir():
                        shutil.move(child, self.config.workspace_dir / child.name)
                raise

    def database_info(self) -> dict[str, Any]:
        db_path = self.config.data_dir / "learning.db"
        files = [path for path in self.config.workspace_dir.rglob("*") if path.is_file()]
        return {
            "database": str(db_path),
            "database_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "workspace": str(self.config.workspace_dir),
            "file_count": len(files),
            "file_bytes": sum(path.stat().st_size for path in files),
        }

    def export_user_data(self, directory: Path) -> dict[str, int]:
        directory.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}
        with self.database.session() as session:
            courses = list(session.scalars(select(Course)))
            course_rows = [{
                "id": item.id, "name": item.name, "description": item.description,
                "education_stage": item.education_stage, "grade_level": item.grade_level,
                "subject": item.subject, "exam_type": item.exam_type,
                "textbook_version": item.textbook_version,
                "target_date": item.target_date.isoformat() if item.target_date else None,
                "target_score": item.target_score, "status": item.status, "progress": item.progress,
            } for item in courses]
            (directory / "courses.json").write_text(
                json.dumps(course_rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            counts["courses"] = len(course_rows)
            tasks = list(session.scalars(select(StudyTask)))
            with (directory / "tasks.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(["id", "title", "date", "duration_minutes", "priority", "completed"])
                writer.writerows([
                    [item.id, item.title, item.planned_date.isoformat(), item.duration_minutes, item.priority, item.completed]
                    for item in tasks
                ])
            counts["tasks"] = len(tasks)
            practices = list(session.scalars(select(PracticeSession)))
            with (directory / "practices.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(["id", "started_at", "total", "correct", "duration_seconds", "status"])
                writer.writerows([
                    [item.id, item.started_at.isoformat(), item.total, item.correct, item.duration_seconds, item.status]
                    for item in practices
                ])
            counts["practices"] = len(practices)
            wrong = list(session.scalars(select(ReviewItem)))
            wrong_rows = [{
                "id": item.id, "question_id": item.question_id, "title": item.title,
                "status": item.status, "wrong_count": item.wrong_count,
                "streak": item.streak, "next_review": item.next_review.isoformat(), "note": item.note,
            } for item in wrong]
            (directory / "wrong_questions.json").write_text(
                json.dumps(wrong_rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            counts["wrong_questions"] = len(wrong_rows)
        QuestionService(self.database).export_json(directory / "questions.json")
        AnalyticsService(self.database).export_csv(
            directory / "analytics.csv", date.today() - timedelta(days=365), date.today()
        )
        return counts

    def integrity_check(self) -> dict[str, Any]:
        with self.database.session() as session:
            database_result = session.connection().exec_driver_sql("PRAGMA quick_check").scalar()
            registered = {
                (self.config.workspace_dir / item.relative_path).resolve()
                for item in session.scalars(select(ResourceFile))
            }
        missing = [str(path) for path in registered if not path.exists()]
        ignored = {self.config.workspace_dir / ".trash"}
        actual = {
            path.resolve() for path in self.config.workspace_dir.rglob("*")
            if path.is_file() and ".trash" not in path.parts
        }
        orphaned = [str(path) for path in actual - registered]
        return {"database": database_result, "missing_files": missing, "orphaned_files": orphaned}

    def vacuum(self) -> None:
        self.database.engine.dispose()
        with self.database.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("VACUUM")

    def reset_all(self, confirmation: str) -> int:
        if confirmation != "RESET":
            raise ValueError("确认文本不正确")
        reset_folder = self.config.workspace_dir / ".trash" / f"reset-{datetime.now():%Y%m%d-%H%M%S}"
        reset_folder.mkdir(parents=True, exist_ok=True)
        for path in list(self.config.workspace_dir.iterdir()):
            if path.name == ".trash":
                continue
            shutil.move(path, reset_folder / path.name)
        deleted = 0
        with self.database.engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            for table in reversed(Base.metadata.sorted_tables):
                result = connection.execute(table.delete())
                deleted += result.rowcount or 0
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        return deleted

    def search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        term = f"%{query}%"
        with self.database.session() as session:
            try:
                connection = session.connection()
                connection.exec_driver_sql(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(kind, item_id UNINDEXED, title)"
                )
                connection.exec_driver_sql("DELETE FROM search_index")
                connection.exec_driver_sql(
                    "INSERT INTO search_index(kind,item_id,title) SELECT '课程',id,name FROM courses WHERE status='active'"
                )
                connection.exec_driver_sql(
                    "INSERT INTO search_index(kind,item_id,title) SELECT '任务',id,title FROM study_tasks"
                )
                connection.exec_driver_sql(
                    "INSERT INTO search_index(kind,item_id,title) SELECT '题目',id,prompt FROM questions WHERE archived=0"
                )
                connection.exec_driver_sql(
                    "INSERT INTO search_index(kind,item_id,title) SELECT '资料',id,name FROM resource_files WHERE trashed=0"
                )
                escaped = '"' + query.replace('"', '""') + '"'
                matches = connection.exec_driver_sql(
                    "SELECT kind,item_id,title FROM search_index WHERE search_index MATCH ? LIMIT ?",
                    (escaped, limit),
                ).fetchall()
                if matches:
                    return [{"type": row[0], "id": row[1], "title": row[2]} for row in matches]
            except Exception:
                # SQLite 未编译 FTS5 时降级到 LIKE。
                session.rollback()
            rows: list[dict[str, Any]] = []
            for item in session.scalars(select(Course).where(Course.name.ilike(term)).limit(limit)):
                rows.append({"type": "课程", "id": item.id, "title": item.name})
            for item in session.scalars(select(StudyTask).where(StudyTask.title.ilike(term)).limit(limit)):
                rows.append({"type": "任务", "id": item.id, "title": item.title})
            for item in session.scalars(select(Question).where(Question.prompt.ilike(term)).limit(limit)):
                rows.append({"type": "题目", "id": item.id, "title": item.prompt[:100]})
            for item in session.scalars(select(ResourceFile).where(ResourceFile.name.ilike(term)).limit(limit)):
                rows.append({"type": "资料", "id": item.id, "title": item.name})
            return rows[:limit]

    def log_tool(self, name: str, arguments: dict[str, Any], callback: Any) -> dict[str, Any]:
        started = perf_counter()
        audit_id = uuid.uuid4().hex
        try:
            result = callback()
            success, summary = True, str(result)[:1000]
            return {"success": True, "result": result, "audit_id": audit_id}
        except Exception as error:
            success, summary = False, str(error)
            return {"success": False, "error": str(error), "audit_id": audit_id}
        finally:
            with self.database.session() as session:
                session.add(ToolCallLog(
                    tool_name=name, arguments=json.dumps(arguments, ensure_ascii=False),
                    success=success, result_summary=summary,
                    elapsed_ms=int((perf_counter() - started) * 1000), audit_id=audit_id
                ))

    def list_tool_logs(self, limit: int = 100) -> list[ToolCallLog]:
        with self.database.session() as session:
            return list(session.scalars(
                select(ToolCallLog).order_by(ToolCallLog.created_at.desc()).limit(limit)
            ))


class JobService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def recover_interrupted(self) -> int:
        with self.database.session() as session:
            jobs = list(session.scalars(select(BackgroundJob).where(BackgroundJob.status == "running")))
            for job in jobs:
                job.status = "interrupted"
                job.finished_at = datetime.now()
            return len(jobs)

    def create(self, job_type: str, detail: str = "") -> BackgroundJob:
        with self.database.session() as session:
            item = BackgroundJob(job_type=job_type, detail=detail, payload=detail)
            session.add(item)
            session.flush()
            return item

    def update(self, job_id: int, status: str, progress: int, detail: str = "", error: str = "") -> None:
        if status not in {"queued", "running", "completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("任务状态无效")
        with self.database.session() as session:
            item = session.get(BackgroundJob, job_id)
            if not item:
                return
            item.status = status
            item.progress = max(0, min(100, progress))
            if detail:
                item.detail = detail
            item.error = error
            if status == "running" and not item.started_at:
                item.started_at = datetime.now()
            if status in {"completed", "failed", "cancelled", "interrupted"}:
                item.finished_at = datetime.now()

    def list(self) -> list[BackgroundJob]:
        with self.database.session() as session:
            return list(session.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at.desc())))

    def get(self, job_id: int) -> BackgroundJob | None:
        with self.database.session() as session:
            return session.get(BackgroundJob, job_id)

    def cancel(self, job_id: int) -> None:
        item = self.get(job_id)
        if item and item.status in {"queued", "running"}:
            self.update(job_id, "cancelled", item.progress, "用户已取消")

    def is_cancelled(self, job_id: int) -> bool:
        item = self.get(job_id)
        return bool(item and item.status == "cancelled")

    def retry(self, job_id: int) -> BackgroundJob:
        with self.database.session() as session:
            item = session.get(BackgroundJob, job_id)
            if not item or item.status not in {"failed", "cancelled", "interrupted"}:
                raise ValueError("只有失败、取消或中断的任务可以重试")
            retry = BackgroundJob(job_type=item.job_type, detail=item.payload, payload=item.payload)
            session.add(retry)
            session.flush()
            return retry

    def clear_history(self) -> int:
        with self.database.session() as session:
            jobs = list(session.scalars(select(BackgroundJob).where(
                BackgroundJob.status.in_(["completed", "failed", "cancelled", "interrupted"])
            )))
            for job in jobs:
                session.delete(job)
            return len(jobs)
