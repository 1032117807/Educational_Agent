from server.agent_tools import WebAgentToolExecutor


def test_web_workspace_can_write_list_and_delete_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("server.agent_tools.tempfile.gettempdir", lambda: str(tmp_path))
    executor = WebAgentToolExecutor(tenant_id="tenant-a", session_id=7)

    assert executor.write_workspace_file("demo.py", "print('ok')") == "wrote demo.py"
    assert executor.list_workspace_files(".", 10) == ["demo.py"]
    assert executor.delete_workspace_file("demo.py") == "deleted demo.py"
    assert executor.list_workspace_files(".", 10) == []


def test_web_workspace_refuses_path_escape_and_non_python_execution(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("server.agent_tools.tempfile.gettempdir", lambda: str(tmp_path))
    executor = WebAgentToolExecutor(tenant_id="tenant-a", session_id=7)
    executor.write_workspace_file("note.txt", "hello")

    try:
        executor.delete_workspace_file("../outside.txt")
    except PermissionError:
        pass
    else:
        raise AssertionError("path escape must be rejected")

    try:
        executor.run_workspace_python("note.txt")
    except ValueError as exc:
        assert "Python" in str(exc)
    else:
        raise AssertionError("non-Python file execution must be rejected")
