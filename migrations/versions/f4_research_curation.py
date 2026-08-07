"""add auditable web research candidates

Revision ID: f4_research_curation
Revises: e3_adaptive_learning
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4_research_curation"
down_revision: Union[str, None] = "e3_adaptive_learning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_runs_course_id", "research_runs", ["course_id"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_index("ix_research_runs_created_at", "research_runs", ["created_at"])
    op.create_table(
        "web_resource_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("research_run_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("relevance_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("learning_uses_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("imported_resource_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["imported_resource_id"], ["resource_files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_web_resource_candidates_research_run_id", ["research_run_id"]),
        ("ix_web_resource_candidates_url", ["url"]),
        ("ix_web_resource_candidates_domain", ["domain"]),
        ("ix_web_resource_candidates_relevance_score", ["relevance_score"]),
        ("ix_web_resource_candidates_status", ["status"]),
        ("ix_web_resource_candidates_imported_resource_id", ["imported_resource_id"]),
    ):
        op.create_index(name, "web_resource_candidates", columns)


def downgrade() -> None:
    for name in (
        "ix_web_resource_candidates_imported_resource_id", "ix_web_resource_candidates_status",
        "ix_web_resource_candidates_relevance_score", "ix_web_resource_candidates_domain",
        "ix_web_resource_candidates_url", "ix_web_resource_candidates_research_run_id",
    ):
        op.drop_index(name, table_name="web_resource_candidates")
    op.drop_table("web_resource_candidates")
    for name in ("ix_research_runs_created_at", "ix_research_runs_status", "ix_research_runs_course_id"):
        op.drop_index(name, table_name="research_runs")
    op.drop_table("research_runs")
