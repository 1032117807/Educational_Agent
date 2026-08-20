from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExecutionTarget = Literal["cloud_sandbox", "desktop_companion"]


@dataclass(frozen=True)
class AgentCapability:
    name: str
    description: str
    execution_target: ExecutionTarget
    requires_confirmation: bool = False
    skill_name: str = ""
    source: str = "local"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    side_effect: str = "none"
    idempotent: bool = True
    timeout_seconds: int = 60
    permission_scopes: tuple[str, ...] = ()
    purpose: str = ""
    use_when: str = ""
    do_not_use_when: str = ""
    result_semantics: str = ""

    def __post_init__(self) -> None:
        if self.source == "local":
            source = "desktop_companion" if self.execution_target == "desktop_companion" else (
                "mcp" if self.name.startswith("mcp.") else "cloud"
            )
            object.__setattr__(self, "source", source)
        if self.side_effect == "none" and self.requires_confirmation:
            object.__setattr__(self, "side_effect", "mutates_state")
        if self.risk_level == "low" and self.requires_confirmation:
            object.__setattr__(self, "risk_level", "medium")
        if not self.permission_scopes and self.skill_name:
            object.__setattr__(self, "permission_scopes", (self.skill_name,))
        if not self.purpose:
            object.__setattr__(self, "purpose", self.description)
        if not self.use_when:
            object.__setattr__(self, "use_when", f"The learner request requires: {self.description}")
        if not self.do_not_use_when:
            object.__setattr__(self, "do_not_use_when", "A more specific capability, existing workspace evidence, or user confirmation is required first.")
        if not self.result_semantics:
            object.__setattr__(self, "result_semantics", "Returns a structured observation with data, summary, error state, and execution metadata.")


# Backwards-compatible name for clients importing the old contract.
AgentTool = AgentCapability


# This is the shared capability manifest. Client UIs render it; executors are
# responsible for applying the same tool semantics in their own environment.
TOOL_CATALOG = (
    AgentTool("tool.search", "Find capability metadata by purpose; use before an unfamiliar tool", "cloud_sandbox"),
    AgentTool("skill.load", "Load the full instructions for one enabled Skill after selecting its metadata", "cloud_sandbox"),
    AgentTool("learning_data.read_snapshot", "Read the current workspace learning data", "cloud_sandbox"),
    # These are the durable Agent actions used by both clients.  Keeping them
    # in the tool catalog makes the confirmation and audit contract explicit
    # instead of hiding data-changing operations behind a client-only button.
    AgentTool("agent.create_goal", "Create a learning goal", "cloud_sandbox", True, "learning-plan"),
    AgentTool("agent.generate_plan", "Generate a learning-plan draft", "cloud_sandbox", True, "learning-plan"),
    AgentTool("agent.generate_report", "Generate a learning report", "cloud_sandbox", True, "report-visualization"),
    AgentTool("agent.start_workflow", "Create a resumable resource-to-report workflow", "cloud_sandbox", True, "learning-workflow"),
    AgentTool("agent.remember", "Save a confirmed learning memory", "cloud_sandbox", True),
    AgentTool("web.search", "Search public web sources", "cloud_sandbox", skill_name="research"),
    AgentTool("web.fetch", "Fetch an allowed public URL", "cloud_sandbox", skill_name="research"),
    AgentTool("mcp.list_workspace_files", "List files in the client workspace", "cloud_sandbox", skill_name="coding"),
    AgentTool("mcp.read_workspace_file", "Read a file in the client workspace", "cloud_sandbox", skill_name="coding"),
    AgentTool("mcp.write_workspace_file", "Write an allowlisted client workspace file", "cloud_sandbox", True, "coding"),
    AgentTool("mcp.search_web", "Search public web sources through Tavily", "cloud_sandbox", skill_name="research"),
    AgentTool("mcp.fetch_public_url", "Fetch an allowed public URL", "cloud_sandbox", skill_name="research"),
    AgentTool("mcp.run_skill_script", "Run an enabled executable Skill", "cloud_sandbox", True),
    AgentTool("skill.resource_analysis", "Run resource analysis skill", "cloud_sandbox", skill_name="resource-analysis"),
    AgentTool("skill.learning_plan", "Run learning plan skill", "cloud_sandbox", skill_name="learning-plan"),
    AgentTool("skill.error_diagnosis", "Run error diagnosis skill", "cloud_sandbox", skill_name="error-diagnosis"),
    AgentTool("skill.report_visualization", "Run report visualization skill", "cloud_sandbox", skill_name="report-visualization"),
    AgentTool("coding.run_python", "Run code in an isolated sandbox", "cloud_sandbox", skill_name="coding"),
    AgentTool("coding.write_workspace", "Write files in the session sandbox workspace", "cloud_sandbox", True, "coding"),
    AgentTool("desktop.list_files", "List files on the linked desktop workspace", "desktop_companion"),
    AgentTool("desktop.read_file", "Read a linked desktop workspace file", "desktop_companion"),
    AgentTool("desktop.write_file", "Write a linked desktop workspace file", "desktop_companion", True),
    AgentTool("desktop.run_code", "Run code through the linked desktop sandbox", "desktop_companion", True, "coding"),
)


def tools_for_client(client: Literal["web", "desktop"]) -> list[dict[str, object]]:
    # Web can dispatch desktop tools only through an authenticated companion;
    # it never executes those operations on the SaaS host itself.
    targets = {"cloud_sandbox", "desktop_companion"}
    return [asdict(tool) for tool in TOOL_CATALOG if tool.execution_target in targets]


def search_capabilities(query: str, *, client: Literal["web", "desktop"] = "web", limit: int = 8) -> list[dict[str, object]]:
    """Return relevant metadata without exposing every tool to the model."""
    terms = {part.casefold() for part in query.split() if part.strip()}
    candidates = []
    for capability in tools_for_client(client):
        haystack = " ".join([
            str(capability["name"]), str(capability["description"]),
            str(capability.get("skill_name", "")), str(capability.get("source", "")),
        ]).casefold()
        score = sum(1 for term in terms if term in haystack)
        if score or not terms:
            candidates.append((score, capability))
    candidates.sort(key=lambda item: (-item[0], str(item[1]["name"])))
    return [item[1] for item in candidates[:max(1, limit)]]
