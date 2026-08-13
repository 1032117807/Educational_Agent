"""Cross-client Agent Runtime contracts.

Desktop and SaaS share tool definitions.  They differ only in the executor
selected for a tool call: the desktop companion or a cloud sandbox.
"""

from app.agent_runtime.catalog import TOOL_CATALOG, tools_for_client

__all__ = ["TOOL_CATALOG", "tools_for_client"]
