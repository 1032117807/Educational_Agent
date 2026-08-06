from __future__ import annotations

from app.services.agent_permissions import AgentPermissionService
from app.services.agent_sessions import AgentSessionService
from app.services.report_export import export_report


def test_mcp_policy_is_persisted(tmp_path):
    service = AgentPermissionService(tmp_path / "mcp_policy.json")
    service.save_policy({"fetch_public_url": False})

    assert not service.decide("fetch_public_url", confirmed=False).allowed
    assert service.decide("write_workspace_file", confirmed=False).needs_confirmation


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
