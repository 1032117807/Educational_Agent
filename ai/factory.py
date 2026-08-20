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
    PlanGenerationService,
    QuestionGenerationService,
    SubjectiveGradingService,
)
from ai.reports import LearningReportService

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
from ai.gateways import create_chat_model, create_reranker

from ai.agents import LearningOrchestrator, LearningPlanAgentService

from app.services.agent_permissions import AgentPermissionService
from app.services.agent_skills import AgentSkillCatalog
from app.services.agent_memory import AgentMemoryService
from app.services.mcp_gateway import MCPGateway
from app.services.research_curation import ResearchCurationService
from app.services.meta_coding import MetaCodingService

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
            contextual_retrieval_enabled=ai_settings.contextual_retrieval_enabled,
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
        reranker=create_reranker(ai_settings) if ai_settings.local_reranker_enabled else None,
        rerank_candidate_limit=ai_settings.rerank_candidate_limit,
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
        batch_size=ai_settings.knowledge_extraction_batch_size,
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
        batch_size=ai_settings.knowledge_extraction_batch_size,
    )


def create_learning_report_service(*, database: Database, app_settings: AppSettings) -> LearningReportService:
    ai_settings = get_ai_settings()
    return LearningReportService(
        database=database,
        chat_model=create_chat_model(ai_settings),
        chart_output_dir=app_settings.data_dir / "report_charts",
    )


def create_plan_generation_service(*, database: Database, app_settings: AppSettings) -> PlanGenerationService:
    ai_settings = get_ai_settings()
    return PlanGenerationService(
        database=database,
        chat_model=create_chat_model(ai_settings),
        provider=ai_settings.provider,
        model_name=ai_settings.chat_model,
    )

def create_learning_orchestrator(
    *,
    database: Database,
    app_settings: AppSettings,
) -> LearningOrchestrator:
    return LearningOrchestrator(
        database=database,
        indexing_factory=lambda: create_resource_indexing_pipeline(database=database, app_settings=app_settings),
        extraction_factory=lambda: create_knowledge_extraction_service(database=database, app_settings=app_settings),
        question_factory=lambda: create_question_generation_service(database=database, app_settings=app_settings),
        report_factory=lambda: create_learning_report_service(database=database, app_settings=app_settings),
        plan_factory=lambda: create_plan_generation_service(database=database, app_settings=app_settings),
    )

def create_learning_plan_agent_service(
    *, database: Database, app_settings: AppSettings, tool_registry=None,
    skill_catalog: AgentSkillCatalog | None = None,
) -> LearningPlanAgentService:
    from app.agent_runtime import AgentBudget
    ai_settings = get_ai_settings()
    return LearningPlanAgentService(
        database=database,
        chat_model=create_chat_model(ai_settings),
        plan_factory=lambda: create_plan_generation_service(
            database=database, app_settings=app_settings
        ),
        tool_registry=tool_registry,
        question_factory=lambda: create_question_generation_service(
            database=database, app_settings=app_settings
        ),
        report_factory=lambda: create_learning_report_service(
            database=database, app_settings=app_settings
        ),
        mcp_gateway=MCPGateway(AgentPermissionService(app_settings.data_dir / "mcp_policy.json")),
        skill_catalog=skill_catalog or AgentSkillCatalog(
            state_path=app_settings.data_dir / "agent_skills.json"
        ),
        memory_service=AgentMemoryService(
            database,
            conflict_resolution_enabled=ai_settings.memory_conflict_resolution_enabled,
        ),
        research_factory=lambda: create_research_curation_service(
            database=database, app_settings=app_settings
        ),
        meta_coding_factory=lambda: MetaCodingService(
            chat_model=create_chat_model(ai_settings),
            mcp_gateway=MCPGateway(AgentPermissionService(
                app_settings.data_dir / "mcp_policy.json"
            )),
            skills_dir=Path(__file__).resolve().parents[1] / "skills",
        ),
        budget_factory=lambda: AgentBudget(
            max_iterations=app_settings.agent_max_iterations,
            max_tool_calls=app_settings.agent_max_tool_calls,
            max_same_tool_retries=app_settings.agent_max_same_tool_retries,
            max_rag_searches=app_settings.agent_max_rag_searches,
            max_subagents=app_settings.agent_max_subagents,
            max_context_tokens=app_settings.agent_max_context_tokens,
            max_tool_result_chars=app_settings.agent_max_tool_result_chars,
        ),
        runtime_v2_enabled=app_settings.agent_runtime_v2,
        skill_progressive_disclosure=app_settings.skill_progressive_disclosure,
        context_status_bar=app_settings.context_status_bar,
        memory_retrieval_enabled=ai_settings.memory_retrieval_enabled,
    )


def create_research_curation_service(
    *, database: Database, app_settings: AppSettings,
) -> ResearchCurationService:
    ai_settings = get_ai_settings()
    return ResearchCurationService(
        database=database,
        app_settings=app_settings,
        chat_model=create_chat_model(ai_settings),
        indexing_factory=lambda: create_resource_indexing_pipeline(
            database=database, app_settings=app_settings
        ),
    )
  
