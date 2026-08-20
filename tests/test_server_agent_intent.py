from server.ai_services.agent import infer_actions, plan_actions, run_learning_agent
from app.database import Database
from app.models import AgentMemory, AgentMessage, Course
from server.agent_stream import _bounded_session_history, _collect_runtime_context, _memory_candidate, _requested_artifact, _requests_web_search, _should_use_parallel_subagents


def test_chinese_agent_intents_are_routed() -> None:
    assert "remember" in infer_actions("请记住我每天晚上学习")
    assert "create_goal" in infer_actions("创建一个学习目标")
    assert "generate_plan" in infer_actions("帮我制定学习计划")
    assert "generate_questions" in infer_actions("根据资料生成练习题")


def test_model_action_plan_is_primary_when_structured_output_is_available() -> None:
    class Planner:
        def invoke(self, _prompt):
            return {"actions": ["generate_questions", "generate_plan"]}

    class Model:
        def with_structured_output(self, _schema, **_kwargs):
            return Planner()

    assert plan_actions("unrelated text", chat_model=Model()) == ["generate_questions", "generate_plan"]


def test_background_web_actions_use_runtime_confirmation_boundary(monkeypatch) -> None:
    monkeypatch.setattr("server.ai_services.agent.plan_actions", lambda _message, **_kwargs: ["create_goal"])
    result = run_learning_agent(
        payload={"tenant_id": "tenant-a", "data": {"message": "create a goal"}},
        session_factory=lambda: None, embeddings=None, embedding_version="test",
        dimensions=512, chat_model=None, provider="test", model_name="test",
    )

    assert result["actions"][0]["status"] == "needs_confirmation"
    assert result["runtime"]["status"] == "waiting_confirmation"
    assert any(item["type"] == "validation" and item["status"] == "confirmation_required" for item in result["runtime"]["trajectory"])


def test_background_web_actions_record_runtime_observation_for_non_mutating_needs_input(monkeypatch) -> None:
    monkeypatch.setattr("server.ai_services.agent.plan_actions", lambda _message, **_kwargs: ["generate_questions"])
    result = run_learning_agent(
        payload={"tenant_id": "tenant-a", "data": {"message": "generate questions"}},
        session_factory=lambda: None, embeddings=None, embedding_version="test",
        dimensions=512, chat_model=None, provider="test", model_name="test",
    )

    assert result["actions"] == [{
        "feature": "generate_questions", "status": "needs_input",
        "detail": "Select a course before the agent can generate grounded questions.",
    }]
    assert result["runtime"]["status"] == "completed"


def test_background_web_runtime_retries_a_transient_action_failure(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("server.ai_services.agent.plan_actions", lambda _message, **_kwargs: ["generate_questions"])

    def generate(**_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("temporary provider failure")
        return {"question_ids": [7], "status": "ok"}

    monkeypatch.setattr("server.ai_services.agent.generate_grounded_questions", generate)
    result = run_learning_agent(
        payload={"tenant_id": "tenant-a", "data": {"message": "generate questions", "course_id": 3}},
        session_factory=lambda: None, embeddings=None, embedding_version="test",
        dimensions=512, chat_model=None, provider="test", model_name="test",
    )

    assert len(calls) == 2
    assert result["actions"][0]["status"] == "completed"
    assert result["runtime"]["status"] == "completed"


def test_stream_agent_detects_web_memory_and_explicit_artifacts() -> None:
    assert _requests_web_search("请联网搜索资料")
    assert _memory_candidate("记住我薄弱的是线性代数", None)["category"] == "weak_point"
    assert _requested_artifact("请导出为 markdown 文件", []) == "markdown_report"
    assert _requested_artifact("给我学习总结", []) is None


def test_parallel_subagents_require_a_clear_independent_workload() -> None:
    assert not _should_use_parallel_subagents("web search calculus references")
    assert _should_use_parallel_subagents("web search multiple topics and compare sources")
    assert _should_use_parallel_subagents("联网搜索并结合我的学习进度分析")
    assert _should_use_parallel_subagents("search sources and have another agent review the answer")


def test_stream_context_uses_shared_runtime_for_tenant_snapshot(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'agent-stream.db').as_posix()}")
    database.create_schema()
    try:
        snapshot, web_results, observations = _collect_runtime_context(
            session_factory=database.session, tenant_id="tenant-a", session_id=1,
            message="show my learning progress", course_id=None,
        )
    finally:
        database.close()

    assert snapshot["courses"] == []
    assert web_results == []
    assert [item["tool_name"] for item in observations] == ["learning_data.read_snapshot"]


def test_all_courses_snapshot_includes_global_and_course_memories(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'agent-memory-snapshot.db').as_posix()}")
    database.create_schema()
    try:
        with database.session() as db:
            course = Course(tenant_id="tenant-a", name="Calculus")
            db.add(course)
            db.flush()
            db.add_all([
                AgentMemory(tenant_id="tenant-a", scope="long_term", category="plan_preference", content_json='{"note":"global"}', confirmed=True, deleted=False),
                AgentMemory(tenant_id="tenant-a", scope="course", category="weak_point", course_id=course.id, content_json='{"note":"course"}', confirmed=True, deleted=False),
            ])
            db.commit()
        snapshot, _, _ = _collect_runtime_context(
            session_factory=database.session, tenant_id="tenant-a", session_id=1,
            message="show my learning progress", course_id=None,
            subagent_runtime_enabled=False,
        )
    finally:
        database.close()

    assert {item["content"]["note"] for item in snapshot["confirmed_memories"]} == {"global", "course"}


def test_stream_context_uses_isolated_parallel_subagents_for_independent_web_evidence(tmp_path, monkeypatch) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'agent-stream-subagents.db').as_posix()}")
    database.create_schema()

    def web_search(_self, name, arguments):
        assert name == "web.search"
        assert arguments == {"query": "web search calculus references and compare sources"}
        return {
            "ok": True,
            "tool_name": name,
            "summary": "Found public sources",
            "data": {"results": [{"title": "Calculus", "url": "https://example.test/calculus"}]},
            "error": None,
            "meta": {"source": "web"},
        }

    monkeypatch.setattr("server.agent_stream.WebAgentToolExecutor.execute_observed", web_search)
    try:
        snapshot, web_results, observations = _collect_runtime_context(
            session_factory=database.session, tenant_id="tenant-a", session_id=1,
            message="web search calculus references and compare sources", course_id=None,
            subagent_runtime_enabled=True,
        )
    finally:
        database.close()

    assert snapshot["courses"] == []
    assert web_results == [{"title": "Calculus", "url": "https://example.test/calculus"}]
    assert {item["tool_name"] for item in observations} == {"learning_data.read_snapshot", "web.search"}


def test_session_history_is_bounded_and_preserves_latest_turns() -> None:
    rows = [AgentMessage(role="user", content=f"turn-{index}") for index in range(20)]
    history = _bounded_session_history(rows, limit=4, max_chars=100)

    assert [item["content"] for item in history] == ["turn-16", "turn-17", "turn-18", "turn-19"]
