from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text


TENANT_TABLES = (
    "courses", "study_tasks", "questions", "review_items", "resource_files", "knowledge_points",
    "practice_sessions", "question_attempts", "practice_session_questions", "review_attempts",
    "study_sessions", "study_goals", "task_recurrences", "background_jobs", "document_indexes",
    "document_chunks", "document_embeddings", "ai_runs", "ai_citations", "knowledge_point_drafts",
    "question_drafts", "subjective_grading_results", "error_analysis_results", "learning_plan_drafts",
    "adaptive_plan_drafts", "learning_report_snapshots", "research_runs", "agent_sessions",
    "agent_memories", "agent_workflows", "audit_events",
)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    app_user = os.environ.get("APP_DB_USER", "")
    if not database_url.startswith("postgresql"):
        print("DATABASE_URL must point to PostgreSQL", file=sys.stderr)
        return 2
    if not app_user:
        print("APP_DB_USER is required to verify the runtime role", file=sys.stderr)
        return 2
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            version = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
            if not version:
                print("pgvector extension is not installed", file=sys.stderr)
                return 1
            embedding_table = connection.scalar(text("SELECT to_regclass('public.document_embeddings')"))
            if embedding_table != "document_embeddings":
                print("document_embeddings migration has not run", file=sys.stderr)
                return 1
            indexes = set(connection.scalars(text("SELECT indexname FROM pg_indexes WHERE tablename = 'document_embeddings'")))
            if "ix_document_embeddings_hnsw" not in indexes:
                print("pgvector HNSW index is missing", file=sys.stderr)
                return 1
            tenant_relations = connection.execute(text(
                "SELECT relation.relname, relation.relrowsecurity, attribute.attnotnull "
                "FROM pg_class relation "
                "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                "JOIN pg_attribute attribute ON attribute.attrelid = relation.oid "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relname = ANY(:tables) "
                "AND attribute.attname = 'tenant_id'"
            ), {"tables": list(TENANT_TABLES)}).all()
            relation_status = {name: (rls_enabled, tenant_not_null) for name, rls_enabled, tenant_not_null in tenant_relations}
            missing = sorted(set(TENANT_TABLES) - set(relation_status))
            unsecured = sorted(name for name, (rls_enabled, tenant_not_null) in relation_status.items() if not rls_enabled or not tenant_not_null)
            if missing or unsecured:
                detail = []
                if missing:
                    detail.append(f"missing tenant_id metadata: {', '.join(missing)}")
                if unsecured:
                    detail.append(f"RLS or NOT NULL missing: {', '.join(unsecured)}")
                print("; ".join(detail), file=sys.stderr)
                return 1
            runtime_role = connection.execute(text(
                "SELECT role.rolsuper, role.rolcreatedb, role.rolcreaterole, role.rolbypassrls, "
                "EXISTS (SELECT 1 FROM pg_database database WHERE database.datname = current_database() AND database.datdba = role.oid) "
                "FROM pg_roles role WHERE role.rolname = :name"
            ), {"name": app_user}).one_or_none()
            if runtime_role is None:
                print("runtime database role does not exist", file=sys.stderr)
                return 1
            if any(runtime_role):
                print("runtime database role has elevated privileges or owns the database", file=sys.stderr)
                return 1
            inherits_privileged_role = connection.scalar(text(
                "WITH RECURSIVE inherited_roles(roleid) AS ("
                "SELECT membership.roleid FROM pg_auth_members membership "
                "JOIN pg_roles member ON member.oid = membership.member "
                "WHERE member.rolname = :name "
                "UNION "
                "SELECT membership.roleid FROM pg_auth_members membership "
                "JOIN inherited_roles inherited ON inherited.roleid = membership.member"
                ") SELECT EXISTS (SELECT 1 FROM inherited_roles "
                "JOIN pg_roles parent ON parent.oid = inherited_roles.roleid "
                "WHERE parent.rolsuper OR parent.rolcreatedb OR parent.rolcreaterole OR parent.rolbypassrls)"
            ), {"name": app_user})
            owns_public_relation = connection.scalar(text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_class relation "
                "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                "JOIN pg_roles role ON role.oid = relation.relowner "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind IN ('r', 'p', 'S', 'v', 'm') "
                "AND role.rolname = :name"
                ")"
            ), {"name": app_user})
            if inherits_privileged_role or owns_public_relation:
                print("runtime database role inherits privileged roles or owns public relations", file=sys.stderr)
                return 1
    finally:
        engine.dispose()
    print("SaaS PostgreSQL/pgvector/RLS integration verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
