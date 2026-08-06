from __future__ import annotations

from pathlib import Path


class AgentSkillCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "skills"

    def descriptions(self) -> list[dict[str, str]]:
        result = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8").strip()
            result.append({"name": path.parent.name, "instructions": text[:4000]})
        return result
