import asyncio
from datetime import date, timedelta

import pytest

from ai.agents import AgentDecision, LearningPlanAgentService
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
