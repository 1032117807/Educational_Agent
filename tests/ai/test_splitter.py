from __future__ import annotations

from pathlib import Path

import pytest

from ai.ingestion import (
    CitationAwareSplitter,
    clean_text_for_retrieval,
)
from ai.models import ParsedDocument, ParsedSection


def make_pdf_document(*page_contents: str) -> ParsedDocument:
    path = Path("教材.pdf")

    sections = tuple(
        ParsedSection(
            content=content,
            source_path=path,
            source_name=path.name,
            file_type="pdf",
            location_label=f"第 {page_number} 页",
            page_start=page_number,
            page_end=page_number,
            metadata={
                "pdf_page_index": page_number - 1,
                "extraction_method": "ocr",
                "ocr_confidence": 0.96,
            },
        )
        for page_number, content in enumerate(page_contents, start=1)
    )

    return ParsedDocument(
        source_path=path,
        file_type="pdf",
        parser_version="test-parser-v1",
        sections=sections,
    )


def test_long_pdf_page_is_split_without_losing_page_number() -> None:
    document = make_pdf_document(
        "第一章内容。" * 150,
        "第二章内容。" * 150,
    )
    splitter = CitationAwareSplitter(
        chunk_size=300,
        chunk_overlap=50,
    )

    chunks = splitter.split_document(document)

    page_one_chunks = [chunk for chunk in chunks if chunk.page_start == 1]
    page_two_chunks = [chunk for chunk in chunks if chunk.page_start == 2]

    assert len(page_one_chunks) > 1
    assert len(page_two_chunks) > 1

    assert all(chunk.page_end == 1 for chunk in page_one_chunks)
    assert all(chunk.location_label == "第 1 页" for chunk in page_one_chunks)

    assert all(chunk.page_end == 2 for chunk in page_two_chunks)
    assert all(chunk.location_label == "第 2 页" for chunk in page_two_chunks)

    assert [chunk.chunk_number for chunk in chunks] == list(range(len(chunks)))


def test_ocr_metadata_is_inherited_by_every_chunk() -> None:
    document = make_pdf_document("扫描内容。" * 150)
    splitter = CitationAwareSplitter(
        chunk_size=300,
        chunk_overlap=50,
    )

    chunks = splitter.split_document(document)

    assert len(chunks) > 1
    assert all(
        chunk.metadata["extraction_method"] == "ocr"
        for chunk in chunks
    )
    assert all(
        chunk.metadata["ocr_confidence"] == 0.96
        for chunk in chunks
    )


def test_retrieval_cleaning_does_not_change_original_content() -> None:
    original = (
        "3.2.3 稀疏嵌入"
        "........................"
        "83"
    )
    document = make_pdf_document(original)
    splitter = CitationAwareSplitter(
        chunk_size=300,
        chunk_overlap=50,
    )

    chunks = splitter.split_document(document)

    assert len(chunks) == 1
    assert "........................" in chunks[0].content
    assert "........................" not in chunks[0].retrieval_text
    assert chunks[0].content_sha256


def test_langchain_document_contains_citation_metadata() -> None:
    document = make_pdf_document("极限描述函数值的变化趋势。")
    splitter = CitationAwareSplitter(
        chunk_size=300,
        chunk_overlap=50,
    )

    chunk = splitter.split_document(document)[0]
    langchain_document = chunk.to_langchain_document()

    assert langchain_document.page_content == chunk.retrieval_text
    assert langchain_document.metadata["source_name"] == "教材.pdf"
    assert langchain_document.metadata["page_start"] == 1
    assert langchain_document.metadata["location_label"] == "第 1 页"


@pytest.mark.parametrize(
    ("chunk_size", "chunk_overlap"),
    [
        (100, 20),
        (300, -1),
        (300, 300),
        (300, 500),
    ],
)
def test_invalid_splitter_configuration_is_rejected(
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    with pytest.raises(ValueError):
        CitationAwareSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )