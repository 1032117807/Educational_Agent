from app.agent_runtime import tools_for_client


def test_web_catalog_excludes_local_desktop_executor_tools() -> None:
    tools = tools_for_client("web")
    assert tools
    assert all(item["execution_target"] == "cloud_sandbox" for item in tools)
    assert any(item["name"] == "coding.run_python" for item in tools)


def test_desktop_catalog_includes_companion_tools() -> None:
    assert any(item["execution_target"] == "desktop_companion" for item in tools_for_client("desktop"))
