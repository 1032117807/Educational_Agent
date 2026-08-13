from __future__ import annotations
import base64, hashlib, hmac, os, secrets
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from server.config import ServerSettings

def hash_password(password: str) -> str:
    if len(password) < 10: raise ValueError("password must contain at least 10 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1$%s$%s" % (base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if algorithm != "scrypt": return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError): return False

def create_access_token(*, user_id: str, organization_id: str, settings: ServerSettings) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "tenant_id": organization_id, "type": "access", "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.secret_key, algorithm="HS256")

def decode_access_token(token: str, settings: ServerSettings) -> dict[str, Any]:
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    if payload.get("type") != "access" or not payload.get("sub") or not payload.get("tenant_id"): raise jwt.InvalidTokenError("invalid access token")
    return payload


def create_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
