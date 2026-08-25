from app.agent_runtime import search_capabilities, tools_for_client


def test_web_catalog_includes_desktop_tools_as_companion_dispatched_capabilities() -> None:
    tools = tools_for_client("web")
    assert tools
    assert any(item["name"] == "coding.run_python" for item in tools)
    assert any(item["name"] == "coding.run_workspace_python" for item in tools)
    assert any(item["name"] == "coding.delete_workspace" for item in tools)
    assert any(item["name"] == "desktop.read_file" and item["execution_target"] == "desktop_companion" for item in tools)
    names = {str(item["name"]) for item in tools}
    assert {
        "agent.create_goal", "agent.generate_plan", "agent.generate_report",
        "agent.start_workflow", "agent.remember",
    } <= names
    assert all(
        item["requires_confirmation"]
        for item in tools if str(item["name"]).startswith("agent.")
    )


def test_desktop_catalog_includes_companion_tools() -> None:
    assert any(item["execution_target"] == "desktop_companion" for item in tools_for_client("desktop"))


def test_capability_metadata_contains_execution_and_risk_contract() -> None:
    report = next(item for item in tools_for_client("web") if item["name"] == "agent.generate_report")

    assert report["source"] == "cloud"
    assert report["side_effect"] == "mutates_state"
    assert report["risk_level"] == "medium"
    assert report["idempotent"] is True
    assert "skill_name" in report
    assert "permission_scopes" in report
    assert report["purpose"]
    assert report["use_when"]
    assert report["do_not_use_when"]
    assert report["result_semantics"]


def test_tool_search_returns_relevant_metadata_only() -> None:
    results = search_capabilities("write workspace", client="web")

    assert results
    assert results[0]["name"] in {"coding.write_workspace", "mcp.write_workspace_file", "desktop.write_file"}
    assert all("description" in item and "input_schema" in item for item in results)


def test_catalog_exposes_progressive_disclosure_tools() -> None:
    names = {str(item["name"]) for item in tools_for_client("web")}

    assert {"tool.search", "skill.load"} <= names
