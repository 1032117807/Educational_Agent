from datetime import date, timedelta

from ai.agents import AgentDecision, LearningPlanAgentService
from app.database import Database
from app.models import StudyGoal


class FakeStructuredModel:
    def __init__(self, decision):
        self.decision = decision

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt):
        return self.decision


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
