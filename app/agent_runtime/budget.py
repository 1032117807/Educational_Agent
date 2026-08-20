"""Deterministic execution limits for the unified Agent Runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json


@dataclass(frozen=True)
class ToolFailureObservation:
    tool_name: str
    arguments_hash: str
    error: str
    consecutive_failures: int
    retry_allowed: bool
    suggestion: str


@dataclass
class AgentBudget:
    max_iterations: int = 10
    max_tool_calls: int = 12
    max_same_tool_retries: int = 2
    max_rag_searches: int = 4
    max_subagents: int = 4
    max_context_tokens: int = 12_000
    max_tool_result_chars: int = 12_000
    iterations: int = 0
    tool_calls: int = 0
    rag_searches: int = 0
    subagents: int = 0
    _failures: dict[tuple[str, str, str], int] = field(default_factory=dict)

    def allow_iteration(self) -> bool:
        if self.iterations >= self.max_iterations:
            return False
        self.iterations += 1
        return True

    def allow_tool_call(self, tool_name: str) -> bool:
        if self.tool_calls >= self.max_tool_calls:
            return False
        if tool_name == "search_knowledge" and self.rag_searches >= self.max_rag_searches:
            return False
        self.tool_calls += 1
        if tool_name == "search_knowledge":
            self.rag_searches += 1
        return True

    def record_tool_failure(
        self, tool_name: str, arguments: dict[str, object], error: str,
    ) -> ToolFailureObservation:
        serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        arguments_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        key = (tool_name, arguments_hash, error.strip())
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        retry_allowed = count <= self.max_same_tool_retries
        return ToolFailureObservation(
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            error=error,
            consecutive_failures=count,
            retry_allowed=retry_allowed,
            suggestion=(
                "retry with a backoff" if retry_allowed
                else "change arguments, choose another tool, ask the user, or stop"
            ),
        )
