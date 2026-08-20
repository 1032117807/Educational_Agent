# Agent Evaluation Benchmark

This directory is an orchestration and reporting layer. It reuses production
retrieval, memory, tool, Skill, Agent Runtime, and Sub-Agent contracts through
`evaluation/run_evaluation.py`; it does not duplicate product behavior.

## Production Cut Points

| Area | Production implementation | Benchmark coverage |
|---|---|---|
| RAG | `ai/ingestion/loaders.py`, `ai/ingestion/splitter.py`, `ai/retrieval/`, `server/rag_retriever.py` | Keyword retrieval, query rewriting, latency; vector/RRF/rerank require a versioned annotated corpus. |
| Long-term memory | `app/services/agent_memory.py` | Confirmed-memory conflict decisions and soft-version contract. |
| Context engineering | `ai/prompts/`, `app/agent_runtime/context.py` | Progressive Skill disclosure and feature-flag ablations. |
| MCP and tools | `app/services/mcp_gateway.py`, `app/tools/registry.py`, `app/agent_runtime/catalog.py` | Tool contracts, retry stop, and workspace-path rejection. |
| Skills | `app/services/agent_skills.py` | Metadata-only routing contract and disclosure ablation. |
| Multi-Agent | `app/agent_runtime/subagents.py`, `server/agent_stream.py` | Sub-Agent structured return and isolated-context contract. |

## Metrics

- `Recall@K`: distinct relevant chunks in the first K results divided by all
  annotated relevant chunks.
- `Precision@K`: relevant results in the first K divided by K.
- `MRR`: reciprocal rank of the first annotated relevant result.
- `nDCG@K`: discounted cumulative gain normalized by ideal gain at K.
- `P50/P95 latency`: linear-interpolated percentile over repeated real calls;
  high percentiles are marked unavailable for insufficient samples.
- `Tool contract success`: whether observed execution outcome equals the case's
  expected outcome. This is distinct from `tool_call_success`, which is false
  for an intentionally blocked unsafe request.
- `Conflict accuracy`: exact match between `ADD/UPDATE/DELETE/NOOP` annotation
  and the memory service decision. Macro-F1 is available through the shared
  classification evaluator once all four labels have sufficient cases.
- `Skill routing accuracy`: expected Skill equals the top metadata-selected
  Skill. `metadata_only` verifies bodies were not injected into selection.
- `Sub-Agent success`: expected structured completion and assigned agent name.

RAG generation faithfulness/relevancy, OCR CER, LLM judge quality, context
evidence retention, and single-vs-multi-agent quality are intentionally
reported as unavailable until de-identified, human-labeled fixtures and an
optional judge adapter are supplied. No proxy metric is substituted for them.

## Commands

```powershell
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite rag
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite memory
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite tools
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite skills
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite multi_agent
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite safety
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite all
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite smoke
.\.venv\Scripts\python.exe evals\run_benchmark.py --suite benchmark
```

Each command writes `benchmark.json`, `benchmark.csv`, and `benchmark.md` to
`evals/reports/latest/` by default. Fixtures are versioned JSONL templates;
real benchmark claims require replacing templates with reviewed annotations.

## pdfQA PDF/RAG Evaluation

`run_pdfqa_rag.py` downloads only the requested pdfQA subset from Hugging Face,
then runs the project's PDF parser, `CitationAwareSplitter`, SQLite FTS index,
and retrieval metrics. Supporting evidence is mapped to generated chunks by
token overlap because pdfQA annotations do not contain this project's chunk
IDs; the report labels these derived gold IDs as heuristic.

```powershell
.venv\Scripts\python.exe evals\run_pdfqa_rag.py `
  --category FinanceBench --documents 5 --questions-per-document 10 `
  --output-dir evals\reports\pdfqa-rag-financebench-5
```

The report includes parse success, section/chunk counts, evidence coverage,
Recall@3/5/10/20, MRR@10, nDCG@10, Hit Rate@10 and per-query latency. It reports
these variants separately: `keyword_raw`, `query_planner_keyword`,
`agentic_keyword`, `vector`, `rrf`, `rrf_rerank`, and `agentic_rrf`. Vector and
rerank failures are recorded as `unavailable` with the provider error; they are
never converted into a zero score. Gold chunks are derived heuristically from
pdfQA supporting evidence because the public annotations do not contain this
project's internal chunk IDs.

`--suite smoke` preserves the 25 synthetic contract cases. `--suite benchmark`
checks the formal RAG (N>=150), memory (N>=100), and Skill (N>=80) annotation
readiness. It deliberately produces no quality score until Gold labels have
been human-confirmed.
