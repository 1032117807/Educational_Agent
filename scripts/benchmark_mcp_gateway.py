"""Measure safe per-call MCP lifecycle overhead without changing policy.

The MCP gateway creates a new stdio process for every call so an approval
token, cancellation scope and workspace environment cannot leak between Agent
runs.  This script measures that intentional trade-off using a read-only tool.
"""
from __future__ import annotations

import argparse
import statistics
import time

from app.services.mcp_gateway import MCPGateway


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark isolated MCP calls")
    parser.add_argument("--runs", type=int, default=5, help="number of read-only calls")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")

    gateway = MCPGateway()
    durations: list[float] = []
    for _ in range(args.runs):
        started = time.perf_counter()
        result = gateway.execute(
            "read_workspace_file", {"relative_path": "mcp_servers/learning_agent_mcp.py"},
            confirmed=False,
        )
        if result["is_error"]:
            raise RuntimeError("read-only MCP benchmark call failed")
        durations.append((time.perf_counter() - started) * 1000)

    print("MCP gateway lifecycle benchmark (isolated stdio per call)")
    print(f"runs={args.runs}")
    print(f"median_ms={statistics.median(durations):.1f}")
    print(f"mean_ms={statistics.mean(durations):.1f}")
    print(f"max_ms={max(durations):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
