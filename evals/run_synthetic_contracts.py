from __future__ import annotations

import json
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Database
from app.services.agent_memory import AgentMemoryService
from app.services.agent_skills import AgentSkillCatalog
from evaluation.metrics.core import classification_metrics, available
from server.ai_services.agent import infer_actions

OUT = ROOT / "evals" / "reports" / "synthetic-latest"


def _meta() -> dict[str, object]:
    return {"dataset_version": "synthetic-contract-v1", "created_at": datetime.now(timezone.utc).isoformat(), "labeling_method": "synthetic authored templates", "gold_label_verified": False, "source": "project capability contracts"}


def build_cases() -> tuple[list[dict], list[dict]]:
    skills = [
        ("resource-analysis", "分析这份学习资料并提取知识点"), ("learning-plan", "帮我制定一个学习计划"),
        ("error-diagnosis", "诊断我的练习错误"), ("research", "检索公开资料并比较来源"),
        ("report-visualization", "生成学习报告和可视化图表"), ("coding", "分析这段代码并修复问题"),
    ]
    skill_rows = []
    for index in range(80):
        name, request = skills[index % len(skills)]
        skill_rows.append({**_meta(), "id": f"skill-synth-{index+1:03d}", "user_request": f"{request}（案例 {index+1}）", "expected_skill": name, "allowed_skills": [name], "no_skill": False, "expected_output_requirements": ["follow_skill_contract"]})
    memory_rows = []
    actions = [("ADD", None, {"minutes": 30}), ("UPDATE", {"minutes": 30}, {"minutes": 60}), ("NOOP", {"minutes": 30}, {"minutes": 30}), ("DELETE", {"minutes": 30}, {"deleted": True})]
    for index in range(100):
        action, old, new = actions[index % len(actions)]
        memory_rows.append({**_meta(), "id": f"memory-synth-{index+1:03d}", "old": old, "new": new, "expected": action, "category": "learning_pace", "provenance": "user_confirmed" if index % 5 else "agent_speculation"})
    return skill_rows, memory_rows


def main() -> int:
    skill_rows, memory_rows = build_cases()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "skill_cases.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in skill_rows) + "\n", encoding="utf-8")
    (OUT / "memory_cases.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in memory_rows) + "\n", encoding="utf-8")
    catalog = AgentSkillCatalog()
    expected_skills = [row["expected_skill"] for row in skill_rows]
    actual_skills = []
    for row in skill_rows:
        terms = set(row["user_request"].casefold().split())
        choices = catalog.skill_metadata()
        selected = max(choices, key=lambda item: sum(term in f"{item['name']} {item['description']}".casefold() for term in terms))["name"]
        actual_skills.append(selected)
    skill_metrics = classification_metrics(expected_skills, actual_skills)
    with tempfile.TemporaryDirectory(prefix="memory-synthetic-") as temp:
        expected_memory, actual_memory = [], []
        for index, row in enumerate(memory_rows):
            # Each case models an independent user history. Reusing one database
            # leaks prior cases into later conflict decisions and biases metrics.
            db = Database(f"sqlite:///{Path(temp) / f'memory-{index}.db'}"); db.create_schema(); service = AgentMemoryService(db)
            if row["old"] is not None and row["expected"] != "ADD":
                service.remember(scope="long_term", category="learning_pace", content=row["old"], confirmed=True)
            decision = service.decide_candidate(scope="long_term", category="learning_pace", content=row["new"])
            expected_memory.append(row["expected"]); actual_memory.append(decision.action)
            db.close()
        memory_metrics = classification_metrics(expected_memory, actual_memory)
    report = {"metadata": _meta(), "sample_counts": {"skill": len(skill_rows), "memory": len(memory_rows)}, "skill": skill_metrics, "memory": memory_metrics, "tool_safety": {"source": "smoke suite", "note": "Run the smoke suite for tool/safety contract metrics; these synthetic samples do not alter production execution."}}
    (OUT / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Synthetic Contract Benchmark", "", "- Gold labels verified: **false**", "- Skill cases: 80", "- Memory cases: 100", "", "These are synthetic authored contract cases, not human-verified product quality results.", "", "## Skill Metrics", "", json.dumps(skill_metrics, ensure_ascii=False, indent=2), "", "## Memory Metrics", "", json.dumps(memory_metrics, ensure_ascii=False, indent=2)]
    (OUT / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
