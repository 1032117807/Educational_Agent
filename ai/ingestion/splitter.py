from __future__ import annotations

import hashlib
import re

from ai.models import ChunkDraft, ParsedDocument, ParsedSection


CHUNKER_VERSION = "recursive-citation-v1"


def clean_text_for_retrieval(text: str) -> str:
    """清理检索噪声，不修改原始引用文本。"""

    text = text.replace("\u00a0", " ")
    text = re.sub(r"(?:\.\s*){4,}", " ", text)
    text = re.sub(r"(?:·\s*){4,}", " ", text)
    text = re.sub(r"(?:…\s*){2,}", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()

def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class CitationAwareSplitter:
    """在每个自然结构区段内部切片，并继承其引用位置。"""

    def __init__(
        self,
        *,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        if chunk_size < 200:
            raise ValueError("chunk_size 不能小于 200")

        if chunk_overlap < 0:
            raise ValueError("chunk_overlap 不能为负数")

        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Import lazily: langchain-text-splitters imports optional
        # sentence-transformers modules from its package initializer, which in
        # turn loads PyTorch. Document splitting itself does not need PyTorch,
        # and a blocked optional native DLL must not prevent the desktop app
        # from starting.
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            keep_separator=True,
            separators=[
                "\n\n",
                "\n",
                "。", "！", "？", "；",
                ". ", "! ", "? ", "; ",
                "，", ", ",
                " ",
                "",
            ],
        )

    @property
    def version(self) -> str:
        return CHUNKER_VERSION

    def split_document(
        self,
        document: ParsedDocument,
    ) -> list[ChunkDraft]:
        chunks: list[ChunkDraft] = []
        next_chunk_number = 0

        # 每个 section 分别切片，禁止跨页或跨幻灯片拼接。
        for section_number, section in enumerate(document.sections):
            section_chunks = self._split_section(
                section=section,
                section_number=section_number,
                first_chunk_number=next_chunk_number,
            )
            chunks.extend(section_chunks)
            next_chunk_number += len(section_chunks)

        return chunks

    def _split_section(
        self,
        *,
        section: ParsedSection,
        section_number: int,
        first_chunk_number: int,
    ) -> list[ChunkDraft]:
        raw_chunks = self._splitter.split_text(section.content)
        result: list[ChunkDraft] = []

        for local_number, raw_content in enumerate(raw_chunks):
            content = raw_content.strip()
            if not content:
                continue

            retrieval_text = clean_text_for_retrieval(content)
            if not retrieval_text:
                continue

            chunk_number = first_chunk_number + len(result)

            result.append(
                ChunkDraft(
                    chunk_number=chunk_number,
                    content=content,
                    retrieval_text=retrieval_text,
                    content_sha256=content_sha256(content),
                    source_path=section.source_path,
                    source_name=section.source_name,
                    file_type=section.file_type,
                    location_label=section.location_label,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    line_start=section.line_start,
                    line_end=section.line_end,
                    section_title=section.section_title,
                    metadata={
                        **section.metadata,
                        "section_number": section_number,
                        "section_chunk_number": local_number,
                        "chunker_version": self.version,
                    },
                )
            )

        return result


