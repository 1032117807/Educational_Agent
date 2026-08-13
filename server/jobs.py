from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob
from server.tenant_session import set_worker_session


class JobQueue:
    """Database-backed durable queue boundary.

    Redis/Celery can call `claim` and `complete` from a worker process without
    changing the API contract. `FOR UPDATE SKIP LOCKED` prevents two workers
    from processing the same job on PostgreSQL.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def enqueue(self, *, tenant_id: str, requested_by: str, job_type: str, payload: dict[str, object]) -> int:
        with self.session_factory() as session:
            job = BackgroundJob(
                tenant_id=tenant_id,
                requested_by=requested_by,
                job_type=job_type,
                status="queued",
                payload=json.dumps(payload, ensure_ascii=False),
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job.id

    def claim(self, *, worker_id: str) -> BackgroundJob | None:
        with self.session_factory() as session:
            set_worker_session(session)
            statement = (
                select(BackgroundJob)
                .where(BackgroundJob.status == "queued")
                .order_by(BackgroundJob.created_at, BackgroundJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = session.scalar(statement)
            if job is None:
                return None
            job.status = "running"
            job.detail = f"worker={worker_id}"
            job.started_at = datetime.now()
            session.commit()
            session.expunge(job)
            return job

    def complete(self, job_id: int, *, result: dict[str, object] | None = None) -> None:
        self._finish(job_id, status="completed", detail=json.dumps(result or {}, ensure_ascii=False))

    def fail(self, job_id: int, error: str) -> None:
        self._finish(job_id, status="failed", error=error[:4000])

    def _finish(self, job_id: int, *, status: str, detail: str = "", error: str = "") -> None:
        with self.session_factory() as session:
            set_worker_session(session)
            job = session.get(BackgroundJob, job_id)
            if job is None:
                return
            job.status = status
            job.detail = detail
            job.error = error
            job.progress = 100 if status == "completed" else job.progress
            job.finished_at = datetime.now()
            session.commit()
