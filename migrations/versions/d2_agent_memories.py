"""add confirmed Agent memories

Revision ID: d2_agent_memories
Revises: c13_agent_workflows
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2_agent_memories"
down_revision: Union[str, None] = "c13_agent_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(30), nullable=False, server_default="user_confirmed"),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memories_scope", "agent_memories", ["scope"])
    op.create_index("ix_agent_memories_course_id", "agent_memories", ["course_id"])
    op.create_index("ix_agent_memories_category", "agent_memories", ["category"])
    op.create_index("ix_agent_memories_confirmed", "agent_memories", ["confirmed"])
    op.create_index("ix_agent_memories_deleted", "agent_memories", ["deleted"])


def downgrade() -> None:
    for name in (
        "ix_agent_memories_deleted", "ix_agent_memories_confirmed",
        "ix_agent_memories_category", "ix_agent_memories_course_id",
        "ix_agent_memories_scope",
    ):
        op.drop_index(name, table_name="agent_memories")
    op.drop_table("agent_memories")
