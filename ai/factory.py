from __future__ import annotations

from pathlib import Path

from ai.config import get_ai_settings
from ai.gateways import create_embedding_model
from ai.indexing import ResourceIndexingPipeline
from ai.ingestion import (
    CitationAwareSplitter,
    DocumentIngestionPipeline,
    create_document_parser_registry,
)
from app.core.config import AppSettings
from app.database import Database
from ai.chains import (
    ErrorAnalysisService,
    QuestionGenerationService,
    SubjectiveGradingService,
)

from ai.retrieval import (
    ChromaVectorIndex,
    HybridRetriever,
    SQLiteKeywordIndex,
    KnowledgePointHybridRetriever,
    KnowledgePointIndex,
    KnowledgePointVectorIndex,
    SQLiteKnowledgePointIndex,
)

from ai.chains import GroundedQAService, KnowledgeExtractionService
from ai.gateways import create_chat_model

def create_resource_indexing_pipeline(
    *,
    database: Database,
    app_settings: AppSettings,
) -> ResourceIndexingPipeline:
    ai_settings = get_ai_settings()
    embeddings = create_embedding_model(ai_settings)

    vector_directory = ai_settings.vector_store_dir
    if not vector_directory.is_absolute():
        vector_directory = app_settings.data_dir / vector_directory

    ingestion = DocumentIngestionPipeline(
        database=database,
        workspace_dir=app_settings.workspace_dir,
        parser_registry=create_document_parser_registry(),
        splitter=CitationAwareSplitter(
            chunk_size=ai_settings.chunk_size,
            chunk_overlap=ai_settings.chunk_overlap,
        ),
        embedding_model=ai_settings.embedding_model,
    )

    vectors = ChromaVectorIndex(
        database=database,
        embeddings=embeddings,
        persist_directory=Path(vector_directory),
        embedding_model=ai_settings.embedding_model,
        collection_prefix=ai_settings.vector_collection_prefix,
        batch_size=ai_settings.embedding_batch_size,
    )

    keywords = SQLiteKeywordIndex(database)

    return ResourceIndexingPipeline(
        ingestion=ingestion,
        vectors=vectors,
        keywords=keywords,
    )

def create_grounded_qa_service(
    *,
    database: Database,
    app_settings: AppSettings,
) -> GroundedQAService:
    ai_settings = get_ai_settings()

    retriever = create_hybrid_retriever(
        database=database,
        app_settings=app_settings,
    )
    chat_model = create_chat_model(ai_settings)

    return GroundedQAService(
        database=database,
        retriever=retriever,
        chat_model=chat_model,
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
        retrieval_limit=ai_settings.retrieval_top_k,
    )

def create_hybrid_retriever(
    *,
    database: Database,
    app_settings: AppSettings,
) -> HybridRetriever:
    ai_settings = get_ai_settings()
    embeddings = create_embedding_model(ai_settings)

    vector_directory = ai_settings.vector_store_dir
    if not vector_directory.is_absolute():
        vector_directory = app_settings.data_dir / vector_directory

    vectors = ChromaVectorIndex(
        database=database,
        embeddings=embeddings,
        persist_directory=Path(vector_directory),
        embedding_model=ai_settings.embedding_model,
        collection_prefix=ai_settings.vector_collection_prefix,
        batch_size=ai_settings.embedding_batch_size,
    )

    return HybridRetriever(
        database=database,
        keyword_index=SQLiteKeywordIndex(database),
        vector_index=vectors,
    )


def create_knowledge_extraction_service(
    *,
    database: Database,
    app_settings: AppSettings,
) -> KnowledgeExtractionService:
    del app_settings  # 与其他工厂保持一致，后续可用于读取课程级提示配置。
    ai_settings = get_ai_settings()
    return KnowledgeExtractionService(
        database=database,
        chat_model=create_chat_model(ai_settings),
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
    )


def create_knowledge_point_index(
    *,
    database: Database,
    app_settings: AppSettings,
) -> KnowledgePointIndex:
    ai_settings = get_ai_settings()
    vector_directory = ai_settings.vector_store_dir
    if not vector_directory.is_absolute():
        vector_directory = app_settings.data_dir / vector_directory
    vectors = KnowledgePointVectorIndex(
        database=database,
        embeddings=create_embedding_model(ai_settings),
        persist_directory=Path(vector_directory),
        embedding_model=ai_settings.embedding_model,
        collection_prefix="knowledge_points",
    )
    return KnowledgePointIndex(
        database=database,
        keywords=SQLiteKnowledgePointIndex(database),
        vectors=vectors,
    )


def create_knowledge_point_retriever(
    *,
    database: Database,
    app_settings: AppSettings,
) -> KnowledgePointHybridRetriever:
    index = create_knowledge_point_index(
        database=database, app_settings=app_settings
    )
    return KnowledgePointHybridRetriever(
        database=database,
        keyword_index=index.keywords,
        vector_index=index.vectors,
    )


def create_question_generation_service(
    *,
    database: Database,
    app_settings: AppSettings,
) -> QuestionGenerationService:
    ai_settings = get_ai_settings()

    return QuestionGenerationService(
        database=database,
        knowledge_retriever=create_knowledge_point_retriever(
            database=database,
            app_settings=app_settings,
        ),
        document_retriever=create_hybrid_retriever(
            database=database,
            app_settings=app_settings,
        ),
        chat_model=create_chat_model(ai_settings),
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
        knowledge_limit=8,
        document_limit=12,
    )


def create_subjective_grading_service(
    *,
    database: Database,
    app_settings: AppSettings,
) -> SubjectiveGradingService:
    ai_settings = get_ai_settings()
    return SubjectiveGradingService(
        database=database,
        document_retriever=create_hybrid_retriever(
            database=database,
            app_settings=app_settings,
        ),
        chat_model=create_chat_model(ai_settings),
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
        retrieval_limit=8,
    )


def create_error_analysis_service(
    *,
    database: Database,
    app_settings: AppSettings,
) -> ErrorAnalysisService:
    ai_settings = get_ai_settings()
    return ErrorAnalysisService(
        database=database,
        chat_model=create_chat_model(ai_settings),
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
    )
  
