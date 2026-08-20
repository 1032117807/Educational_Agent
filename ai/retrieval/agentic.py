"""A bounded, observable Agentic RAG loop; the existing QA path remains fast."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.agent_runtime import AgentBudget
from ai.retrieval.query_planner import RetrievalQueryPlanner


@dataclass(frozen=True)
class RetrievalObservation:
    query: str
    hit_ids: tuple[int, ...]
    new_information: bool
    duplicate_evidence: bool
    evidence_gap: bool


class AgenticRAG:
    def __init__(self, retrieve: Callable[..., list[Any]], *, budget: AgentBudget | None = None) -> None:
        self.retrieve = retrieve
        self.budget = budget or AgentBudget()
        self.planner = RetrievalQueryPlanner()

    def search(self, message: str, **filters: object) -> tuple[list[Any], list[RetrievalObservation]]:
        course_id = filters.get("course_id") if isinstance(filters.get("course_id"), int) else None
        plan = self.planner.plan(message, course_id=course_id)
        all_hits: list[Any] = []
        seen: set[int] = set()
        observations: list[RetrievalObservation] = []
        previous_ids: tuple[int, ...] = ()
        for query in (plan.primary_query, *plan.optional_followups):
            if not self.budget.allow_tool_call("search_knowledge"):
                break
            hits = self.retrieve(query, **filters)
            ids = tuple(int(getattr(hit, "chunk_id", index)) for index, hit in enumerate(hits))
            new_hits = [hit for hit in hits if int(getattr(hit, "chunk_id", -1)) not in seen]
            seen.update(int(getattr(hit, "chunk_id", -1)) for hit in new_hits)
            all_hits.extend(new_hits)
            observation = RetrievalObservation(query, ids, bool(new_hits), ids == previous_ids and bool(ids), not bool(new_hits))
            observations.append(observation)
            if observation.duplicate_evidence or not observation.evidence_gap:
                break
            previous_ids = ids
        return all_hits, observations
