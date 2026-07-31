from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class AISettings(BaseSettings):
    """AI 子系统配置。

    默认兼容 OpenAI API，也支持提供 OpenAI 兼容接口的本地服务。
    """

    enabled: bool = False

    provider: Literal["openai", "openai_compatible"] = "openai"
    api_key: str = ""
    base_url: str | None = None

    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: Literal["cpu", "cuda", "mps"] = "cpu"
    embedding_normalize: bool = True
    embedding_local_files_only: bool = True
    embedding_model_dir: Path = Path(
        "models/fastembed/bge-small-zh-v1.5"
    )

    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    request_timeout_seconds: float = Field(default=60.0, gt=0)
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
    ocr_detection_model_dir: Path = Path(
        "models/paddleocr/PP-OCRv5_mobile_det_infer"
    )
    ocr_recognition_model_name: str = "PP-OCRv5_mobile_rec"
    ocr_recognition_model_dir: Path = Path(
        "models/paddleocr/PP-OCRv5_mobile_rec_infer"
    )
    ocr_use_doc_orientation: bool = False
    ocr_use_textline_orientation: bool = False
    ocr_enable_mkldnn: bool = False

    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    vector_collection_prefix: str = "learning_chunks"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LEARNING_AI_",
        extra="ignore",
    )




@lru_cache(maxsize=1)
def get_ai_settings() -> AISettings:
    return AISettings()
