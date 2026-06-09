"""Q12 (Day 13F) — invariant #6 airtightness: case ACL bypass attempts.

CLAUDE.md §4 invariant #6: "case_id is checked on every request. No way to
bypass." These tests probe the edges a reviewer would: path-traversal-shaped
case_ids, cross-tenant case access, a case_id that differs only by whitespace /
casing from an allowed one, and role escalation via the header.

The demo ACL (backend/gateway/auth.py:_CASE_ACL):
  * alice (attorney, tenant_a): CASE-2025-001/002/003
  * bob   (paralegal, tenant_a): CASE-2025-001/002
"""
from __future__ import annotations

import pytest

from backend.gateway.auth import authorize_case_access
from backend.shared.models import User, UserRole

_ALICE_CASE = "CASE-2025-001"


def _login(client, user_id: str) -> str:
    resp = client.post(
        "/v1/auth/login", json={"user_id": user_id, "password": f"demo-{user_id}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _alice() -> User:
    return User(
        user_id="alice",
        tenant_id="tenant_a",
        role=UserRole.ATTORNEY,
        display_name="a",
        daily_token_quota=1000,
    )


# ---------------------------------------------------------------------------
# authorize_case_access unit-level edge cases (exact-match only).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "evil_case",
    [
        "CASE-2025-001/../CASE-2025-099",   # path traversal
        "CASE-2025-001\x00CASE-2025-099",   # null-byte smuggling
        "CASE-2025-001 ",                    # trailing whitespace
        " CASE-2025-001",                    # leading whitespace
        "case-2025-001",                     # case-folded
        "CASE-2025-001%00",                  # url-encoded null
        "CASE-2025-00*",                     # glob-ish
        "*",                                 # the auditor wildcard, claimed by alice
    ],
)
def test_authorize_case_access_is_exact_match_only(evil_case):
    """Anything that is not byte-equal to an ACL entry must 403. In particular
    a non-auditor user supplying '*' must NOT inherit the auditor wildcard."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        authorize_case_access(_alice(), evil_case)
    assert ei.value.status_code == 403, evil_case


def test_authorize_allows_exact_acl_member():
    # Counter-test: the legitimate exact case passes.
    authorize_case_access(_alice(), _ALICE_CASE)  # no raise


# ---------------------------------------------------------------------------
# End-to-end: traversal / cross-tenant case_id via the live gateway.
# ---------------------------------------------------------------------------
def test_traversal_case_id_in_header_is_403(gateway_client):
    alice = _login(gateway_client, "alice")
    resp = gateway_client.post(
        "/v1/redact",
        headers={"Authorization": f"Bearer {alice}", "X-Case-Id": "CASE-2025-001/../CASE-2025-099"},
        json={"text": "alice@apex-ip.com"},
    )
    assert resp.status_code == 403, resp.text


def test_cross_tenant_case_access_is_403(gateway_client, patched_ai_engine):
    """bob (tenant_a) trying a case he has no ACL on is refused — even though
    the case_id is well-formed. ACL is per-user, so this also covers the
    cross-tenant shape (no tenant_b user has any tenant_a case)."""
    bob = _login(gateway_client, "bob")
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={"Authorization": f"Bearer {bob}"},
        json={
            "oa_text": "x",
            "case_id": "CASE-2025-003",  # alice-only; bob has no ACL
            "target_patent_no": "US1",
        },
    )
    assert resp.status_code == 403, resp.text


def test_wildcard_case_id_from_non_auditor_is_403(gateway_client):
    """A non-auditor sending the literal '*' as case_id must not inherit the
    auditor's tenant-wildcard ACL — exact-match only."""
    alice = _login(gateway_client, "alice")
    resp = gateway_client.post(
        "/v1/redact",
        headers={"Authorization": f"Bearer {alice}", "X-Case-Id": "*"},
        json={"text": "x"},
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Role escalation: a self-issued role claim in the JWT is ignored — role comes
# from _USERS via verify_token, not from the token's 'role' claim.
# ---------------------------------------------------------------------------
def test_role_claim_in_jwt_does_not_escalate(gateway_client):
    """bob forges a JWT claiming role=it_admin. verify_token resolves the role
    from _USERS (paralegal), so the audit endpoint (auditor/it_admin only)
    still 403s and analyze (attorney/paralegal) still works."""
    import jwt
    from datetime import datetime, timedelta, timezone

    from backend.shared.config import settings

    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": "bob",
            "tenant_id": "tenant_a",
            "role": "it_admin",  # the lie
            "iss": settings.JWT_ISS,
            "aud": settings.JWT_AUD,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "jti": "bob-escalation-attempt",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGO,
    )
    # The audit endpoint is auditor/it_admin only — bob's forged it_admin claim
    # must NOT get him in (role resolved from _USERS = paralegal).
    resp = gateway_client.get(
        "/v1/audit/recent", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 403, resp.text
