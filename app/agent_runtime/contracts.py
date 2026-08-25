"""Cross-client contracts for the unified learning Agent."""
from __future__ import annotations

from typing import Final


AGENT_ACTIONS: Final[tuple[str, ...]] = (
    "chat", "show_status", "create_goal", "generate_plan", "generate_questions",
    "generate_report", "start_workflow", "navigate", "tool", "remember",
    "research_collect", "meta_code",
)

MUTATING_TOOLS: Final[frozenset[str]] = frozenset({
    "mcp.write_workspace_file", "mcp.run_skill_script", "coding.write_workspace",
    "coding.delete_workspace",
    "desktop.write_file", "desktop.run_code",
    "agent.create_goal", "agent.generate_plan", "agent.generate_report",
    "agent.start_workflow", "agent.remember", "agent.meta_code",
})


def tool_requires_confirmation(name: str) -> bool:
    return name in MUTATING_TOOLS or name.endswith(".write_workspace_file")
