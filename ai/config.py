from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AISettings(BaseSettings):
    """AI 子系统配置。

    默认兼容 OpenAI API，也支持提供 OpenAI 兼容接口的本地服务。
    """

    enabled: bool = False

    provider: Literal["openai", "openai_compatible"] = "openai"
    api_key: str = ""
    base_url: str | None = None

    # DeepSeek is the preferred OpenAI-compatible chat provider for SaaS.
    chat_model: str = "deepseek-chat"
    embedding_provider: Literal["local", "siliconflow", "openai_compatible"] = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_api_key: str = ""
    embedding_base_url: str | None = None
    embedding_device: Literal["cpu", "cuda", "mps"] = "cpu"
    embedding_normalize: bool = True
    embedding_local_files_only: bool = True
    embedding_model_dir: Path = Path(
        "models/fastembed/bge-small-zh-v1.5"
    )

    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    knowledge_extraction_batch_size: int = Field(default=2, ge=1, le=12)
    max_retries: int = Field(default=2, ge=0, le=10)

    chunk_size: int = Field(default=800, ge=200, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    retrieval_top_k: int = Field(default=8, ge=1, le=50)

    vector_store_dir: Path = Path("data/vector_store")

    ocr_enabled: bool = True
    ocr_language: str = "ch"
    ocr_device: str = "cpu"
    ocr_dpi: int = Field(default=300, ge=150, le=600)
    ocr_min_native_characters: int = Field(default=30, ge=0, le=1000)
    ocr_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    ocr_detection_model_name: str = "PP-OCRv5_mobile_det"
    # None lets PaddleOCR download/cache its official CPU model on first use.
    ocr_detection_model_dir: Path | None = None
    ocr_recognition_model_name: str = "PP-OCRv5_mobile_rec"
    ocr_recognition_model_dir: Path | None = None
    ocr_use_doc_orientation: bool = False
    ocr_use_textline_orientation: bool = False
    ocr_enable_mkldnn: bool = False
    # Optional vision/OCR API. It is attempted first, then local PaddleOCR
    # handles failures so transient provider problems do not block indexing.
    ocr_api_enabled: bool = False
    ocr_api_key: str = ""
    ocr_api_base_url: str | None = None
    ocr_api_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    ocr_api_timeout_seconds: float = Field(default=45.0, gt=0)

    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    # BAAI/bge-small-zh-v1.5 returns 512 dimensions. The pgvector schema uses
    # the same fixed dimension and must be migrated when this changes.
    embedding_dimensions: int = Field(default=512, ge=1, le=8192)
    rerank_enabled: bool = False
    rerank_provider: Literal["siliconflow", "aliyun", "openai_compatible"] = "siliconflow"
    rerank_api_key: str = ""
    rerank_base_url: str | None = None
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidate_limit: int = Field(default=24, ge=1, le=100)
    vector_collection_prefix: str = "learning_chunks"
    contextual_retrieval_enabled: bool = True
    query_rewrite_enabled: bool = True
    agentic_rag_enabled: bool = True
    local_reranker_enabled: bool = True
    saas_hybrid_retrieval_enabled: bool = True
    subagent_runtime_enabled: bool = True
    memory_retrieval_enabled: bool = True
    memory_conflict_resolution_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LEARNING_AI_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_pgvector_dimensions(self) -> "AISettings":
        # The production migration declares document_embeddings as vector(512).
        # A dimension change is a schema migration plus a full re-index.
        if self.embedding_dimensions != 512:
            raise ValueError(
                "embedding_dimensions must be 512 for BAAI/bge-small-zh-v1.5; changing models requires a pgvector migration and full re-index"
            )
        if self.enabled and not self.api_key.strip():
            raise ValueError("LEARNING_AI_API_KEY is required when LEARNING_AI_ENABLED=true")
        if self.provider == "openai_compatible" and self.enabled and not self.base_url:
            raise ValueError("LEARNING_AI_BASE_URL is required for openai_compatible provider")
        if self.rerank_enabled and not self.rerank_api_key.strip():
            raise ValueError("LEARNING_AI_RERANK_API_KEY is required when rerank is enabled")
        if self.ocr_api_enabled and (not self.ocr_api_key.strip() or not self.ocr_api_base_url):
            raise ValueError("LEARNING_AI_OCR_API_KEY and LEARNING_AI_OCR_API_BASE_URL are required when OCR API is enabled")
        return self




@lru_cache(maxsize=1)
def get_ai_settings() -> AISettings:
    return AISettings()
