from __future__ import annotations

from pathlib import Path

from ai.config import get_ai_settings
from ai.gateways import create_embedding_model, create_reranker
from ai.gateways import create_chat_model
from ai.exceptions import AIConfigurationError
from ai.ingestion import CitationAwareSplitter, DocumentIngestionPipeline, create_document_parser_registry
from app.database import Database
from server.config import ServerSettings
from server.db import session_factory
from server.indexing_worker import index_resource_from_object_store
from server.pgvector_indexer import PgVectorDocumentIndexer
from server.pgvector_indexer import embedding_version_for
from server.rag_worker import retrieve_rag_evidence
from server.question_generation_worker import generate_grounded_questions
from server.vocabulary_worker import generate_vocabulary
from server.ai_services import run_ai_feature
from server.ai_services.agent import run_learning_agent
from server.saas_indexing import SaaSResourceIndexingPipeline
from server.storage import S3ObjectStorage


def create_index_resource_handler(settings: ServerSettings):
    """Build the production index handler used by the durable worker."""
    ai_settings = get_ai_settings()
    sessions = session_factory(settings)
    storage = S3ObjectStorage(settings)
    embeddings = create_embedding_model(ai_settings)

    def pipeline_factory(workspace: Path, tenant_id: str) -> SaaSResourceIndexingPipeline:
        database = Database(settings.database_url)
        ingestion = DocumentIngestionPipeline(
            database=database,
            workspace_dir=workspace,
            parser_registry=create_document_parser_registry(),
            splitter=CitationAwareSplitter(chunk_size=ai_settings.chunk_size, chunk_overlap=ai_settings.chunk_overlap),
            embedding_model=ai_settings.embedding_model,
            tenant_id=tenant_id,
        )
        vectors = PgVectorDocumentIndexer(
            session_factory=sessions,
            embeddings=embeddings,
            embedding_model=ai_settings.embedding_model,
            dimensions=ai_settings.embedding_dimensions,
            batch_size=ai_settings.embedding_batch_size,
            tenant_id=tenant_id,
        )
        return SaaSResourceIndexingPipeline(ingestion=ingestion, vectors=vectors)

    return lambda payload: index_resource_from_object_store(
        payload=payload,
        session_factory=sessions,
        storage=storage,
        pipeline_factory=pipeline_factory,
    )


def create_rag_retrieval_handler(settings: ServerSettings):
    ai_settings = get_ai_settings()
    sessions = session_factory(settings)
    embeddings = create_embedding_model(ai_settings)
    chat_model = None
    if ai_settings.enabled and ai_settings.api_key.strip():
        try:
            chat_model = create_chat_model(ai_settings)
        except AIConfigurationError:
            chat_model = None
    version = embedding_version_for(ai_settings.embedding_model, ai_settings.embedding_dimensions)
    reranker = create_reranker(ai_settings)
    return lambda payload: retrieve_rag_evidence(
        payload=payload,
        session_factory=sessions,
        embeddings=embeddings,
        embedding_version=version,
        dimensions=ai_settings.embedding_dimensions,
        model_name=ai_settings.embedding_model,
        chat_model=chat_model,
        chat_provider=ai_settings.provider,
        chat_model_name=ai_settings.chat_model,
        reranker=reranker,
        rerank_candidate_limit=ai_settings.rerank_candidate_limit,
        query_rewrite_enabled=ai_settings.query_rewrite_enabled,
        hybrid_retrieval_enabled=ai_settings.saas_hybrid_retrieval_enabled,
        agentic_rag_enabled=ai_settings.agentic_rag_enabled,
    )


def create_question_generation_handler(settings: ServerSettings):
    ai_settings = get_ai_settings()
    if not ai_settings.enabled or not ai_settings.api_key.strip():
        raise AIConfigurationError("AI question generation requires LEARNING_AI_ENABLED and LEARNING_AI_API_KEY")
    sessions = session_factory(settings)
    embeddings = create_embedding_model(ai_settings)
    chat_model = create_chat_model(ai_settings)
    version = embedding_version_for(ai_settings.embedding_model, ai_settings.embedding_dimensions)
    reranker = create_reranker(ai_settings)
    return lambda payload: generate_grounded_questions(
        payload=payload,
        session_factory=sessions,
        embeddings=embeddings,
        embedding_version=version,
        dimensions=ai_settings.embedding_dimensions,
        chat_model=chat_model,
        chat_provider=ai_settings.provider,
        chat_model_name=ai_settings.chat_model,
        reranker=reranker,
        rerank_candidate_limit=ai_settings.rerank_candidate_limit,
        query_rewrite_enabled=ai_settings.query_rewrite_enabled,
        hybrid_retrieval_enabled=ai_settings.saas_hybrid_retrieval_enabled,
    )


def create_vocabulary_handler(settings: ServerSettings):
    ai_settings = get_ai_settings()
    if not ai_settings.enabled or not ai_settings.api_key.strip():
        raise AIConfigurationError("Vocabulary generation requires LEARNING_AI_ENABLED and LEARNING_AI_API_KEY")
    sessions = session_factory(settings); embeddings = create_embedding_model(ai_settings); chat_model = create_chat_model(ai_settings)
    version = embedding_version_for(ai_settings.embedding_model, ai_settings.embedding_dimensions); reranker = create_reranker(ai_settings)
    return lambda payload: generate_vocabulary(payload=payload, session_factory=sessions, embeddings=embeddings,
        embedding_version=version, dimensions=ai_settings.embedding_dimensions, chat_model=chat_model,
        reranker=reranker, rerank_candidate_limit=ai_settings.rerank_candidate_limit,
        query_rewrite_enabled=ai_settings.query_rewrite_enabled, hybrid_retrieval_enabled=ai_settings.saas_hybrid_retrieval_enabled)


def create_ai_feature_handler(settings: ServerSettings):
    ai_settings = get_ai_settings()
    if not ai_settings.enabled or not ai_settings.api_key.strip():
        raise AIConfigurationError("AI features require LEARNING_AI_ENABLED and LEARNING_AI_API_KEY")
    sessions = session_factory(settings)
    embeddings = create_embedding_model(ai_settings)
    chat_model = create_chat_model(ai_settings)
    version = embedding_version_for(ai_settings.embedding_model, ai_settings.embedding_dimensions)
    reranker = create_reranker(ai_settings)
    return lambda payload: run_ai_feature(
        payload=payload,
        session_factory=sessions,
        embeddings=embeddings,
        embedding_version=version,
        dimensions=ai_settings.embedding_dimensions,
        chat_model=chat_model,
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
        reranker=reranker,
        rerank_candidate_limit=ai_settings.rerank_candidate_limit,
        query_rewrite_enabled=ai_settings.query_rewrite_enabled,
        hybrid_retrieval_enabled=ai_settings.saas_hybrid_retrieval_enabled,
    )


def create_learning_agent_handler(settings: ServerSettings):
    ai_settings = get_ai_settings()
    if not ai_settings.enabled or not ai_settings.api_key.strip():
        raise AIConfigurationError("Learning agent requires LEARNING_AI_ENABLED and LEARNING_AI_API_KEY")
    sessions = session_factory(settings)
    embeddings = create_embedding_model(ai_settings)
    reranker = create_reranker(ai_settings)
    return lambda payload: run_learning_agent(
        payload=payload, session_factory=sessions, embeddings=embeddings,
        embedding_version=embedding_version_for(ai_settings.embedding_model, ai_settings.embedding_dimensions),
        dimensions=ai_settings.embedding_dimensions, chat_model=create_chat_model(ai_settings),
        provider=ai_settings.provider, model_name=ai_settings.chat_model,
        reranker=reranker, rerank_candidate_limit=ai_settings.rerank_candidate_limit,
        query_rewrite_enabled=ai_settings.query_rewrite_enabled,
        hybrid_retrieval_enabled=ai_settings.saas_hybrid_retrieval_enabled,
    )
