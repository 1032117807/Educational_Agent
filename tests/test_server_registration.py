from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.models import Organization, OrganizationMember, User
from server.routers import RegisterRequest, register


def test_registration_flushes_user_and_organization_before_owner_membership(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'registration.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()

    tokens = register(RegisterRequest(
        organization_name="Learning Team",
        display_name="Learner",
        email="learner@example.com",
        password="long-enough-password",
    ), session)

    user = session.scalar(select(User).where(User.email == "learner@example.com"))
    organization = session.scalar(select(Organization).where(Organization.name == "Learning Team"))
    assert user is not None
    assert organization is not None
    member = session.scalar(select(OrganizationMember).where(
        OrganizationMember.user_id == user.id,
        OrganizationMember.organization_id == organization.id,
    ))
    assert member is not None
    assert member.role == "owner"
    assert tokens["access_token"]
    assert tokens["refresh_token"]
