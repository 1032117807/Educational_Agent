import asyncio
from datetime import date, timedelta

import pytest

from ai.agents import AgentDecision, LearningPlanAgentService
from app.agent_runtime import AgentBudget
from app.database import Database
from app.models import StudyGoal
from app.services.cancellation import CancellationToken, OperationCancelled


class FakeStructuredModel:
    def __init__(self, decision):
        self.decision = decision

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt):
        return self.decision


class SlowAsyncStructuredModel(FakeStructuredModel):
    async def ainvoke(self, _prompt):
        await asyncio.sleep(5)
        return self.decision


class ChunkedAsyncStructuredModel(FakeStructuredModel):
    async def astream(self, _prompt):
        yield {"reply": "正在分析"}
        yield {"reply": "正在分析你的学习情况。", "action": "chat"}


def test_agent_resolves_the_only_active_goal(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    db.create_schema()
    with db.session() as session:
        session.add(StudyGoal(
            title="完成数学复习",
            target_date=date.today() + timedelta(days=7),
            weekly_minutes=300,
        ))

    service = LearningPlanAgentService(
        database=db,
        chat_model=FakeStructuredModel(AgentDecision(
            reply="可以生成计划草稿。",
            action="generate_plan",
            daily_minutes=45,
        )),
        plan_factory=lambda: None,
    )
    decision = service.respond("帮我制定计划")
    assert decision.action == "generate_plan"
    assert decision.goal_id == 1
    assert decision.daily_minutes == 45
    db.close()


def test_agent_tool_arguments_are_parsed_from_json():
    decision = AgentDecision(
        reply="已准备完成任务。",
        action="tool",
        tool_name="study_task.complete",
        tool_arguments_json='{"id": 12}',
    )
    assert decision.tool_arguments == {"id": 12}


def test_agent_routes_web_research_requests_to_tavily_search(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    db.create_schema()
    service = LearningPlanAgentService(
        database=db, chat_model=FakeStructuredModel(None), plan_factory=lambda: None,
    )

    decision = service.respond("帮我联网搜索高等数学导数资料")

    assert decision.action == "research_collect"
    assert decision.research_request
    assert decision.tool_arguments == {"query": "帮我联网搜索高等数学导数资料"}
    db.close()


def test_agent_keeps_learning_report_download_out_of_web_search(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    db.create_schema()
    service = LearningPlanAgentService(
        database=db, chat_model=FakeStructuredModel(None), plan_factory=lambda: None,
        report_factory=lambda: None,
    )

    assert service.respond("下载学习报告").action == "generate_report"
    db.close()


def test_agent_decision_keeps_user_visible_reasoning_summary():
    decision = AgentDecision(
        reply="可以生成计划草稿。",
        reasoning_summary=["读取了当前目标", "检测到本周剩余学习时间不足"],
    )

    assert decision.reasoning_summary == ["读取了当前目标", "检测到本周剩余学习时间不足"]


def test_agent_recognizes_learning_report_request_without_model_call(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    db.create_schema()
    service = LearningPlanAgentService(
        database=db,
        chat_model=FakeStructuredModel(None),
        plan_factory=lambda: None,
        report_factory=lambda: None,
    )

    decision = service.respond("帮我生成学习报告")

    assert decision.action == "generate_report"
    db.close()


def test_agent_context_exposes_core_tools_and_discloses_other_tools_on_demand(tmp_path):
    from app.core.config import AppSettings
    from app.tools.registry import ToolRegistry

    db = Database(f"sqlite:///{(tmp_path / 'agent-tools.db').as_posix()}")
    db.create_schema()
    settings = AppSettings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    service = LearningPlanAgentService(
        database=db, chat_model=FakeStructuredModel(AgentDecision(reply="ok")),
        plan_factory=lambda: None, tool_registry=ToolRegistry(db, settings),
    )

    names = {item["name"] for item in service.context()["available_tools"]}
    discovered = service.discover_tools("backup")

    assert "tool.search" in names
    assert "database.backup" not in names
    assert discovered[0]["name"] == "database.backup"
    db.close()


def test_desktop_tool_execution_uses_shared_runtime_observation(tmp_path):
    from app.core.config import AppSettings
    from app.tools.registry import ToolRegistry

    db = Database(f"sqlite:///{(tmp_path / 'agent-runtime-tool.db').as_posix()}")
    db.create_schema()
    settings = AppSettings(data_dir=tmp_path / "data")
    settings.ensure_directories()
    service = LearningPlanAgentService(
        database=db, chat_model=FakeStructuredModel(AgentDecision(reply="ok")),
        plan_factory=lambda: None, tool_registry=ToolRegistry(db, settings),
    )

    result = service.execute_tool_runtime("tool.search", {"query": "backup"})

    assert result["ok"] is True
    assert result["runtime"]["status"] == "completed"
    assert result["data"]["capabilities"][0]["name"] == "database.backup"
    db.close()


def test_agent_memory_retrieval_feature_flag_excludes_memory_from_context(tmp_path):
    from app.services.agent_memory import AgentMemoryService

    db = Database(f"sqlite:///{(tmp_path / 'agent-memory-flag.db').as_posix()}")
    db.create_schema()
    memories = AgentMemoryService(db)
    memories.remember(scope="long_term", category="learning_pace", content={"minutes": 30}, confirmed=True)
    service = LearningPlanAgentService(
        database=db, chat_model=FakeStructuredModel(AgentDecision(reply="ok")),
        plan_factory=lambda: None, memory_service=memories, memory_retrieval_enabled=False,
    )

    assert service.context()["confirmed_memories"] == []
    db.close()


def test_desktop_runtime_returns_full_tool_result_artifacts(tmp_path):
    class LargeToolRegistry:
        def execute(self, _name, _arguments, *, confirmed=False):
            assert not confirmed
            return {"content": "x" * 500}

    db = Database(f"sqlite:///{(tmp_path / 'agent-large-tool.db').as_posix()}")
    db.create_schema()
    service = LearningPlanAgentService(
        database=db, chat_model=FakeStructuredModel(AgentDecision(reply="ok")),
        plan_factory=lambda: None, tool_registry=LargeToolRegistry(),
        budget_factory=lambda: AgentBudget(max_tool_result_chars=100),
    )

    result = service.execute_tool_runtime("course.list", {})

    artifact_ref = result["meta"]["artifact_ref"]
    assert result["runtime"]["tool_result_artifacts"][artifact_ref] == {"content": "x" * 500}
    db.close()


def test_async_agent_request_can_be_cancelled(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    db.create_schema()
    service = LearningPlanAgentService(
        database=db,
        chat_model=SlowAsyncStructuredModel(AgentDecision(reply="迟到的回复")),
        plan_factory=lambda: None,
    )
    token = CancellationToken()

    async def run() -> None:
        task = asyncio.create_task(service.respond_async("帮我分析", cancellation=token))
        await asyncio.sleep(0.02)
        token.cancel("test cancellation")
        with pytest.raises(OperationCancelled, match="test cancellation"):
            await task

    asyncio.run(run())
    db.close()


def test_async_agent_streams_visible_reply_chunks(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}")
    db.create_schema()
    service = LearningPlanAgentService(
        database=db,
        chat_model=ChunkedAsyncStructuredModel(None),
        plan_factory=lambda: None,
    )
    chunks: list[str] = []

    decision = asyncio.run(service.respond_async(
        "帮我分析", cancellation=CancellationToken(), on_text=chunks.append
    ))

    assert decision.reply == "正在分析你的学习情况。"
    assert "".join(chunks) == "正在分析你的学习情况。"
    db.close()
