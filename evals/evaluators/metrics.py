from __future__ import annotations

from statistics import fmean
from typing import Any


def aggregate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate only numeric metrics returned by real suite executions."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for record in records:
        for name, metric in record.get("metrics", {}).items():
            if isinstance(metric, dict) and metric.get("status") == "available":
                value = metric.get("value")
                if isinstance(value, (int, float)):
                    grouped.setdefault((str(record.get("module")), name), []).append(float(value))
    return [
        {"module": module, "metric": metric, "n": len(values), "mean": fmean(values)}
        for (module, metric), values in sorted(grouped.items())
    ]
