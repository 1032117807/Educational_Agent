from __future__ import annotations

import asyncio
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from app.services.agent_permissions import AgentPermissionService
from app.services.cancellation import CancellationToken, OperationCancelled


class MCPGateway:
    """Starts the local stdio MCP server per call with a one-time approval secret."""

    TOOLS = (
        ("list_workspace_files", "List files inside the project workspace", False),
        ("read_workspace_file", "Read a UTF-8 file inside the project workspace", False),
        ("fetch_public_url", "Fetch a public HTTPS page from the domain allowlist", False),
        ("search_web", "Search public web sources through Brave Search", False),
        ("write_workspace_file", "Write an allowlisted project file", True),
        ("run_python_in_sandbox", "Run Python inside the Docker sandbox", True),
        ("run_skill_script", "Run an allowlisted executable Agent Skill in the Docker sandbox", True),
    )

    def __init__(self, permissions: AgentPermissionService | None = None) -> None:
        self.permissions = permissions or AgentPermissionService()
        self.root = Path(__file__).resolve().parents[2]
        self.server_file = self.root / "mcp_servers" / "learning_agent_mcp.py"

    def tool_specs(self) -> list[dict[str, object]]:
        return [
            {"name": f"mcp.{name}", "description": description, "mutates_data": mutates}
            for name, description, mutates in self.TOOLS
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, Any]:
        decision = self.permissions.decide(name, confirmed=confirmed)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if not self.server_file.is_file():
            raise FileNotFoundError("Local MCP server file is missing")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        return asyncio.run(
            self._call(name, arguments, confirmed=confirmed, cancellation=cancellation)
        )

    async def _call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, Any]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        approval_token = secrets.token_urlsafe(32)
        payload = dict(arguments)
        if confirmed:
            # The model never receives this value. The server verifies it too.
            payload["approval_token"] = approval_token
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_file)],
            env={
                **os.environ,
                "AGENT_WORKSPACE": str(self.root),
                "MCP_APPROVAL_TOKEN": approval_token,
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                call = asyncio.create_task(session.call_tool(name, payload))
                while not call.done():
                    if cancellation is not None and cancellation.is_cancelled():
                        call.cancel()
                        try:
                            await call
                        except asyncio.CancelledError:
                            pass
                        raise OperationCancelled(
                            cancellation.reason or "MCP tool cancelled"
                        )
                    await asyncio.sleep(0.05)
                result = await call
        response = {
            "is_error": bool(getattr(result, "isError", False)),
            "content": [getattr(item, "text", str(item)) for item in result.content],
        }
        if response["is_error"]:
            detail = "\n".join(response["content"]).strip() or "MCP server returned an error"
            raise RuntimeError(f"MCP tool {name} failed: {detail}")
        return response
