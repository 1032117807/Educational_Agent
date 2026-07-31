"""add knowledge point vector tracking

Revision ID: d6a77b92e310
Revises: c3f9a821d104
Create Date: 2026-07-29 19:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6a77b92e310"
down_revision: Union[str, None] = "c3f9a821d104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_points") as batch:
        batch.add_column(sa.Column("vector_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column(
            "embedding_model", sa.String(160), nullable=False, server_default=""
        ))
        batch.create_unique_constraint("uq_knowledge_points_vector_id", ["vector_id"])


def downgrade() -> None:
    with op.batch_alter_table("knowledge_points") as batch:
        batch.drop_constraint("uq_knowledge_points_vector_id", type_="unique")
        batch.drop_column("embedding_model")
        batch.drop_column("vector_id")
