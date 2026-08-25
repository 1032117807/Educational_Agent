from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, future=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        # 轻量内置迁移：保证早期版本数据库升级时不丢失用户数据。
        migrations = {
            "courses": {
                "grade_level": "VARCHAR(40) NOT NULL DEFAULT ''",
                "exam_type": "VARCHAR(60) NOT NULL DEFAULT ''",
                "textbook_version": "VARCHAR(80) NOT NULL DEFAULT ''",
                "color_tag": "VARCHAR(20) NOT NULL DEFAULT '#155EEF'",
                "source": "VARCHAR(20) NOT NULL DEFAULT 'user'",
                "vector_id": "VARCHAR(100)",
                "embedding_model": "VARCHAR(160) NOT NULL DEFAULT ''",
            },
            "study_tasks": {
                "scheduled_time": "VARCHAR(5) NOT NULL DEFAULT ''",
                "note": "TEXT NOT NULL DEFAULT ''",
                "source": "VARCHAR(20) NOT NULL DEFAULT 'user'",
                "recurrence_key": "VARCHAR(80) NOT NULL DEFAULT ''",
                "knowledge_point_id": "INTEGER",
                "status": "VARCHAR(20) NOT NULL DEFAULT 'planned'",
                "started_at": "DATETIME",
            },
            "questions": {
                "explanation": "TEXT NOT NULL DEFAULT ''",
                "tags": "VARCHAR(300) NOT NULL DEFAULT ''",
                "options": "TEXT NOT NULL DEFAULT ''",
                "knowledge_point_id": "INTEGER",
                "source": "VARCHAR(20) NOT NULL DEFAULT 'user'",
            },
                "knowledge_points": {
                "category": "VARCHAR(30) NOT NULL DEFAULT '概念'",
                "definition": "TEXT NOT NULL DEFAULT ''",
                "formula": "TEXT NOT NULL DEFAULT ''",
                "prerequisites_json": "TEXT NOT NULL DEFAULT '[]'",
                "related_points_json": "TEXT NOT NULL DEFAULT '[]'",
                "common_mistakes_json": "TEXT NOT NULL DEFAULT '[]'",
                "difficulty": "INTEGER NOT NULL DEFAULT 3",
                "importance": "INTEGER NOT NULL DEFAULT 3",
                "confidence": "FLOAT NOT NULL DEFAULT 0",
                "source": "VARCHAR(20) NOT NULL DEFAULT 'user'",
                "vector_id": "VARCHAR(100)",
                "embedding_model": "VARCHAR(160) NOT NULL DEFAULT ''",
                "practice_count": "INTEGER NOT NULL DEFAULT 0",
                "correct_count": "INTEGER NOT NULL DEFAULT 0",
                "wrong_count": "INTEGER NOT NULL DEFAULT 0",
                "last_studied_at": "DATETIME",
                "next_review_at": "DATETIME",
            },
            "knowledge_point_drafts": {
                "tenant_id": "VARCHAR(36)",
                "category": "VARCHAR(30) NOT NULL DEFAULT '概念'",
                "difficulty": "INTEGER NOT NULL DEFAULT 3",
                "confidence": "FLOAT NOT NULL DEFAULT 0",
            },
            "question_drafts": {
                "tenant_id": "VARCHAR(36)",
            },
            "review_items": {
                "source": "VARCHAR(20) NOT NULL DEFAULT 'user'",
                "error_reason": "VARCHAR(300) NOT NULL DEFAULT ''",
                "ai_analysis": "TEXT NOT NULL DEFAULT ''",
                "created_at": "DATETIME",
                "last_reviewed_at": "DATETIME",
            },
            "resource_files": {
                "original_name": "VARCHAR(255) NOT NULL DEFAULT ''",
                "source_path": "VARCHAR(1000) NOT NULL DEFAULT ''",
                "tags": "VARCHAR(500) NOT NULL DEFAULT ''",
            },
            "background_jobs": {"payload": "TEXT NOT NULL DEFAULT ''"},
        }
        with self.engine.begin() as connection:
            for table, columns in migrations.items():
                existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
                for column, definition in columns.items():
                    if column not in existing:
                        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self) -> None:
        """Release pooled SQLite handles before shutdown or file maintenance."""
        self.engine.dispose()

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
