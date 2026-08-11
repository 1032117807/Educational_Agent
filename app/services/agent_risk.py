"""Conservative, enforceable risk decisions for Agent operations.

The model may describe the user's intent, but it never gets to lower a safety
boundary.  Unknown operations are therefore treated as requiring approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RiskLevel = Literal["auto", "confirm", "deny"]


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    reason: str
    remember_scope: str | None = None

    @property
    def needs_confirmation(self) -> bool:
        return self.level == "confirm"


class AgentRiskService:
    """Classify tool operations with safe defaults before they are executed."""

    _AUTO = {
        "mcp.list_workspace_files": "只读取工作区文件列表。",
        "mcp.read_workspace_file": "只读取已允许的工作区文件。",
        "mcp.run_python_in_sandbox": "仅在无网络、只读沙箱中运行临时代码。",
    }
    _CONFIRM = {
        "mcp.search_web": ("将访问公共网络搜索服务。", "network_read"),
        "mcp.fetch_public_url": ("将访问指定的公共网页。", "network_read"),
    }
    _HIGH_RISK = {
        "mcp.write_workspace_file": "会写入项目工作区文件。",
        "mcp.run_skill_script": "会执行可写入或依赖外部环境的 Skill 脚本。",
    }

    def assess_tool(self, tool_name: str, arguments: dict | None = None) -> RiskAssessment:
        """Return an enforced decision; dangerous argument shapes are denied."""
        arguments = arguments or {}
        if self._has_path_escape(arguments):
            return RiskAssessment("deny", "参数包含越出工作区的路径。")
        if tool_name in self._AUTO:
            return RiskAssessment("auto", self._AUTO[tool_name])
        if tool_name in self._CONFIRM:
            reason, scope = self._CONFIRM[tool_name]
            return RiskAssessment("confirm", reason, scope)
        if tool_name in self._HIGH_RISK:
            # 高风险操作永不允许“本会话记住”。
            return RiskAssessment("confirm", self._HIGH_RISK[tool_name])
        # Codex 可以提出新能力，但未知工具不能被模型自动放行。
        return RiskAssessment("confirm", "操作风险无法可靠判定，需要你的确认。")

    @staticmethod
    def _has_path_escape(arguments: dict) -> bool:
        path_keys = {"path", "relative_path", "filename", "file_path"}

        def contains_escape(value: object, *, is_path: bool = False) -> bool:
            if isinstance(value, str) and is_path:
                normalized = value.replace("\\", "/")
                return "../" in normalized or normalized.startswith("/") or ":/" in normalized
            if isinstance(value, dict):
                return any(
                    contains_escape(item, is_path=key.lower() in path_keys)
                    for key, item in value.items()
                )
            if isinstance(value, (list, tuple)):
                return any(contains_escape(item, is_path=is_path) for item in value)
            return False

        return contains_escape(arguments)
