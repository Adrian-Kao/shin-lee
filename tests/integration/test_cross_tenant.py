"""Cross-tenant isolation hardening tests (H-3 + H-4).

H-3: Mock embeddings were a pure function of text. Two tenants indexing
the same patent got byte-identical vectors. A similarity-oracle attack
against /v1/retrieve_prior_art could confirm whether a given patent
was in some tenant's index. Fix: salt the mock SHA-256 with tenant_id.

H-4: Per-tenant audit verify is blind to a fabricated row whose
tenant_id is one the auditor doesn't think to query (typo, ghost
tenant). Fix: ``verify_global_chain()`` walks every tenant + asserts
each tenant_id is in DEMO_TENANTS + every prev_row_hash references a
real row.

These tests are the load-bearing assertions that close H-3 and H-4.
"""
from __future__ import annotations

import uuid

import numpy as np


# ---------------------------------------------------------------------------
# H-3 — same text, different tenants → different mock embeddings
# ---------------------------------------------------------------------------
def test_mock_embedding_differs_across_tenants():
    """Embed the same text under two distinct tenant_ids; assert the
    vectors are NOT byte-identical and not cosine-1.0 similar.

    Pre-fix the cosine sim was exactly 1.0 because the hash input had
    no tenant component. Post-fix the salt ``f"{tenant_id}:{text}"``
    means the vectors live in different points on the 384-dim sphere.

    Why both byte-identical AND cosine-1.0 checks? A future change might
    keep the vectors numerically distinct but inadvertently restore the
    cosine-1.0 property (e.g. if both got salt-rotated through the
    same transform). The cosine check is the load-bearing security
    assertion; byte-identical is the cheap canary.
    """
    from backend.ai_engine.rag import embed

    text = "claim 1: a method for predicting battery degradation"
    v1 = np.array(embed(text, tenant_id="tenant_a"))
    v2 = np.array(embed(text, tenant_id="tenant_b"))

    # Cheap canary: byte-identical vectors mean the salt wasn't applied.
    assert not np.array_equal(v1, v2), (
        "Mock embedding vectors are byte-identical across tenants — "
        "H-3 fix regressed; tenant_id salt is not being applied."
    )
    # Load-bearing: cosine sim must NOT be 1.0. Some floating-point slack
    # because the unit-normalisation makes exact 1.0 the failure signal,
    # not a 0.9999 near-miss.
    sim = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
    assert sim < 0.9999, (
        f"Mock embedding cosine sim is {sim:.6f} across tenants — must be "
        "< 1.0 to defeat the similarity-oracle attack on /v1/retrieve_prior_art."
    )


# ---------------------------------------------------------------------------
# H-4 — global audit chain verify
# ---------------------------------------------------------------------------
def _seed_audit_rows(writer, tenant_id: str, n: int) -> list[str]:
    """Helper: write `n` audit rows for `tenant_id` via the legitimate
    write() path so the hash chain is intact. Returns the audit_ids."""
    from backend.shared.models import User, UserRole

    user = User(
        user_id=f"u_{tenant_id}",
        tenant_id=tenant_id,
        role=UserRole.ATTORNEY,
        display_name="test",
        daily_token_quota=10_000,
    )
    audit_ids = []
    for i in range(n):
        aid = writer.write(
            user=user,
            case_id=f"CASE-{tenant_id}-{i}",
            endpoint="/test",
            request_payload={"i": i},
            response_payload={"ok": True},
            masked_rules=[],
            model_used="mock",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1,
            policy_decisions={"authn_passed": True},
        )
        audit_ids.append(aid)
    return audit_ids


def test_verify_global_chain_with_intact_rows_reports_no_breakage(tmp_path, monkeypatch):
    """Seed two tenants with rows written through the legitimate write()
    path. ``verify_global_chain`` must report ``broken=[]`` and
    ``by_tenant`` populated for every tenant present."""
    from backend.gateway.audit import AuditWriter

    # Use a per-test SQLite DB so we don't see rows from earlier tests.
    db_path = tmp_path / "audit.db"
    writer = AuditWriter(path=db_path)

    _seed_audit_rows(writer, "tenant_a", n=3)
    _seed_audit_rows(writer, "tenant_b", n=2)

    result = writer.verify_global_chain()
    assert result["broken"] == [], result
    assert result["verified"] == 5, result
    assert set(result["by_tenant"].keys()) == {"tenant_a", "tenant_b"}, result
    # Each per-tenant report carries its own verified count.
    assert result["by_tenant"]["tenant_a"]["verified"] == 3
    assert result["by_tenant"]["tenant_b"]["verified"] == 2


def test_verify_global_chain_detects_fabricated_unknown_tenant(tmp_path, monkeypatch):
    """An attacker (or compromised DBA) writes a row with a tenant_id
    NOT in DEMO_TENANTS. Per-tenant verify never sees it. Global
    verify MUST flag it via the ``unknown_tenant`` marker and list
    its audit_id in the global ``broken`` list.

    Implementation note: we bypass AuditWriter.write() because the
    writer is the very thing being subverted in the threat model. We
    write a raw INSERT — which would be how a compromised DBA could
    inject the row (the append-only TRIGGER blocks UPDATE/DELETE but
    not INSERT, by design).
    """
    from backend.gateway.audit import AuditWriter

    db_path = tmp_path / "audit.db"
    writer = AuditWriter(path=db_path)

    # Seed one legitimate row so the chain has something normal in it.
    _seed_audit_rows(writer, "tenant_a", n=1)

    # Now sneak in a ghost row tagged with tenant_zzz (not in
    # DEMO_TENANTS). Direct INSERT via the writer's connection.
    ghost_id = str(uuid.uuid4())
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO audit ("
            " audit_id, timestamp_utc, timestamp_local, user_id, tenant_id, case_id,"
            " endpoint, request_hash, response_hash, masked_field_rules,"
            " model_used, prompt_tokens, completion_tokens, latency_ms,"
            " policy_decisions, prev_row_hash, row_hash"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ghost_id, "2026-06-04T00:00:00+00:00", "2026-06-04T08:00:00",
                "ghost_user", "tenant_zzz", "GHOST-001",
                "/ghost", "", "", "[]",
                "mock", 0, 0, 0,
                '{"authn_passed": true}', "", "FAKE_HASH_NEVER_RECOMPUTABLE",
            ),
        )
        writer._conn.commit()

    result = writer.verify_global_chain()
    # tenant_zzz must appear in by_tenant with the unknown_tenant flag.
    assert "tenant_zzz" in result["by_tenant"], result
    assert result["by_tenant"]["tenant_zzz"].get("unknown_tenant") is True, result
    # The ghost row must be in the broken list, tagged with its tenant.
    broken_pairs = result["broken"]
    assert any(
        tid == "tenant_zzz" and aid == ghost_id
        for (tid, aid) in broken_pairs
    ), (
        "ghost row in unknown tenant was NOT flagged in global broken list — "
        f"H-4 fix regressed. broken={broken_pairs!r}"
    )


def test_verify_global_chain_detects_fabricated_prev_hash(tmp_path):
    """A row whose prev_row_hash points to nothing (no such row_hash
    exists anywhere in the table) must be flagged. Catches the case
    where a row was written by something that bypassed AuditWriter's
    ``_last_row_hash`` lookup — e.g. a buggy migration script.
    """
    from backend.gateway.audit import AuditWriter

    db_path = tmp_path / "audit.db"
    writer = AuditWriter(path=db_path)

    _seed_audit_rows(writer, "tenant_a", n=2)

    # Sneak in a row whose prev_row_hash references a never-existed hash.
    ghost_id = str(uuid.uuid4())
    with writer._lock:
        writer._conn.execute(
            "INSERT INTO audit ("
            " audit_id, timestamp_utc, timestamp_local, user_id, tenant_id, case_id,"
            " endpoint, request_hash, response_hash, masked_field_rules,"
            " model_used, prompt_tokens, completion_tokens, latency_ms,"
            " policy_decisions, prev_row_hash, row_hash"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ghost_id, "2026-06-04T00:00:00+00:00", "2026-06-04T08:00:00",
                "u_tenant_a", "tenant_a", "CASE-X",
                "/ghost", "", "", "[]",
                "mock", 0, 0, 0,
                '{"authn_passed": true}',
                "DEADBEEF_NEVER_A_REAL_ROW_HASH",  # prev points to nothing
                "DOESNT_MATTER_FOR_THIS_TEST_ROW_HASH",
            ),
        )
        writer._conn.commit()

    result = writer.verify_global_chain()
    broken_pairs = result["broken"]
    assert any(aid == ghost_id for (_tid, aid) in broken_pairs), (
        f"row with dangling prev_row_hash was NOT flagged. broken={broken_pairs!r}"
    )


# ---------------------------------------------------------------------------
# /v1/audit/verify?scope=global — auditor-only gate
# ---------------------------------------------------------------------------
def _login(client, user_id: str) -> str:
    resp = client.post(
        "/v1/auth/login",
        json={"user_id": user_id, "password": f"demo-{user_id}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_global_verify_endpoint_blocks_attorney(gateway_client):
    """Alice (ATTORNEY) MUST get 403 on scope=global — the cross-tenant
    audit view is auditor-only. Catches a regression where a future
    refactor relaxes the auditor-only gate to the per-tenant
    auditor/it_admin set (which would let an IT_ADMIN enumerate every
    tenant's case_ids)."""
    alice_token = _login(gateway_client, "alice")
    resp = gateway_client.get(
        "/v1/audit/verify?scope=global",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert resp.status_code == 403, resp.text


def test_global_verify_endpoint_blocks_it_admin(gateway_client):
    """Carol (IT_ADMIN) MUST get 403 on scope=global. The audit
    finding flags IT_ADMIN as per-tenant connectors/dashboards — they
    have no business reading a cross-tenant audit chain (which would
    leak other tenants' case IDs / endpoint usage patterns).

    The per-tenant /v1/audit/verify (no scope param) IS allowed for
    IT_ADMIN — that's a different endpoint, tested elsewhere."""
    carol_token = _login(gateway_client, "carol")
    resp = gateway_client.get(
        "/v1/audit/verify?scope=global",
        headers={"Authorization": f"Bearer {carol_token}"},
    )
    assert resp.status_code == 403, resp.text


def test_global_verify_endpoint_allows_auditor(gateway_client):
    """audit_dave (AUDITOR) is the only role allowed on scope=global.
    Returns the cross-tenant shape (``by_tenant`` populated)."""
    auditor_token = _login(gateway_client, "audit_dave")
    resp = gateway_client.get(
        "/v1/audit/verify?scope=global",
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Shape sanity — these keys must be present even if the chain is empty.
    assert "verified" in body
    assert "broken" in body
    assert "by_tenant" in body
    assert isinstance(body["by_tenant"], dict)
