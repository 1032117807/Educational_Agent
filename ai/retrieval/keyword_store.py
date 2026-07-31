from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import jieba
from sqlalchemy import text

from app.database import Database
from app.models import DocumentChunk

jieba.setLogLevel(logging.WARNING)


@dataclass(frozen=True, slots=True)
class KeywordHit:
    chunk_id: int
    rank: int
    bm25_score: float

def tokenize_for_search(value:str) -> list[str]:
     """同时支持中文分词、英文单词和数字。"""

     normalized = value.casefold()  
     normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", normalized)

     tokens:list[str] = []

     for segment in jieba.cut_for_search(normalized):
          token = segment.strip()

          if not token:
               continue

          if re.fullmatch(r"[\W_]+", token):
               continue

          tokens.append(token)

     # 保持原顺序并去重。
     return list(dict.fromkeys(tokens))

def build_fts_query(query: str) -> str:
    """构建安全的 FTS 查询，避免用户输入成为 FTS 语法。"""

    tokens = tokenize_for_search(query)

    if not tokens:
        return ""

    quoted = [
        f'"{token.replace(chr(34), chr(34) * 2)}"'
        for token in tokens
    ]

    return " OR ".join(quoted)


class SQLiteKeywordIndex:
     """document_chunks 的可重建 FTS5 索引。"""

     def __init__(self, database: Database) -> None:
        self.database = database
        self.ensure_schema()

     def ensure_schema(self) -> None:
          with self.database.engine.begin() as connection:
               try:
                    connection.exec_driver_sql(
                         """
                         CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts
                         USING fts5(
                         chunk_id UNINDEXED,
                         document_index_id UNINDEXED,
                         resource_id UNINDEXED,
                         course_id UNINDEXED,
                         search_text,
                         tokenize='unicode61 remove_diacritics 2'
                         )
                         """
                    )
               except Exception as exc:
                    raise RuntimeError(
                         "当前 SQLite 不支持 FTS5，无法建立关键词索引"
                    ) from exc

     def rebuild_document(self, document_index_id: int) -> int:
          """重建一份文档的关键词索引。"""

          with self.database.session() as session:
               chunks = list(
                    session.query(DocumentChunk)
                    .filter(
                         DocumentChunk.document_index_id
                         == document_index_id
                    )
                    .order_by(DocumentChunk.chunk_number)
               )

          rows: list[dict[str, str | int]] = []

          for chunk in chunks:
               metadata = json.loads(chunk.metadata_json or "{}")
               retrieval_text = str(
                    metadata.get("retrieval_text") or chunk.content
               )
               tokenized_text = " ".join(
                    tokenize_for_search(retrieval_text)
               )

               if not tokenized_text:
                    continue

               rows.append({
                    "chunk_id": chunk.id,
                    "document_index_id": chunk.document_index_id,
                    "resource_id": chunk.resource_id,
                    "course_id": (
                         chunk.course_id
                         if chunk.course_id is not None
                         else -1
                    ),
                    "search_text": tokenized_text,
               })

          with self.database.engine.begin() as connection:
               connection.execute(
                    text(
                         """
                         DELETE FROM document_chunks_fts
                         WHERE document_index_id = :document_index_id
                         """
                    ),
                    {"document_index_id": document_index_id},
               )

               if rows:
                    connection.execute(
                         text(
                         """
                         INSERT INTO document_chunks_fts (
                              chunk_id,
                              document_index_id,
                              resource_id,
                              course_id,
                              search_text
                         )
                         VALUES (
                              :chunk_id,
                              :document_index_id,
                              :resource_id,
                              :course_id,
                              :search_text
                         )
                         """
                         ),
                         rows,
                    )

          return len(rows)

     def delete_document(self, document_index_id: int) -> int:
        with self.database.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM document_chunks_fts
                    WHERE document_index_id = :document_index_id
                    """
                ),
                {"document_index_id": document_index_id},
            )

            return int(result.rowcount or 0)

     def search(
          self,
          query: str,
          *,
          limit: int = 20,
          course_id: int | None = None,
          resource_ids: list[int] | None = None,
     ) -> list[KeywordHit]:
          fts_query = build_fts_query(query)

          if not fts_query:
               return []

          conditions = [
               "document_chunks_fts MATCH :query",
               "di.status = 'completed'",
          ]
          parameters: dict[str, object] = {
               "query": fts_query,
               "limit": limit,
          }

          if course_id is not None:
               conditions.append("rf.course_id = :course_id")
               parameters["course_id"] = course_id

          if resource_ids:
               placeholders: list[str] = []

               for index, resource_id in enumerate(resource_ids):
                    name = f"resource_id_{index}"
                    placeholders.append(f":{name}")
                    parameters[name] = resource_id

               conditions.append(
                    "CAST(f.resource_id AS INTEGER) IN "
                    f"({', '.join(placeholders)})"
               )

          statement = text(
               f"""
               SELECT
                    CAST(f.chunk_id AS INTEGER) AS chunk_id,
                    bm25(document_chunks_fts) AS score
               FROM document_chunks_fts AS f
               JOIN document_chunks AS dc
                    ON dc.id = CAST(f.chunk_id AS INTEGER)
               JOIN document_indexes AS di
                    ON di.id = dc.document_index_id
               JOIN resource_files AS rf
                    ON rf.id = dc.resource_id
               WHERE {' AND '.join(conditions)}
               ORDER BY score
               LIMIT :limit
               """
          )

          with self.database.engine.connect() as connection:
               rows = connection.execute(
                    statement,
                    parameters,
               ).fetchall()

          return [
               KeywordHit(
                    chunk_id=int(row.chunk_id),
                    rank=rank,
                    bm25_score=float(row.score),
               )
               for rank, row in enumerate(rows, start=1)
          ]

    
