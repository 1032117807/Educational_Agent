"""Create reviewable RAG annotation candidates from supplied learning files.

It never assigns relevant_chunk_ids. Reviewers add real IDs only after the
document has been indexed by the application.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _pages(source: Path) -> list[str]:
    if source.suffix.lower() in {".md", ".txt"}:
        return [source.read_text(encoding="utf-8", errors="replace")]
    if source.suffix.lower() == ".pdf":
        executable = shutil.which("pdftotext")
        if not executable:
            raise RuntimeError("pdftotext is required to extract PDF candidates")
        output = subprocess.run([executable, "-layout", str(source), "-"], check=True, capture_output=True).stdout.decode("utf-8", errors="replace")
        return output.split("\f")
    raise ValueError("source must be .pdf, .md, or .txt")


def candidates(source: Path, *, limit: int = 200) -> list[dict[str, object]]:
    topics: list[tuple[int | None, str]] = []
    for page_number, page in enumerate(_pages(source), 1):
        lines = [line.strip().lstrip("#").strip() for line in page.splitlines()]
        # Prefer short heading-like lines. Pages without a title use the first
        # substantive sentence, retaining the true page reference for review.
        topic = next((line for line in lines if 4 <= len(line) <= 80 and not line[-1:] in {"。", ".", "，", ","}), None)
        topic = topic or next((line for line in lines if 12 <= len(line) <= 120), None)
        if topic:
            topics.append((page_number if source.suffix.lower() == ".pdf" else None, topic))
    topics = list(dict.fromkeys(topics))[:limit]
    now = datetime.now(timezone.utc).isoformat()
    return [{
        "id": f"candidate-{index:04d}", "query": f"Explain {topic}.", "relevant_chunk_ids": [],
        "source_document": source.name, "source_page": page_number, "category": "unreviewed", "difficulty": "unreviewed",
        "dataset_version": "rag-candidates-v1", "created_at": now,
        "labeling_method": "heuristic topic extraction; human confirmation required", "gold_label_verified": False,
        "source": str(source), "annotation_note": "Index this source, replace relevant_chunk_ids with actual IDs, then review all fields.",
    } for index, (page_number, topic) in enumerate(topics, 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="Learning material: .pdf, UTF-8 .md, or .txt")
    parser.add_argument("--output", type=Path, default=Path("evals/datasets/rag_candidates.jsonl"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    rows = candidates(args.source, limit=max(1, args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")
    print(f"{args.output}: {len(rows)} unverified candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
