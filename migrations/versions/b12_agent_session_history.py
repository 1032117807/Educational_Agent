"""add agent session history

Revision ID: b12_agent_session_history
Revises: f4c2e8a6d901
Create Date: 2026-08-04 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b12_agent_session_history"
down_revision: Union[str, None] = "f4c2e8a6d901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("agent_sessions", sa.Column("id", sa.Integer(), nullable=False), sa.Column("title", sa.String(length=160), nullable=False), sa.Column("archived", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_sessions_archived", "agent_sessions", ["archived"])
    op.create_index("ix_agent_sessions_created_at", "agent_sessions", ["created_at"])
    op.create_index("ix_agent_sessions_updated_at", "agent_sessions", ["updated_at"])
    op.create_table("agent_messages", sa.Column("id", sa.Integer(), nullable=False), sa.Column("session_id", sa.Integer(), nullable=False), sa.Column("role", sa.String(length=20), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])
    op.create_index("ix_agent_messages_created_at", "agent_messages", ["created_at"])
    op.create_table("agent_tool_calls", sa.Column("id", sa.Integer(), nullable=False), sa.Column("session_id", sa.Integer(), nullable=False), sa.Column("tool_name", sa.String(length=120), nullable=False), sa.Column("status", sa.String(length=20), nullable=False), sa.Column("detail", sa.Text(), nullable=False), sa.Column("input_json", sa.Text(), nullable=False), sa.Column("output_json", sa.Text(), nullable=False), sa.Column("error_message", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("finished_at", sa.DateTime(), nullable=True), sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_tool_calls_session_id", "agent_tool_calls", ["session_id"])
    op.create_index("ix_agent_tool_calls_status", "agent_tool_calls", ["status"])
    op.create_index("ix_agent_tool_calls_created_at", "agent_tool_calls", ["created_at"])
    op.create_table("agent_handoffs", sa.Column("id", sa.Integer(), nullable=False), sa.Column("session_id", sa.Integer(), nullable=False), sa.Column("kind", sa.String(length=50), nullable=False), sa.Column("target_id", sa.Integer(), nullable=True), sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_handoffs_session_id", "agent_handoffs", ["session_id"])
    op.create_index("ix_agent_handoffs_kind", "agent_handoffs", ["kind"])
    op.create_index("ix_agent_handoffs_target_id", "agent_handoffs", ["target_id"])
    op.create_index("ix_agent_handoffs_created_at", "agent_handoffs", ["created_at"])


def downgrade() -> None:
    op.drop_table("agent_handoffs")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_messages")
    op.drop_table("agent_sessions")
