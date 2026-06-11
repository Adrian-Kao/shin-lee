"""Q12 (Day 13F) — SAML Assertion Consumer Service (ACS) hardening.

The named ``/v1/auth/saml/acs`` stub is fleshed out into a testable, MOCKABLE
path. The IdP is an offline stub that HMAC-signs an assertion blob standing in
for the real XML-DSig signature verification against the IdP certificate. The
replay guard (single-use assertion id) is provider-agnostic and lives in the
gateway.

Threat model under test:
  * forged / wrong-secret assertion 401s (signature check).
  * audience-mismatch assertion 401s (the assertion must be addressed to us).
  * outside the NotBefore/NotOnOrAfter window (too early / expired) 401s.
  * REPLAY: a previously-consumed assertion id is 401 even inside its window.
  * a federated user gets a revocable session JWT; can NEVER self-assert
    AUDITOR / IT_ADMIN; a known user pins role/tenant to _USERS.
  * exactly one audit row; the raw assertion is never stored.
"""

from __future__ import annotations

import time
import uuid

import pytest

from backend.gateway import auth as auth_mod
from backend.shared.config import settings


@pytest.fixture(autouse=True)
def _reset_idp_state():
    from backend.gateway import rate_limit as rl

    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    rl._login_ip_rpm.clear()
    yield
    auth_mod._clear_idp_state()
    auth_mod._FEDERATED_USERS.clear()
    rl._login_ip_rpm.clear()


def _mint(
    *,
    subject,
    assertion_id=None,
    issuer="https://idp.example.com",
    audience=None,
    not_before=None,
    not_on_or_after=None,
    tenant=None,
    role=None,
    secret=None,
) -> str:
    now = int(time.time())
    return auth_mod.StubSAMLProvider.mint_assertion(
        secret if secret is not None else settings.SAML_STUB_SIGNING_SECRET,
        assertion_id=assertion_id or str(uuid.uuid4()),
        subject=subject,
        issuer=issuer,
        audience=audience if audience is not None else settings.SAML_AUDIENCE,
        not_before=not_before if not_before is not None else now - 30,
        not_on_or_after=not_on_or_after if not_on_or_after is not None else now + 300,
        tenant=tenant,
        role=role,
    )


def _acs(client, assertion):
    return client.post("/v1/auth/saml/acs", json={"SAMLResponse": assertion})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_saml_happy_path_known_user(gateway_client):
    assertion = _mint(subject="alice")
    r = _acs(gateway_client, assertion)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "alice"
    assert body["role"] == "attorney"
    assert body["tenant_id"] == "tenant_a"
    resp = gateway_client.get("/v1/quota", headers={"Authorization": f"Bearer {body['token']}"})
    assert resp.status_code == 200, resp.text


def test_saml_federated_unknown_user(gateway_client):
    assertion = _mint(subject="ext-saml-user", tenant="tenant_partner", role="paralegal")
    r = _acs(gateway_client, assertion)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == "ext-saml-user"
    assert body["role"] == "paralegal"
    assert body["tenant_id"] == "tenant_partner"


# ---------------------------------------------------------------------------
# signature
# ---------------------------------------------------------------------------
def test_saml_wrong_secret_assertion_is_rejected(gateway_client):
    assertion = _mint(subject="alice", secret="the-wrong-secret")
    r = _acs(gateway_client, assertion)
    assert r.status_code == 401, r.text


def test_saml_tampered_assertion_is_rejected(gateway_client):
    assertion = _mint(subject="alice")
    b64, _, sig = assertion.rpartition(".")
    flipped = "A" if sig[0] != "A" else "B"
    tampered = f"{b64}.{flipped}{sig[1:]}"
    r = _acs(gateway_client, tampered)
    assert r.status_code == 401, r.text


def test_saml_malformed_assertion_is_rejected(gateway_client):
    r = _acs(gateway_client, "no-dot-delimiter")
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# audience
# ---------------------------------------------------------------------------
def test_saml_wrong_audience_is_rejected(gateway_client):
    assertion = _mint(subject="alice", audience="some-other-sp")
    r = _acs(gateway_client, assertion)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# time window
# ---------------------------------------------------------------------------
def test_saml_expired_assertion_is_rejected(gateway_client):
    now = int(time.time())
    assertion = _mint(subject="alice", not_before=now - 600, not_on_or_after=now - 300)
    r = _acs(gateway_client, assertion)
    assert r.status_code == 401, r.text


def test_saml_not_yet_valid_assertion_is_rejected(gateway_client):
    now = int(time.time())
    assertion = _mint(subject="alice", not_before=now + 600, not_on_or_after=now + 1200)
    r = _acs(gateway_client, assertion)
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------
def test_saml_assertion_replay_is_rejected(gateway_client):
    aid = str(uuid.uuid4())
    assertion = _mint(subject="alice", assertion_id=aid)
    first = _acs(gateway_client, assertion)
    assert first.status_code == 200, first.text
    # SAME assertion id, well within its time window — must be refused.
    second = _acs(gateway_client, assertion)
    assert second.status_code == 401, second.text


def test_saml_distinct_assertion_ids_both_succeed(gateway_client):
    """Counter-test to the replay guard: two DIFFERENT assertions for the same
    subject both succeed (the guard keys on assertion id, not subject)."""
    a1 = _mint(subject="alice", assertion_id=str(uuid.uuid4()))
    a2 = _mint(subject="alice", assertion_id=str(uuid.uuid4()))
    assert _acs(gateway_client, a1).status_code == 200
    assert _acs(gateway_client, a2).status_code == 200


# ---------------------------------------------------------------------------
# privilege boundary
# ---------------------------------------------------------------------------
def test_saml_unknown_user_cannot_claim_auditor(gateway_client):
    assertion = _mint(subject="eve", tenant="tenant_a", role="auditor")
    r = _acs(gateway_client, assertion)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "paralegal", r.text
    token = r.json()["token"]
    audit = gateway_client.get("/v1/audit/recent", headers={"Authorization": f"Bearer {token}"})
    assert audit.status_code == 403, audit.text


def test_saml_known_user_role_pins_to_USERS(gateway_client):
    assertion = _mint(subject="alice", tenant="tenant_b", role="it_admin")
    r = _acs(gateway_client, assertion)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "attorney", r.text
    assert r.json()["tenant_id"] == "tenant_a", r.text


# ---------------------------------------------------------------------------
# revocable session + feature gate
# ---------------------------------------------------------------------------
def test_saml_session_is_revocable(gateway_client):
    token = _acs(gateway_client, _mint(subject="alice")).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert gateway_client.get("/v1/quota", headers=auth).status_code == 200
    assert gateway_client.post("/v1/auth/logout", headers=auth).json()["revoked"] is True
    assert gateway_client.get("/v1/quota", headers=auth).status_code == 401


def test_saml_disabled_returns_401(gateway_client, monkeypatch):
    monkeypatch.setattr(settings, "SAML_ENABLED", False)
    r = _acs(gateway_client, _mint(subject="alice"))
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def _preauth_rows():
    from backend.gateway import audit as audit_mod

    return audit_mod.writer.list_for_tenant("_preauth_", limit=1000)


def test_saml_acs_writes_exactly_one_audit_row_and_never_stores_assertion(gateway_client):
    assertion = _mint(subject="alice")
    before = len(_preauth_rows())
    _acs(gateway_client, assertion)
    after = _preauth_rows()
    assert len(after) == before + 1
    assert after[0]["endpoint"] == "/v1/auth/saml/acs"
    assert assertion not in repr(after), "raw SAML assertion leaked into audit"
