"""Gateway auth (Q12).

Three IdP modes are supported in production: built-in / OIDC SAML / magic link.
POC simplifies to JWT — but the **case_id check** is the part that matters
most and that we keep verbatim:

    Every API call must carry case_id.
    The user must have access to that case.
    This avoids conflict-of-interest 看錯案件.

This is a real legal compliance requirement, not generic auth.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status

from backend.shared.config import settings
from backend.shared.models import User, UserRole

# POC: in-memory user store. Production: replace with IdP middleware.
_USERS: dict[str, User] = {
    "alice": User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="Alice Chen (Attorney)",
        daily_token_quota=200_000,
    ),
    "bob": User(
        user_id="bob",
        tenant_id="tenant_a",
        role=UserRole.PARALEGAL,
        display_name="Bob Lin (Paralegal)",
        daily_token_quota=50_000,
    ),
    "carol": User(
        user_id="carol",
        tenant_id="tenant_b",
        role=UserRole.IT_ADMIN,
        display_name="Carol Wang (IT Admin)",
        daily_token_quota=10_000,
    ),
    "audit_dave": User(
        user_id="audit_dave",
        tenant_id="tenant_a",
        role=UserRole.AUDITOR,
        display_name="Dave Yu (Auditor)",
        daily_token_quota=5_000,
    ),
}

# POC: which case_ids each user has access to.
# Production: query from case-management system per request.
_CASE_ACL: dict[str, set[str]] = {
    "alice": {"CASE-2025-001", "CASE-2025-002", "CASE-2025-003"},
    "bob": {"CASE-2025-001", "CASE-2025-002"},
    "carol": set(),  # IT admin doesn't access cases by default
    "audit_dave": {"*"},  # auditor sees all in their tenant
}


def issue_token(user_id: str) -> str:
    """Sign a short-lived JWT for the user."""
    if user_id not in _USERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown user: {user_id}")
    user = _USERS[user_id]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.user_id,
        "tenant_id": user.tenant_id,
        "role": user.role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRES_MIN)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGO)


def verify_token(token: str) -> User:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")

    user_id = payload.get("sub")
    if user_id not in _USERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return _USERS[user_id]


def authorize_case_access(user: User, case_id: Optional[str]) -> None:
    """Q12: legal compliance — confirm user has access to this specific case.

    Raises 403 if not.  This is the conflict-of-interest 看錯案件 防呆.
    """
    if not case_id:
        # Some endpoints (e.g. /health) don't need case_id.
        return
    allowed = _CASE_ACL.get(user.user_id, set())
    if "*" in allowed or case_id in allowed:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"user {user.user_id} has no access to {case_id}. "
        "If this is a new case, an authorised attorney must grant access first.",
    )


async def auth_dependency(request: Request) -> User:
    """FastAPI dependency: extract token, verify, attach user to request.state."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth_header[7:]
    user = verify_token(token)

    # Case-level access check
    case_id = request.headers.get("X-Case-Id") or request.query_params.get("case_id")
    if not case_id and request.method == "POST":
        body = getattr(request.state, "_cached_body", None)
        if body and isinstance(body, dict):
            case_id = body.get("case_id")
    authorize_case_access(user, case_id)

    request.state.user = user
    request.state.case_id = case_id
    return user
