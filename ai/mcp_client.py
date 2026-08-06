# ai/mcp_client.py
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

LEARNING_AGENT_MCP = {
    "command": sys.executable,
    "args": ["mcp_servers/learning_agent_mcp.py"],
    "cwd": str(PROJECT_ROOT),
}
