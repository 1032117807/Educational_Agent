"""Backfill legacy single-tenant rows into one organization.

The command is intentionally dry-run by default. It only fills NULL tenant_id
values and never rewrites rows that already belong to an organization.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMember, User


TENANT_TABLES = (
    "courses",
    "study_tasks",
    "questions",
    "review_items",
    "resource_files",
    "knowledge_points",
    "practice_sessions",
    "question_attempts",
    "practice_session_questions",
    "review_attempts",
    "study_sessions",
    "study_goals",
    "background_jobs",
    "document_indexes",
    "document_chunks",
    "document_embeddings",
    "ai_runs",
    "ai_citations",
    "knowledge_point_drafts",
    "question_drafts",
    "subjective_grading_results",
    "error_analysis_results",
    "learning_plan_drafts",
    "adaptive_plan_drafts",
    "learning_report_snapshots",
    "research_runs",
    "agent_sessions",
    "agent_memories",
    "agent_workflows",
    "task_recurrences",
    "learning_events",
)


@dataclass(frozen=True)
class BackfillReport:
    tenant_id: str
    existing_tables: tuple[str, ...]
    pending_rows: dict[str, int]
    changed_rows: int
    applied: bool


def validate_tenant_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("tenant_id must be a UUID") from exc


def backfill_legacy_rows(
    engine: Engine,
    *,
    tenant_id: str,
    organization_name: str = "Legacy workspace",
    owner_email: str | None = None,
    apply: bool = False,
) -> BackfillReport:
    tenant_id = validate_tenant_id(tenant_id)
    inspector = inspect(engine)
    existing = tuple(table for table in TENANT_TABLES if inspector.has_table(table))
    pending: dict[str, int] = {}
    with Session(engine) as session:
        for table in existing:
            columns = {column["name"] for column in inspector.get_columns(table)}
            if "tenant_id" not in columns:
                continue
            count = session.scalar(text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IS NULL")) or 0
            if count:
                pending[table] = int(count)
        if not apply:
            return BackfillReport(tenant_id, existing, pending, 0, False)

        # Identity rows are created only during an explicit apply. Existing
        # organizations/users are preserved and are never overwritten.
        organization = session.get(Organization, tenant_id)
        if organization is None:
            organization = Organization(id=tenant_id, name=organization_name.strip() or "Legacy workspace", slug=f"legacy-{tenant_id[:8]}")
            session.add(organization)
            session.flush()
        if owner_email:
            owner = session.scalar(select(User).where(User.email == owner_email.lower()))
            if owner is None:
                raise ValueError("owner email does not exist; create the user before backfill")
            member = session.scalar(select(OrganizationMember).where(
                OrganizationMember.organization_id == tenant_id,
                OrganizationMember.user_id == owner.id,
            ))
            if member is None:
                session.add(OrganizationMember(organization_id=tenant_id, user_id=owner.id, role="owner"))

        changed = 0
        for table, count in pending.items():
            result = session.execute(text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), {"tenant_id": tenant_id})
            changed += int(result.rowcount if result.rowcount is not None and result.rowcount >= 0 else count)
        session.commit()
    return BackfillReport(tenant_id, existing, pending, changed, True)
