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


class QuestionService:
    OBJECTIVE = {"单选", "多选", "判断", "填空"}

    def __init__(self, database: Database) -> None:
        self.database = database

    def list_questions(self, search: str = "", kind: str = "") -> list[Question]:
        with self.database.session() as session:
            stmt = select(Question).where(~Question.archived)
            if search:
                stmt = stmt.where(Question.prompt.ilike(f"%{search}%"))
            if kind:
                stmt = stmt.where(Question.kind == kind)
            return list(session.scalars(stmt.order_by(Question.id.desc())))

    def get_question(self, question_id: int) -> Question | None:
        with self.database.session() as session:
            return session.get(Question, question_id)

    def save_question(
        self, prompt: str, answer: str, kind: str = "单选",
        difficulty: int = 3, course_id: int | None = None, question_id: int | None = None,
        options: str = "", explanation: str = "", tags: str = "",
        knowledge_point_id: int | None = None
    ) -> Question:
        if not prompt.strip() or not answer.strip():
            raise ValueError("题干和答案不能为空")
        if kind not in {"单选", "多选", "判断", "填空", "简答"}:
            raise ValueError("不支持的题型")
        with self.database.session() as session:
            item = session.get(Question, question_id) if question_id else Question()
            if not item:
                raise ValueError("题目不存在")
            item.prompt = prompt.strip()
            item.answer = answer.strip()
            item.kind = kind
            item.difficulty = max(1, min(5, difficulty))
            item.course_id = course_id
            item.knowledge_point_id = knowledge_point_id
            item.options = options.strip()
            item.explanation = explanation.strip()
            item.tags = tags.strip()
            session.add(item)
            session.flush()
            return item

    def list_courses(self) -> list[Course]:
        with self.database.session() as session:
            return list(session.scalars(select(Course).where(Course.status == "active").order_by(Course.name)))

    def list_knowledge(self, course_id: int | None = None) -> list[KnowledgePoint]:
        with self.database.session() as session:
            stmt = select(KnowledgePoint)
            if course_id:
                stmt = stmt.where(KnowledgePoint.course_id == course_id)
            return list(session.scalars(stmt.order_by(KnowledgePoint.name)))

    def save_knowledge(
        self, course_id: int, name: str, mastery: int = 0, note: str = "",
        knowledge_id: int | None = None
    ) -> KnowledgePoint:
        if not name.strip():
            raise ValueError("知识点名称不能为空")
        with self.database.session() as session:
            if not session.get(Course, course_id):
                raise ValueError("课程不存在")
            item = session.get(KnowledgePoint, knowledge_id) if knowledge_id else KnowledgePoint()
            if not item:
                raise ValueError("知识点不存在")
            item.course_id = course_id
            item.name = name.strip()
            item.mastery = max(0, min(100, mastery))
            item.note = note.strip()
            session.add(item)
            session.flush()
            return item

    def archive(self, question_id: int) -> None:
        with self.database.session() as session:
            item = session.get(Question, question_id)
            if item:
                item.archived = True

    @staticmethod
    def grade(kind: str, expected: str, response: str) -> bool | None:
        if kind == "简答":
            return None
        normalize = lambda value: value.strip().casefold()
        if kind == "多选":
            split = lambda value: sorted(part.strip().casefold() for part in value.replace("，", ",").split(",") if part.strip())
            return split(expected) == split(response)
        return normalize(expected) == normalize(response)

    def create_practice(
        self, count: int, course_id: int | None = None, kinds: list[str] | None = None,
        difficulty: int | None = None, seed: int | None = None
    ) -> tuple[PracticeSession, list[Question]]:
        with self.database.session() as session:
            stmt = select(Question).where(~Question.archived)
            if course_id:
                stmt = stmt.where(Question.course_id == course_id)
            if kinds:
                stmt = stmt.where(Question.kind.in_(kinds))
            if difficulty:
                stmt = stmt.where(Question.difficulty == difficulty)
            questions = list(session.scalars(stmt))
            rng = random.Random(seed)
            rng.shuffle(questions)
            chosen = questions[:max(1, count)]
            if not chosen:
                raise ValueError("没有符合条件的题目")
            practice = PracticeSession(course_id=course_id, total=len(chosen), seed=seed)
            session.add(practice)
            session.flush()
            for position, question in enumerate(chosen):
                session.add(PracticeSessionQuestion(
                    session_id=practice.id, question_id=question.id, position=position
                ))
            return practice, chosen

    def resume_latest(self) -> tuple[PracticeSession, list[Question]] | None:
        with self.database.session() as session:
            practice = session.scalar(select(PracticeSession).where(
                PracticeSession.status == "running"
            ).order_by(PracticeSession.started_at.desc()))
            if not practice:
                return None
            links = list(session.scalars(select(PracticeSessionQuestion).where(
                PracticeSessionQuestion.session_id == practice.id
            ).order_by(PracticeSessionQuestion.position)))
            questions = [session.get(Question, link.question_id) for link in links]
            return practice, [question for question in questions if question is not None]

    def saved_responses(self, session_id: int) -> dict[int, str]:
        with self.database.session() as session:
            attempts = session.scalars(select(QuestionAttempt).where(QuestionAttempt.session_id == session_id))
            return {item.question_id: item.response for item in attempts}

    def save_draft(self, session_id: int, question_id: int, response: str) -> None:
        with self.database.session() as session:
            attempt = session.scalar(select(QuestionAttempt).where(
                QuestionAttempt.session_id == session_id, QuestionAttempt.question_id == question_id
            ))
            if not attempt:
                attempt = QuestionAttempt(session_id=session_id, question_id=question_id)
            attempt.response = response
            attempt.attempted_at = datetime.now()
            session.add(attempt)

    def toggle_mark(self, session_id: int, question_id: int) -> bool:
        with self.database.session() as session:
            link = session.scalar(select(PracticeSessionQuestion).where(
                PracticeSessionQuestion.session_id == session_id,
                PracticeSessionQuestion.question_id == question_id,
            ))
            if not link:
                raise ValueError("练习题目不存在")
            link.marked = not link.marked
            return link.marked

    def submit(self, session_id: int, question_id: int, response: str, elapsed: int = 0, self_grade: bool | None = None) -> bool | None:
        with self.database.session() as session:
            practice = session.get(PracticeSession, session_id)
            question = session.get(Question, question_id)
            if not practice or not question:
                raise ValueError("练习或题目不存在")
            correct = self_grade if question.kind == "简答" else self.grade(question.kind, question.answer, response)
            attempt = session.scalar(select(QuestionAttempt).where(
                QuestionAttempt.session_id == session_id, QuestionAttempt.question_id == question_id
            ))
            if not attempt:
                attempt = QuestionAttempt(session_id=session_id, question_id=question_id)
            attempt.response = response
            attempt.correct = correct
            attempt.elapsed_seconds = elapsed
            attempt.attempted_at = datetime.now()
            session.add(attempt)
            if correct is False:
                review = session.scalar(select(ReviewItem).where(ReviewItem.question_id == question_id))
                if review:
                    review.wrong_count += 1
                    review.status = "reviewing"
                    review.streak = 0
                    review.next_review = date.today() + timedelta(days=1)
                else:
                    session.add(ReviewItem(
                        question_id=question_id, title=question.prompt[:180],
                        status="new", next_review=date.today() + timedelta(days=1)
                    ))
            if question.knowledge_point_id and correct is not None:
                knowledge = session.get(KnowledgePoint, question.knowledge_point_id)
                if knowledge:
                    target = 100 if correct else 0
                    knowledge.mastery = round(knowledge.mastery * 0.8 + target * 0.2)
            session.flush()
            return correct

    def finish(self, session_id: int, duration_seconds: int) -> PracticeSession:
        with self.database.session() as session:
            practice = session.get(PracticeSession, session_id)
            if not practice:
                raise ValueError("练习不存在")
            attempts = list(session.scalars(select(QuestionAttempt).where(QuestionAttempt.session_id == session_id)))
            practice.correct = sum(1 for item in attempts if item.correct)
            practice.duration_seconds = max(0, duration_seconds)
            practice.finished_at = datetime.now()
            practice.status = "completed"
            session.flush()
            return practice

    def list_sessions(self) -> list[PracticeSession]:
        with self.database.session() as session:
            return list(session.scalars(
                select(PracticeSession).order_by(PracticeSession.started_at.desc())
            ))

    def session_results(self, session_id: int) -> list[dict[str, Any]]:
        with self.database.session() as session:
            attempts = list(session.scalars(select(QuestionAttempt).where(
                QuestionAttempt.session_id == session_id
            ).order_by(QuestionAttempt.id)))
            rows = []
            for attempt in attempts:
                question = session.get(Question, attempt.question_id)
                if question:
                    rows.append({
                        "prompt": question.prompt, "response": attempt.response,
                        "answer": question.answer, "correct": attempt.correct,
                        "explanation": question.explanation,
                    })
            return rows

    def import_json(self, path: Path) -> tuple[int, list[str]]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON 顶层必须是数组")
        count, errors = 0, []
        for row, item in enumerate(data, 1):
            try:
                self.save_question(
                    str(item["prompt"]), str(item["answer"]), str(item.get("kind", "单选")),
                    int(item.get("difficulty", 3)), item.get("course_id"),
                    options=str(item.get("options", "")), explanation=str(item.get("explanation", "")),
                    tags=str(item.get("tags", ""))
                )
                count += 1
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"第 {row} 条：{error}")
        return count, errors

    def import_csv(self, path: Path) -> tuple[int, list[str]]:
        count, errors = 0, []
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            for row_number, item in enumerate(csv.DictReader(stream), 2):
                try:
                    self.save_question(
                        item.get("prompt", ""), item.get("answer", ""),
                        item.get("kind", "单选"), int(item.get("difficulty", 3)),
                        options=item.get("options", ""), explanation=item.get("explanation", ""),
                        tags=item.get("tags", "")
                    )
                    count += 1
                except (TypeError, ValueError) as error:
                    errors.append(f"第 {row_number} 行：{error}")
        return count, errors

    def export_json(self, path: Path) -> int:
        rows = [{
            "id": q.id, "course_id": q.course_id, "kind": q.kind,
            "prompt": q.prompt, "answer": q.answer, "difficulty": q.difficulty,
            "options": q.options, "explanation": q.explanation, "tags": q.tags,
        } for q in self.list_questions()]
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(rows)


class ReviewService:
    INTERVALS = (1, 3, 7, 14, 30)

    def __init__(self, database: Database) -> None:
        self.database = database

    def list_items(self, due_only: bool = False) -> list[ReviewItem]:
        with self.database.session() as session:
            stmt = select(ReviewItem).where(ReviewItem.status != "archived")
            if due_only:
                stmt = stmt.where(ReviewItem.next_review <= date.today(), ReviewItem.status != "mastered")
            return list(session.scalars(stmt.order_by(ReviewItem.next_review)))

    def review(self, item_id: int, result: str) -> ReviewItem:
        if result not in {"correct", "wrong", "mastered", "postpone"}:
            raise ValueError("复习结果无效")
        with self.database.session() as session:
            item = session.get(ReviewItem, item_id)
            if not item:
                raise ValueError("复习项不存在")
            previous = item.streak
            if result == "wrong":
                item.streak = 0
                item.status = "reviewing"
                item.next_review = date.today() + timedelta(days=1)
            elif result == "postpone":
                item.next_review = date.today() + timedelta(days=1)
            elif result == "mastered":
                item.status = "mastered"
                item.next_review = date.today() + timedelta(days=30)
            else:
                item.streak += 1
                interval = self.INTERVALS[min(item.streak - 1, len(self.INTERVALS) - 1)]
                item.next_review = date.today() + timedelta(days=interval)
                item.status = "mastered" if item.streak >= 5 else "reviewing"
            session.add(ReviewAttempt(
                review_item_id=item.id, result=result, previous_streak=previous,
                next_review=item.next_review
            ))
            session.flush()
            return item

    def update_notes(self, item_id: int, error_reason: str, note: str) -> None:
        with self.database.session() as session:
            item = session.get(ReviewItem, item_id)
            if not item:
                raise ValueError("复习项不存在")
            item.error_reason = error_reason.strip()
            item.note = note.strip()

    def history(self, item_id: int) -> list[ReviewAttempt]:
        with self.database.session() as session:
            return list(session.scalars(select(ReviewAttempt).where(
                ReviewAttempt.review_item_id == item_id
            ).order_by(ReviewAttempt.created_at.desc())))


