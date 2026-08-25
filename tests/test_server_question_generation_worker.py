import pytest

from server.question_generation_worker import _validate_question


def test_generated_question_requires_retrieved_evidence_citations() -> None:
    with pytest.raises(ValueError, match="requires evidence citations"):
        _validate_question(
            {
                "prompt": "What is a vector index?",
                "answer": "An index",
                "kind": "short_answer",
                "explanation": "A concise explanation without a source.",
                "citations": [],
            },
            evidence_count=2,
        )


def test_generated_choice_question_preserves_grounding_and_options() -> None:
    question = _validate_question(
        {
            "prompt": "Choose the supported index.",
            "answer": "HNSW",
            "kind": "single_choice",
            "options": ["HNSW", "B-tree"],
            "explanation": "The supplied material names HNSW. [1]",
            "tags": ["pgvector"],
            "difficulty": 3,
            "citations": [1],
        },
        evidence_count=1,
    )
    assert question["options"] == '["HNSW", "B-tree"]'
    assert question["citations"] == [1]


def test_generated_short_answer_has_valid_empty_options_json() -> None:
    question = _validate_question(
        {
            "prompt": "Explain the index.",
            "answer": "HNSW",
            "kind": "short_answer",
            "explanation": "The material describes it. [1]",
            "citations": [1],
        },
        evidence_count=1,
    )
    assert question["options"] == "[]"


def test_generated_fill_blank_is_supported_without_choice_options() -> None:
    question = _validate_question(
        {
            "prompt": "Fill in the missing term: a vector database uses ___.",
            "answer": "embeddings",
            "kind": "fill_blank",
            "explanation": "The material identifies embeddings. [1]",
            "citations": [1],
        },
        evidence_count=1,
    )
    assert question["kind"] == "fill_blank"
    assert question["options"] == "[]"
from server.question_generation_worker import _validate_question


def test_ungrounded_baseline_question_discards_placeholder_citations() -> None:
    question = _validate_question({
        "prompt": "选择正确的词义", "answer": "A", "kind": "single_choice",
        "options": ["A", "B"], "explanation": "这是基线练习。", "citations": [1],
    }, 0, allow_ungrounded=True)
    assert question["citations"] == []
