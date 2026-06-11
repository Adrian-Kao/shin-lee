"""Q5 — adversarial cross-tenant isolation PROOF (tests only).

This suite exists to give an architecture reviewer a single green/red answer
to the question: *"How do you know tenant_a can't see tenant_b?"*

It does NOT change any product code. It probes every isolation plane the
design relies on and asserts the boundary holds. Each plane is proved
independently and hermetically so a regression in one layer surfaces as
exactly one red test rather than a cascade.

Planes proved (one section each):

  1. Vector store        — rag._store / _tenant_index + H-3 per-tenant salt
  2. Cache               — cache.response_cache_key namespacing
  3. Audit               — audit.writer.list_for_tenant / verify_chain ROW-level
  4. Masking mapping     — masking._store (tenant_id, placeholder) PK
  5. API-level case ACL  — /v1/oa/analyze 403 for a foreign-tenant case_id

Design facts the assertions are calibrated against (so we don't assert
something the design intentionally allows):

  * The audit hash chain is GLOBAL (audit.py ``_last_row_hash`` is not
    tenant-scoped), so a tenant_b row's ``prev_row_hash`` may legitimately
    point at a tenant_a ``row_hash``. We therefore assert ROW-LEVEL tenant
    separation (``list_for_tenant`` / per-tenant ``verify_chain`` never
    *returns* foreign rows), NOT chain separation. See audit.py
    ``verify_global_chain`` docstring + CLAUDE.md §7 pitfall #4.

  * Mock embeddings are salted with tenant_id (H-3). Real bge-m3 embeddings
    are content-only; the production isolation defence there is the
    per-tenant Qdrant collection (Q5 stub), exercised here via the memory
    backend's ``_tenant_index``.
"""

from __future__ import annotations

import uuid

import numpy as np

from backend.shared.models import Patent, User, UserRole

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_TENANT_A = "tenant_a"
_TENANT_B = "tenant_b"


def _unique_patent(prefix: str) -> Patent:
    """Build a Patent with a per-call-unique patent_no.

    rag._store is a process-global singleton (memory backend), so tests that
    index must use distinct patent_nos to avoid colliding with each other or
    with rows left by a prior test in the same session. A uuid suffix makes
    every call hermetic without needing a store reset fixture.
    """
    pno = f"{prefix}-{uuid.uuid4().hex[:8]}"
    from datetime import datetime

    return Patent(
        patent_no=pno,
        title="Battery degradation prediction method",
        abstract="A method for predicting battery degradation using a model.",
        claims=[
            "1. A method for predicting battery degradation comprising training a model.",
            "2. The method of claim 1, wherein the model is a neural network.",
        ],
        jurisdiction="US",
        publication_date=datetime(2024, 1, 1),
        is_local=True,
    )


def _login(client, user_id: str) -> str:
    resp = client.post(
        "/v1/auth/login",
        json={"user_id": user_id, "password": f"demo-{user_id}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# ===========================================================================
# PLANE 1 — VECTOR STORE ISOLATION (rag._tenant_index + H-3 salt)
# ===========================================================================
def test_vector_store_retrieve_does_not_cross_tenants():
    """Index a patent for tenant_a; retrieving the SAME query under tenant_b
    must return ZERO hits referencing tenant_a's patent.

    This is the load-bearing Q5 assertion: the memory store partitions by
    ``_tenant_index``, so tenant_b's search space never includes tenant_a's
    chunk_ids. A regression that flattened the index (e.g. searching all
    chunks regardless of tenant) would make tenant_a's patent_no appear in
    tenant_b's hits and fail this test.
    """
    from backend.ai_engine import rag

    patent = _unique_patent("US-TENANT-A")
    query = "method for predicting battery degradation"

    n = rag.index_patent(_TENANT_A, patent)
    assert n >= 1, "indexing produced no chunks — fixture is broken"

    # Sanity: tenant_a CAN find its own patent (proves the query is well-formed
    # and the boost path works), so a zero result for tenant_b is meaningful.
    a_hits = rag.retrieve(_TENANT_A, query, top_k=10, prefer_patent_no=patent.patent_no)
    assert any(h.patent_no == patent.patent_no for h in a_hits), (
        "tenant_a could not retrieve its own freshly-indexed patent — the "
        "negative tenant_b assertion below would be vacuous."
    )

    # Adversarial: tenant_b retrieves with the identical query. It must NOT
    # see tenant_a's patent. We also pass prefer_patent_no to try to *coax*
    # the foreign patent to the top — if isolation leaked, the boost would
    # surface it.
    b_hits = rag.retrieve(_TENANT_B, query, top_k=10, prefer_patent_no=patent.patent_no)
    leaked = [h.patent_no for h in b_hits if h.patent_no == patent.patent_no]
    assert not leaked, (
        f"VECTOR LEAK: tenant_b retrieved tenant_a's patent {patent.patent_no!r}. "
        f"hits={[h.patent_no for h in b_hits]!r}"
    )


def test_vector_store_tenant_b_sees_only_its_own_corpus():
    """Index DISTINCT patents under each tenant, then assert each tenant's
    retrieval only ever returns its own patent_no. Belt-and-braces over the
    previous test: proves the partition is symmetric, not just one-directional.
    """
    from backend.ai_engine import rag

    pa = _unique_patent("US-A")
    pb = _unique_patent("US-B")
    query = "method for predicting battery degradation"

    rag.index_patent(_TENANT_A, pa)
    rag.index_patent(_TENANT_B, pb)

    a_pnos = {h.patent_no for h in rag.retrieve(_TENANT_A, query, top_k=10)}
    b_pnos = {h.patent_no for h in rag.retrieve(_TENANT_B, query, top_k=10)}

    assert pb.patent_no not in a_pnos, (
        f"VECTOR LEAK: tenant_a saw tenant_b's patent {pb.patent_no!r}; a_pnos={a_pnos!r}"
    )
    assert pa.patent_no not in b_pnos, (
        f"VECTOR LEAK: tenant_b saw tenant_a's patent {pa.patent_no!r}; b_pnos={b_pnos!r}"
    )


def test_h3_same_text_different_tenant_yields_different_embedding():
    """H-3 property: the SAME patent text embedded under tenant_a vs tenant_b
    must yield DIFFERENT mock vectors.

    Without the per-tenant salt, two tenants indexing identical text would
    share byte-identical vectors — a similarity oracle: an attacker who can
    reach the AI Engine could confirm whether a known patent text sits in
    *some* tenant's index by matching the vector. The salt
    ``f"{tenant_id}:{text}"`` defeats that.

    (This mirrors test_cross_tenant.py::test_mock_embedding_differs_across_
    tenants but is restated here so the Q5 isolation proof is self-contained
    across every plane in one file.)
    """
    from backend.ai_engine import rag

    text = "1. A method for predicting battery degradation comprising training a model."
    va = np.array(rag.embed(text, tenant_id=_TENANT_A))
    vb = np.array(rag.embed(text, tenant_id=_TENANT_B))

    assert not np.array_equal(va, vb), (
        "H-3 REGRESSION: same text under two tenants produced byte-identical "
        "mock embeddings — the tenant salt is not being applied."
    )
    # Load-bearing: cosine sim must not be ~1.0 (the salt must actually move
    # the vector, not merely flip a byte that normalises away).
    sim = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))
    assert sim < 0.9999, (
        f"H-3 REGRESSION: cross-tenant mock embedding cosine sim is {sim:.6f}; "
        "must be < 1.0 to defeat the similarity-oracle attack."
    )


# ===========================================================================
# PLANE 2 — CACHE ISOLATION (cache.response_cache_key namespacing)
# ===========================================================================
def test_cache_response_not_shared_across_tenants():
    """Two users in different tenants issuing the 'same' analyze request
    (same case_id-shaped string, same prompt hash) must NOT share a cached
    response.

    The cache key is ``resp:sha256(tenant|user|case|prompt_hash)`` — tenant is
    the FIRST component, so a tenant_a write is unreadable under any tenant_b
    read. We assert at the public-API level (get/set_response) so we're
    testing the contract the orchestrator actually uses, not a private detail.
    """
    from backend.gateway import cache

    case_id = "CASE-SHARED-001"
    prompt_hash = "deadbeefprompthash"
    secret_a = {"draft": "tenant_a privileged answer"}

    cache.set_response(_TENANT_A, "userX", case_id, prompt_hash, secret_a)

    # Same user_id, same case_id, same prompt_hash — only the tenant differs.
    leaked = cache.get_response(_TENANT_B, "userX", case_id, prompt_hash)
    assert leaked is None, f"CACHE LEAK: tenant_b read tenant_a's cached response: {leaked!r}"

    # Positive control: tenant_a CAN read its own write back (proves the
    # None above is real isolation, not a write that silently failed).
    assert cache.get_response(_TENANT_A, "userX", case_id, prompt_hash) == secret_a


def test_cache_keys_are_tenant_distinct():
    """The derived cache KEY itself must differ by tenant. A collision here
    would be a latent leak even if get/set happened to dedupe — assert the
    namespacing primitive directly.
    """
    from backend.gateway import cache

    ka = cache.response_cache_key(_TENANT_A, "u", "C", "h")
    kb = cache.response_cache_key(_TENANT_B, "u", "C", "h")
    assert ka != kb, "response cache keys collide across tenants — namespacing broken"

    # Retrieval keys are tenant-scoped too (different on-prem corpora).
    ra = cache.retrieval_cache_key(_TENANT_A, "qhash")
    rb = cache.retrieval_cache_key(_TENANT_B, "qhash")
    assert ra != rb, "retrieval cache keys collide across tenants — namespacing broken"


# ===========================================================================
# PLANE 3 — AUDIT ISOLATION (ROW-LEVEL, not chain-level)
# ===========================================================================
def _audit_user(tenant_id: str, uid: str) -> User:
    return User(
        user_id=uid,
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name="audit test",
        daily_token_quota=10_000,
    )


def _write_audit(writer, tenant_id: str, uid: str, case_id: str) -> str:
    return writer.write(
        user=_audit_user(tenant_id, uid),
        case_id=case_id,
        endpoint="/v1/oa/analyze",
        request_payload={"case": case_id},
        response_payload={"ok": True},
        masked_rules=[],
        model_used="mock",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=1,
        policy_decisions={"authn_passed": True},
    )


def test_audit_list_for_tenant_never_returns_foreign_rows(tmp_path):
    """``list_for_tenant(tenant_a)`` must NEVER return a tenant_b row.

    Uses an isolated SQLite DB (tmp_path) so the session-global audit DB's
    accumulated rows don't pollute the assertion. We interleave writes so
    that tenant_b rows sit BETWEEN tenant_a rows in the global chain — if the
    WHERE tenant_id filter were dropped, the interleaving guarantees foreign
    rows would surface.
    """
    from backend.gateway.audit import AuditWriter

    writer = AuditWriter(path=tmp_path / "audit.db")

    a1 = _write_audit(writer, _TENANT_A, "alice", "CASE-A-1")
    b1 = _write_audit(writer, _TENANT_B, "bcarol", "CASE-B-1")
    a2 = _write_audit(writer, _TENANT_A, "alice", "CASE-A-2")
    b2 = _write_audit(writer, _TENANT_B, "bcarol", "CASE-B-2")

    a_ids = {r["audit_id"] for r in writer.list_for_tenant(_TENANT_A)}
    b_ids = {r["audit_id"] for r in writer.list_for_tenant(_TENANT_B)}

    assert a_ids == {a1, a2}, f"tenant_a list wrong: {a_ids!r}"
    assert b_ids == {b1, b2}, f"tenant_b list wrong: {b_ids!r}"
    # The load-bearing isolation assertion: no overlap, no foreign leak.
    assert b1 not in a_ids and b2 not in a_ids, "AUDIT LEAK: tenant_b rows in tenant_a list"
    assert a1 not in b_ids and a2 not in b_ids, "AUDIT LEAK: tenant_a rows in tenant_b list"


def test_audit_verify_chain_only_walks_one_tenant(tmp_path):
    """Per-tenant ``verify_chain(tenant_x)`` must only ever reference rows
    belonging to ``tenant_x`` — its ``broken`` audit_ids are a subset of
    that tenant's rows, and it never verifies a foreign row.

    This proves the verifier is scoped by the WHERE tenant_id clause (Q5
    row-level isolation), which is the question an architecture reviewer
    actually cares about.

    NOTE — we deliberately do NOT assert ``verified + len(broken)`` equals
    the row count. ``verify_chain`` can append the SAME row to ``broken``
    for a prev-mismatch AND still ``ok += 1`` on a passing hash recompute,
    so that arithmetic double-counts a single row. (Observed: tenant_b's
    first row reports verified=2 AND broken=1 from only 2 rows — the prev
    mismatch is the GLOBAL-chain artefact described in audit.py
    ``verify_global_chain``, not a row-isolation failure.) We instead assert
    on the *identity* of the rows touched, which is the real isolation claim.

    We ALSO assert tenant_a's contiguous-from-genesis sub-chain is intact,
    because tenant_a's first row genuinely starts the global chain (prev='').
    """
    from backend.gateway.audit import AuditWriter

    writer = AuditWriter(path=tmp_path / "audit.db")

    a_ids = {
        _write_audit(writer, _TENANT_A, "alice", "CASE-A-1"),
        _write_audit(writer, _TENANT_A, "alice", "CASE-A-2"),
        _write_audit(writer, _TENANT_A, "alice", "CASE-A-3"),
    }
    b_ids = {
        _write_audit(writer, _TENANT_B, "bcarol", "CASE-B-1"),
        _write_audit(writer, _TENANT_B, "bcarol", "CASE-B-2"),
    }

    res_a = writer.verify_chain(_TENANT_A)
    res_b = writer.verify_chain(_TENANT_B)

    assert res_a["tenant"] == _TENANT_A
    assert res_b["tenant"] == _TENANT_B

    # Row-level isolation: any broken id a per-tenant walk reports must belong
    # to that tenant. A foreign id here would mean the WHERE clause leaked.
    assert set(res_a["broken"]) <= a_ids, (
        f"AUDIT LEAK: verify_chain(tenant_a) flagged foreign rows: {res_a['broken']!r}"
    )
    assert set(res_b["broken"]) <= b_ids, (
        f"AUDIT LEAK: verify_chain(tenant_b) flagged foreign rows: {res_b['broken']!r}"
    )
    # The verified COUNT can never exceed the tenant's own row count — if it
    # did, the walk pulled in foreign rows.
    assert res_a["verified"] <= len(a_ids), res_a
    assert res_b["verified"] <= len(b_ids), res_b
    # tenant_a rows are contiguous from genesis, so its sub-chain is intact.
    assert res_a["broken"] == [], f"tenant_a contiguous sub-chain reported broken: {res_a!r}"


# ===========================================================================
# PLANE 4 — MASKING MAPPING ISOLATION (tenant_id is part of the PK)
# ===========================================================================
def test_masking_mapping_cannot_be_unmasked_cross_tenant():
    """A placeholder→original mapping remembered under tenant_a must be
    invisible under tenant_b.

    The mapping table PK is ``(tenant_id, placeholder)`` and ``get_original``
    filters on both, so an attacker holding a placeholder string cannot
    un-mask another tenant's PII even if they guess/replay the exact
    placeholder. We assert at the store API level (the durable contract).
    """
    from backend.gateway import masking

    placeholder = "[EMAIL_DEADBEEF]"
    secret = "alice@apex-ip.example"

    masking._store.remember(_TENANT_A, placeholder, secret, rule_id="email")

    # Adversarial: tenant_b asks for the SAME placeholder.
    leaked = masking._store.get_original(_TENANT_B, placeholder)
    assert leaked is None, f"MASKING LEAK: tenant_b un-masked tenant_a's value: {leaked!r}"

    # Positive control: tenant_a can reverse its own mapping.
    assert masking._store.get_original(_TENANT_A, placeholder) == secret


def test_masking_redact_then_unmask_is_tenant_scoped():
    """End-to-end through the public redact()/unmask() API: redact under
    tenant_a, then attempt to unmask the resulting placeholder under
    tenant_b. The placeholder must survive UNCHANGED (no original found),
    while tenant_a recovers the real value.

    This is the realistic attack: a redacted document leaks to a tenant_b
    user who runs it back through unmask() hoping the shared mapping table
    de-references it. The (tenant_id, placeholder) PK denies them.
    """
    from backend.gateway import masking

    raw = "Contact attorney at alice@apex-ip.example for case details."
    redacted, triggered = masking.redact(raw, _TENANT_A)
    assert "email" in triggered, f"email rule did not fire: {triggered!r}"
    assert "alice@apex-ip.example" not in redacted, "redaction failed to mask the email"

    # tenant_b cannot reverse it — the placeholder stays as-is.
    b_view = masking.unmask(redacted, _TENANT_B)
    assert b_view == redacted, (
        "MASKING LEAK: tenant_b's unmask() changed tenant_a's redacted text "
        f"(de-referenced a foreign mapping). got={b_view!r}"
    )
    assert "alice@apex-ip.example" not in b_view

    # tenant_a CAN reverse it (proves the placeholder was reversible at all).
    a_view = masking.unmask(redacted, _TENANT_A)
    assert "alice@apex-ip.example" in a_view, (
        f"tenant_a could not un-mask its own redaction: {a_view!r}"
    )


# ===========================================================================
# PLANE 5 — API-LEVEL CASE ACL (cross-tenant 403)
# ===========================================================================
def test_foreign_tenant_attorney_cannot_reach_tenant_a_case(
    gateway_client, patched_ai_engine, monkeypatch
):
    """A tenant_b ATTORNEY POSTing /v1/oa/analyze with a tenant_a case_id
    gets 403 on the case ACL — NOT on the role gate.

    The demo ``_USERS`` has no tenant_b attorney (carol is tenant_b but
    IT_ADMIN, which would 403 at the *role* gate and thus prove nothing
    about cross-tenant *case* ACL). We therefore mint a synthetic tenant_b
    attorney via the trusted-upstream-header auth path: digiRunner-style
    identity injection that auth.py honours for an unknown user_id, but only
    with ATTORNEY/PARALEGAL (never a privileged role). That user has NO
    ``_CASE_ACL`` entry, so ANY case_id → 403 from ``authorize_case_access``.

    We point the case_id at ``CASE-2025-001`` (a real tenant_a case) to make
    the cross-tenant intent explicit: a tenant_b principal reaching for a
    tenant_a case must be denied.
    """
    from backend.shared import config as cfg

    # Trust the TestClient's synthetic peer ("testclient") so the upstream
    # header path is taken; no shared secret configured (loopback-style).
    monkeypatch.setattr(cfg.settings, "TRUSTED_UPSTREAM_IPS", ("testclient",))
    monkeypatch.setattr(cfg.settings, "UPSTREAM_AUTH_SHARED_SECRET", "")

    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "x-user-id": "mallory_tenant_b",  # unknown user → upstream role honoured
            "x-tenant-id": _TENANT_B,
            "x-user-role": UserRole.ATTORNEY.value,  # passes the analyze role gate
        },
        json={
            "oa_text": "irrelevant",
            "case_id": "CASE-2025-001",  # a tenant_a case
            "target_patent_no": "US17123456",
        },
    )
    assert resp.status_code == 403, (
        "cross-tenant case ACL did not deny a tenant_b attorney reaching a "
        f"tenant_a case_id. status={resp.status_code} body={resp.text!r}"
    )
    # Must be the case-ACL denial, not a role-gate denial — assert the
    # message names the case, not the role list.
    assert "CASE-2025-001" in resp.text or "no access" in resp.text.lower(), resp.text


def test_foreign_tenant_attorney_role_gate_is_not_the_blocker(
    gateway_client, patched_ai_engine, monkeypatch
):
    """Counter-test for the assertion above: prove the synthetic tenant_b
    attorney would PASS the role gate (so the 403 in the previous test is
    unambiguously the case ACL, not the role check).

    We grant the synthetic upstream user ACL on a case by routing through a
    case_id the ACL layer treats as accessible is not possible for an unknown
    user (no _CASE_ACL entry), so instead we assert the negative: sending NO
    case_id at all (header absent, body case_id present is still ACL-checked)
    — but a body with a case the user can't reach still 403s. To isolate the
    role gate we instead confirm the role gate alone does not 403 by checking
    that an IT_ADMIN upstream role IS downgraded (proving role plumbing works)
    while ATTORNEY is honoured.

    Concretely: an unknown upstream user asserting IT_ADMIN is silently
    downgraded to PARALEGAL (auth.py _UPSTREAM_ASSERTABLE_ROLES), which is
    STILL allowed on /v1/oa/analyze — so a role-gate 403 is impossible for
    this path, confirming the previous test's 403 came from the case ACL.
    """
    from backend.shared import config as cfg

    monkeypatch.setattr(cfg.settings, "TRUSTED_UPSTREAM_IPS", ("testclient",))
    monkeypatch.setattr(cfg.settings, "UPSTREAM_AUTH_SHARED_SECRET", "")

    # Assert a privileged upstream role is downgraded (not honoured) — this is
    # the role-plumbing proof. The downgraded PARALEGAL role still passes the
    # analyze role gate, so the only thing that can 403 this request is the
    # case ACL.
    resp = gateway_client.post(
        "/v1/oa/analyze",
        headers={
            "x-user-id": "mallory2_tenant_b",
            "x-tenant-id": _TENANT_B,
            "x-user-role": UserRole.IT_ADMIN.value,  # must be DOWNGRADED, not honoured
        },
        json={
            "oa_text": "irrelevant",
            "case_id": "CASE-2025-001",  # tenant_a case → ACL 403
            "target_patent_no": "US17123456",
        },
    )
    # 403 from the CASE ACL (the downgraded paralegal role passes the gate).
    # If the role gate had fired we'd still get 403 but the body would name the
    # role; we assert the case-ACL signature to prove it's the ACL.
    assert resp.status_code == 403, resp.text
    assert "CASE-2025-001" in resp.text or "no access" in resp.text.lower(), (
        "expected a case-ACL 403 (role was downgraded to paralegal which is "
        f"allowed on analyze); got body={resp.text!r}"
    )


def test_jwt_tenant_b_user_blocked_from_tenant_a_case_via_header(gateway_client):
    """Belt-and-braces using a REAL demo user on the normal JWT path: carol
    (tenant_b) sending X-Case-Id for a tenant_a case is denied at
    ``auth_dependency``'s header ACL check (before the role gate even runs).

    Carol is IT_ADMIN so this would 403 at the role gate on a POST anyway;
    using the header ACL on auth_dependency lets us prove the cross-tenant
    case denial happens at the authn layer for a genuine tenant_b principal.
    We use /v1/quota (allowed for any role) so the ONLY thing that can 403 is
    the X-Case-Id ACL check in auth_dependency.
    """
    carol_token = _login(gateway_client, "carol")
    resp = gateway_client.get(
        "/v1/quota",
        headers={
            "Authorization": f"Bearer {carol_token}",
            "X-Case-Id": "CASE-2025-001",  # tenant_a case; carol has empty ACL
        },
    )
    assert resp.status_code == 403, (
        "tenant_b user (carol) was NOT denied a tenant_a case_id at the "
        f"auth-dependency ACL check. status={resp.status_code} body={resp.text!r}"
    )
