from __future__ import annotations

import time
from collections.abc import Callable

from server.config import get_server_settings
from server.db import session_factory
from server.factory import create_ai_feature_handler, create_index_resource_handler, create_learning_agent_handler, create_question_generation_handler, create_rag_retrieval_handler
from server.jobs import JobQueue
from server.worker import run_once


def lazy_handler(factory: Callable[[], Callable[[dict[str, object]], dict[str, object]]]) -> Callable[[dict[str, object]], dict[str, object]]:
    """Avoid loading embedding models until a matching job is actually claimed."""
    handler: Callable[[dict[str, object]], dict[str, object]] | None = None

    def invoke(payload: dict[str, object]) -> dict[str, object]:
        nonlocal handler
        if handler is None:
            handler = factory()
        return handler(payload)

    return invoke


def main() -> int:
    settings = get_server_settings()
    queue = JobQueue(session_factory(settings))
    handlers = {
        "index_resource": lazy_handler(lambda: create_index_resource_handler(settings)),
        "rag_question": lazy_handler(lambda: create_rag_retrieval_handler(settings)),
        "generate_questions": lazy_handler(lambda: create_question_generation_handler(settings)),
        "ai_feature": lazy_handler(lambda: create_ai_feature_handler(settings)),
        "learning_agent": lazy_handler(lambda: create_learning_agent_handler(settings)),
    }
    while True:
        if not run_once(queue, handlers):
            time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
