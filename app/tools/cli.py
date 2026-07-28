from __future__ import annotations

import argparse
import json

from app.bootstrap import bootstrap
from app.database import Database
from app.tools.registry import ToolRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="个性化学习助手本地工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("name")
    run.add_argument("--json", default="{}")
    run.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    service, config = bootstrap()
    registry = ToolRegistry(service.database, config)
    if args.command == "list":
        output = [{
            "name": tool.name, "description": tool.description, "risk": tool.risk,
            "mutates_data": tool.mutates_data, "schema": tool.schema(),
        } for tool in registry.list()]
    else:
        output = registry.execute(args.name, json.loads(args.json), args.confirm)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
