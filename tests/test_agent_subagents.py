from app.agent_runtime import SubAgentRuntime, SubAgentTask


def test_subagent_receives_only_task_context_and_returns_structured_result():
    seen = []

    def runner(task, context):
        seen.append(context)
        return {"summary": task.objective, "evidence": [{"chunk_id": 3}], "confidence": 0.8, "artifacts": ["reports/a.md"]}

    result = SubAgentRuntime(runner).run([
        SubAgentTask("research", "find evidence", context={"course_id": 2}, allowed_tools=("web.search",), allowed_skills=("research",))
    ], shared_context={"private_history": "must not be copied"})[0]

    assert result.summary == "find evidence"
    assert result.evidence == ({"chunk_id": 3},)
    assert result.artifacts == ("reports/a.md",)
    assert seen[0]["course_id"] == 2
    assert seen[0]["allowed_tools"] == ["web.search"]
    assert "private_history" not in seen[0]


def test_subagent_runtime_caps_parallel_tasks():
    calls = []

    def runner(task, _context):
        calls.append(task.agent_type)
        return {"summary": task.agent_type}

    tasks = [SubAgentTask(str(index), "work") for index in range(6)]
    results = SubAgentRuntime(runner, max_subagents=2).run(tasks)

    assert len(results) == 2
    assert len(calls) == 2


def test_subagent_failure_is_structured_not_a_main_context_traceback():
    result = SubAgentRuntime(lambda _task, _context: (_ for _ in ()).throw(RuntimeError("bad source"))).run([
        SubAgentTask("knowledge", "verify")
    ])[0]

    assert result.status == "failed"
    assert result.validation[0]["error"] == "bad source"
