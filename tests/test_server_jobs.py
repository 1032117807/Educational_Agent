from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models
from app.database import Base
from server.jobs import JobQueue


def test_job_queue_claims_and_completes(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    queue = JobQueue(factory)
    job_id = queue.enqueue(tenant_id="tenant-1", requested_by="user-1", job_type="rag_question", payload={"q": "x"})
    job = queue.claim(worker_id="test")
    assert job is not None and job.id == job_id and job.status == "running"
    queue.complete(job_id, result={"answer": "ok"})
    with factory() as session:
        stored = session.get(type(job), job_id)
        assert stored is not None and stored.status == "completed"
