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
