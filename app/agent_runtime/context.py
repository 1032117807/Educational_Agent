"""Context budgeting that preserves operational invariants while compressing data."""
from __future__ import annotations

import json
from typing import Any


class ContextBudgetManager:
    REQUIRED_KEYS = frozenset({"constraints", "goal", "todo", "validation", "file_path", "resource_id", "course_id", "run_id", "workflow_id", "url"})

    def __init__(
        self,
        *,
        max_tokens: int = 12_000,
        max_chars: int | None = None,
        category_token_limits: dict[str, int] | None = None,
    ) -> None:
        self.max_tokens = max(250, max_tokens)
        self.max_chars = max(1_000, max_chars if max_chars is not None else self.max_tokens * 4)
        defaults = {"base": 4_000, "status": 800, "history": 2_400, "observations": 4_800}
        self.category_token_limits = {
            key: max(64, value)
            for key, value in (category_token_limits or defaults).items()
        }

    def build(self, *, base: dict[str, Any], status: str, history: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "base": self._fit(base, "base"),
            "status": self._fit_text(status, "status"),
            "history": self._fit_events(history[-8:], "history"),
            "observations": self._fit_events(observations[-8:], "observations"),
        }
        if self._size(payload) <= self.max_chars:
            return payload
        # Tighten only expendable histories. Base constraints and status retain
        # their per-category contracts and required identifiers.
        payload["history"] = self._fit_events(history[-3:], "history", compact=True)
        payload["observations"] = self._fit_events(observations[-5:], "observations", compact=True)
        return payload

    def _fit(self, value: dict[str, Any], category: str) -> dict[str, Any]:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        if len(raw) <= self._char_limit(category):
            return value
        return self._compact(value)

    def _fit_text(self, value: str, category: str) -> str:
        return value[:self._char_limit(category)]

    def _fit_events(self, values: list[dict[str, Any]], category: str, *, compact: bool = False) -> list[dict[str, Any]]:
        limit = self._char_limit(category)
        result: list[dict[str, Any]] = []
        used = 0
        for value in reversed(values):
            item = self._compact(value) if compact else value
            encoded = self._size(item)
            if result and used + encoded > limit:
                continue
            result.append(item)
            used += encoded
        return list(reversed(result))

    def _char_limit(self, category: str) -> int:
        return self.category_token_limits.get(category, 512) * 4

    @staticmethod
    def _size(value: Any) -> int:
        return len(json.dumps(value, ensure_ascii=False, default=str))

    def _compact(self, value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in self.REQUIRED_KEYS or key in {"tool_name", "status", "summary", "error", "artifact_ref"}:
                result[key] = item if not isinstance(item, str) else item[:2_000]
            elif isinstance(item, str):
                result[key] = item[:500]
            elif isinstance(item, (int, float, bool)) or item is None:
                result[key] = item
        return result
