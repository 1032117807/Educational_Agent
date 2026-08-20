from pathlib import Path

from app.services.agent_skills import AgentSkillCatalog
from server.agent_tools import WebAgentToolExecutor


def test_web_executor_searches_capabilities_without_loading_skill_bodies(tmp_path: Path) -> None:
    executor = WebAgentToolExecutor(tenant_id="tenant-test", session_id=17)

    result = executor.execute("tool.search", {"query": "workspace code"})

    assert result["capabilities"]
    assert all("instructions" not in item for item in result["capabilities"])


def test_web_executor_loads_only_the_requested_enabled_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / "coding"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: coding\ndescription: Code safely\nversion: 1.0.0\n---\n# Workflow\nUse tests.",
        encoding="utf-8",
    )
    executor = WebAgentToolExecutor(tenant_id="tenant-test", session_id=18)
    executor.skills_dir = tmp_path

    result = executor.execute("skill.load", {"name": "coding"})

    assert result["skill"] == "coding"
    assert "# Workflow" in result["instructions"]
    assert AgentSkillCatalog(tmp_path).skill_metadata()[0]["description"] == "Code safely"
