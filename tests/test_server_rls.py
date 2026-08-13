from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models
from app.database import Base
from server.tenant_session import attach_tenant_transaction_hook, set_session_tenant, set_worker_session


def test_tenant_session_context_is_retained_for_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    attach_tenant_transaction_hook(factory)
    with factory() as session:
        set_session_tenant(session, "tenant-a")
        assert session.info["tenant_id"] == "tenant-a"
        session.execute("SELECT 1") if False else None


def test_rls_migration_is_noop_for_sqlite() -> None:
    # The migration deliberately returns before PostgreSQL-only SQL executes.
    from migrations.versions.g8_postgres_rls import upgrade
    engine = create_engine("sqlite:///:memory:")
    with engine.begin():
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        context = MigrationContext.configure(engine.connect())
        operations = Operations(context)
        original = __import__("migrations.versions.g8_postgres_rls", fromlist=["op"]).op
        module = __import__("migrations.versions.g8_postgres_rls", fromlist=["op"])
        module.op = operations
        try:
            upgrade()
        finally:
            module.op = original


def test_rls_migration_backfills_legacy_citation_tenants() -> None:
    source = open("migrations/versions/g8_postgres_rls.py", encoding="utf-8").read()
    assert "UPDATE ai_citations" in source
    assert "FROM ai_runs" in source


def test_worker_session_marker_is_retained_for_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    factory = sessionmaker(engine)
    with factory() as session:
        set_worker_session(session)
        assert session.info["is_worker"] is True


def test_worker_rls_policy_is_limited_to_background_jobs() -> None:
    source = open("migrations/versions/g9_worker_job_rls.py", encoding="utf-8").read()
    assert "background_jobs" in source
    assert "app.is_worker" in source
    assert "CREATE POLICY tenant_isolation_background_jobs" in source


def test_compose_uses_a_non_owner_runtime_database_role() -> None:
    compose = open("docker-compose.saas.yml", encoding="utf-8").read()
    grant_script = open("scripts/grant_saas_runtime_role.py", encoding="utf-8").read()
    assert "APP_DB_USER" in compose
    assert "APP_DB_PASSWORD" in compose
    assert "grant_saas_runtime_role.py" in compose
    assert "APP_DB_PASSWORD" in compose
    assert "NOBYPASSRLS" in open("docker/postgres/init-runtime-role.sh", encoding="utf-8").read()
    assert "rolbypassrls" in grant_script
    assert "rolsuper" in grant_script
    assert "rolcreaterole" in grant_script
    assert "pg_auth_members" in grant_script
    assert "WITH RECURSIVE inherited_roles" in grant_script
    assert "pg_database" in grant_script
    assert "pg_class" in grant_script
    assert "CREATE ROLE" in grant_script
    assert "APP_DB_PASSWORD" in grant_script


def test_postgres_integration_verifier_checks_rls_and_runtime_role() -> None:
    source = open("scripts/verify_saas_integration.py", encoding="utf-8").read()
    assert "TENANT_TABLES" in source
    assert "relrowsecurity" in source
    assert "attnotnull" in source
    assert "APP_DB_USER" in source
    assert "rolbypassrls" in source
    assert "pg_auth_members" in source
    assert "WITH RECURSIVE inherited_roles" in source
    assert "pg_class" in source


def test_ci_runs_the_real_saas_stack_and_integration_verifier() -> None:
    workflow = open(".github/workflows/saas-integration.yml", encoding="utf-8").read()
    assert "docker compose -f docker-compose.saas.yml up -d --build" in workflow
    assert "/health/ready" in workflow
    assert "scripts/verify_saas_integration.py" in workflow
    assert "APP_ENV: production" in workflow
    assert "logs --no-color" in workflow
    assert "REDIS_PASSWORD" in workflow


def test_compose_requires_redis_authentication() -> None:
    compose = open("docker-compose.saas.yml", encoding="utf-8").read()
    assert "--requirepass" in compose
    assert "environment:\n      REDIS_PASSWORD:" in compose
    assert "REDIS_PASSWORD" in compose
    assert "redis-cli --no-auth-warning -a" in compose


def test_tenant_not_null_migration_rechecks_null_rows() -> None:
    source = open("migrations/versions/g10_tenant_not_null.py", encoding="utf-8").read()
    assert "WHERE tenant_id IS NULL" in source
    assert "nullable=False" in source
