from types import SimpleNamespace

from ai.retrieval import AgenticRAG, RetrievalQueryPlanner
from app.agent_runtime import AgentBudget


def test_query_planner_expands_ambiguous_message_with_course_and_goal():
    plan = RetrievalQueryPlanner().plan(
        "why is this wrong", current_course="Linear Algebra", current_goal="matrix review", course_id=3,
    )

    assert "Linear Algebra" in plan.primary_query
    assert plan.filters == {"course_id": 3}


def test_agentic_rag_respects_search_budget():
    calls: list[str] = []

    def retrieve(query, **_filters):
        calls.append(query)
        return []

    _, observations = AgenticRAG(retrieve, budget=AgentBudget(max_rag_searches=1)).search("missing evidence")

    assert len(calls) == 1
    assert observations[0].evidence_gap


def test_agentic_rag_stops_after_new_evidence():
    def retrieve(_query, **_filters):
        return [SimpleNamespace(chunk_id=7)]

    hits, observations = AgenticRAG(retrieve).search("find theorem")

    assert [hit.chunk_id for hit in hits] == [7]
    assert len(observations) == 1
