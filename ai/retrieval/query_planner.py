"""Bounded query planning shared by fast and agentic retrieval paths."""
from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class RetrievalQueryPlan:
    primary_query: str
    keyword_query: str
    filters: dict[str, object] = field(default_factory=dict)
    optional_followups: tuple[str, ...] = ()


class RetrievalQueryPlanner:
    def plan(self, message: str, *, recent_context: str = "", current_course: str = "", current_goal: str = "", course_id: int | None = None) -> RetrievalQueryPlan:
        query = " ".join(message.strip().split())
        context_terms = " ".join(part.strip() for part in (current_course, current_goal) if part.strip())
        primary = " ".join(part for part in (query, context_terms) if part).strip()
        keyword = re.sub(r"[^\w\u4e00-\u9fff ]+", " ", primary, flags=re.UNICODE)
        followups = (query,) if query and recent_context.strip() else ()
        return RetrievalQueryPlan(primary[:2000], " ".join(keyword.split())[:2000], {"course_id": course_id} if course_id is not None else {}, followups)
