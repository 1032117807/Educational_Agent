"""Unified bounded ReAct loop used by desktop and cloud adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, Callable
from uuid import uuid4

from app.agent_runtime.budget import AgentBudget
from app.agent_runtime.context import ContextBudgetManager
from app.agent_runtime.observations import observe_failure, observe_success
from app.agent_runtime.contracts import tool_requires_confirmation
from app.agent_runtime.state import AgentRuntimeState
from app.agent_runtime.trajectory import AgentTrajectory


@dataclass(frozen=True)
class AgentTurn:
    decision_summary: str = ""
    action: str = "final"
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str = ""


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    status: str
    trajectory: AgentTrajectory
    tool_result_artifacts: dict[str, Any] = field(default_factory=dict)

    def read_tool_result(self, artifact_ref: str) -> Any:
        if artifact_ref not in self.tool_result_artifacts:
            raise KeyError(f"unknown tool result artifact: {artifact_ref}")
        return self.tool_result_artifacts[artifact_ref]


class AgentRuntime:
    def __init__(self, *, model: Callable[[dict[str, Any]], AgentTurn | dict[str, Any]], executor: Callable[[str, dict[str, Any]], Any], budget: AgentBudget | None = None, context_budget: ContextBudgetManager | None = None) -> None:
        self.model = model
        self.executor = executor
        self.budget = budget or AgentBudget()
        self.context_budget = context_budget or ContextBudgetManager(
            max_tokens=self.budget.max_context_tokens,
            max_chars=self.budget.max_context_tokens * 4,
        )

    def run(
        self,
        message: str,
        *,
        base_context: dict[str, Any] | None = None,
        confirmation_granted: bool = False,
    ) -> AgentRunResult:
        state = AgentRuntimeState(goal=message)
        started_at = time.perf_counter()
        trajectory = AgentTrajectory()
        artifacts: dict[str, Any] = {}
        base = dict(base_context or {})
        base["user_message"] = message
        for _ in range(self.budget.max_iterations):
            if not self.budget.allow_iteration():
                break
            context = self.context_budget.build(
                base=base,
                status=state.render_status(self.budget),
                history=trajectory.context_events(),
                observations=trajectory.tool_observations(),
            )
            state.record_timing(elapsed_ms=round((time.perf_counter() - started_at) * 1000))
            raw = self.model(context)
            turn = raw if isinstance(raw, AgentTurn) else AgentTurn(**raw)
            trajectory.add("decision", decision_summary=turn.decision_summary, action=turn.action, tool_name=turn.tool_name)
            if turn.action in {"final", "answer", "chat"}:
                return AgentRunResult(turn.answer, "completed", trajectory, artifacts)
            if turn.action != "tool" or not turn.tool_name:
                return AgentRunResult(turn.answer or "I need more information before continuing.", "needs_input", trajectory, artifacts)
            if not self.budget.allow_tool_call(turn.tool_name):
                trajectory.add("validation", status="budget_exhausted", tool_name=turn.tool_name)
                return AgentRunResult("The Agent execution budget was reached; please refine the request.", "budget_exhausted", trajectory, artifacts)
            if tool_requires_confirmation(turn.tool_name) and not confirmation_granted:
                state.waiting_for_confirmation = True
                trajectory.add("validation", status="confirmation_required", tool_name=turn.tool_name)
                return AgentRunResult("This action requires your confirmation before execution.", "waiting_confirmation", trajectory, artifacts)
            state.record_tool_call(turn.tool_name)
            tool_started_at = time.perf_counter()
            try:
                raw_result = self.executor(turn.tool_name, turn.arguments)
                latency_ms = round((time.perf_counter() - tool_started_at) * 1000)
                if isinstance(raw_result, dict) and "ok" in raw_result:
                    result = dict(raw_result)
                    meta = dict(result.get("meta") or {})
                    meta.setdefault("latency_ms", latency_ms)
                    result["meta"] = meta
                else:
                    result = observe_success(turn.tool_name, raw_result, latency_ms=latency_ms)
                state.record_timing(elapsed_ms=round((time.perf_counter() - started_at) * 1000), tool_latency_ms=latency_ms)
            except Exception as exc:
                latency_ms = round((time.perf_counter() - tool_started_at) * 1000)
                failure = self.budget.record_tool_failure(turn.tool_name, turn.arguments, str(exc))
                result = observe_failure(
                    turn.tool_name, exc, retryable=failure.retry_allowed,
                    suggestion=failure.suggestion, latency_ms=latency_ms,
                )
                state.record_timing(elapsed_ms=round((time.perf_counter() - started_at) * 1000), tool_latency_ms=latency_ms)
                state.record_tool_failure(turn.tool_name)
            result = self._compress_observation(result, artifacts)
            trajectory.add("observation", **result)
            if not result.get("ok", False) and not result.get("error", {}).get("retryable", False):
                return AgentRunResult("The requested tool could not complete. Please provide more information or choose another action.", "needs_input", trajectory, artifacts)
            if result.get("data", {}).get("confirmation_required") if isinstance(result.get("data"), dict) else False:
                state.waiting_for_confirmation = True
                return AgentRunResult("This action requires your confirmation before execution.", "waiting_confirmation", trajectory, artifacts)
        return AgentRunResult("The Agent reached its iteration limit without a validated answer.", "budget_exhausted", trajectory, artifacts)

    def _compress_observation(self, result: dict[str, Any], artifacts: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data")
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        if len(serialized) <= self.budget.max_tool_result_chars:
            return result
        artifact_ref = f"tool-result://{uuid4()}"
        artifacts[artifact_ref] = data
        compact = dict(result)
        compact["data"] = {
            "preview": serialized[:self.budget.max_tool_result_chars],
            "artifact_ref": artifact_ref,
        }
        compact["summary"] = compact.get("summary") or "Large tool result stored as an artifact."
        meta = dict(compact.get("meta") or {})
        meta.update({"truncated": True, "artifact_ref": artifact_ref})
        compact["meta"] = meta
        return compact
