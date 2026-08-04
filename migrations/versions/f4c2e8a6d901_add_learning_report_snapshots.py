"""add learning report snapshots

Revision ID: f4c2e8a6d901
Revises: a31_learning_plan_drafts
Create Date: 2026-08-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c2e8a6d901"
down_revision: Union[str, None] = "a31_learning_plan_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learning_report_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("learning_report_snapshots", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_learning_report_snapshots_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_learning_report_snapshots_end_date"), ["end_date"], unique=False)
        batch_op.create_index(batch_op.f("ix_learning_report_snapshots_start_date"), ["start_date"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("learning_report_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_learning_report_snapshots_start_date"))
        batch_op.drop_index(batch_op.f("ix_learning_report_snapshots_end_date"))
        batch_op.drop_index(batch_op.f("ix_learning_report_snapshots_created_at"))
    op.drop_table("learning_report_snapshots")
