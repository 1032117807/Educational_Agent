from __future__ import annotations

from app.agent_runtime import AgentBudget, AgentRuntimeState, ContextBudgetManager
from app.services.agent_skills import AgentSkillCatalog
from ai.prompts import AGENT_PROMPT_VERSION, AgentPromptRenderer


def test_skill_metadata_does_not_include_full_skill_instructions(tmp_path):
    skill_path = tmp_path / "skills" / "research" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    instructions = "# Research\n\nVersion: 2.0.0\n\n" + ("detailed workflow\n" * 500)
    skill_path.write_text(instructions, encoding="utf-8")
    catalog = AgentSkillCatalog(tmp_path / "skills")

    metadata = catalog.skill_metadata()

    assert metadata == [{
        "name": "research",
        "description": "detailed workflow",
        "version": "2.0.0",
        "permissions": ["mcp.search_web", "mcp.fetch_public_url"],
    }]
    assert "instructions" not in metadata[0]
    assert catalog.load_skill("research") == instructions.strip()


def test_skill_frontmatter_is_used_as_the_metadata_contract(tmp_path):
    skill_path = tmp_path / "skills" / "coding" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: coding\ndescription: >\n  Safe coding workflow\nversion: 3.2.1\n---\n\n# Workflow\n",
        encoding="utf-8",
    )

    metadata = AgentSkillCatalog(tmp_path / "skills").skill_metadata()

    assert metadata[0]["name"] == "coding"
    assert metadata[0]["description"] == "Safe coding workflow"
    assert metadata[0]["version"] == "3.2.1"


def test_prompt_renderer_keeps_dynamic_context_out_of_stable_policy():
    renderer = AgentPromptRenderer()
    prompt = renderer.render()
    messages = prompt.format_messages(
        context='{"courses": []}', history='[]', message="help me plan"
    )

    assert AGENT_PROMPT_VERSION.startswith("learning-agent-v")
    assert all("{context}" not in message.content for message in messages[:-1])
    assert "help me plan" in messages[-1].content
    assert "{" in messages[-1].content
    assert "untrusted data" in " ".join(message.content for message in messages[:-1])


def test_agent_state_status_bar_is_programmatically_derived():
    state = AgentRuntimeState(goal="create a study plan", active_course_id=7)
    state.begin_phase("planning", skill="learning-plan")
    state.record_tool_call("learning_data.read_snapshot")
    state.add_completed_step("read_learning_snapshot")
    state.add_todo("generate_plan")

    status = state.render_status(AgentBudget(max_tool_calls=12))

    assert "goal: create a study plan" in status
    assert "active_course: 7" in status
    assert "tool_calls: 1 / 12" in status
    assert "generate_plan" in status


def test_budget_stops_repeating_same_failed_tool_call():
    budget = AgentBudget(max_same_tool_retries=2)

    first = budget.record_tool_failure("web.search", {"query": "calculus"}, "timeout")
    second = budget.record_tool_failure("web.search", {"query": "calculus"}, "timeout")
    third = budget.record_tool_failure("web.search", {"query": "calculus"}, "timeout")

    assert first.retry_allowed
    assert second.retry_allowed
    assert not third.retry_allowed
    assert third.suggestion == "change arguments, choose another tool, ask the user, or stop"


def test_context_budget_uses_category_limits_and_preserves_identifiers():
    manager = ContextBudgetManager(
        max_tokens=500,
        category_token_limits={"base": 80, "status": 40, "history": 40, "observations": 80},
    )
    context = manager.build(
        base={"goal": "study", "course_id": 7, "unneeded": "x" * 5000},
        status="thinking" * 200,
        history=[{"message": "old " + "x" * 3000, "workflow_id": 11}],
        observations=[{"tool_name": "search_knowledge", "summary": "y" * 3000, "chunk_id": 9, "url": "https://example.test"}],
    )

    assert context["base"]["goal"] == "study"
    assert context["base"]["course_id"] == 7
    assert context["observations"][0]["url"] == "https://example.test"
    assert len(context["status"]) <= 256
