from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.models import AIRun, Organization, OrganizationMember, User
from server.deps import RequestContext
from server.routers import organization_token_usage


def _run(*, tenant_id: str, user_id: str | None, input_tokens: int, output_tokens: int) -> AIRun:
    return AIRun(
        tenant_id=tenant_id, user_id=user_id, run_uuid=f"run-{tenant_id}-{user_id}-{input_tokens}",
        feature="qa", status="completed", provider="test", model_name="test", prompt_version="v1",
        input_tokens=input_tokens, output_tokens=output_tokens, created_at=datetime.now(),
    )


def test_organization_admin_can_see_member_token_totals(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'usage.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        Organization(id="org-1", name="Team", slug="team"),
        User(id="owner", email="owner@example.com", password_hash="x", display_name="Owner"),
        User(id="member", email="member@example.com", password_hash="x", display_name="Member"),
        OrganizationMember(organization_id="org-1", user_id="owner", role="owner"),
        OrganizationMember(organization_id="org-1", user_id="member", role="member"),
        _run(tenant_id="org-1", user_id="member", input_tokens=12, output_tokens=8),
        _run(tenant_id="org-1", user_id=None, input_tokens=3, output_tokens=2),
        _run(tenant_id="other", user_id="member", input_tokens=99, output_tokens=1),
    ])
    db.commit()

    result = organization_token_usage(RequestContext("owner", "org-1", "owner"), db, days=30)

    assert result["totals"] == {"input_tokens": 15, "output_tokens": 10, "total_tokens": 25}
    assert result["users"][0]["email"] == "member@example.com"
    assert result["users"][0]["total_tokens"] == 20
    assert result["users"][1]["email"] == "Unattributed historical runs"


def test_member_cannot_read_organization_token_usage(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'usage-denied.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    with pytest.raises(HTTPException, match="organization admin role required"):
        organization_token_usage(RequestContext("member", "org-1", "member"), db, days=30)
