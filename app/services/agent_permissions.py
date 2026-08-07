from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


MUTATING_MCP_TOOLS = {"write_workspace_file", "run_python_in_sandbox", "run_skill_script"}

DEFAULT_POLICY = {
    "list_workspace_files": (True, False),
    "read_workspace_file": (True, False),
    "fetch_public_url": (True, False),
    "search_web": (True, False),
    "write_workspace_file": (True, True),
    "run_python_in_sandbox": (True, True),
    "run_skill_script": (True, True),
}


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    needs_confirmation: bool
    reason: str


class AgentPermissionService:
    """Default-deny permissions for capabilities exposed through MCP."""

    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path

    def policy(self) -> dict[str, tuple[bool, bool]]:
        policy = dict(DEFAULT_POLICY)
        if self.policy_path is None or not self.policy_path.is_file():
            return policy
        try:
            saved = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return policy
        for name, value in saved.items():
            if name in policy and isinstance(value, dict):
                # Mutating tools always retain human confirmation.
                policy[name] = (bool(value.get("enabled", policy[name][0])), policy[name][1])
        return policy

    def save_policy(self, enabled_tools: dict[str, bool]) -> None:
        if self.policy_path is None:
            raise ValueError("A policy path is required to save MCP permissions")
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: {"enabled": bool(enabled_tools.get(name, rule[0]))}
                   for name, rule in DEFAULT_POLICY.items()}
        self.policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def decide(self, tool_name: str, *, confirmed: bool) -> PermissionDecision:
        rule = self.policy().get(tool_name)
        if rule is None:
            return PermissionDecision(False, False, "MCP tool is not allowlisted")
        enabled, needs_confirmation = rule
        if not enabled:
            return PermissionDecision(False, False, "MCP tool is disabled")
        if needs_confirmation and not confirmed:
            return PermissionDecision(False, True, "Human confirmation is required")
        return PermissionDecision(True, needs_confirmation, "Allowed by policy")
