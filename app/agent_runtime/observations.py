"""Stable result envelope shared by local, MCP, cloud, and companion tools."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    ok: bool
    data: Any = None
    summary: str = ""
    error: dict[str, Any] | None = None
    latency_ms: int | None = None
    source: str = "local"
    truncated: bool = False
    artifact_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        meta = {
            "latency_ms": payload.pop("latency_ms"),
            "source": payload.pop("source"),
            "truncated": payload.pop("truncated"),
            "artifact_ref": payload.pop("artifact_ref"),
        }
        payload["meta"] = meta
        return payload


def observe_success(tool_name: str, data: Any, *, summary: str = "", source: str = "local", latency_ms: int | None = None) -> dict[str, Any]:
    return ToolObservation(tool_name, True, data=data, summary=summary, source=source, latency_ms=latency_ms).to_dict()


def observe_failure(
    tool_name: str, error: Exception | str, *, retryable: bool = False,
    suggestion: str = "", latency_ms: int | None = None,
) -> dict[str, Any]:
    message = str(error)
    return ToolObservation(
        tool_name, False, summary="Tool execution failed", latency_ms=latency_ms,
        error={"type": type(error).__name__ if isinstance(error, Exception) else "ToolError", "message": message, "retryable": retryable, "suggestion": suggestion},
    ).to_dict()
