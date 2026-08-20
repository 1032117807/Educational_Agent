"""Evaluate the production PDF parsing, chunking and keyword retrieval path on pdfQA.

Only the requested document subset is downloaded from Hugging Face. Gold chunk
IDs are derived from pdfQA's ``sources`` supporting spans by overlap with the
chunks produced by this project; the report labels these derived labels as
heuristic because the public annotations do not publish this project's IDs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from huggingface_hub import hf_hub_download, list_repo_files

from app.database import Database
from app.models import DocumentChunk, DocumentIndex, ResourceFile
from ai.ingestion.loaders import DocumentParserRegistry
from ai.ingestion.splitter import CitationAwareSplitter
from ai.retrieval.keyword_store import SQLiteKeywordIndex, tokenize_for_search
from ai.retrieval.hybrid import HybridRetriever
from ai.retrieval.agentic import AgenticRAG
from ai.retrieval.vector_store import ChromaVectorIndex
from ai.gateways.embeddings import create_embedding_model
from ai.gateways.rerank import create_reranker
from ai.config import get_ai_settings
from app.agent_runtime import AgentBudget
from evaluation.metrics.core import retrieval_metrics

ANNOTATION_REPO = "pdfqa/pdfQA-Annotations"
BENCHMARK_REPO = "pdfqa/pdfQA-Benchmark"


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("\u00a0", " ")).strip()


def _evidence_spans(sources: list[Any]) -> list[str]:
    spans: list[str] = []
    for item in sources:
        text = str(item)
        if "{" in text:
            text = text.split("{", 1)[1]
        text = text.rsplit("}", 1)[0]
        if len(_norm(text)) >= 20:
            spans.append(text)
    return spans


def _gold_chunks(chunks: list[dict[str, Any]], spans: list[str]) -> tuple[set[int], int, int]:
    """Map supporting spans to generated chunks using token overlap."""
    relevant: set[int] = set()
    covered = 0
    for span in spans:
        span_tokens = set(tokenize_for_search(span))
        if not span_tokens:
            continue
        ranked = []
        for chunk in chunks:
            chunk_tokens = set(tokenize_for_search(str(chunk["content"])))
            overlap = len(span_tokens & chunk_tokens) / max(1, min(len(span_tokens), 120))
            ranked.append((overlap, int(chunk["id"])))
        ranked.sort(reverse=True)
        matches = [item for item in ranked if item[0] >= 0.18][:5]
        if matches:
            covered += 1
            relevant.update(chunk_id for _, chunk_id in matches)
    return relevant, covered, len(spans)


def _download_subset(category: str, documents: int) -> list[tuple[str, Path, list[dict[str, Any]]]]:
    annotation_files = sorted(
        item for item in list_repo_files(ANNOTATION_REPO, repo_type="dataset")
        if item.startswith(f"real-pdfQA/{category}/") and item.endswith(".json")
    )[:documents]
    if not annotation_files:
        raise ValueError(f"No pdfQA annotation files found for category {category!r}")
    result = []
    for annotation_file in annotation_files:
        filename = annotation_file.rsplit("/", 1)[1][:-5]
        annotation_path = hf_hub_download(ANNOTATION_REPO, filename=annotation_file, repo_type="dataset")
        pdf_file = f"real-pdfQA/01.2_Input_Files_PDF/{category}/{filename}.pdf"
        pdf_path = Path(hf_hub_download(BENCHMARK_REPO, filename=pdf_file, repo_type="dataset"))
        rows = json.loads(Path(annotation_path).read_text(encoding="utf-8"))
        result.append((filename, pdf_path, rows if isinstance(rows, list) else []))
    return result


def _persist_document(database: Database, pdf_path: Path, parser: DocumentParserRegistry, splitter: CitationAwareSplitter) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    parsed = parser.parse(pdf_path)
    drafts = splitter.split_document(parsed)
    with database.session() as session:
        resource = ResourceFile(
            name=pdf_path.name, original_name=pdf_path.name, source_path=str(pdf_path),
            relative_path=pdf_path.name, sha256="pdfqa-" + str(abs(hash(pdf_path.name))),
            size=pdf_path.stat().st_size, course_id=None, tags="pdfqa", tenant_id="pdfqa",
        )
        session.add(resource); session.flush()
        index = DocumentIndex(
            tenant_id="pdfqa", resource_id=resource.id, status="completed",
            parser_version=parsed.parser_version, chunker_version=splitter.version,
            embedding_model="none", source_sha256=resource.sha256, chunk_count=len(drafts),
        )
        session.add(index); session.flush()
        chunks: list[dict[str, Any]] = []
        for draft in drafts:
            row = DocumentChunk(
                tenant_id="pdfqa", document_index_id=index.id, resource_id=resource.id,
                chunk_number=draft.chunk_number, content=draft.content,
                content_sha256=draft.content_sha256, page_start=draft.page_start,
                page_end=draft.page_end, line_start=draft.line_start, line_end=draft.line_end,
                section_title=draft.section_title, location_label=draft.location_label,
                metadata_json=json.dumps({**draft.metadata, "retrieval_text": draft.retrieval_text}, ensure_ascii=False),
                vector_id=None, token_count=0,
            )
            session.add(row); session.flush()
            chunks.append({"id": row.id, "content": row.content, "page_start": row.page_start, "chunk_number": row.chunk_number})
    return index.id, chunks, {"resource_id": resource.id, "index_id": index.id, "parsed_characters": parsed.total_characters, "sections": len(parsed.sections), "chunks": len(chunks)}


VARIANTS = ("keyword_raw", "query_planner_keyword", "agentic_keyword", "vector", "rrf", "rrf_rerank", "agentic_rrf")


def _metric_bundle(hit_ids: list[int], relevant: set[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k in (3, 5, 10, 20):
        for name, value in retrieval_metrics(hit_ids, relevant, k).items():
            result[f"{name.removesuffix('_at_k')}_at_{k}"] = value
    return result


def _mean_metric(records: list[dict[str, Any]], variant: str, name: str) -> float | None:
    values = [r["metrics"][name]["value"] for r in records if r.get("variant") == variant and r.get("metrics", {}).get(name, {}).get("status") == "available"]
    return sum(values) / len(values) if values else None


def run(*, category: str, documents: int, questions_per_document: int, chunk_size: int, chunk_overlap: int, ocr: bool, output_dir: Path) -> dict[str, Any]:
    subset = _download_subset(category, documents)
    records: list[dict[str, Any]] = []
    variant_errors: dict[str, str] = {}
    parser = DocumentParserRegistry(ocr_enabled=ocr)
    splitter = CitationAwareSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, contextual_retrieval_enabled=True)
    with tempfile.TemporaryDirectory(prefix="pdfqa-rag-", ignore_cleanup_errors=True) as work:
        database = Database(f"sqlite:///{(Path(work) / 'pdfqa.db').as_posix()}")
        database.create_schema()
        index = SQLiteKeywordIndex(database)
        settings = get_ai_settings()
        vector_index = None
        hybrid = None
        rerank_hybrid = None
        try:
            embeddings = create_embedding_model(settings)
            vector_index = ChromaVectorIndex(database=database, embeddings=embeddings, persist_directory=Path(work) / "vectors", embedding_model=settings.embedding_model, collection_prefix="pdfqa_eval")
        except Exception as exc:
            variant_errors["vector"] = f"{type(exc).__name__}: {exc}"
            variant_errors["rrf"] = variant_errors["vector"]
            variant_errors["agentic_rrf"] = variant_errors["vector"]
        try:
            for filename, pdf_path, annotations in subset:
                started = time.perf_counter()
                try:
                    index_id, chunks, parse_stats = _persist_document(database, pdf_path, parser, splitter)
                    index.rebuild_document(index_id)
                    if vector_index is not None:
                        # DocumentIndex.embedding_model must match the active embedding model.
                        with database.session() as session:
                            from app.models import DocumentIndex
                            session.get(DocumentIndex, index_id).embedding_model = settings.embedding_model
                        try:
                            vector_index.index_document(index_id)
                        except Exception as exc:
                            variant_errors["vector"] = f"{type(exc).__name__}: {exc}"
                            variant_errors["rrf"] = variant_errors["vector"]
                            variant_errors["agentic_rrf"] = variant_errors["vector"]
                            vector_index = None
                    if vector_index is not None:
                        hybrid = HybridRetriever(database=database, keyword_index=index, vector_index=vector_index, reranker=None)
                        try:
                            rerank_hybrid = HybridRetriever(database=database, keyword_index=index, vector_index=vector_index, reranker=create_reranker(settings))
                            if rerank_hybrid.reranker is None:
                                variant_errors["rrf_rerank"] = "rerank is disabled or no rerank API key is configured"
                        except Exception as exc:
                            variant_errors["rrf_rerank"] = f"{type(exc).__name__}: {exc}"
                    questions = annotations[:questions_per_document]
                    for number, annotation in enumerate(questions, 1):
                        spans = _evidence_spans(annotation.get("sources", []))
                        relevant, covered, span_count = _gold_chunks(chunks, spans)
                        question = str(annotation.get("question", ""))
                        planner = __import__("ai.retrieval.query_planner", fromlist=["RetrievalQueryPlanner"]).RetrievalQueryPlanner()
                        plan = planner.plan(question)
                        calls: dict[str, tuple[list[int], list[str], str]] = {}
                        calls["keyword_raw"] = ([h.chunk_id for h in index.search(question, limit=20)], [], question)
                        calls["query_planner_keyword"] = ([h.chunk_id for h in index.search(plan.keyword_query, limit=20)], [], plan.keyword_query)
                        h, obs = AgenticRAG(lambda q, **kw: index.search(q, limit=20), budget=AgentBudget(max_tool_calls=2, max_rag_searches=2)).search(question)
                        calls["agentic_keyword"] = ([x.chunk_id for x in h], [o.query for o in obs], obs[0].query if obs else question)
                        if vector_index is not None and hybrid is not None:
                            h = hybrid.retrieve(question, limit=20, candidate_limit=30)
                            calls["rrf"] = ([x.chunk_id for x in h], [], question)
                            if rerank_hybrid is not None and rerank_hybrid.reranker is not None:
                                h = rerank_hybrid.retrieve(question, limit=20, candidate_limit=30)
                                calls["rrf_rerank"] = ([x.chunk_id for x in h], [], question)
                            h, obs = AgenticRAG(lambda q, **kw: hybrid.retrieve(q, limit=20, candidate_limit=30), budget=AgentBudget(max_tool_calls=2, max_rag_searches=2)).search(question)
                            calls["agentic_rrf"] = ([x.chunk_id for x in h], [o.query for o in obs], obs[0].query if obs else question)
                            h = vector_index.search(question, limit=20)
                            calls["vector"] = ([x.chunk_id for x in h], [], question)
                        for variant in VARIANTS:
                            if variant not in calls:
                                records.append({"id": f"{category}:{filename}:{number}:{variant}", "variant": variant, "category": category, "document": filename, "question": question, "source_spans": span_count, "covered_spans": covered, "evidence_coverage": covered / span_count if span_count else None, "gold_chunk_count": len(relevant), "retrieved_chunk_ids": [], "metrics": {}, "query_used": "", "agentic_queries": [], "parse": parse_stats, "latency_ms": 0.0, "error": variant_errors.get(variant, "variant unavailable")})
                                continue
                            hit_ids, queries, query_used = calls[variant]
                            records.append({"id": f"{category}:{filename}:{number}:{variant}", "variant": variant, "category": category, "document": filename, "question": question, "answer": annotation.get("answer", ""), "source_spans": span_count, "covered_spans": covered, "evidence_coverage": covered / span_count if span_count else None, "gold_chunk_count": len(relevant), "retrieved_chunk_ids": hit_ids, "metrics": _metric_bundle(hit_ids, relevant) if relevant else {}, "query_used": query_used, "agentic_queries": queries, "parse": parse_stats, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": ""})
                except Exception as exc:
                    records.append({"id": f"{category}:{filename}", "category": category, "document": filename, "question": "", "source_spans": 0, "covered_spans": 0, "evidence_coverage": None, "metrics": {}, "parse": {}, "latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": f"{type(exc).__name__}: {exc}"})
        finally:
            if vector_index is not None:
                client = getattr(vector_index.vector_store, "_client", None)
                if client is not None:
                    try:
                        client.reset()
                    except Exception:
                        pass
            database.close()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"metadata": {"dataset": "pdfQA", "category": category, "documents": documents, "questions_per_document": questions_per_document, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap, "ocr": ocr, "variants": VARIANTS, "gold_label_method": "derived from pdfQA sources by token-overlap with generated chunks; not official chunk IDs"}, "summary": {"records": len(records), "errors": sum(bool(item.get("error")) for item in records), "document_errors": sum(bool(item.get("error")) and not item.get("variant") for item in records), "variant_unavailable": sum(bool(item.get("error")) and bool(item.get("variant")) for item in records), "variant_errors": variant_errors, "by_variant": {v: {"records": sum(r.get("variant") == v for r in records), "usable": sum(r.get("variant") == v and not r.get("error") and bool(r.get("metrics")) for r in records), "recall_at_3": _mean_metric(records, v, "recall_at_3"), "recall_at_5": _mean_metric(records, v, "recall_at_5"), "recall_at_10": _mean_metric(records, v, "recall_at_10"), "recall_at_20": _mean_metric(records, v, "recall_at_20"), "mrr_at_10": _mean_metric(records, v, "mrr_at_10"), "ndcg_at_10": _mean_metric(records, v, "ndcg_at_10"), "hit_rate_at_10": _mean_metric(records, v, "hit_rate_at_10") } for v in VARIANTS}}, "records": records}
    (output_dir / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# pdfQA Retrieval Matrix", "", f"- Category: `{category}`", f"- Documents: {documents}", f"- Chunk config: `{chunk_size}` chars / `{chunk_overlap}` overlap", f"- OCR: `{ocr}`", "", "| Variant | Usable | Recall@3 | Recall@5 | Recall@10 | Recall@20 | MRR@10 | nDCG@10 | Hit Rate@10 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for variant, values in payload["summary"]["by_variant"].items():
        fmt = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else "unavailable"
        lines.append(f"| {variant} | {values['usable']} | {fmt(values['recall_at_3'])} | {fmt(values['recall_at_5'])} | {fmt(values['recall_at_10'])} | {fmt(values['recall_at_20'])} | {fmt(values['mrr_at_10'])} | {fmt(values['ndcg_at_10'])} | {fmt(values['hit_rate_at_10'])} |")
    lines += ["", "Gold chunk IDs are derived by overlap with pdfQA supporting spans; they are not official chunk IDs.", "Variant errors: `" + json.dumps(variant_errors, ensure_ascii=False) + "`", ""]
    (output_dir / "benchmark.md").write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="FinanceBench")
    parser.add_argument("--documents", type=int, default=1)
    parser.add_argument("--questions-per-document", type=int, default=10)
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evals" / "reports" / "pdfqa-rag-latest")
    args = parser.parse_args()
    payload = run(category=args.category, documents=max(1, args.documents), questions_per_document=max(1, args.questions_per_document), chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap, ocr=args.ocr, output_dir=args.output_dir)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
