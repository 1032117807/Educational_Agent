# Agent Harness V2

## Architecture

The project retains its existing desktop service, Web streaming API, workflow
services, tool registry, MCP gateway, and tenant isolation. Harness V2 adds a
shared runtime layer in `app/agent_runtime` rather than a parallel framework.

`AgentRuntime` runs a bounded decision -> tool -> observation loop. It records
only decision summaries, actions, observations, and validation events in
`AgentTrajectory`; private model reasoning is neither requested nor persisted.

The Web streaming path now uses that runtime for tenant-scoped learning
snapshot collection and optional public-web evidence collection. Its existing
intent router remains a deterministic compatibility/fast path for durable
background feature dispatch; it emits the same canonical `generate_plan`
action as the Desktop client.

For background jobs, Web action planning first requests a bounded
`WebActionPlan` structured response from the configured model. The resulting
actions are then executed through the same bounded `AgentRuntime`, which owns
the observation trail and confirmation boundary. The deterministic router is
used only if that model is unavailable or returns an invalid plan.

Desktop generic tool execution also enters the shared runtime after the
existing risk dialog. The runtime applies the same budget, confirmation and
observation contract, while `ToolRegistry` and `MCPGateway` remain the local
executors.

## Prompt And Context

- `ai/prompts/` provides composable stable policies and
  `AGENT_PROMPT_VERSION=learning-agent-v2`.
- Dynamic workspace data, recent history, status, and observations are request
  context, not system policy.
- `AgentRuntimeState` programmatically renders the status bar.
- Runtime observations now carry measured tool latency, and the status bar
  exposes elapsed runtime plus the last tool latency for timeout/slow-call
  adaptation.
- `ContextBudgetManager` allocates separate budgets for base context, status,
  history, and tool observations. It retains goals, constraints, validation,
  identifiers, artifact paths, URLs, and errors while compacting old payloads.
- `AgentBudget` limits iterations, tools, repeated failures, RAG searches,
  sub-agents, context, and tool result size.
- Oversized tool data is retained under a run-local `tool-result://` artifact
  reference. The trajectory and next model context receive only a bounded
  preview plus that reference, so compression does not silently discard data.

## Skills And Tools

- Initial Skill context is metadata-only. `AgentSkillCatalog.load_skill()` is
  the explicit second disclosure layer.
- The seven built-in Skills use YAML frontmatter while legacy `Version:` Skills
  remain supported.
- `AgentCapability` is the shared desktop/Web contract with source, target,
  schemas, risk, side effects, idempotency, confirmation, permission data, and
  machine-readable purpose/use/do-not-use/result-semantics guidance.
- `search_capabilities()` and `/v1/agent/tools/search` support dynamic tool
  discovery.
- Both Desktop and Web executors implement `tool.search` and `skill.load`.
  A full `SKILL.md` is returned only as the result of a named `skill.load`.
- Local, MCP and cloud executors expose optional `execute_observed()` methods
  returning the same `ToolObservation` envelope.

## RAG

- Existing FTS5 + Chroma + RRF remains intact; SaaS now combines tenant-safe
  PostgreSQL FTS and pgvector candidates with RRF before reranking.
- SaaS course/resource filters are pushed into the pgvector candidate query,
  preventing unrelated tenant chunks from displacing scoped evidence before
  the relational citation check.
- SaaS `RetrievalHit` records `rerank_score`, `final_rank`, and
  `retrieval_stage`, with a tested RRF fallback when reranking is unavailable.
- Desktop `HybridRetriever` now applies the configured reranker after RRF,
  with rerank score, final rank and retrieval stage on `RetrievalHit`.
- Chunk `content` stays citation-safe; `retrieval_text` now contains document,
  course, section, heading and location context. The chunker version was
  bumped to trigger re-indexing.
- `RetrievalQueryPlanner` and `AgenticRAG` provide a budgeted tool path. The
  ordinary grounded-QA path remains the fast path.
- `LEARNING_AI_QUERY_REWRITE_ENABLED` and
  `LEARNING_AI_SAAS_HYBRID_RETRIEVAL_ENABLED` are propagated to the shared SaaS
  retriever for QA, question generation, AI feature jobs, and background Agent
  jobs. `LEARNING_AI_AGENTIC_RAG_ENABLED` enables the bounded Agentic RAG path
  for SaaS grounded QA and persists its retrieval observations with the AI run.

## Memory And Sub-Agents

- Confirmed core memory is still the only writable memory. Candidates are
  classified as ADD, UPDATE or NOOP before the confirmed write; UPDATE soft
  deletes the superseded fact.
- Episodic history is searched from existing `AgentMessage` rows on demand;
  conversations are not duplicated.
- Web streaming now also injects a bounded view of the current session's most
  recent messages into the model prompt. The UI history and model history are
  therefore the same persisted source, while old turns are capped and treated
  as untrusted data.
- `LEARNING_AI_MEMORY_RETRIEVAL_ENABLED` controls whether confirmed memory is
  included in Agent context. `LEARNING_AI_MEMORY_CONFLICT_RESOLUTION_ENABLED`
  controls whether a conflicting confirmed card supersedes the older one.
- `SubAgentRuntime` gives Research/Knowledge/Memory style tasks isolated
  objective/context/tool/Skill whitelists and returns only structured results.
  Full main trajectories cannot cross the boundary.
- Web streaming now uses it for the genuinely independent pair of read-only
  learning-snapshot and public-web evidence tasks when
  `LEARNING_AI_SUBAGENT_RUNTIME_ENABLED=true`; each task has its own bounded
  `AgentRuntime` and tenant-scoped database session. Disabling the flag keeps
  the sequential shared-runtime collector as a compatibility fallback.
- Existing deterministic specialists now expose the same style of handoff:
  evidence, artifacts, validation, missing information, confidence, and a
  next recommendation, without changing workflow dependencies into free-form
  multi-agent planning.

## Safety And Flags

Existing workspace boundary, default deny, human confirmation, one-time MCP
approval, no-network/read-only sandbox, soft delete, tenant isolation and
citation validation are unchanged. Phase A flags are in `.env.example`:
`LEARNING_AGENT_RUNTIME_V2`, `LEARNING_SKILL_PROGRESSIVE_DISCLOSURE`, and
`LEARNING_CONTEXT_STATUS_BAR`; the AI feature flags include
`LEARNING_AI_QUERY_REWRITE_ENABLED`, `LEARNING_AI_AGENTIC_RAG_ENABLED`,
`LEARNING_AI_SUBAGENT_RUNTIME_ENABLED`,
`LEARNING_AI_MEMORY_RETRIEVAL_ENABLED`, and
`LEARNING_AI_MEMORY_CONFLICT_RESOLUTION_ENABLED`. Each restores its documented
compatibility path without relaxing permissions.

`docs/MCP_LIFECYCLE_DECISION.md` records the measured lifecycle decision: MCP
uses one isolated stdio process per call to preserve one-time approval and
cancellation scope. `scripts/benchmark_mcp_gateway.py` is the reproducible
read-only latency benchmark for revisiting that decision.

## Verification

Targeted coverage includes Skill disclosure, prompt/status/budget, capability
metadata/search, normalized observations, contextual retrieval, Agentic RAG
budgeting, memory conflict handling, ReAct recovery, confirmation, Web runtime
evidence collection, and Sub-Agent isolation. The offline evaluator executes
the routing, retry, Skill-selection, memory-conflict, query-rewrite, and
Sub-Agent contract datasets in addition to its existing retrieval/tool cases.
Run `python -m pytest -q` for the repository regression suite and
`python evaluation/run_evaluation.py` for the benchmark.

## Before And After

| Area | Before | Harness V2 |
| --- | --- | --- |
| Agent control flow | Desktop and Web had separate adapter flows and ad-hoc tool calls. | `AgentRuntime` owns bounded decision/tool/observation loops; Web durable action execution and Desktop generic tools use it. |
| Prompt | Repeated rules were mixed with request data. | A versioned, composable stable policy is separated from bounded dynamic context. |
| Context | Skills and history could grow without a common budget. | Metadata-first Skills, on-demand loading and protected context budgets. |
| Tools / MCP | Different local descriptors and unstructured result shapes. | Capability metadata, dynamic discovery and normalized observations; MCP retains explicit approval and isolated lifecycle. |
| Retrieval | Base hybrid retrieval without all cross-client enhancement controls. | Contextual retrieval text, query rewrite, RRF/hybrid SaaS retrieval, optional reranking and bounded Agentic RAG. |
| Memory | Candidate persistence did not provide a full conflict lifecycle. | Confirmed core memory plus episodic retrieval, ADD/UPDATE/NOOP classification and confirmation-first writes. |
| Multi-agent | Specialist outputs were service-specific. | Isolated sub-agent task/result contracts and a production read-only parallel evidence path. |

## Operational Evidence

- Full regression: `242 passed` using `python -m pytest -q` on 2026-08-14.
- Offline harness evaluation: `evaluation/results/20260814-174235/`.
  Its ablation table verifies deterministic feature-path differences for Skill
  disclosure, query rewrite, Agentic RAG and Sub-Agent enablement. It is not
  presented as an LLM quality claim.
- MCP lifecycle benchmark: three isolated read-only calls on the Windows
  development environment measured median `852.8 ms`, mean `1001.4 ms`, and
  maximum `1328.2 ms`; see `MCP_LIFECYCLE_DECISION.md`.

## Explicit Limits

The evaluation is deliberately honest about unavailable infrastructure: it did
not make a live LLM quality, GPU, FastEmbed, or production latency claim when
those services were unavailable. Production rollout still requires secrets,
PostgreSQL/pgvector migrations, object storage, and a tenant-scoped staging
test with the selected model provider. These are deployment prerequisites, not
weakened safety fallbacks in the Harness.
