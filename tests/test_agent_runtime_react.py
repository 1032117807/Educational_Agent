from app.agent_runtime import AgentBudget, AgentRuntime, AgentTurn


def test_runtime_reasons_acts_observes_then_answers():
    decisions = iter([
        AgentTurn(decision_summary="Need course data", action="tool", tool_name="course.list"),
        AgentTurn(decision_summary="Data is available", action="final", answer="I found the course."),
    ])
    observed_contexts = []

    def model(context):
        observed_contexts.append(context)
        return next(decisions)

    result = AgentRuntime(model=model, executor=lambda _name, _args: [{"id": 1}]).run("find my course")

    assert result.status == "completed"
    assert result.answer == "I found the course."
    assert [event.event_type for event in result.trajectory.events] == ["decision", "observation", "decision"]
    assert observed_contexts[1]["observations"][0]["ok"] is True
    assert observed_contexts[1]["observations"][0]["meta"]["latency_ms"] is not None


def test_runtime_stops_when_budget_is_exhausted():
    calls = []

    def model(_context):
        return AgentTurn(action="tool", tool_name="web.search", arguments={"q": "same"})

    def executor(name, args):
        calls.append((name, args))
        raise TimeoutError("upstream")

    result = AgentRuntime(
        model=model, executor=executor,
        budget=AgentBudget(max_iterations=8, max_tool_calls=8, max_same_tool_retries=1),
    ).run("search")

    assert result.status == "needs_input"
    assert len(calls) == 2
    assert result.trajectory.tool_observations()[-1]["error"]["retryable"] is False


def test_runtime_waits_for_confirmation_from_executor():
    result = AgentRuntime(
        model=lambda _context: AgentTurn(action="tool", tool_name="agent.create_goal"),
        executor=lambda _name, _args: {"ok": True, "data": {"confirmation_required": True}},
    ).run("create a goal")

    assert result.status == "waiting_confirmation"


def test_runtime_enforces_catalog_confirmation_before_executor_runs():
    calls = []
    result = AgentRuntime(
        model=lambda _context: AgentTurn(action="tool", tool_name="agent.create_goal"),
        executor=lambda name, arguments: calls.append((name, arguments)),
    ).run("create a goal")

    assert result.status == "waiting_confirmation"
    assert calls == []
    assert result.trajectory.events[-1].payload["status"] == "confirmation_required"


def test_runtime_executes_confirmed_catalog_capability():
    calls = []
    result = AgentRuntime(
        model=lambda context: (
            AgentTurn(action="tool", tool_name="agent.create_goal")
            if not context["observations"] else AgentTurn(action="final", answer="done")
        ),
        executor=lambda name, arguments: calls.append((name, arguments)) or {"id": 7},
    ).run("create a goal", confirmation_granted=True)

    assert result.status == "completed"
    assert calls == [("agent.create_goal", {})]


def test_runtime_compresses_large_tool_results_without_losing_artifact():
    decisions = iter([
        AgentTurn(action="tool", tool_name="course.list"),
        AgentTurn(action="final", answer="done"),
    ])
    full_result = {"content": "x" * 500}
    result = AgentRuntime(
        model=lambda _context: next(decisions), executor=lambda _name, _args: full_result,
        budget=AgentBudget(max_tool_result_chars=100),
    ).run("inspect course")

    observation = result.trajectory.tool_observations()[0]
    artifact_ref = observation["meta"]["artifact_ref"]
    assert observation["meta"]["truncated"] is True
    assert observation["data"]["artifact_ref"] == artifact_ref
    assert result.read_tool_result(artifact_ref) == full_result
