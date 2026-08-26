"""LangGraph state machine for adaptive, multi-agent learning loops.

The graph is deliberately provider-agnostic: existing specialist services are
injected as callables, while the serializable state can be stored in the
existing AgentWorkflow context between user sessions.
"""
from __future__ import annotations

from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


class AdaptiveLearningState(TypedDict, total=False):
    course_id: int
    round: int
    max_rounds: int
    mastery_threshold: float
    answers: list[dict[str, Any]]
    weak_points: list[dict[str, Any]]
    next_action: Literal["remediate", "advance", "complete"]
    practice_question_ids: list[int]
    plan_updates: list[dict[str, Any]]
    negotiations: list[dict[str, Any]]
    completed_topics: list[int]


class AdaptiveLearningGraph:
    """Build and run the adaptive loop using injected project specialists."""

    def __init__(
        self,
        *,
        assess: Callable[[AdaptiveLearningState], list[dict[str, Any]]],
        remediate: Callable[[AdaptiveLearningState], dict[str, Any]],
        advance: Callable[[AdaptiveLearningState], dict[str, Any]],
        revise_plan: Callable[[AdaptiveLearningState], dict[str, Any]],
        negotiate: Callable[[AdaptiveLearningState], dict[str, Any]] | None = None,
    ) -> None:
        self.assess = assess
        self.remediate = remediate
        self.advance = advance
        self.revise_plan = revise_plan
        self.negotiate = negotiate or (lambda state: {"decision": state.get("next_action", "advance")})

    def build(self):
        graph = StateGraph(AdaptiveLearningState)
        graph.add_node("assess", self._assess)
        graph.add_node("negotiate", self._negotiate)
        graph.add_node("remediate", self._remediate)
        graph.add_node("advance", self._advance)
        graph.add_node("revise_plan", self._revise_plan)
        graph.add_edge(START, "assess")
        graph.add_edge("assess", "negotiate")
        graph.add_conditional_edges("negotiate", self._route, {"remediate": "remediate", "advance": "advance", "complete": END})
        graph.add_edge("remediate", "revise_plan")
        graph.add_edge("advance", "revise_plan")
        graph.add_conditional_edges("revise_plan", self._continue, {"loop": "assess", "done": END})
        return graph.compile()

    def invoke(self, state: AdaptiveLearningState) -> AdaptiveLearningState:
        state = dict(state)
        state.setdefault("round", 0)
        state.setdefault("max_rounds", 5)
        state.setdefault("mastery_threshold", 70)
        return self.build().invoke(state)

    def _assess(self, state):
        answers = self.assess(state) or state.get("answers", [])
        weak = [item for item in answers if item.get("mastery", 0) < state["mastery_threshold"] or item.get("correct") is False]
        return {"answers": answers, "weak_points": weak, "next_action": "remediate" if weak else "advance"}

    def _negotiate(self, state):
        decision = self.negotiate(state) or {}
        action = decision.get("decision", state.get("next_action", "advance"))
        if not state.get("weak_points") and action == "remediate":
            action = "advance"
        if state.get("round", 0) >= state.get("max_rounds", 5):
            action = "complete"
        return {"negotiations": [*state.get("negotiations", []), decision], "next_action": action}

    def _remediate(self, state):
        result = self.remediate(state) or {}
        return {**result, "round": state.get("round", 0) + 1}

    def _advance(self, state):
        result = self.advance(state) or {}
        return {**result, "round": state.get("round", 0) + 1}

    def _revise_plan(self, state):
        update = self.revise_plan(state) or {}
        return {"plan_updates": [*state.get("plan_updates", []), update]}

    @staticmethod
    def _route(state):
        return state.get("next_action", "advance")

    @staticmethod
    def _continue(state):
        # One invocation represents one learner interaction.  Persist the
        # state after creating the next practice set; the next submission
        # invokes the graph again with fresh answers, avoiding stale-answer
        # loops while retaining cross-session progress in AgentWorkflow.
        return "done"
