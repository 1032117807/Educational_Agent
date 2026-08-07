from __future__ import annotations

import json
from pathlib import Path
import re


DEFAULT_SKILL_METADATA = {
    "learning-workflow": {
        "display_name": "学习闭环",
        "permissions": ["local.read_learning_data", "local.write_drafts", "human.confirmation"],
    },
    "resource-analysis": {
        "display_name": "资料分析",
        "permissions": ["local.read_learning_data", "local.read_resources"],
    },
    "error-diagnosis": {
        "display_name": "错题诊断",
        "permissions": ["local.read_learning_data", "local.read_attempts"],
    },
    "learning-plan": {
        "display_name": "学习计划",
        "permissions": ["local.read_learning_data", "local.write_drafts", "human.confirmation"],
    },
    "research": {
        "display_name": "网页研究",
        "permissions": ["mcp.search_web", "mcp.fetch_public_url"],
    },
    "coding": {
        "display_name": "代码协作",
        "permissions": ["mcp.list_workspace_files", "mcp.read_workspace_file", "mcp.write_workspace_file", "mcp.run_python_in_sandbox"],
    },
}


class AgentSkillCatalog:
    def __init__(self, root: Path | None = None, state_path: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "skills"
        self.state_path = state_path

    def list_skills(self) -> list[dict[str, object]]:
        saved = self._load_state()
        result: list[dict[str, object]] = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            name = path.parent.name
            text = path.read_text(encoding="utf-8").strip()
            manifest = self._manifest(path.parent)
            metadata = DEFAULT_SKILL_METADATA.get(name, {})
            config = saved.get(name, {})
            result.append({
                "name": name,
                "display_name": metadata.get("display_name", name),
                "version": self._version(text),
                "description": self._description(text),
                "instructions": text[:4000],
                "permissions": list(config.get("permissions", metadata.get("permissions", []))),
                "enabled": bool(config.get("enabled", True)),
                "executable": bool(manifest.get("entrypoint")),
                "entrypoint": str(manifest.get("entrypoint", "")),
            })
        return result

    def descriptions(self) -> list[dict[str, str]]:
        return [
            {"name": str(item["name"]), "instructions": str(item["instructions"]),
             "version": str(item["version"]), "permissions": ", ".join(item["permissions"])}
            for item in self.list_skills() if item["enabled"]
        ]

    def update(self, name: str, *, enabled: bool, permissions: list[str]) -> None:
        if not any(item["name"] == name for item in self.list_skills()):
            raise ValueError(f"未知 Skill：{name}")
        saved = self._load_state()
        saved[name] = {
            "enabled": bool(enabled),
            "permissions": sorted({item.strip() for item in permissions if item.strip()}),
        }
        self._save_state(saved)

    def is_enabled(self, name: str) -> bool:
        return any(item["name"] == name and item["enabled"] for item in self.list_skills())

    def allows_mcp_tool(self, tool_name: str) -> bool:
        scope = f"mcp.{tool_name.removeprefix('mcp.')}"
        return any(
            item["enabled"] and scope in item["permissions"]
            for item in self.list_skills()
        )

    def can_execute(self, name: str) -> bool:
        return any(
            item["name"] == name and item["enabled"] and item["executable"]
            for item in self.list_skills()
        )

    def _load_state(self) -> dict[str, dict]:
        if self.state_path is None or not self.state_path.is_file():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_state(self, state: dict[str, dict]) -> None:
        if self.state_path is None:
            raise ValueError("Skill 状态路径未配置")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _manifest(skill_dir: Path) -> dict:
        path = skill_dir / "skill.json"
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _version(text: str) -> str:
        match = re.search(r"^Version:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        return match.group(1).strip() if match else "1.0.0"

    @staticmethod
    def _description(text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        return next((line for line in lines if line and not line.startswith("#")), "")[:240]
