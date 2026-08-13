from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import OrganizationMember, User
from server.config import get_server_settings
from server.db import session_factory
from server.security import decode_access_token
from server.tenant_session import set_session_tenant

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")
@dataclass(frozen=True)
class RequestContext:
    user_id: str
    tenant_id: str
    role: str
def get_db():
    session = session_factory(get_server_settings())()
    try: yield session
    finally: session.close()
def get_request_context(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> RequestContext:
    try: payload = decode_access_token(token, get_server_settings())
    except jwt.InvalidTokenError as exc: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token") from exc
    user_id, tenant_id = str(payload["sub"]), str(payload["tenant_id"])
    user = db.get(User, user_id)
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == user_id, OrganizationMember.organization_id == tenant_id))
    if user is None or not user.is_active or member is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user or organization membership is inactive")
    set_session_tenant(db, tenant_id)
    return RequestContext(user_id=user_id, tenant_id=tenant_id, role=member.role)
DbSession = Annotated[Session, Depends(get_db)]
CurrentContext = Annotated[RequestContext, Depends(get_request_context)]


def require_org_admin(context: RequestContext) -> RequestContext:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="organization admin role required")
    return context
