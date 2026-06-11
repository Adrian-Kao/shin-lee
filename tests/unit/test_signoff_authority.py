"""Q12/Q16 (Day 13F) — sign-off authority is an ATTORNEY-only, role-gated act.

``assert_signoff_authority`` makes the Q16 responsibility boundary an explicit,
unit-testable function reused by the /v1/oa/export handler as defence-in-depth
behind the require_roles(ATTORNEY) endpoint gate.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.gateway import signoff
from backend.shared.models import User, UserRole


def _user(role: UserRole) -> User:
    return User(
        user_id="u",
        tenant_id="tenant_a",
        role=role,
        display_name="u",
        daily_token_quota=1000,
    )


def test_attorney_may_sign_off():
    signoff.assert_signoff_authority(_user(UserRole.ATTORNEY))  # no raise


@pytest.mark.parametrize("role", [UserRole.PARALEGAL, UserRole.AUDITOR, UserRole.IT_ADMIN])
def test_non_attorney_may_not_sign_off(role):
    with pytest.raises(HTTPException) as ei:
        signoff.assert_signoff_authority(_user(role))
    assert ei.value.status_code == 403
    assert role.value in ei.value.detail


def test_audit_fields_record_authority_and_outcome():
    fields = signoff.signoff_audit_fields(_user(UserRole.ATTORNEY), signed_off=True)
    assert fields["signoff_authority_role"] == "attorney"
    assert fields["signoff_by"] == "u"
    assert fields["signoff_passed"] is True
    # The refusal path records signed_off False.
    refused = signoff.signoff_audit_fields(_user(UserRole.ATTORNEY), signed_off=False)
    assert refused["signoff_passed"] is False
