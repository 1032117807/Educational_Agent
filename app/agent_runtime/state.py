"""Program-owned Agent status. Models consume it but never maintain it."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agent_runtime.budget import AgentBudget


@dataclass
class AgentRuntimeState:
    goal: str
    current_phase: str = "understanding"
    active_course_id: int | None = None
    active_skill: str = ""
    active_tools: list[str] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)
    tool_call_count: int = 0
    subagent_count: int = 0
    waiting_for_confirmation: bool = False
    unresolved_questions: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    last_tool_latency_ms: int | None = None

    def begin_phase(self, phase: str, *, skill: str = "") -> None:
        self.current_phase = phase
        if skill:
            self.active_skill = skill

    def record_tool_call(self, name: str) -> None:
        self.tool_call_count += 1
        self.active_tools = [name]

    def record_tool_failure(self, name: str) -> None:
        if name not in self.failed_tools:
            self.failed_tools.append(name)

    def record_timing(self, *, elapsed_ms: int, tool_latency_ms: int | None = None) -> None:
        self.elapsed_ms = max(0, int(elapsed_ms))
        self.last_tool_latency_ms = tool_latency_ms

    def add_completed_step(self, step: str) -> None:
        if step not in self.completed_steps:
            self.completed_steps.append(step)

    def add_todo(self, step: str) -> None:
        if step not in self.todo:
            self.todo.append(step)

    def render_status(self, budget: AgentBudget) -> str:
        """Render a bounded, inspectable status bar for the next model call."""
        lines = [
            "<agent_status>",
            f"goal: {self.goal[:300]}",
            f"phase: {self.current_phase}",
            f"active_course: {self.active_course_id if self.active_course_id is not None else 'none'}",
            f"active_skill: {self.active_skill or 'none'}",
            f"active_tools: {', '.join(self.active_tools) or 'none'}",
            f"completed: {', '.join(self.completed_steps[-8:]) or 'none'}",
            f"todo: {', '.join(self.todo[-8:]) or 'none'}",
            f"tool_calls: {self.tool_call_count} / {budget.max_tool_calls}",
            f"rag_searches: {budget.rag_searches} / {budget.max_rag_searches}",
            f"subagents: {self.subagent_count} / {budget.max_subagents}",
            f"failed_tools: {', '.join(self.failed_tools[-5:]) or 'none'}",
            f"elapsed_ms: {self.elapsed_ms}",
            f"last_tool_latency_ms: {self.last_tool_latency_ms if self.last_tool_latency_ms is not None else 'none'}",
            f"waiting_confirmation: {str(self.waiting_for_confirmation).lower()}",
            f"unresolved_questions: {', '.join(self.unresolved_questions[-5:]) or 'none'}",
            "</agent_status>",
        ]
        return "\n".join(lines)
