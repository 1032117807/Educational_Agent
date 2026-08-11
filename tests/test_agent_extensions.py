from __future__ import annotations

from app.services.agent_permissions import AgentPermissionService
from app.services.agent_sessions import AgentSessionService
from app.services.agent_skills import AgentSkillCatalog
from app.services.agent_memory import AgentMemoryService
from app.services.report_export import export_report


def test_mcp_policy_is_persisted(tmp_path):
    service = AgentPermissionService(tmp_path / "mcp_policy.json")
    service.save_policy({"fetch_public_url": False})

    assert not service.decide("fetch_public_url", confirmed=False).allowed
    assert service.decide("write_workspace_file", confirmed=False).needs_confirmation
    assert service.decide("run_python_in_sandbox", confirmed=False).allowed


def test_report_export_writes_markdown_html_and_docx(tmp_path):
    markdown = "# Study report\n\n## Summary\nA useful result.\n\n- Practice more"

    for suffix in (".md", ".html", ".docx"):
        target = tmp_path / f"report{suffix}"
        export_report(markdown, target)
        assert target.is_file()
        assert target.stat().st_size > 0


def test_agent_session_archive_restore_and_search(tmp_path):
    from app.database import Database

    database = Database(f"sqlite:///{(tmp_path / 'sessions.db').as_posix()}")
    database.create_schema()
    service = AgentSessionService(database)
    session = service.create_session("高等数学复习")
    service.create_session("英语阅读")

    assert [item.title for item in service.search_sessions("数学")] == ["高等数学复习"]
    service.archive(session.id)
    assert all(item.id != session.id for item in service.list_sessions())
    assert [item.id for item in service.search_sessions("数学", include_archived=True)] == [session.id]
    service.restore(session.id)
    assert any(item.id == session.id for item in service.list_sessions())
    database.close()


def test_skill_catalog_persists_enablement_and_permission_scopes(tmp_path):
    skill_root = tmp_path / "skills"
    skill_file = skill_root / "research" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# Research\n\nVersion: 2.1.0\n\nResearch safely.", encoding="utf-8")
    (skill_file.parent / "skill.json").write_text(
        '{"entrypoint": "scripts/run.py"}', encoding="utf-8"
    )
    catalog = AgentSkillCatalog(skill_root, tmp_path / "agent_skills.json")

    assert catalog.list_skills()[0]["version"] == "2.1.0"
    assert catalog.can_execute("research")
    assert catalog.allows_mcp_tool("mcp.search_web")
    catalog.update("research", enabled=False, permissions=["mcp.fetch_public_url"])

    restored = AgentSkillCatalog(skill_root, tmp_path / "agent_skills.json")
    assert not restored.is_enabled("research")
    assert restored.descriptions() == []
    assert not restored.allows_mcp_tool("mcp.fetch_public_url")


def test_agent_memory_requires_confirmation_and_supports_soft_delete(tmp_path):
    from app.database import Database

    database = Database(f"sqlite:///{(tmp_path / 'memory.db').as_posix()}")
    database.create_schema()
    service = AgentMemoryService(database)

    import pytest
    with pytest.raises(PermissionError):
        service.remember(
            scope="long_term", category="learning_pace",
            content={"minutes": 25}, confirmed=False,
        )
    item = service.remember(
        scope="long_term", category="learning_pace",
        content={"minutes": 25}, confirmed=True,
    )
    assert service.context() == [{
        "id": item.id, "scope": "long_term",
        "category": "learning_pace", "content": {"minutes": 25},
    }]
    service.delete_memory(item.id)
    assert service.context() == []
    database.close()
