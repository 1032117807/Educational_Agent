from app.agent_runtime import observe_failure, observe_success


def test_tool_observation_success_has_stable_envelope():
    result = observe_success("course.list", [{"id": 1}], summary="one course", source="local")

    assert result["ok"] is True
    assert result["data"] == [{"id": 1}]
    assert result["error"] is None
    assert result["meta"]["source"] == "local"


def test_tool_observation_failure_is_actionable():
    result = observe_failure("web.search", TimeoutError("upstream timeout"), retryable=True, suggestion="retry once")

    assert result["ok"] is False
    assert result["error"]["type"] == "TimeoutError"
    assert result["error"]["retryable"] is True
    assert result["error"]["suggestion"] == "retry once"
