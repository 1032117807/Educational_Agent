from datetime import date

from server.ai_services.agent import infer_actions, plan_actions, run_learning_agent
from app.database import Database
from app.models import AgentMemory, AgentMessage, Course, KnowledgePoint, Question, ReviewItem, StudyTask
from server.agent_stream import _auto_importable_materials, _bounded_session_history, _collect_runtime_context, _is_learning_launch_request, _learning_launch_target_date, _memory_candidate, _requested_artifact, _requests_web_search, _should_use_parallel_subagents, learning_snapshot, rich_response_blocks
from server.routers import _course_title_from_request


def test_chinese_agent_intents_are_routed() -> None:
    assert "remember" in infer_actions("请记住我每天晚上学习")
    assert "create_goal" in infer_actions("创建一个学习目标")
    assert "generate_plan" in infer_actions("帮我制定学习计划")
    assert "generate_questions" in infer_actions("根据资料生成练习题")


def test_code_and_diagram_requests_stay_in_the_conversational_lane() -> None:
    code_request = "\u8bf7\u4e3a\u4e8c\u5206\u67e5\u627e\u5199 Python \u51fd\u6570\uff0c\u4e0d\u8981\u521b\u5efa\u5b66\u4e60\u8ba1\u5212\u3002"
    diagram_request = "\u8bf7\u753b\u4e00\u4e2a React \u72b6\u6001\u6d41\u8f6c\u7684 Mermaid \u6d41\u7a0b\u56fe\u3002"
    assert infer_actions(code_request) == ["chat"]
    assert infer_actions(diagram_request) == ["chat"]
    assert not _requests_web_search(code_request)


def test_plain_chat_does_not_queue_a_redundant_background_agent_job(tmp_path, monkeypatch) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'agent-chat.db').as_posix()}")
    database.create_schema()
    monkeypatch.setattr("server.agent_stream.create_chat_model", lambda *_args, **_kwargs: None)
    with database.session() as db:
        from app.models import AgentSession
        session = AgentSession(tenant_id="tenant-a", title="New session")
        db.add(session)
        db.flush()
        session_id = session.id
    events = list(__import__("server.agent_stream", fromlist=["stream_agent_reply"]).stream_agent_reply(
        session_factory=database.session, tenant_id="tenant-a", user_id="user-a",
        session_id=session_id, message="explain binary search", course_id=None,
    ))
    with database.session() as db:
        assert db.query(__import__("app.models", fromlist=["BackgroundJob"]).BackgroundJob).count() == 0
    assert any("Selected: chat" in event for event in events)


def test_course_less_public_research_does_not_queue_curation_job(tmp_path, monkeypatch) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'public-research.db').as_posix()}")
    database.create_schema()
    monkeypatch.setattr("server.agent_stream.create_chat_model", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("server.agent_stream.plan_actions", lambda *_args, **_kwargs: ["research_curation"])
    with database.session() as db:
        from app.models import AgentSession
        session = AgentSession(tenant_id="tenant-a", title="Research")
        db.add(session)
        db.flush()
        session_id = session.id

    events = list(__import__("server.agent_stream", fromlist=["stream_agent_reply"]).stream_agent_reply(
        session_factory=database.session, tenant_id="tenant-a", user_id="user-a",
        session_id=session_id, message="find CET-6 public resources", course_id=None,
    ))

    with database.session() as db:
        assert db.query(__import__("app.models", fromlist=["BackgroundJob"]).BackgroundJob).count() == 0
    assert any("Selected: research_curation" in event for event in events)


def test_rich_blocks_turn_chinese_exam_style_questions_into_clickable_quiz_data() -> None:
    blocks = rich_response_blocks(
        "**第2题（句子听辨）**\n你听到一句话，这句话最可能出现什么场景？\n"
        "A. 新闻报道\nB. 学术讲座\nC. 日常对话\nD. 商业广告\n"
    )
    quiz = next(block for block in blocks if block["type"] == "quiz")
    assert quiz["questions"][0]["number"] == 2
    assert quiz["questions"][0]["options"][1] == {"id": "B", "label": "学术讲座"}


def test_model_action_plan_is_primary_when_structured_output_is_available() -> None:
    class Planner:
        def invoke(self, _prompt):
            return {"actions": ["generate_questions", "generate_plan"]}

    class Model:
        def with_structured_output(self, _schema, **_kwargs):
            return Planner()

    assert plan_actions("unrelated text", chat_model=Model()) == ["generate_questions", "generate_plan"]


def test_model_can_open_a_coding_workspace_without_keyword_fallback() -> None:
    class Planner:
        def invoke(self, _prompt):
            return {"actions": ["chat"], "intent": "workspace", "workspace_mode": "code"}

    class Model:
        def with_structured_output(self, _schema, **_kwargs):
            return Planner()

    assert plan_actions("帮我把这个想法做成可以反复试验的小工具", chat_model=Model()) == ["meta_code"]


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


def test_public_research_does_not_call_course_scoped_curation_without_a_course(monkeypatch) -> None:
    monkeypatch.setattr("server.ai_services.agent.plan_actions", lambda _message, **_kwargs: ["research_curation"])
    monkeypatch.setattr(
        "server.ai_services.agent.run_ai_feature",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("course curation must not run")),
    )

    result = run_learning_agent(
        payload={"tenant_id": "tenant-a", "data": {"message": "research CET-6 resources"}},
        session_factory=lambda: None, embeddings=None, embedding_version="test",
        dimensions=512, chat_model=None, provider="test", model_name="test",
    )

    assert result["actions"] == [{
        "feature": "research_curation",
        "status": "completed",
        "detail": "Public-source research is complete in this conversation. Select a course only when you want to import or curate course materials.",
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
    assert _requests_web_search("检索下载相关资料和题目")
    assert _requests_web_search("帮我找资料并列出来源")
    assert _memory_candidate("记住我薄弱的是线性代数", None)["category"] == "weak_point"
    assert _requested_artifact("请导出为 markdown 文件", []) == "markdown_report"
    assert _requested_artifact("给我学习总结", []) is None


def test_natural_download_request_selects_only_direct_learning_files() -> None:
    results = [
        {"title": "CET-6 真题 PDF", "url": "https://example.test/cet6.pdf", "description": "download"},
        {"title": "PDF 下载页", "url": "https://example.test/landing", "description": "PDF material"},
    ]
    assert _auto_importable_materials("检索下载相关资料", results) == [
        {"title": "CET-6 真题 PDF", "url": "https://example.test/cet6.pdf"},
    ]


def test_daily_task_request_is_a_single_learning_launch_not_question_only() -> None:
    assert _is_learning_launch_request("请直接生成六级备考的具体任务，每周固定任务，细化到每天，并为每项任务配练习题")
    assert _is_learning_launch_request("制定未来 7 天每日任务，围绕极限的定义安排练习，并生成 3 道题目")
    assert not _is_learning_launch_request("给我生成五道英语练习题")


def test_full_exam_plan_request_creates_an_automatic_learning_launch_and_clear_course_name() -> None:
    request = "我要参加今年12月份的英语6级，目标425分以上，帮我制定学习计划和检索下载相关资料、题目与单词。"
    assert _is_learning_launch_request(request)
    assert _course_title_from_request(request) == "大学英语六级：备考"


def test_learning_launch_honors_explicit_day_count() -> None:
    assert (_learning_launch_target_date("制定未来 7 天每日任务") - date.today()).days == 6
    assert not _requests_web_search("请生成六级备考的每日学习任务")
    assert _requests_web_search("六级什么时候考试")


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


def test_learning_snapshot_exposes_actionable_tutor_context(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'tutor-snapshot.db').as_posix()}")
    database.create_schema()
    with database.session() as db:
        course = Course(tenant_id="tenant-a", name="Calculus")
        db.add(course)
        db.flush()
        point = KnowledgePoint(tenant_id="tenant-a", course_id=course.id, name="Limits", mastery=38, importance=5)
        question = Question(tenant_id="tenant-a", course_id=course.id, knowledge_point_id=point.id, prompt="Limit question", answer="A")
        db.add_all([point, question])
        db.flush()
        db.add_all([
            StudyTask(tenant_id="tenant-a", course_id=course.id, title="Review limits", planned_date=date.today(), duration_minutes=25),
            ReviewItem(tenant_id="tenant-a", question_id=question.id, title="Limit question", next_review=date.today(), wrong_count=2),
        ])
    try:
        with database.session() as db:
            snapshot = learning_snapshot(db, "tenant-a", course.id)
        assert snapshot["available_minutes"] == 25
        assert snapshot["today"]["due_review_count"] == 1
        assert snapshot["review_queue"]["items"][0]["question_id"] == question.id
        assert snapshot["knowledge_mastery"][0]["name"] == "Limits"
    finally:
        database.close()
