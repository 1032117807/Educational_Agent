from __future__ import annotations

import pytest

from app.services.agent_permissions import AgentPermissionService
from app.services.mcp_gateway import MCPGateway
from app.services.cancellation import CancellationToken, OperationCancelled


def test_mutating_mcp_tool_requires_confirmation():
    decision = AgentPermissionService().decide("write_workspace_file", confirmed=False)

    assert not decision.allowed
    assert decision.needs_confirmation


def test_executable_skill_requires_confirmation():
    decision = AgentPermissionService().decide("run_skill_script", confirmed=False)

    assert not decision.allowed
    assert decision.needs_confirmation


def test_unknown_mcp_tool_is_denied():
    decision = AgentPermissionService().decide("run_shell", confirmed=True)

    assert not decision.allowed


def test_gateway_reads_a_workspace_file_through_mcp():
    result = MCPGateway().execute(
        "read_workspace_file", {"relative_path": "ai/mcp_client.py"}, confirmed=False
    )

    assert not result["is_error"]
    assert "learning_agent_mcp.py" in "\n".join(result["content"])


def test_gateway_blocks_unconfirmed_write_before_starting_server():
    with pytest.raises(PermissionError, match="Human confirmation"):
        MCPGateway().execute(
            "write_workspace_file",
            {"relative_path": "scratch.md", "content": "test"},
            confirmed=False,
        )


def test_gateway_honors_cancelled_token_before_starting_server():
    token = CancellationToken()
    token.cancel("user cancelled")

    with pytest.raises(OperationCancelled, match="user cancelled"):
        MCPGateway().execute(
            "read_workspace_file", {"relative_path": "ai/mcp_client.py"},
            confirmed=False, cancellation=token,
        )
