"""Small, isolated Sub-Agent runtime for genuinely parallel specialist work."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent_runtime.budget import AgentBudget


@dataclass(frozen=True)
class SubAgentTask:
    agent_type: str
    objective: str
    context: dict[str, Any] = field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ()
    allowed_skills: tuple[str, ...] = ()
    budget: AgentBudget = field(default_factory=AgentBudget)
    output_schema: tuple[str, ...] = ("summary", "evidence", "artifacts", "validation")


@dataclass(frozen=True)
class SubAgentResult:
    agent_name: str
    status: str
    summary: str
    findings: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[str, ...] = ()
    validation: tuple[dict[str, Any], ...] = ()
    missing_information: tuple[str, ...] = ()
    confidence: float = 0.0
    next_recommendation: str = ""


class SubAgentRuntime:
    def __init__(self, runner: Callable[[SubAgentTask, dict[str, Any]], dict[str, Any]], *, max_subagents: int = 4) -> None:
        self.runner = runner
        self.max_subagents = max(1, max_subagents)

    def run(self, tasks: list[SubAgentTask], *, shared_context: dict[str, Any] | None = None) -> list[SubAgentResult]:
        selected = tasks[:self.max_subagents]
        # Callers must opt in to each shared field through `minimal_context`;
        # the main Agent's full history and trajectory never flow here.
        base = dict((shared_context or {}).get("minimal_context", {}))

        def execute(task: SubAgentTask) -> SubAgentResult:
            # Only the task's explicit context crosses the isolation boundary.
            context = {**base, **task.context, "objective": task.objective, "allowed_tools": list(task.allowed_tools), "allowed_skills": list(task.allowed_skills)}
            try:
                raw = self.runner(task, context)
                return SubAgentResult(
                    agent_name=task.agent_type, status=str(raw.get("status", "completed")),
                    summary=str(raw.get("summary", ""))[:4000],
                    findings=tuple(raw.get("findings", ()))[:20], evidence=tuple(raw.get("evidence", ()))[:20],
                    artifacts=tuple(str(item) for item in raw.get("artifacts", ()))[:20],
                    validation=tuple(raw.get("validation", ()))[:20],
                    missing_information=tuple(str(item) for item in raw.get("missing_information", ()))[:20],
                    confidence=max(0.0, min(1.0, float(raw.get("confidence", 0.0)))),
                    next_recommendation=str(raw.get("next_recommendation", ""))[:1000],
                )
            except Exception as exc:
                return SubAgentResult(task.agent_type, "failed", "Sub-Agent failed", validation=({"error": str(exc), "retryable": False},))

        if len(selected) <= 1:
            return [execute(task) for task in selected]
        with ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix="learning-subagent") as pool:
            futures = [pool.submit(execute, task) for task in selected]
            return [future.result() for future in as_completed(futures)]
