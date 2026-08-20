from evals.evaluators.metrics import aggregate_records


def test_aggregate_records_uses_only_available_numeric_values() -> None:
    rows = aggregate_records([
        {"module": "rag", "metrics": {"recall": {"status": "available", "value": 1.0}, "judge": {"status": "unavailable", "value": None}}},
        {"module": "rag", "metrics": {"recall": {"status": "available", "value": 0.5}}},
    ])
    assert rows == [{"module": "rag", "metric": "recall", "n": 2, "mean": 0.75}]
