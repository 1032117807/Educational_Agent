"""统一的时间来源。

项目此前散落着大量 naive ``datetime.now()``，导致同一条记录的时间在不同
写入路径下含义不一致（本地时区 vs UTC）。所有新代码一律使用本模块：
存储与比较用 :func:`now`（UTC-aware），仅在面向用户展示时用
:func:`to_local`。
"""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """返回当前 UTC 时间（带时区）。所有持久化时间戳的唯一来源。"""
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    """把可能为 naive 的时间补成 UTC-aware。

    历史数据里的 naive 值按 UTC 解释：迁移脚本会先把旧的本地时间换算成
    UTC 再写回，因此读取阶段不应再做本地时区推断。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local(value: datetime) -> datetime:
    """转换为本机时区，仅用于展示。"""
    return ensure_aware(value).astimezone()


def isoformat(value: datetime) -> str:
    """序列化为 UTC ISO-8601 字符串，用于 API 与日志。"""
    return ensure_aware(value).isoformat()
