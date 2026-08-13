from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


ExecutionTarget = Literal["cloud_sandbox", "desktop_companion"]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    execution_target: ExecutionTarget
    requires_confirmation: bool = False
    skill_name: str = ""


# This is the shared capability manifest. Client UIs render it; executors are
# responsible for applying the same tool semantics in their own environment.
TOOL_CATALOG = (
    AgentTool("learning_data.read_snapshot", "Read the current workspace learning data", "cloud_sandbox"),
    AgentTool("web.search", "Search public web sources", "cloud_sandbox", skill_name="research"),
    AgentTool("web.fetch", "Fetch an allowed public URL", "cloud_sandbox", skill_name="research"),
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
    targets = {"cloud_sandbox"} if client == "web" else {"cloud_sandbox", "desktop_companion"}
    return [asdict(tool) for tool in TOOL_CATALOG if tool.execution_target in targets]
