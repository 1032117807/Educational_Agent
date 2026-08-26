"""模型 token 用量采集。

``AIRun.input_tokens`` / ``output_tokens`` 字段与迁移一直存在，但没有任何
写入路径给它们赋值。此处在网关层统一采集：结构化输出（``with_structured_output``）
会把原始响应解析成 pydantic 对象，usage 元数据在返回值里已经丢失，因此必须
用回调在 LLM 响应层拿，而不是读 ``invoke`` 的结果。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


@dataclass
class TokenUsage:
    """一次或多次调用累计的 token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, *, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.call_count += 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


_active_usage: ContextVar[TokenUsage | None] = ContextVar("_active_usage", default=None)


def _read_usage(payload: dict[str, Any] | None) -> tuple[int, int] | None:
    """从提供方元数据中提取 (input, output)。

    OpenAI 兼容端点用 prompt_tokens/completion_tokens，LangChain 的标准化
    字段用 input_tokens/output_tokens；不同网关只给其中一种。
    """
    if not payload:
        return None
    for input_key, output_key in (
        ("input_tokens", "output_tokens"),
        ("prompt_tokens", "completion_tokens"),
    ):
        if input_key in payload or output_key in payload:
            return int(payload.get(input_key) or 0), int(payload.get(output_key) or 0)
    return None


def response_token_usage(response: Any) -> tuple[int, int]:
    """Return normalized token counts from one direct LangChain response."""
    counts = _read_usage(getattr(response, "usage_metadata", None))
    if counts is None:
        counts = _read_usage((getattr(response, "response_metadata", None) or {}).get("token_usage"))
    return counts or (0, 0)


class UsageCollector(BaseCallbackHandler):
    """把 LLM 响应里的 token 用量累加到当前活跃的 :class:`TokenUsage`。"""

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage = _active_usage.get()
        if usage is None:
            return

        counts = _read_usage((response.llm_output or {}).get("token_usage"))
        if counts is None:
            counts = self._read_from_generations(response)
        if counts is None:
            return

        usage.add(input_tokens=counts[0], output_tokens=counts[1])

    @staticmethod
    def _read_from_generations(response: LLMResult) -> tuple[int, int] | None:
        """回退路径：流式响应的用量只挂在消息上，不在 ``llm_output``。"""
        for batch in response.generations:
            for generation in batch:
                message = getattr(generation, "message", None)
                if message is None:
                    continue
                counts = _read_usage(getattr(message, "usage_metadata", None))
                if counts is None:
                    counts = _read_usage(
                        (getattr(message, "response_metadata", None) or {}).get("token_usage")
                    )
                if counts is not None:
                    return counts
        return None


@contextmanager
def track_usage() -> Iterator[TokenUsage]:
    """在此上下文内的所有模型调用都会累加到返回的 :class:`TokenUsage`。

    嵌套安全：内层会拿到自己的实例，退出后恢复外层。
    """
    usage = TokenUsage()
    token = _active_usage.set(usage)
    try:
        yield usage
    finally:
        _active_usage.reset(token)
