"""P2 — consolidated rate-limit gates (rate_limit.gate_rpm / reserve_llm_budget).

The refactor moved main.py's scattered "RPM → hard cap → quota reserve"
sequences into two entry points. These tests pin the contract the handlers
now rely on:

  1. Ordering (invariant #8): RPM is checked first, the hard cap second, the
     ATOMIC quota reserve last — a failure at any layer must leave the later
     layers untouched (no phantom reservation).
  2. policy_decisions bookkeeping: each flag flips ONLY after its gate
     passes, so the audit row shows exactly which gate rejected a request.
  3. The returned reservation equals what check_quotas reserved (the caller
     settles it via record_usage, same contract as before the refactor).
"""

import pytest
from fastapi import HTTPException

from backend.gateway import rate_limit as rl
from backend.shared.config import settings
from backend.shared.models import User, UserRole


@pytest.fixture(autouse=True)
def _clean():
    def _wipe():
        for name in (
            "_user_rpm",
            "_login_ip_rpm",
            "_user_daily_tokens",
            "_tenant_monthly_tokens",
            "_tenant_monthly_cost",
            "_tenant_model_usage",
        ):
            store = getattr(rl, name, None)
            if store is not None:
                store.clear()

    _wipe()
    yield
    _wipe()


def _user(user_id="alice", tenant_id="tenant_a", quota=1_000) -> User:
    return User(
        user_id=user_id,
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name=user_id,
        daily_token_quota=quota,
    )


def _decisions() -> dict:
    return {"rate_limit_passed": False, "quota_passed": False}


def test_reserve_llm_budget_happy_path_sets_flags_and_returns_reservation():
    user = _user()
    decisions = _decisions()
    reserved = rl.reserve_llm_budget(user, 100, decisions)
    assert reserved == 100
    assert decisions["rate_limit_passed"] is True
    assert decisions["quota_passed"] is True
    # The reservation actually landed on the counters (atomic reserve).
    day = rl._today()
    assert rl._user_daily_tokens[(user.user_id, day)] == 100


def test_reserve_llm_budget_hard_cap_failure_leaves_quota_untouched():
    user = _user()
    decisions = _decisions()
    too_big = settings.REQUEST_HARD_LIMIT_TOKENS + 1
    with pytest.raises(HTTPException) as exc:
        rl.reserve_llm_budget(user, too_big, decisions)
    assert exc.value.status_code == 413
    # RPM passed (layer 1) but the quota flag must still be False (layer 3
    # never ran) and no reservation may have leaked onto the counters.
    assert decisions["rate_limit_passed"] is True
    assert decisions["quota_passed"] is False
    day = rl._today()
    assert rl._user_daily_tokens[(user.user_id, day)] == 0


def test_reserve_llm_budget_quota_failure_keeps_quota_flag_false():
    user = _user(quota=50)
    decisions = _decisions()
    with pytest.raises(HTTPException) as exc:
        rl.reserve_llm_budget(user, 100, decisions)
    assert exc.value.status_code == 402
    assert decisions["rate_limit_passed"] is True
    assert decisions["quota_passed"] is False


def test_reserve_llm_budget_rpm_failure_runs_no_later_layer(monkeypatch):
    user = _user()
    decisions = _decisions()
    monkeypatch.setattr(settings, "DEFAULT_RPM", 1)
    rl.reserve_llm_budget(user, 10, decisions)  # consumes the only RPM token
    decisions2 = _decisions()
    with pytest.raises(HTTPException) as exc:
        rl.reserve_llm_budget(user, 10, decisions2)
    assert exc.value.status_code == 429
    assert decisions2["rate_limit_passed"] is False
    assert decisions2["quota_passed"] is False
    # Only the FIRST call's reservation exists — the rejected call must not
    # have touched the quota counters.
    day = rl._today()
    assert rl._user_daily_tokens[(user.user_id, day)] == 10


def test_gate_rpm_sets_flag_only_on_pass(monkeypatch):
    user = _user()
    decisions = _decisions()
    rl.gate_rpm(user, decisions)
    assert decisions["rate_limit_passed"] is True

    monkeypatch.setattr(settings, "DEFAULT_RPM", 1)
    rl._user_rpm.clear()
    rl.gate_rpm(user)  # consume the only token; no-decisions form is allowed
    decisions2 = _decisions()
    with pytest.raises(HTTPException):
        rl.gate_rpm(user, decisions2)
    assert decisions2["rate_limit_passed"] is False


def test_gate_helpers_accept_missing_decisions_dict():
    user = _user()
    # Both helpers must tolerate policy_decisions=None (smoke-test callers).
    rl.gate_rpm(user, None)
    assert rl.reserve_llm_budget(user, 10, None) == 10
