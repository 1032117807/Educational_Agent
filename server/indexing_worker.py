from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BackgroundJob, ResourceFile
from server.storage import ObjectStorage
from server.tenant_session import set_session_tenant


def index_resource_from_object_store(
    *,
    payload: dict[str, object],
    session_factory: Callable[[], Session],
    storage: ObjectStorage,
    pipeline_factory: Callable[[Path, str], object],
) -> dict[str, object]:
    """Download an authorized object to an isolated temporary workspace, then index it.

    `pipeline_factory` keeps the current parser/splitter pipeline reusable while
    the SaaS worker controls all object storage access and tenant validation.
    """
    resource_id = int(payload["resource_id"])
    tenant_id = str(payload["tenant_id"])
    with session_factory() as session:
        set_session_tenant(session, tenant_id)
        resource = session.scalar(
            select(ResourceFile).where(
                ResourceFile.id == resource_id,
                ResourceFile.tenant_id == tenant_id,
                ResourceFile.trashed.is_(False),
            )
        )
        if resource is None:
            raise ValueError("resource not found in tenant")
        object_key = resource.relative_path
        filename = Path(resource.name).name
        course_id = resource.course_id
        vocabulary_source = any(term in filename.casefold() for term in ("词汇", "单词", "vocabulary", "wordlist", "word-list"))

    with tempfile.TemporaryDirectory(prefix="learning-index-") as temporary:
        workspace = Path(temporary)
        destination = workspace / filename
        storage.download_to(key=object_key, destination=destination)
        result = pipeline_factory(workspace, tenant_id).index_resource(
            resource_id,
            source_path_override=destination,
        )
    question_job_id = None
    vocabulary_job_id = None
    plan_job_id = None
    follow_up = payload.get("question_follow_up")
    if isinstance(follow_up, dict):
        with session_factory() as session:
            set_session_tenant(session, tenant_id)
            question_job = BackgroundJob(
                tenant_id=tenant_id,
                job_type="generate_questions",
                status="queued",
                payload=json.dumps({
                    "tenant_id": tenant_id, "course_id": course_id,
                    "resource_ids": [resource_id], "request": str(follow_up.get("request") or "根据课程资料生成练习题"),
                    "count": 5, "difficulty": 3, "kinds": ["single_choice", "short_answer"],
                    "auto_practice": True, "auto_accept": True, "goal_id": follow_up.get("goal_id"), "agent_session_id": follow_up.get("session_id"),
                }, ensure_ascii=False),
                detail="queued by question agent after resource indexing",
            )
            session.add(question_job)
            vocabulary_job = BackgroundJob(
                tenant_id=tenant_id,
                job_type="generate_vocabulary",
                status="queued",
                payload=json.dumps({
                    "tenant_id": tenant_id, "course_id": course_id,
                    "count": int(follow_up.get("vocabulary_count", 10)),
                    "request": str(follow_up.get("request") or "从课程资料提取核心词汇"),
                }, ensure_ascii=False),
                detail="queued vocabulary extraction after resource indexing",
            )
            session.add(vocabulary_job)
            session.commit()
            question_job_id = question_job.id
            vocabulary_job_id = vocabulary_job.id
    elif vocabulary_source and course_id is not None:
        with session_factory() as session:
            set_session_tenant(session, tenant_id)
            vocabulary_job = BackgroundJob(
                tenant_id=tenant_id, job_type="generate_vocabulary", status="queued",
                payload=json.dumps({"tenant_id": tenant_id, "course_id": course_id, "count": 30,
                                    "request": f"从词汇资料 {filename} 提取可复习的单词、释义和例句"}, ensure_ascii=False),
                detail="queued because an indexed vocabulary resource was detected",
            )
            session.add(vocabulary_job); session.commit(); vocabulary_job_id = vocabulary_job.id
    return {"resource_id": resource_id, "document_index_id": result.document_index_id, "chunk_count": result.chunk_count, "question_job_id": question_job_id, "vocabulary_job_id": vocabulary_job_id, "plan_job_id": plan_job_id}
