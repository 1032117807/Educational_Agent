"""Generic adapter for trusted, project-bundled Skill scripts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class SkillScriptRunner:
    """Run a manifest-declared Skill script with JSON input and JSON output."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir or Path(__file__).resolve().parents[2] / "skills"

    def run(self, skill_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        skill_dir = (self.skills_dir / skill_name).resolve()
        if self.skills_dir.resolve() not in skill_dir.parents:
            raise PermissionError("Skill path is outside the allowed skills directory")
        manifest_path = skill_dir / "skill.json"
        if not manifest_path.is_file():
            raise ValueError("Skill manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entrypoint = manifest.get("entrypoint")
        if not isinstance(entrypoint, str) or not entrypoint.endswith(".py"):
            raise ValueError("Skill manifest must declare a Python entrypoint")
        script = (skill_dir / entrypoint).resolve()
        if skill_dir not in script.parents or not script.is_file() or script.is_symlink():
            raise PermissionError("Skill entrypoint is invalid")
        result = subprocess.run(
            [sys.executable, "-I", str(script)],
            input=json.dumps(arguments, ensure_ascii=False, default=str),
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:] or "Skill script failed")
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Skill script did not return JSON") from exc
        if not isinstance(output, dict):
            raise ValueError("Skill script must return a JSON object")
        return output
