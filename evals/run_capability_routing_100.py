"""Generate and run a 100-case offline Skill/MCP/tool routing benchmark.

This benchmark intentionally does not call an external LLM. It measures the
current metadata router and capability catalog, so its result is a deterministic
baseline. Use the generated JSONL as the same prompt set for a model adapter
when measuring end-to-end model tool selection later.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_runtime.catalog import search_capabilities, tools_for_client
from app.services.agent_skills import AgentSkillCatalog
from server.ai_services.agent import infer_actions

DATASET = ROOT / "evals" / "datasets" / "capability_routing_100.jsonl"
DEFAULT_OUTPUT = ROOT / "evals" / "reports" / "capability-routing-100"


def _cases() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skill_prompts = {
        "research": [
            "Research authoritative calculus references on limits.",
            "Find and compare public sources for matrix multiplication.",
            "Search the web for a beginner probability textbook.",
            "Collect online course materials about derivatives.",
            "Verify these learning resources against independent sources.",
        ],
        "resource-analysis": [
            "Analyze my imported lecture notes and extract the key concepts.",
            "Index the uploaded PDF and identify its main knowledge points.",
            "Break this course material into concepts and evidence.",
            "Extract a structured outline from the attached study resource.",
            "Review my document for missing concepts and source locations.",
        ],
        "learning-plan": [
            "Create a study plan for my calculus exam next month.",
            "Arrange my weekly learning tasks around a 60 minute daily budget.",
            "Plan the next two weeks of practice for linear algebra.",
            "Turn my active learning goal into a daily schedule.",
            "Generate a draft plan and wait for confirmation before saving tasks.",
        ],
        "error-diagnosis": [
            "Diagnose why I keep making mistakes in derivatives.",
            "Analyze the errors in my latest probability attempt.",
            "Explain the misconception behind this wrong matrix answer.",
            "Find the weak concept causing my repeated practice errors.",
            "Classify my learning mistakes and suggest targeted exercises.",
        ],
        "report-visualization": [
            "Generate a weekly learning report with a progress chart.",
            "Visualize my study time and practice accuracy.",
            "Create a dashboard-style summary of my learning activity.",
            "Export a report showing progress, weak areas, and trends.",
            "Plot my recent course completion and review statistics.",
        ],
        "learning-workflow": [
            "Run the complete learning workflow from resources to questions.",
            "Start the full course pipeline and pause for each confirmation.",
            "Process this course material through extraction and practice.",
            "Create a resumable learning workflow for course 3.",
            "Run indexing, knowledge extraction, question generation, and reporting.",
            "Continue the learning workflow from its last approved step.",
            "Orchestrate resource analysis, practice, and a final report.",
            "Launch the end-to-end study workflow for this course.",
            "Resume the staged course workflow after reviewing knowledge drafts.",
            "Prepare the complete learning loop without skipping confirmations.",
        ],
        "coding": [
            "Inspect the project files and explain this Python bug.",
            "Read the workspace configuration and propose a code fix.",
            "Run a small read-only calculation in the coding sandbox.",
            "List the files in my linked workspace before debugging.",
            "Write the requested script into the approved workspace after confirmation.",
        ],
    }
    for skill, prompts in skill_prompts.items():
        for prompt in prompts:
            rows.append({"id": f"cap-{len(rows)+1:03d}", "kind": "skill", "prompt": prompt, "expected": skill})

    mcp_prompts = [
        ("mcp.search_web", "Search public web sources for a current explanation of eigenvectors."),
        ("mcp.search_web", "Use the public internet to find authoritative study references."),
        ("mcp.search_web", "Look up recent information about spaced repetition research."),
        ("mcp.search_web", "Find online sources comparing two calculus textbooks."),
        ("mcp.search_web", "Search external sources and return links with citations."),
        ("mcp.fetch_public_url", "Fetch and read this public URL: https://example.org/course."),
        ("mcp.fetch_public_url", "Open the allowed public webpage and extract its title."),
        ("mcp.fetch_public_url", "Retrieve the contents of this public documentation link."),
        ("mcp.fetch_public_url", "Read the specified external article without downloading files."),
        ("mcp.fetch_public_url", "Fetch a public source so I can cite its exact wording."),
        ("mcp.list_workspace_files", "List files in my linked desktop workspace."),
        ("mcp.list_workspace_files", "Show the directory contents of the approved workspace."),
        ("mcp.list_workspace_files", "Which files are currently available in my project folder?"),
        ("mcp.list_workspace_files", "Inspect the workspace file names before I choose one."),
        ("mcp.list_workspace_files", "Give me a read-only listing of the connected files."),
        ("mcp.read_workspace_file", "Read the text of notes/limits.md from my workspace."),
        ("mcp.read_workspace_file", "Open the approved project README for inspection."),
        ("mcp.read_workspace_file", "Show me the contents of the selected local configuration file."),
        ("mcp.read_workspace_file", "Read a workspace file and summarize its relevant settings."),
        ("mcp.read_workspace_file", "Inspect the chosen source file without modifying it."),
        ("mcp.write_workspace_file", "After confirmation, write this markdown report to the approved workspace."),
        ("mcp.write_workspace_file", "Save the generated notes into an allowlisted workspace file."),
        ("mcp.write_workspace_file", "Create a new text file in the permitted project directory."),
        ("mcp.write_workspace_file", "Update the selected workspace document with these edits."),
        ("mcp.write_workspace_file", "Persist this export only after the user confirms the write."),
        ("mcp.run_skill_script", "Run the enabled research Skill script on the approved input."),
        ("mcp.run_skill_script", "Execute the selected executable Skill with its allowed arguments."),
        ("mcp.run_skill_script", "Use the enabled Skill entrypoint to process this resource."),
        ("mcp.run_skill_script", "Run an installed Skill script after checking its permission."),
        ("mcp.run_skill_script", "Execute the approved automation Skill in its sandbox."),
    ]
    for expected, prompt in mcp_prompts:
        rows.append({"id": f"cap-{len(rows)+1:03d}", "kind": "mcp", "prompt": prompt, "expected": expected})

    tool_prompts = [
        ("tool.search", "Find the capability metadata for reading course progress."),
        ("tool.search", "Which registered tool can create a learning goal?"),
        ("tool.search", "Discover the tool used to list today's study tasks."),
        ("tool.search", "Search the capability catalog for a report generator."),
        ("tool.search", "Look up an unfamiliar tool by its purpose before executing it."),
        ("learning_data.read_snapshot", "Read my current courses, goals, tasks, and practice summary."),
        ("learning_data.read_snapshot", "Show a read-only snapshot of my learning workspace."),
        ("learning_data.read_snapshot", "Check my recent study minutes and wrong question IDs."),
        ("learning_data.read_snapshot", "Inspect the confirmed learning memories and progress."),
        ("learning_data.read_snapshot", "Give the agent the current tenant-scoped learning data."),
        ("agent.create_goal", "Create a new learning goal for calculus by June 30."),
        ("agent.create_goal", "Set up a goal to score 90 on my upcoming exam."),
        ("agent.create_goal", "Add an active study objective with 300 weekly minutes."),
        ("agent.create_goal", "Establish a target for finishing linear algebra."),
        ("agent.create_goal", "Save this new learning goal after I confirm it."),
        ("agent.generate_plan", "Generate a draft plan for my active goal."),
        ("agent.generate_plan", "Create daily learning tasks from goal 4."),
        ("agent.generate_plan", "Draft a schedule with 45 minutes per day."),
        ("agent.generate_plan", "Turn my goal into a planned sequence of study tasks."),
        ("agent.generate_plan", "Prepare a learning-plan draft for confirmation."),
        ("agent.generate_report", "Generate my learning report for the last seven days."),
        ("agent.generate_report", "Create a report snapshot of my recent study activity."),
        ("agent.generate_report", "Produce the weekly progress report."),
        ("agent.generate_report", "Summarize my learning data as a report artifact."),
        ("agent.generate_report", "Make the report requested by the learner."),
        ("agent.start_workflow", "Start the resumable resource-to-report learning workflow."),
        ("agent.start_workflow", "Run the complete learning pipeline for course 2."),
        ("agent.start_workflow", "Begin indexing, extraction, questions, and reporting as one workflow."),
        ("agent.remember", "Save my confirmed preference to study in short daily sessions."),
        ("agent.remember", "Remember that my weak point is integration by parts."),
    ]
    for expected, prompt in tool_prompts:
        rows.append({"id": f"cap-{len(rows)+1:03d}", "kind": "tool", "prompt": prompt, "expected": expected})
    assert len(rows) == 100, len(rows)
    return rows


def _score_skill(catalog: AgentSkillCatalog, prompt: str) -> str:
    terms = set(prompt.casefold().split())
    choices = catalog.skill_metadata()
    ranked = sorted(choices, key=lambda item: -sum(
        term in f"{item['name']} {item['description']}".casefold() for term in terms
    ))
    return str(ranked[0]["name"]) if ranked else ""


def _score_capability(prompt: str, *, kind: str) -> str:
    choices = search_capabilities(prompt, client="web", limit=20)
    if kind == "mcp":
        choices = [item for item in choices if str(item["name"]).startswith("mcp.")]
    elif kind == "tool":
        choices = [item for item in choices if not str(item["name"]).startswith("mcp.")]
    return str(choices[0]["name"]) if choices else ""


def _tool_name(capability: str) -> str:
    """Map catalog names to OpenAI function-name-safe identifiers."""
    return "cap__" + capability.replace(".", "__").replace("-", "_")


def _real_model_tools(rows: list[dict[str, Any]], kind: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    from app.agent_runtime.catalog import TOOL_CATALOG

    mapping: dict[str, str] = {}
    if kind == "skill":
        catalog = AgentSkillCatalog()
        candidates = [str(item["name"]) for item in catalog.skill_metadata()]
        descriptions = {str(item["name"]): str(item["description"]) for item in catalog.skill_metadata()}
    elif kind == "mcp":
        candidates = [str(item.name) for item in TOOL_CATALOG if str(item.name).startswith("mcp.")]
        descriptions = {str(item.name): str(item.description) for item in TOOL_CATALOG}
    else:
        candidates = [str(item.name) for item in TOOL_CATALOG if not str(item.name).startswith("mcp.")]
        descriptions = {str(item.name): str(item.description) for item in TOOL_CATALOG}
    tools: list[dict[str, Any]] = []
    for capability in candidates:
        function_name = _tool_name(capability)
        mapping[function_name] = capability
        tools.append({
            "type": "function",
            "function": {
                "name": function_name,
                "description": descriptions.get(capability, capability)[:500],
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        })
    return tools, mapping


def _call_real_model(prompt: str, kind: str, *, client: Any, model: str) -> tuple[str, str]:
    tools, mapping = _real_model_tools([], kind)
    system = (
        "You are evaluating capability routing. Select exactly one function that best satisfies the user request. "
        "Do not answer in prose and do not invent a function. For Skill cases, select the specialist Skill function; "
        "for MCP and tool cases, select the narrowest matching capability."
    )
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        tools=tools,
        tool_choice="required",
        max_tokens=200,
    )
    message = response.choices[0].message
    calls = getattr(message, "tool_calls", None) or []
    if calls:
        name = str(calls[0].function.name)
        return mapping.get(name, ""), "tool_call"
    content = str(getattr(message, "content", "") or "")
    try:
        payload = json.loads(content)
        return str(payload.get("name", "")), "json_fallback"
    except (TypeError, json.JSONDecodeError):
        return "", "no_tool_call"


def run_real(output_dir: Path, *, model: str | None = None, delay_seconds: float = 0.0, workers: int = 8) -> dict[str, Any]:
    """Run all 100 prompts against the configured OpenAI-compatible Chat API."""
    from openai import OpenAI
    from ai.config import get_ai_settings
    from ai.gateways.chat import normalize_openai_base_url

    settings = get_ai_settings()
    if not settings.api_key.strip():
        raise RuntimeError("LEARNING_AI_API_KEY is empty; configure the model API first")
    base_url = normalize_openai_base_url(settings.base_url) if settings.base_url else None
    client = OpenAI(api_key=settings.api_key, base_url=base_url, timeout=min(settings.request_timeout_seconds, 20.0), max_retries=0)
    selected_model = model or settings.chat_model
    rows = _cases()
    records: list[dict[str, Any] | None] = [None] * len(rows)

    def evaluate_one(index: int, row: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        error = ""
        actual = ""
        response_mode = ""
        try:
            actual, response_mode = _call_real_model(row["prompt"], row["kind"], client=client, model=selected_model)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return {**row, "actual": actual, "correct": actual == row["expected"], "response_mode": response_mode, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": error}

    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="capability-eval") as pool:
        futures = {pool.submit(evaluate_one, index, row): index for index, row in enumerate(rows, 1)}
        for future in as_completed(futures):
            index = futures[future]
            records[index - 1] = future.result()
            item = records[index - 1]
            assert item is not None
            print(f"[{index:03d}/100] {item['kind']} expected={item['expected']} actual={item['actual'] or '<none>'} {'OK' if item['correct'] else 'MISS'}", flush=True)
    completed_records = [item for item in records if item is not None]
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in ("skill", "mcp", "tool"):
        subset = [item for item in completed_records if item["kind"] == kind]
        correct = sum(bool(item["correct"]) for item in subset)
        by_kind[kind] = {"cases": len(subset), "correct": correct, "accuracy": correct / len(subset) if subset else 0.0}
    payload = {
        "metadata": {"dataset_version": "capability-routing-100-v1", "created_at": datetime.now(timezone.utc).isoformat(), "mode": "real OpenAI-compatible tool calling", "model": selected_model, "base_url": settings.base_url, "gold_verified": False},
        "summary": {"cases": len(completed_records), "correct": sum(bool(item["correct"]) for item in completed_records), "accuracy": sum(bool(item["correct"]) for item in completed_records) / len(completed_records), "api_errors": sum(bool(item["error"]) for item in completed_records)},
        "by_kind": by_kind, "records": completed_records,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Real Model Capability Routing Benchmark (100 prompts)", "", f"- Model: `{selected_model}`", f"- API mode: OpenAI-compatible Chat Completions tool calling", f"- API errors: {payload['summary']['api_errors']}", "", "| Kind | Cases | Correct | Accuracy |", "|---|---:|---:|---:|"]
    lines.extend(f"| {kind} | {item['cases']} | {item['correct']} | {item['accuracy']:.3f} |" for kind, item in by_kind.items())
    lines.extend(["", f"Overall accuracy: **{payload['summary']['accuracy']:.3f}**", "", "Accuracy means the model selected the expected function/tool name. This does not execute mutating tools or external web searches.", ""])
    (output_dir / "benchmark.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def run(output_dir: Path) -> dict[str, Any]:
    rows = _cases()
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    DATASET.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    catalog = AgentSkillCatalog()
    records: list[dict[str, Any]] = []
    for row in rows:
        if row["kind"] == "skill":
            actual = _score_skill(catalog, row["prompt"])
        elif row["kind"] in {"mcp", "tool"}:
            actual = _score_capability(row["prompt"], kind=row["kind"])
        else:
            actions = infer_actions(row["prompt"])
            actual = actions[0] if actions else "chat"
        records.append({**row, "actual": actual, "correct": actual == row["expected"]})

    by_kind: dict[str, dict[str, Any]] = {}
    confusion: Counter[str] = Counter()
    for item in records:
        if not item["correct"]:
            confusion[f"{item['expected']} -> {item['actual'] or '<none>'}"] += 1
    for kind in ("skill", "mcp", "tool"):
        subset = [item for item in records if item["kind"] == kind]
        correct = sum(bool(item["correct"]) for item in subset)
        by_kind[kind] = {"cases": len(subset), "correct": correct, "accuracy": correct / len(subset) if subset else 0.0}
    available = {str(item["name"]): item for item in tools_for_client("web")}
    contract = {
        "target_capabilities": len({str(row["expected"]) for row in rows if row["kind"] != "skill"}),
        "catalog_targets_present": sum(str(row["expected"]) in available for row in rows if row["kind"] != "skill"),
        "skill_targets_present": sum(any(item["name"] == row["expected"] for item in catalog.skill_metadata()) for row in rows if row["kind"] == "skill"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {"dataset_version": "capability-routing-100-v1", "created_at": datetime.now(timezone.utc).isoformat(), "mode": "offline deterministic metadata router", "gold_verified": False},
        "summary": {"cases": len(rows), "correct": sum(bool(item["correct"]) for item in records), "accuracy": sum(bool(item["correct"]) for item in records) / len(records)},
        "by_kind": by_kind, "confusion": confusion.most_common(20), "contract": contract, "records": records,
    }
    (output_dir / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Capability Routing Benchmark (100 prompts)", "", "- Dataset: `capability-routing-100-v1`", "- Mode: offline deterministic metadata router", "- Gold labels verified: false", "", "| Kind | Cases | Correct | Accuracy |", "|---|---:|---:|---:|"]
    lines.extend(f"| {kind} | {item['cases']} | {item['correct']} | {item['accuracy']:.3f} |" for kind, item in by_kind.items())
    lines.extend(["", f"Overall accuracy: **{payload['summary']['accuracy']:.3f}**", "", "## Top Confusions", "", "| Expected -> Actual | Count |", "|---|---:|"])
    lines.extend(f"| {pair} | {count} |" for pair, count in confusion.most_common(10))
    lines.extend(["", "This is a routing baseline, not an LLM tool-calling score. Run the same JSONL through a configured model adapter for model accuracy; execution success and permission safety should be reported separately.", ""])
    (output_dir / "benchmark.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--real-model", action="store_true", help="Call the configured OpenAI-compatible Chat API")
    parser.add_argument("--model", default=None)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    payload = run_real(args.output_dir, model=args.model, delay_seconds=args.delay_seconds, workers=args.workers) if args.real_model else run(args.output_dir)
    print(json.dumps({"dataset": str(DATASET), "output": str(args.output_dir), "summary": payload["summary"], "by_kind": payload["by_kind"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
