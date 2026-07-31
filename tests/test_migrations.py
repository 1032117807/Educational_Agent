from __future__ import annotations

import sqlite3

from app.database import Database
from sqlalchemy import inspect

# from app.models import EXPECTED_AI_TABLES  # 不要添加这一行


def test_legacy_database_is_upgraded_without_data_loss(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE courses (id INTEGER PRIMARY KEY, name VARCHAR(120), description TEXT, "
        "education_stage VARCHAR(40), subject VARCHAR(60), target_date DATE, target_score FLOAT, "
        "status VARCHAR(20), progress INTEGER, created_at DATETIME, updated_at DATETIME, last_opened_at DATETIME)"
    )
    connection.execute(
        "INSERT INTO courses VALUES (1,'旧课程','','大学','数学',NULL,NULL,'active',10,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,NULL)"
    )
    connection.commit()
    connection.close()
    database = Database(f"sqlite:///{path.as_posix()}")
    database.create_schema()
    with database.engine.connect() as upgraded:
        columns = {row[1] for row in upgraded.exec_driver_sql("PRAGMA table_info(courses)")}
        assert {"grade_level", "exam_type", "textbook_version", "source"} <= columns
        assert upgraded.exec_driver_sql("SELECT name FROM courses WHERE id=1").scalar() == "旧课程"
        


def test_create_schema_adds_ai_tables_to_existing_database(tmp_path):
    path = tmp_path / "existing.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE courses ("
        "id INTEGER PRIMARY KEY, "
        "name VARCHAR(120), "
        "description TEXT, "
        "education_stage VARCHAR(40), "
        "subject VARCHAR(60), "
        "target_date DATE, "
        "target_score FLOAT, "
        "status VARCHAR(20), "
        "progress INTEGER, "
        "created_at DATETIME, "
        "updated_at DATETIME, "
        "last_opened_at DATETIME"
        ")"
    )
    connection.commit()
    connection.close()

    database = Database(f"sqlite:///{path.as_posix()}")
    database.create_schema()

    tables = set(inspect(database.engine).get_table_names())

    assert {
        "ai_runs",
        "ai_citations",
        "document_indexes",
        "document_chunks",
        "knowledge_point_drafts",
        "question_drafts",
    } <= tables

    database.close()


def test_create_schema_adds_knowledge_vector_columns(tmp_path):
    path = tmp_path / "legacy-knowledge.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE knowledge_points ("
        "id INTEGER PRIMARY KEY, "
        "name VARCHAR(160) NOT NULL"
        ")"
    )
    connection.execute(
        "INSERT INTO knowledge_points (id, name) VALUES (1, '函数极限')"
    )
    connection.commit()
    connection.close()

    database = Database(f"sqlite:///{path.as_posix()}")
    database.create_schema()

    with database.engine.connect() as upgraded:
        columns = {
            row[1]
            for row in upgraded.exec_driver_sql(
                "PRAGMA table_info(knowledge_points)"
            )
        }
        name = upgraded.exec_driver_sql(
            "SELECT name FROM knowledge_points WHERE id=1"
        ).scalar()

    assert {"vector_id", "embedding_model"} <= columns
    assert name == "函数极限"
    database.close()
