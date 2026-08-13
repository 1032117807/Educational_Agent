from server.rag_worker import has_valid_citations, retrieve_rag_evidence


def test_rag_worker_rejects_empty_question_before_database_access() -> None:
    try:
        retrieve_rag_evidence(
            payload={"tenant_id": "tenant-1", "question": "  "},
            session_factory=lambda: None,
            embeddings=None,
            embedding_version="v1",
            dimensions=384,
            model_name="model",
        )
    except ValueError as exc:
        assert "question" in str(exc)
    else:
        raise AssertionError("empty question must be rejected")


def test_rag_worker_signature_keeps_generation_optional() -> None:
    # No model key is required for evidence-only retrieval. The optional
    # chat_model argument enables grounded generation only when configured.
    assert retrieve_rag_evidence.__kwdefaults__["chat_model"] is None
    assert retrieve_rag_evidence.__kwdefaults__["chat_provider"] == ""


def test_rag_worker_writes_citation_tenant_scope() -> None:
    source = open("server/rag_worker.py", encoding="utf-8").read()
    assert "AICitation(" in source
    assert "tenant_id=tenant_id" in source


def test_generated_answer_citations_must_match_retrieved_evidence() -> None:
    assert has_valid_citations("答案来自资料。[1] 另一个结论。[3]", evidence_count=3)
    assert not has_valid_citations("答案没有来源标记", evidence_count=3)
    assert not has_valid_citations("引用了不存在的资料。[4]", evidence_count=3)
    assert not has_valid_citations("无效编号。[0]", evidence_count=3)
