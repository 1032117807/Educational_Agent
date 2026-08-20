"""Cross-client Agent Runtime contracts.

Desktop and SaaS share tool definitions.  They differ only in the executor
selected for a tool call: the desktop companion or a cloud sandbox.
"""

from app.agent_runtime.catalog import AgentCapability, AgentTool, TOOL_CATALOG, search_capabilities, tools_for_client
from app.agent_runtime.contracts import AGENT_ACTIONS, MUTATING_TOOLS, tool_requires_confirmation
from app.agent_runtime.budget import AgentBudget, ToolFailureObservation
from app.agent_runtime.state import AgentRuntimeState
from app.agent_runtime.observations import ToolObservation, observe_failure, observe_success
from app.agent_runtime.context import ContextBudgetManager
from app.agent_runtime.runtime import AgentRunResult, AgentRuntime, AgentTurn
from app.agent_runtime.trajectory import AgentTrajectory, TrajectoryEvent
from app.agent_runtime.subagents import SubAgentResult, SubAgentRuntime, SubAgentTask

__all__ = [
    "AgentCapability", "AgentTool", "TOOL_CATALOG", "tools_for_client", "search_capabilities",
    "AGENT_ACTIONS", "MUTATING_TOOLS",
    "tool_requires_confirmation", "AgentBudget", "ToolFailureObservation", "AgentRuntimeState",
    "ToolObservation", "observe_failure", "observe_success",
    "ContextBudgetManager", "AgentRuntime", "AgentTurn", "AgentRunResult",
    "AgentTrajectory", "TrajectoryEvent",
    "SubAgentTask", "SubAgentResult", "SubAgentRuntime",
]
