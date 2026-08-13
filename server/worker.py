from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable

from server.jobs import JobQueue

logger = logging.getLogger(__name__)


def run_once(queue: JobQueue, handlers: dict[str, Callable[[dict[str, object]], dict[str, object]]]) -> bool:
    """Claim and execute one job; return whether work was performed."""
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    job = queue.claim(worker_id=worker_id)
    if job is None:
        return False
    try:
        import json
        payload = json.loads(job.payload or "{}")
        handler = handlers.get(job.job_type)
        if handler is None:
            raise ValueError(f"unsupported job type: {job.job_type}")
        queue.complete(job.id, result=handler(payload))
    except Exception as exc:
        logger.exception("background job failed: %s", job.id)
        queue.fail(job.id, f"{type(exc).__name__}: {exc}")
    return True
