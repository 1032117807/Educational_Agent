"""PostgreSQL session state used by tenant RLS policies."""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker


def set_session_tenant(session: Session, tenant_id: str) -> None:
    """Store a tenant on the session and set it for the current transaction."""
    info = getattr(session, "info", None)
    if info is None:
        # Lightweight test doubles may not model SQLAlchemy session state.
        return
    info["tenant_id"] = tenant_id
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})


def set_worker_session(session: Session) -> None:
    """Mark a trusted worker transaction for durable job claim/update only."""
    session.info["is_worker"] = True
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT set_config('app.is_worker', 'true', true)"))


def attach_tenant_transaction_hook(factory: sessionmaker) -> None:
    """Restore app.tenant_id after commit starts the next transaction."""
    @event.listens_for(factory, "after_begin")
    def set_tenant_on_transaction(session: Session, transaction, connection) -> None:
        tenant_id = session.info.get("tenant_id")
        if tenant_id and connection.dialect.name == "postgresql":
            connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
        if session.info.get("is_worker") and connection.dialect.name == "postgresql":
            connection.execute(text("SELECT set_config('app.is_worker', 'true', true)"))
