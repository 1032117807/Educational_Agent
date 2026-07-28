from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

@dataclass(frozen=True, slots=True)
class ParsedSection:
    """文档解析后的自然结构单元。

    PDF 的一个 section 对应一页，PPTX 对应一张幻灯片，
    DOCX 对应一个非空段落，Markdown 对应一个标题区段，
    TXT 对应一个由空行分隔的文本段。
    """

    content: str
    source_path: Path
    source_name: str
    file_type: str
    location_label: str

    page_start : int | None = None
    page_end : int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_title: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_langchain_document(self) -> Document:
        """转换成 LangChain Document，同时保留引用信息。"""

        document_metadata:dict[str,Any] = {
            "source": str(self.source_path),
            "source_name": self.source_name,
            "file_type": self.file_type,
            "location_label": self.location_label,
            "section_title": self.section_title,
            **self.metadata,
        }

        if self.page_start is not None:
            document_metadata["page_start"] = self.page_start

        if self.page_end is not None:
            document_metadata["page_end"] = self.page_end

        if self.line_start is not None:
            document_metadata["line_start"] = self.line_start

        if self.line_end is not None:
            document_metadata["line_end"] = self.line_end

        return Document(
            page_content=self.content,
            metadata=document_metadata,
        )


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """一个文件的完整解析结果。"""
    source_path:Path
    file_type:str
    parser_version:str
    sections:tuple[ParsedSection,...]

    @property
    def is_empty(self) -> bool:
        return not self.sections

    @property
    def total_characters(self) -> int:
        return sum(len(section.content) for section in self.sections)

    def to_langchain_documents(self) -> list[Document]:
        return [section.to_langchain_document() for section in self.sections]


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """尚未写入数据库的文档切片。"""

    chunk_number: int
    content: str
    retrieval_text: str
    content_sha256: str

    source_path: Path
    source_name: str
    file_type: str
    location_label: str

    page_start: int | None = None
    page_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_title: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_langchain_document(self) -> Document:
        document_metadata: dict[str, Any] = {
            "chunk_number": self.chunk_number,
            "content_sha256": self.content_sha256,
            "source": str(self.source_path),
            "source_name": self.source_name,
            "file_type": self.file_type,
            "location_label": self.location_label,
            "section_title": self.section_title,
            **self.metadata,
        }

        if self.page_start is not None:
            document_metadata["page_start"] = self.page_start

        if self.page_end is not None:
            document_metadata["page_end"] = self.page_end

        if self.line_start is not None:
            document_metadata["line_start"] = self.line_start

        if self.line_end is not None:
            document_metadata["line_end"] = self.line_end

        return Document(
            page_content=self.retrieval_text,
            metadata=document_metadata,
        )
