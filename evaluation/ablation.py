"""Named feature-flag profiles for repeatable Agent Harness ablations."""
from __future__ import annotations


ABLATIONS: dict[str, dict[str, bool]] = {
    "baseline": {
        "skill_progressive_disclosure": True, "reranker": True, "query_rewrite": True,
        "memory_retrieval": True, "agentic_rag": True, "subagent_runtime": True,
    },
    "without_skill_progressive_disclosure": {"skill_progressive_disclosure": False},
    "without_reranker": {"reranker": False},
    "without_query_rewrite": {"query_rewrite": False},
    "without_memory_retrieval": {"memory_retrieval": False},
    "without_agentic_rag": {"agentic_rag": False},
    "without_subagent_runtime": {"subagent_runtime": False},
}


def profile(name: str) -> dict[str, bool]:
    if name not in ABLATIONS:
        raise ValueError(f"unknown ablation profile: {name}")
    baseline = dict(ABLATIONS["baseline"])
    baseline.update(ABLATIONS[name])
    return baseline
