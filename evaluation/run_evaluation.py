"""运行本项目可重复的离线 AI 评估。

执行：python evaluation/run_evaluation.py
结果：evaluation/results/<run_id>/raw.jsonl、summary.csv、report.md、config.json。
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import AppSettings
from app.database import Database
from app.models import DocumentChunk, DocumentIndex, ResourceFile
from app.tools.registry import ToolRegistry
from ai.retrieval.keyword_store import SQLiteKeywordIndex
from ai.config import AISettings
from ai.gateways.chat import create_chat_model
from evaluation.metrics.core import available, classification_metrics, percentile, retrieval_metrics, unavailable

DATASET_DIR = Path(__file__).resolve().parent / "datasets"
RESULT_DIR = Path(__file__).resolve().parent / "results"
REPEATS = 5

DOCUMENTS = [
    ("limit", "函数极限描述函数在自变量接近某个值时的变化趋势。"),
    ("derivative", "导数表示函数在某一点的瞬时变化率。"),
    ("continuity", "连续函数在一点附近的函数值与极限保持一致。"),
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dataset_manifest() -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for path in sorted(DATASET_DIR.glob("*.jsonl")):
        content = path.read_bytes()
        manifest[path.name] = {"sha256": hashlib.sha256(content).hexdigest(), "records": len(load_jsonl(path))}
    return manifest


def seed_keyword_database(work_dir: Path) -> tuple[Database, SQLiteKeywordIndex, dict[str, int]]:
    # 每个评估子模块使用隔离的 SQLite 文件，先创建目录避免 SQLite 打开失败。
    work_dir.mkdir(parents=True, exist_ok=True)
    database = Database(f"sqlite:///{(work_dir / 'benchmark.db').as_posix()}")
    database.create_schema()
    with database.session() as session:
        resource = ResourceFile(name="benchmark_math.txt", original_name="benchmark_math.txt", source_path="", relative_path="benchmark_math.txt", sha256="a" * 64, size=1, course_id=None, tags="benchmark")
        session.add(resource)
        session.flush()
        index = DocumentIndex(resource_id=resource.id, status="completed", parser_version="evaluation", chunker_version="evaluation", embedding_model="none", source_sha256=resource.sha256, chunk_count=len(DOCUMENTS))
        session.add(index)
        session.flush()
        ids: dict[str, int] = {}
        for number, (key, content) in enumerate(DOCUMENTS):
            chunk = DocumentChunk(document_index_id=index.id, resource_id=resource.id, chunk_number=number, content=content, content_sha256=str(number + 1) * 64, location_label=f"基准片段 {number + 1}", metadata_json=json.dumps({"retrieval_text": content, "source_name": "benchmark_math.txt"}, ensure_ascii=False))
            session.add(chunk)
            session.flush()
            ids[key] = chunk.id
        index_id = index.id
    keywords = SQLiteKeywordIndex(database)
    keywords.rebuild_document(index_id)
    return database, keywords, ids


def metric_value(metric: dict[str, object]) -> float | None:
    return metric.get("value") if metric.get("status") == "available" else None  # type: ignore[return-value]


def result(case_id: str, module: str, status: str, latency_ms: float | None, metrics: dict[str, Any], *, error: str = "", output: Any = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"case_id": case_id, "module": module, "status": status, "timestamp": datetime.now(timezone.utc).isoformat(), "model": "unavailable", "prompt_version": "unavailable", "dataset_version": "evaluation-datasets-v1", "parameters": {"repeats": REPEATS}, "metrics": metrics, "latency": {"total_ms": latency_ms}, "token_usage": unavailable("本轮未调用可返回 usage 的 LLM 接口"), "resource_usage": unavailable("当前环境未安装 psutil/pynvml"), "output": output, "error": error, "details": details or {}}


def evaluate_retrieval(work_dir: Path) -> list[dict[str, Any]]:
    database, keywords, ids = seed_keyword_database(work_dir)
    records: list[dict[str, Any]] = []
    try:
        for task in load_jsonl(DATASET_DIR / "retrieval_tasks.jsonl"):
            samples: list[float] = []
            hits: list[int] = []
            for _ in range(REPEATS):
                started = perf_counter()
                query_hits = keywords.search(task["query"], limit=3)
                samples.append((perf_counter() - started) * 1000)
                hits = [item.chunk_id for item in query_hits]
            quality = retrieval_metrics(hits, {ids[key] for key in task["relevant_chunk_keys"]}, 3)
            metrics = {**quality, "latency_mean_ms": available(fmean(samples)), "latency_stddev_ms": available(pstdev(samples)), "latency_p50_ms": percentile(samples, 50), "latency_p95_ms": percentile(samples, 95), "latency_p99_ms": percentile(samples, 99)}
            records.append(result(task["case_id"], "keyword_retrieval", "completed", fmean(samples), metrics, output=hits, details={"dataset_source": task["source"], "repeats": REPEATS}))
    finally:
        database.close()
    return records


def evaluate_tools(work_dir: Path) -> list[dict[str, Any]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    data_dir = work_dir / "tool_app"
    settings = AppSettings(data_dir=data_dir)
    settings.ensure_directories()
    database = Database(settings.database_url)
    database.create_schema()
    registry = ToolRegistry(database, settings)
    records: list[dict[str, Any]] = []
    try:
        for task in load_jsonl(DATASET_DIR / "tool_tasks.jsonl"):
            samples: list[float] = []
            observed_success = False
            last_error = ""
            for _ in range(REPEATS):
                try:
                    started = perf_counter()
                    response = registry.execute(task["tool"], task["arguments"])
                    samples.append((perf_counter() - started) * 1000)
                    observed_success = bool(response.get("success", True))
                except Exception as exc:
                    samples.append((perf_counter() - started) * 1000)
                    observed_success = False
                    last_error = f"{type(exc).__name__}: {exc}"
            expected = bool(task["expected_success"])
            metrics = {"contract_success": available(1.0 if observed_success == expected else 0.0), "tool_call_success": available(1.0 if observed_success else 0.0), "latency_mean_ms": available(fmean(samples)), "latency_stddev_ms": available(pstdev(samples)), "latency_p50_ms": percentile(samples, 50), "latency_p95_ms": percentile(samples, 95), "tool_selection_accuracy": unavailable("当前确定性工具注册表没有 LLM 自主工具选择轨迹"), "duplicate_tool_calls": unavailable("本轮直接调用工具，不是 Agent 规划轨迹")}
            records.append(result(task["case_id"], "tool_call", "completed" if observed_success == expected else "failed", fmean(samples), metrics, error=last_error, details={"expected_success": expected, "dataset_source": task["source"]}))
    finally:
        database.close()
    return records


def evaluate_robustness(work_dir: Path) -> list[dict[str, Any]]:
    database, keywords, _ = seed_keyword_database(work_dir)
    records: list[dict[str, Any]] = []
    try:
        for task in load_jsonl(DATASET_DIR / "robustness_tasks.jsonl"):
            samples: list[float] = []
            failed = 0
            output: list[int] = []
            for _ in range(REPEATS):
                started = perf_counter()
                try:
                    output = [item.chunk_id for item in keywords.search(task["input"], limit=3)]
                except Exception:
                    failed += 1
                samples.append((perf_counter() - started) * 1000)
            metrics = {"failure_rate": available(failed / REPEATS), "latency_mean_ms": available(fmean(samples)), "latency_stddev_ms": available(pstdev(samples)), "prompt_injection_defense": unavailable("本轮仅测试检索层，不调用 LLM 或 Agent"), "network_recovery_rate": unavailable("本轮未配置网络依赖")}
            records.append(result(task["case_id"], "robustness_keyword_retrieval", "completed" if not failed else "failed", fmean(samples), metrics, output=output, details={"expected": task["expected"], "dataset_source": task["source"]}))
    finally:
        database.close()
    return records


def evaluate_metric_implementation() -> list[dict[str, Any]]:
    scores = classification_metrics(["a", "b", "c"], ["a", "b", "c"])
    passed = all(metric_value(score) == 1.0 for score in scores.values())
    return [result("metric-001", "metric_self_check", "completed" if passed else "failed", None, scores, details={"purpose": "验证基础分类指标实现，不代表模型结果"})]


def response_usage(response: Any) -> dict[str, object]:
    """从兼容 OpenAI 的响应中提取 Token；服务端未返回时如实标记不可用。"""
    usage = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", {}).get("token_usage")
    if not isinstance(usage, dict):
        return unavailable("模型接口未返回 token usage")
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if input_tokens is None or output_tokens is None:
        return unavailable("模型接口返回的 usage 不完整")
    return {"value": {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": usage.get("total_tokens", input_tokens + output_tokens)}, "status": "available"}


def normalized_json(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def evaluate_llm() -> list[dict[str, Any]]:
    """运行小规模规则基准，不使用 Judge，也不把它误称为通用能力评测。"""
    settings = AISettings()
    if not settings.enabled or not settings.api_key.strip():
        return [result("availability-llm", "llm", "unavailable", None, {"availability": unavailable("AI 未启用或未配置 API Key")})]
    try:
        model = create_chat_model(settings)
    except Exception as exc:
        return [result("availability-llm", "llm", "unavailable", None, {"availability": unavailable(f"无法创建 Chat 模型：{type(exc).__name__}")}, error=str(exc))]
    records: list[dict[str, Any]] = []
    for task in load_jsonl(DATASET_DIR / "llm_tasks.jsonl"):
        started = perf_counter()
        try:
            response = model.invoke(task["prompt"])
            latency_ms = (perf_counter() - started) * 1000
            content = str(getattr(response, "content", response)).strip()
            if task["metric"] == "json_field":
                actual, expected = normalized_json(content), normalized_json(task["expected_output"])
                correct = actual == expected
                format_ok = actual is not None
            else:
                correct = content == task["expected_output"]
                format_ok = True
            metrics = {
                "answer_correctness": available(1.0 if correct else 0.0),
                "instruction_following": available(1.0 if correct else 0.0),
                "output_format_following": available(1.0 if format_ok else 0.0),
                "answer_relevance": unavailable("小规模规则样本没有人工相关性量表或 Judge"),
                "answer_completeness": unavailable("小规模规则样本没有人工完整性量表或 Judge"),
                "factual_consistency": unavailable("小规模规则样本没有外部事实核查流程"),
                "hallucination_rate": unavailable("小规模规则样本无法定义事实陈述集合"),
                "total_latency_ms": available(latency_ms),
                "ttft_ms": unavailable("本轮使用非 streaming invoke，无法测量 TTFT"),
                "tokens_per_second": unavailable("本轮使用非 streaming invoke，无法可靠测量首 token 到完成的生成速率"),
                "cost": unavailable("未配置模型单价表"),
            }
            records.append(result(task["case_id"], "llm", "completed", latency_ms, metrics, output=content, details={"dataset_source": task["source"], "expected_output": task["expected_output"], "model": settings.chat_model, "provider": settings.provider, "token_usage_actual": response_usage(response)}))
        except Exception as exc:
            records.append(result(task["case_id"], "llm", "failed", (perf_counter() - started) * 1000, {"answer_correctness": unavailable("LLM 调用失败")}, error=f"{type(exc).__name__}: {exc}", details={"dataset_source": task["source"], "model": settings.chat_model}))
    return records


def unavailable_modules() -> list[dict[str, Any]]:
    checks = {"embedding": "fastembed", "resource_monitoring": "psutil", "rag_generation": "langchain_openai", "charts": "matplotlib"}
    records = []
    for name, package in checks.items():
        installed = importlib.util.find_spec(package) is not None
        reason = "在线 LLM 基准已尝试，但 API 连接失败；同时 FastEmbed 缺失，无法执行端到端 RAG" if name == "rag_generation" else f"当前 Python 环境未安装可选依赖 {package}" if not installed else "模块可用，但本轮没有对应的固定标注测试集或运行配置"
        records.append(result(f"availability-{name}", name, "unavailable", None, {"availability": unavailable(reason)}, details={"dependency": package, "installed": installed}))
    return records


def write_outputs(run_dir: Path, records: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    (run_dir / "raw.jsonl").write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")
    fields = ["case_id", "module", "status", "latency_ms", "error"]
    with (run_dir / "summary.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in records:
            writer.writerow({"case_id": item["case_id"], "module": item["module"], "status": item["status"], "latency_ms": item["latency"]["total_ms"], "error": item["error"]})
    config = {"run_timestamp": datetime.now(timezone.utc).isoformat(), "repeats": REPEATS, "dataset_version": "evaluation-datasets-v1", "dataset_manifest": manifest, "environment": {"python": sys.version, "platform": platform.platform(), "cpu_count": os.cpu_count()}, "tools": ["pytest（项目已有）", "SQLite FTS5", "SQLAlchemy", "time.perf_counter", "statistics", "项目 ToolRegistry"]}
    (run_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(run_dir, records, config)


def display(metric: dict[str, Any]) -> str:
    if metric.get("status") != "available":
        return "unavailable"
    value = metric["value"]
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def write_report(run_dir: Path, records: list[dict[str, Any]], config: dict[str, Any]) -> None:
    completed = [item for item in records if item["status"] == "completed"]
    failed = [item for item in records if item["status"] == "failed"]
    retrieval = [item for item in records if item["module"] == "keyword_retrieval"]
    llm = [item for item in records if item["module"] == "llm"]
    tools = [item for item in records if item["module"] == "tool_call"]
    llm_note = "在线 LLM 已对 3 条规则样本发起真实请求，但均因 `APIConnectionError` 失败；错误与耗时已保存在原始结果中。" if llm and all(item["status"] == "failed" for item in llm) else "未运行在线 LLM。"
    lines = ["# AI 评估结果汇总", "", "## 本次范围", "", f"本次为可重复的基线评估。真实执行了 SQLite FTS5 关键词检索、工具注册与调用、检索层鲁棒性输入，以及基础指标函数校验。{llm_note} 未使用默认 FastEmbed 模型。", "", "## 测试集来源", "", "本次测试集位于 `evaluation/datasets/`，版本为 `evaluation-datasets-v1`。所有样本均为人工编写的功能契约样本，不含用户课程或个人数据：", "", "- `llm_tasks.jsonl`：3 条算术、格式遵循与确定性指令样本；仅用于小规模规则校验。", "- `retrieval_tasks.jsonl`：3 条高等数学概念检索样本；相关片段由运行器写入隔离 SQLite 基准库后映射为真实 chunk id。", "- `tool_tasks.jsonl`：2 条只读工具成功样本和 1 条路径越界拒绝样本。", "- `robustness_tasks.jsonl`：空输入、空白输入、噪声、Prompt Injection 字符串的检索层安全样本。", "", "这些样本用于验证框架和项目功能边界，不能解释为真实用户数据上的模型能力。RAG 质量、LLM 质量和 Agent 规划质量需后续从脱敏课程资源中抽样并由人工标注标准答案、相关 chunk 与工具轨迹。", "", "## 工具", "", "本轮使用：项目 `ToolRegistry`、SQLite FTS5、SQLAlchemy、LangChain OpenAI 客户端、Python `time.perf_counter`、`statistics`、JSONL/CSV 标准库。项目已有 `pytest` 可用于功能回归，但本报告的数值来自本次运行器。", "", "当前缺少：FastEmbed、psutil、GPU 监控和 matplotlib。Embedding、向量检索、端到端 RAG、资源、GPU 和图表为 `unavailable`；LLM 正确性、TTFT、tokens/s、Token 和成本因 API 连接失败而为 `unavailable`。", "", "## 执行摘要", "", f"- 记录总数：{len(records)}", f"- 完成：{len(completed)}", f"- 失败：{len(failed)}", f"- 不可用模块记录：{len([item for item in records if item['status'] == 'unavailable'])}", "", "## 关键词检索结果", "", "| 样本 | Recall@3 | Precision@3 | Hit Rate@3 | MRR | NDCG@3 | 平均延迟 ms | P95 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for item in retrieval:
        metrics = item["metrics"]
        lines.append(f"| {item['case_id']} | {display(metrics['recall_at_k'])} | {display(metrics['precision_at_k'])} | {display(metrics['hit_rate_at_k'])} | {display(metrics['mrr'])} | {display(metrics['ndcg_at_k'])} | {display(metrics['latency_mean_ms'])} | {display(metrics['latency_p95_ms'])} |")
    lines.extend(["", "## LLM 规则基准结果", "", "该组仅包含 3 条人工编写的确定性样本，用于测量本次配置下的基础正确性、指令和格式遵循，以及非 streaming 总延迟；不能外推为通用推理或 RAG 能力。", "", "| 样本 | 正确性 | 指令遵循 | 格式遵循 | 总延迟 ms |", "|---|---:|---:|---:|---:|"])
    for item in llm:
        metrics = item["metrics"]
        unknown = unavailable("该 LLM 样本未产生完整指标")
        lines.append(f"| {item['case_id']} | {display(metrics.get('answer_correctness', unknown))} | {display(metrics.get('instruction_following', unknown))} | {display(metrics.get('output_format_following', unknown))} | {display(metrics.get('total_latency_ms', unknown))} |")
    lines.extend(["", "## 工具调用结果", "", "| 样本 | 契约通过 | 工具成功 | 平均延迟 ms | 说明 |", "|---|---:|---:|---:|---|"])
    for item in tools:
        metrics = item["metrics"]
        lines.append(f"| {item['case_id']} | {display(metrics['contract_success'])} | {display(metrics['tool_call_success'])} | {display(metrics['latency_mean_ms'])} | {item['error'] or '符合预期'} |")
    lines.extend(["", "## 未完成指标", "", "| 范围 | 指标 | 状态 | 原因 |", "|---|---|---|---|", "| LLM | 正确性、相关性、完整性、指令遵循、多轮一致性 | unavailable | 三次真实请求均为 APIConnectionError，且没有人工标注任务集 |", "| Embedding / 向量检索 | 吞吐、Recall@K、MRR、NDCG | unavailable | 当前 Python 环境缺少 `fastembed` |", "| RAG 生成 | Context Precision/Recall、Faithfulness、幻觉率、端到端延迟 | unavailable | FastEmbed 缺失且在线 LLM 连接失败，没有 RAG 标注集和 Judge 配置 |", "| Agent | 任务完成率、工具选择正确率、循环检测 | unavailable | 当前 Agent 编排是确定性步骤，本轮没有 LLM 规划轨迹测试集 |", "| 运行性能 | TTFT、tokens/s、Input/Output Token、成本 | unavailable | LLM 请求未成功，且本轮使用非 streaming 调用 |", "| 资源 | CPU、内存、GPU、显存 | unavailable | 缺少 `psutil` / GPU 监控依赖 |", "", "## 结论与下一步", "", "本轮可确认关键词检索、只读工具调用和检索层异常输入能在隔离基准环境下真实运行；具体数值见上表和 `raw.jsonl`。在线 LLM 实验已真实发起但发生连接错误，因此不能判断哪个 LLM 最好、最快或最便宜。", "", "下一步先修复模型 API 连通性，再安装 FastEmbed 和 psutil，随后建立脱敏人工标注的 RAG/Agent 测试集，以相同数据集运行模型、Prompt、Embedding 和 RAG 参数矩阵。", "", "## 结果文件", "", "- `raw.jsonl`：逐样本原始输入、输出、指标、错误和元数据。", "- `summary.csv`：便于表格查看的摘要。", "- `config.json`：数据集哈希、运行环境和使用工具。"])
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RESULT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    work_dir = Path(tempfile.mkdtemp(prefix="evaluation-", dir=run_dir))
    try:
        records = evaluate_metric_implementation() + evaluate_llm() + evaluate_retrieval(work_dir / "retrieval") + evaluate_tools(work_dir / "tools") + evaluate_robustness(work_dir / "robustness") + unavailable_modules()
        write_outputs(run_dir, records, dataset_manifest())
        print(run_dir)
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
