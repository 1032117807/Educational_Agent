# Agent Harness Audit

## Scope

This audit covers the desktop and SaaS Agent call paths before the incremental
Harness V2 work. It does not replace APIs, database entities, or tenant boundaries.

## Current Call Paths

| Client | Path | Observation |
| --- | --- | --- |
| Desktop | UI -> `LearningPlanAgentService.respond()` -> `AgentDecision` -> UI/service execution | Structured decision output, local tool registry, MCP gateway, confirmation and local session services are present. |
| Web | `/agent/sessions/.../stream` -> shared runtime evidence collection -> model stream -> background `run_learning_agent()` | The runtime collects tenant-scoped snapshot and optional web evidence with observation envelopes. When enabled, independent snapshot/web evidence is isolated into bounded parallel Sub-Agents. The deterministic intent router remains a compatibility fast path for durable background dispatch. |

## Retained Components

- `app/agent_runtime/catalog.py` and `contracts.py` remain the cross-client action and confirmation contract.
- Workspace boundaries, default-deny permissions, one-time MCP approvals, read-only/no-network sandboxing, soft delete, citations, and tenant isolation remain mandatory.
- Existing deterministic specialist workflows remain deterministic workflows; they are not converted into unconstrained agents.
- Desktop FTS5/Chroma/RRF and SaaS pgvector/reranker remain the retrieval base.

## Findings And Phase Mapping

| Finding | Risk | Change location | Verification |
| --- | --- | --- | --- |
| Desktop prompt contained duplicate system rules and business-local prompt text. | Drift and costly context. | `ai/prompts/`, `learning_plan_agent.py` | Prompt renderer/version tests. |
| Enabled Skill bodies were injected into every desktop context. | Context bloat and unsafe progressive disclosure. | `agent_skills.py` | Metadata/load tests. |
| No program-owned status or budget contract existed in `app/agent_runtime`. | Unbounded future loops and unobservable state. | `state.py`, `budget.py` | Status and retry tests. |
| Desktop decision service and Web durable intent dispatch retain different adapters. | Semantic divergence for multi-step action planning. | Web background action execution now uses the shared Runtime after structured planning; desktop model planning remains an adapter boundary. | Runtime confirmation/observation tests, Web runtime evidence tests, and canonical action tests. |
| Tool/MCP/catalog metadata differ. | Tool selection and audit ambiguity. | Phase B: unified capability model. | Schema parity tests. |
| Retrieval, memory conflict handling, sub-agent isolation, and evaluation datasets are incomplete. | Quality and safety regressions if introduced ad hoc. | Phases C-F. | Requirement-specific evaluation suites. |

## Phase A Result

Phase A adds a versioned prompt renderer, metadata-first Skills with explicit loading, a program-owned status bar, configurable execution budgets, and feature flags. It leaves existing execution and safety mechanisms intact.

## Requirement-Level Evidence

| Prompt sections | Delivered evidence |
| --- | --- |
| 1-11: call chains, Runtime, budgets, prompt, status, context and compression | `app/agent_runtime/`, `ai/prompts/`, Desktop runtime adapter tests and `tests/test_agent_runtime_react.py`. |
| 12-22: Skills, capability model, observations, safety and MCP lifecycle | `app/services/agent_skills.py`, `app/agent_runtime/catalog.py`, `app/services/mcp_gateway.py`, `tests/test_agent_runtime_catalog.py`, `tests/test_mcp_gateway.py`, and `MCP_LIFECYCLE_DECISION.md`. |
| 23-32: hybrid RAG, rerank, contextual retrieval, rewrite, Agentic RAG and citations | `ai/retrieval/`, `ai/ingestion/splitter.py`, `server/rag_retriever.py`, `server/rag_worker.py`, and retrieval regression tests. The optional LLM contextual prefix is intentionally not enabled: deterministic document metadata contextualization is the default indexing path. |
| 33-38: dual-layer memory | `app/services/agent_memory.py`, existing `AgentMessage` retrieval, confirmation tests, and the memory-conflict evaluation dataset. |
| 39-47: specialists, isolated Sub-Agents and injection handling | `ai/agents/specialists.py`, `app/agent_runtime/subagents.py`, production Web evidence collection, `ai/prompts/agent_base.py`, and `tests/test_agent_subagents.py`. |
| 48-51: flags, evaluation, ablations and regression cases | `.env.example`, `evaluation/run_evaluation.py`, `evaluation/ablation.py`, six Harness JSONL datasets and `242` passing tests. |
| 52-56: priority files, phased delivery, retained constraints, architecture and report | The listed priority modules were changed incrementally; the retained constraints and final architecture are documented in `AGENT_HARNESS_V2.md`. |

No change in this work permits direct model SQL, arbitrary shell access, sandbox networking, cross-tenant reads, unconfirmed writes, or citation bypass.
