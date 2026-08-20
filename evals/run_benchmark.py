"""Run reproducible Agent benchmark suites without reimplementing production logic.

Examples:
  python evals/run_benchmark.py --suite rag
  python evals/run_benchmark.py --suite all --output-dir evals/reports/latest
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation import run_evaluation as legacy
from evals.evaluators import aggregate_records


def _records_for(suite: str, work_dir: Path) -> list[dict[str, Any]]:
    harness = legacy.evaluate_agent_harness(work_dir / "harness")
    select: dict[str, Callable[[], list[dict[str, Any]]]] = {
        "rag": lambda: legacy.evaluate_retrieval(work_dir / "retrieval") + [item for item in harness if item["module"] == "rag_query_rewrite"],
        "memory": lambda: [item for item in harness if item["module"] == "memory_conflict"],
        "tools": lambda: legacy.evaluate_tools(work_dir / "tools") + [item for item in harness if item["module"] == "tool_retry"],
        "skills": lambda: [item for item in harness if item["module"] == "skill_selection"] + legacy.evaluate_ablations(),
        "multi_agent": lambda: [item for item in harness if item["module"] == "subagent_routing"],
        "safety": lambda: legacy.evaluate_tools(work_dir / "safety_tools") + legacy.evaluate_robustness(work_dir / "robustness"),
    }
    if suite == "smoke":
        suite = "all"
    if suite == "benchmark":
        return _formal_benchmark_status()
    if suite == "all":
        return legacy.evaluate_metric_implementation() + harness + legacy.evaluate_ablations() + legacy.evaluate_retrieval(work_dir / "retrieval") + legacy.evaluate_tools(work_dir / "tools") + legacy.evaluate_robustness(work_dir / "robustness")
    return select[suite]()


def _formal_benchmark_status() -> list[dict[str, Any]]:
    """Refuse to turn unverified annotation candidates into Gold results."""
    manifest = json.loads((ROOT / "evals" / "datasets" / "benchmark_manifest.json").read_text(encoding="utf-8"))
    records = []
    for module, config in manifest.items():
        verified = int(config.get("verified_records", 0))
        minimum = int(config.get("minimum_records", 0))
        ready = verified >= minimum and minimum > 0
        records.append({
            "case_id": f"benchmark-readiness-{module}", "module": f"{module}_benchmark", "status": "completed" if ready else "unavailable",
            "metrics": {"gold_ready": {"status": "available" if ready else "unavailable", "value": 1.0 if ready else None, "reason": "verified annotation count below minimum" if not ready else ""}},
            "details": {"verified_records": verified, "minimum_records": minimum, "gold_label_verified": ready, "dataset": config.get("gold_dataset")}, "error": "" if ready else "Gold dataset requires human verification before benchmark execution",
        })
    return records


def _write_report(output_dir: Path, suite: str, records: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    aggregates = aggregate_records(records)
    payload = {"metadata": metadata, "records": records, "aggregates": aggregates}
    (output_dir / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "benchmark.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["module", "metric", "n", "mean"])
        writer.writeheader(); writer.writerows(aggregates)
    completed = sum(item.get("status") == "completed" for item in records)
    failed = sum(item.get("status") == "failed" for item in records)
    lines = [f"# Agent Benchmark: {suite}", "", "## Run", "", f"- Cases: {len(records)}", f"- Completed: {completed}", f"- Failed: {failed}", f"- Dataset version: {metadata['dataset_version']}", "", "## Aggregates", "", "| Module | Metric | N | Mean |", "|---|---|---:|---:|"]
    lines.extend(f"| {row['module']} | {row['metric']} | {row['n']} | {row['mean']:.4f} |" for row in aggregates)
    readiness = [item for item in records if "verified_records" in item.get("details", {})]
    if readiness:
        lines.extend(["", "## Formal Dataset Readiness", "", "| Module | Verified N | Required N | Human-confirmed Gold |", "|---|---:|---:|---|"])
        lines.extend(f"| {item['module']} | {item['details']['verified_records']} | {item['details']['minimum_records']} | {item['details']['gold_label_verified']} |" for item in readiness)
    lines.extend(["", "## Unavailable Metrics", "", "RAG generation faithfulness/relevancy, OCR CER, full LLM tool planning, and single-vs-multi-agent quality require versioned human ground truth or a configured judge adapter. They are intentionally not estimated by this deterministic smoke benchmark.", "", "## Failure Cases", ""])
    failures = [item for item in records if item.get("status") == "failed"]
    lines.extend(f"- `{item['case_id']}` ({item['module']}): {item.get('error') or 'contract mismatch'}" for item in failures) or lines.append("- None")
    (output_dir / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["smoke", "benchmark", "rag", "memory", "tools", "skills", "multi_agent", "safety", "all"], default="smoke")
    parser.add_argument("--config", type=Path, default=ROOT / "evals" / "configs" / "default.json")
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--candidate", default="current")
    parser.add_argument("--repetitions", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evals" / "reports" / "latest")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.repetitions is not None:
        config["repetitions"] = args.repetitions
    metadata = {"suite": args.suite, "baseline": args.baseline, "candidate": args.candidate, "dataset_version": config["dataset_version"], "requested_repetitions": config["repetitions"], "timestamp": datetime.now(timezone.utc).isoformat(), "python": sys.version, "platform": platform.platform()}
    work_dir = Path(tempfile.mkdtemp(prefix="agent-benchmark-"))
    try:
        records = _records_for(args.suite, work_dir)
        _write_report(args.output_dir, args.suite, records, metadata)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    print(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
