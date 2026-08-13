"""allow trusted workers to claim tenant jobs under RLS

Revision ID: g9_worker_job_rls
Revises: g8_postgres_rls
"""

from typing import Sequence, Union

from alembic import op


revision: str = "g9_worker_job_rls"
down_revision: Union[str, None] = "g8_postgres_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenant_isolation_background_jobs ON background_jobs")
    op.execute(
        "CREATE POLICY tenant_isolation_background_jobs ON background_jobs "
        "USING (tenant_id = current_setting('app.tenant_id', true) "
        "OR current_setting('app.is_worker', true) = 'true') "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true) "
        "OR current_setting('app.is_worker', true) = 'true')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenant_isolation_background_jobs ON background_jobs")
    op.execute(
        "CREATE POLICY tenant_isolation_background_jobs ON background_jobs "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
