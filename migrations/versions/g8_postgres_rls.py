"""enable PostgreSQL row level security after tenant backfill

Revision ID: g8_postgres_rls
Revises: g7_audit_events
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8_postgres_rls"
down_revision: Union[str, None] = "g7_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
    "courses", "study_tasks", "questions", "review_items", "resource_files", "knowledge_points",
    "practice_sessions", "question_attempts", "practice_session_questions", "review_attempts",
    "study_sessions", "study_goals", "task_recurrences", "background_jobs", "document_indexes",
    "document_chunks", "document_embeddings", "ai_runs", "ai_citations", "knowledge_point_drafts",
    "question_drafts", "subjective_grading_results", "error_analysis_results", "learning_plan_drafts",
    "adaptive_plan_drafts", "learning_report_snapshots", "research_runs", "agent_sessions",
    "agent_memories", "agent_workflows", "audit_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if inspector.has_table("ai_citations") and "tenant_id" not in {column["name"] for column in inspector.get_columns("ai_citations")}:
        op.add_column("ai_citations", sa.Column("tenant_id", sa.String(length=36), nullable=True))
        op.create_index("ix_ai_citations_tenant_id", "ai_citations", ["tenant_id"])
    # Citations inherit their tenant from the AI run. This migration predates
    # the explicit citation tenant column, so fill it before the generic NULL
    # guard below enables RLS.
    if inspector.has_table("ai_citations") and inspector.has_table("ai_runs"):
        bind.execute(sa.text(
            "UPDATE ai_citations citation SET tenant_id = run.tenant_id "
            "FROM ai_runs run "
            "WHERE citation.ai_run_id = run.id AND citation.tenant_id IS NULL"
        ))
    for table in TENANT_TABLES:
        if not inspector.has_table(table):
            continue
        null_count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL")).scalar_one()
        if null_count:
            raise RuntimeError(
                f"cannot enable RLS: {table} has {null_count} rows without tenant_id; "
                "run scripts/backfill_legacy_tenant.py --apply first"
            )
        quoted = bind.dialect.identifier_preparer.quote(table)
        policy = bind.dialect.identifier_preparer.quote(f"tenant_isolation_{table}")
        bind.execute(sa.text(f"ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(
            f"CREATE POLICY {policy} ON {quoted} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    for table in reversed(TENANT_TABLES):
        if not inspector.has_table(table):
            continue
        quoted = bind.dialect.identifier_preparer.quote(table)
        policy = bind.dialect.identifier_preparer.quote(f"tenant_isolation_{table}")
        bind.execute(sa.text(f"DROP POLICY IF EXISTS {policy} ON {quoted}"))
        bind.execute(sa.text(f"ALTER TABLE {quoted} DISABLE ROW LEVEL SECURITY"))
    if inspector.has_table("ai_citations") and "tenant_id" in {column["name"] for column in inspector.get_columns("ai_citations")}:
        bind.execute(sa.text("DROP INDEX IF EXISTS ix_ai_citations_tenant_id"))
        op.drop_column("ai_citations", "tenant_id")
