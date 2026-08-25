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


def test_cet_material_search_excludes_unrelated_school_and_programming_results(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("server.agent_tools.tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"title": "CET-6 历年真题 PDF", "url": "https://example.test/cet", "content": "大学英语六级听力和阅读练习"},
                {"title": "七年级英语计划", "url": "https://example.test/middle", "content": "英语学习资料"},
                {"title": "Python 教程", "url": "https://example.test/python", "content": "编程学习资料"},
            ]}

    monkeypatch.setattr("server.agent_tools.requests.post", lambda *args, **kwargs: Response())
    items = WebAgentToolExecutor(tenant_id="tenant-a", session_id=7).search_web("大学英语六级 CET-6 历年真题 PDF 学习资料")

    assert [item["title"] for item in items] == ["CET-6 历年真题 PDF"]
