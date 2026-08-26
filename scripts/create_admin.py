"""Create the first production owner without enabling public registration."""
from __future__ import annotations

import argparse
import os
from uuid import uuid4

from sqlalchemy import select

from app.models import Organization, OrganizationMember, User
from server.config import get_server_settings
from server.db import session_factory
from server.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    parser.add_argument("--organization", default=os.environ.get("ADMIN_ORGANIZATION", "Learning Space"))
    args = parser.parse_args()
    if not args.email or len(args.password) < 10:
        parser.error("provide --email and a password of at least 10 characters")
    settings = get_server_settings()
    with session_factory(settings)() as db:
        email = args.email.strip().lower()
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("admin email already exists")
        organization_id = str(uuid4()); user_id = str(uuid4())
        db.add(Organization(id=organization_id, name=args.organization.strip(), slug=f"org-{organization_id[:8]}"))
        db.add(User(id=user_id, email=email, password_hash=hash_password(args.password), display_name="Administrator"))
        db.flush()
        db.add(OrganizationMember(organization_id=organization_id, user_id=user_id, role="owner"))
        db.commit()
    print(f"created owner account: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
