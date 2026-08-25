"""AIRun 收尾的共享逻辑。

五条 chain 各自实现 ``_complete_run`` / ``_fail_run``，重复写 status、
finished_at 与 token 回填。此处集中处理，确保时间来源统一（UTC-aware）
且 token 用量不会漏记。
"""

from __future__ import annotations

from app.core.clock import now
from app.models import AIRun
from ai.usage import TokenUsage


def apply_usage(run: AIRun, usage: TokenUsage | None) -> None:
    """把采集到的 token 用量写入运行记录。

    没采集到用量时保持字段原值，而不是覆写成 0——重试场景下前一次的
    真实用量比一个假的 0 更有意义。
    """
    if usage is None or usage.call_count == 0:
        return
    run.input_tokens = usage.input_tokens
    run.output_tokens = usage.output_tokens


def finish_run(
    run: AIRun,
    *,
    output_json: str,
    usage: TokenUsage | None = None,
) -> None:
    """标记运行成功。"""
    run.status = "completed"
    run.output_json = output_json
    run.error_message = ""
    run.finished_at = now()
    apply_usage(run, usage)


def fail_run(
    run: AIRun,
    *,
    error_message: str,
    usage: TokenUsage | None = None,
) -> None:
    """标记运行失败。

    失败前已消耗的 token 同样计费，因此照常回填。
    """
    run.status = "failed"
    run.error_message = error_message
    run.finished_at = now()
    apply_usage(run, usage)
