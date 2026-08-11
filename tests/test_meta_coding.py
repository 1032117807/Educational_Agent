import json

import pytest

from app.services.meta_coding import MetaCodeProposal, MetaCodingService


class FakeGateway:
    """模拟 MCP 沙箱，确认临时代码不会要求持久化授权。"""

    def execute(self, name, arguments, *, confirmed=False):
        assert name == "run_python_in_sandbox"
        assert confirmed is False
        assert "payload" in arguments["code"]
        return {"content": [json.dumps({
            "returncode": 0, "stdout": '{"sum": 6}', "stderr": "",
        })]}


class FakeModel:
    def with_structured_output(self, _schema, **_kwargs):
        return self

    def invoke(self, _prompt):
        return MetaCodeProposal(
            title="数组求和",
            can_solve=True,
            explanation="计算 payload 中 numbers 的总和。",
            python_code='print(json.dumps({"sum": sum(payload["numbers"])}))',
            expected_output='{"sum": 6}',
        )


def test_temporary_meta_code_runs_without_writing_skills(tmp_path):
    skills_dir = tmp_path / "skills"
    service = MetaCodingService(
        chat_model=FakeModel(), mcp_gateway=FakeGateway(), skills_dir=skills_dir,
    )

    proposal = service.propose(
        request="计算 1、2、3 的和", available_tools=[], available_skills=[],
        payload={"numbers": [1, 2, 3]},
    )
    result = service.run_temporary(proposal=proposal, payload={"numbers": [1, 2, 3]})

    assert result.returncode == 0
    assert '"sum": 6' in result.stdout
    assert not skills_dir.exists()


def test_publishing_meta_skill_requires_explicit_confirmation(tmp_path):
    service = MetaCodingService(
        chat_model=FakeModel(), mcp_gateway=FakeGateway(), skills_dir=tmp_path / "skills",
    )
    proposal = MetaCodeProposal(
        title="数组求和",
        can_solve=True,
        explanation="求和。",
        python_code='print(json.dumps({"ok": True}))',
        publishable=True,
        skill_name="sum-numbers",
        skill_description="对输入数组求和。",
        skill_script=(
            "import json\nimport sys\npayload = json.load(sys.stdin)\n"
            "print(json.dumps({\"sum\": sum(payload[\"numbers\"])}))"
        ),
    )

    with pytest.raises(PermissionError):
        service.publish_skill(proposal=proposal, confirmed=False)

    path = service.publish_skill(proposal=proposal, confirmed=True)
    assert (path / "SKILL.md").is_file()
    assert (path / "skill.json").is_file()
    assert (path / "scripts" / "main.py").is_file()
