# Annotation Workflow

The formal datasets are intentionally empty until a person reviews candidates.
Use the candidate schemas below, edit `relevant_chunk_ids` or conflict labels
in a spreadsheet/JSONL editor, then set `gold_label_verified: true` only after
review. Never promote model-proposed labels automatically.

RAG records must contain `id`, `query`, `relevant_chunk_ids`, `source_document`,
optional `source_page`, `category`, `difficulty`, `dataset_version`,
`created_at`, `labeling_method`, `gold_label_verified`, and `source`.

Memory records must contain the same metadata plus `old`, `new`, and one of
`ADD`, `UPDATE`, `DELETE`, `NOOP`. Include provenance flags for user-confirmed,
third-party, speculative, uncertain, cross-session, and time-changing cases.

Skill records must contain `user_request`, `expected_skill`, `allowed_skills`,
`no_skill`, `expected_output_requirements`, and the same metadata fields.
