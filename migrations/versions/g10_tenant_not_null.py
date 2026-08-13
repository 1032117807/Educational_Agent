"""require tenant scope for PostgreSQL SaaS records

Revision ID: g10_tenant_not_null
Revises: g9_worker_job_rls
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.versions.g8_postgres_rls import TENANT_TABLES


revision: str = "g10_tenant_not_null"
down_revision: Union[str, None] = "g9_worker_job_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    for table in TENANT_TABLES:
        if not inspector.has_table(table):
            continue
        null_count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL")).scalar_one()
        if null_count:
            raise RuntimeError(f"cannot require tenant_id: {table} has {null_count} NULL rows")
        op.alter_column(table, "tenant_id", existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    for table in reversed(TENANT_TABLES):
        if inspector.has_table(table):
            op.alter_column(table, "tenant_id", existing_type=sa.String(length=36), nullable=True)
