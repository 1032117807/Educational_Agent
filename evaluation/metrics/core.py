"""无需第三方评估框架的基础指标实现。"""

from __future__ import annotations

from math import log2
from statistics import quantiles
from typing import Iterable


def unavailable(reason: str) -> dict[str, object]:
    """统一表示不可计算指标，避免用 0 掩盖缺失能力。"""
    return {"value": None, "status": "unavailable", "reason": reason}


def available(value: float | int) -> dict[str, object]:
    return {"value": value, "status": "available"}


def classification_metrics(expected: Iterable[str], actual: Iterable[str]) -> dict[str, dict[str, object]]:
    """计算多分类的 Accuracy 与宏平均 Precision/Recall/F1。"""
    truth, predicted = list(expected), list(actual)
    if not truth or len(truth) != len(predicted):
        return {name: unavailable("标签为空或长度不一致") for name in ("accuracy", "precision_macro", "recall_macro", "f1_macro")}
    labels = sorted(set(truth) | set(predicted))
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(truth, predicted))
        fp = sum(a != label and b == label for a, b in zip(truth, predicted))
        fn = sum(a == label and b != label for a, b in zip(truth, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    return {
        "accuracy": available(sum(a == b for a, b in zip(truth, predicted)) / len(truth)),
        "precision_macro": available(sum(precisions) / len(precisions)),
        "recall_macro": available(sum(recalls) / len(recalls)),
        "f1_macro": available(sum(f1s) / len(f1s)),
    }


def retrieval_metrics(retrieved: list[int], relevant: set[int], k: int) -> dict[str, dict[str, object]]:
    """根据人工标注的相关 chunk id 计算检索质量指标。"""
    if not relevant:
        return {name: unavailable("样本未标注相关 chunk") for name in ("recall_at_k", "precision_at_k", "hit_rate_at_k", "mrr", "ndcg_at_k")}
    top = retrieved[:k]
    hits = [chunk_id for chunk_id in top if chunk_id in relevant]
    recall = len(set(hits)) / len(relevant)
    precision = len(hits) / k if k else 0.0
    reciprocal_rank = next((1 / rank for rank, chunk_id in enumerate(top, 1) if chunk_id in relevant), 0.0)
    dcg = sum(1 / log2(rank + 1) for rank, chunk_id in enumerate(top, 1) if chunk_id in relevant)
    ideal_count = min(len(relevant), k)
    idcg = sum(1 / log2(rank + 1) for rank in range(1, ideal_count + 1))
    return {
        "recall_at_k": available(recall),
        "precision_at_k": available(precision),
        "hit_rate_at_k": available(1.0 if hits else 0.0),
        "mrr": available(reciprocal_rank),
        "ndcg_at_k": available(dcg / idcg if idcg else 0.0),
    }


def percentile(values: list[float], percentage: int) -> dict[str, object]:
    """采用线性插值计算分位数；样本不足时不伪造 P95/P99。"""
    if not values:
        return unavailable("没有延迟样本")
    if len(values) == 1 and percentage > 50:
        return unavailable("样本数不足，不能稳定估计高分位延迟")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentage / 100
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    value = ordered[low] + (ordered[high] - ordered[low]) * (position - low)
    return available(value)
