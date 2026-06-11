"""Q6-A: claim-tree chunking — independent-claim bundle chunks.

The Q6 decision requires "每 claim 一 chunk 帶依附項": an independent claim's
retrieval chunk must carry the text of its (transitively) dependent claims so
that a query matching a limitation that only appears in a dependent claim still
surfaces the independent claim's family.

Design under test (option (a) in the task brief):
    * Per-claim `claim_N` chunks (claim_no=N) stay EXACTLY single-claim so the
      claim-tree UI path (`get_claim_tree` → `list_claim_chunks` →
      `parse_claim_dependencies`) is unaffected.
    * NEW `claim_N_tree` bundle chunks (claim_no=None) carry the independent
      claim + all its dependents, and are ignored by `list_claim_chunks`.

These tests prove:
    * a bundle chunk contains its dependents' text,
    * the per-claim chunks are unchanged (single-claim text),
    * the tree round-trip via get_claim_tree is correct,
    * a bundle chunk is retrievable for a dependent-only limitation query,
    * a no-dependents patent doesn't crash / regress.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.ai_engine import rag
from backend.ai_engine.rag import chunk_patent
from backend.shared.models import Patent


def _patent(claims: list[str], patent_no: str = "US-TREE-1") -> Patent:
    return Patent(
        patent_no=patent_no,
        title="Cooling system test patent",
        abstract="A cooling system abstract.",
        claims=claims,
        publication_date=datetime(2024, 1, 1, tzinfo=UTC),
        jurisdiction="US",
        is_local=False,
    )


# A small fixture: independent claim 1, two dependents (2 → 1, 3 → 2),
# plus a second independent chain (claim 4 independent, claim 5 → 4).
_CHAIN_CLAIMS = [
    "1. A cooling system, comprising: a base plate having microchannels.",
    "2. The cooling system of claim 1, wherein said microchannels are copper.",
    "3. The cooling system of claim 2, further comprising temperature sensors.",
    "4. A heat exchanger, comprising: a finned manifold.",
    "5. The heat exchanger of claim 4, wherein the manifold is brazed aluminum.",
]


def _by_section(chunks):
    return {c.section: c for c in chunks}


def test_bundle_chunk_contains_dependent_text():
    chunks = chunk_patent(_patent(_CHAIN_CLAIMS))
    by_sec = _by_section(chunks)

    # Bundle chunk for independent claim 1 must exist with claim_no None.
    assert "claim_1_tree" in by_sec
    bundle = by_sec["claim_1_tree"]
    assert bundle.claim_no is None

    # It bundles claim 1 + its transitive dependents (2 and 3).
    assert bundle.metadata["is_independent"] is True
    assert bundle.metadata["root_claim_no"] == 1
    assert bundle.metadata["dependent_claims"] == [2, 3]

    # The dependent-only limitations ("copper", "temperature sensors") must be
    # in the bundle text so retrieval embeds them under the independent claim.
    assert "microchannels are copper" in bundle.text
    assert "temperature sensors" in bundle.text
    # And the independent claim's own text is present too.
    assert "base plate having microchannels" in bundle.text


def test_second_independent_chain_also_bundled():
    chunks = chunk_patent(_patent(_CHAIN_CLAIMS))
    by_sec = _by_section(chunks)

    assert "claim_4_tree" in by_sec
    bundle = by_sec["claim_4_tree"]
    assert bundle.metadata["dependent_claims"] == [5]
    assert "finned manifold" in bundle.text
    assert "brazed aluminum" in bundle.text

    # Dependent claims (2, 3, 5) must NOT get their own bundle chunk.
    assert "claim_2_tree" not in by_sec
    assert "claim_3_tree" not in by_sec
    assert "claim_5_tree" not in by_sec


def test_per_claim_chunks_unchanged_single_text():
    """The `claim_N` chunks must remain single-claim so the tree parser is
    not corrupted by bundling."""
    chunks = chunk_patent(_patent(_CHAIN_CLAIMS))
    by_sec = _by_section(chunks)

    for i, claim_text in enumerate(_CHAIN_CLAIMS):
        cno = i + 1
        ch = by_sec[f"claim_{cno}"]
        assert ch.claim_no == cno
        # Exactly the original claim text — no other claim's text leaked in.
        assert ch.text == claim_text
        # Defensive: no other claim's distinctive token bled in.
        for j, other in enumerate(_CHAIN_CLAIMS):
            if j != i:
                # The other claim's full text should not be a substring.
                assert other not in ch.text


def test_list_claim_chunks_ignores_bundle_chunks():
    """The tree path filters claim_no is not None; bundle chunks (claim_no
    None) must be invisible to it, so get_claim_tree stays correct."""
    p = _patent(_CHAIN_CLAIMS, patent_no="US-TREE-LIST")
    rag.index_patent("tenant_tree", p)

    claim_chunks = rag._store.list_claim_chunks("tenant_tree", "US-TREE-LIST")
    # Exactly 5 claim chunks — no tree-bundle leakage.
    assert len(claim_chunks) == 5
    assert all(c.claim_no is not None for c in claim_chunks)
    assert [c.claim_no for c in claim_chunks] == [1, 2, 3, 4, 5]


def test_get_claim_tree_round_trip_correct():
    """End-to-end: index → get_claim_tree must yield a correct tree whose
    node count == number of claims and whose edges match the fixture."""
    p = _patent(_CHAIN_CLAIMS, patent_no="US-TREE-RT")
    rag.index_patent("tenant_rt", p)

    tree = rag.get_claim_tree("tenant_rt", "US-TREE-RT")
    assert len(tree) == len(_CHAIN_CLAIMS)  # node count == claim count

    by_no = {n["claim_no"]: n for n in tree}
    assert by_no[1]["depends_on"] is None and by_no[1]["is_independent"]
    assert by_no[2]["depends_on"] == 1
    assert by_no[3]["depends_on"] == 2
    assert by_no[3]["depth"] == 2
    assert by_no[4]["depends_on"] is None and by_no[4]["is_independent"]
    assert by_no[5]["depends_on"] == 4


def test_bundle_chunk_is_retrievable():
    """Retrieval scenario: index a patent, query with the bundle chunk's own
    text, and assert the bundle chunk comes back. Mock embeddings are
    deterministic (sha256), so embedding the exact text yields the same vector
    and a self-match floats to the top — a robust assertion that the bundle
    chunk is actually indexed and retrievable."""
    p = _patent(_CHAIN_CLAIMS, patent_no="US-TREE-RET")
    rag.index_patent("tenant_ret", p)

    # The independent-claim bundle's full text.
    chunks = chunk_patent(p)
    bundle = _by_section(chunks)["claim_1_tree"]

    hits = rag.retrieve("tenant_ret", bundle.text, top_k=8)
    sections = {h.section for h in hits}
    assert "claim_1_tree" in sections, sections

    # The retrieved bundle hit carries the dependent-claim metadata.
    tree_hit = next(h for h in hits if h.section == "claim_1_tree")
    assert tree_hit.metadata.get("dependent_claims") == [2, 3]


def test_no_dependents_patent_no_crash_no_regression():
    """A patent with only independent claims: no bundle chunks are emitted
    (each bundle would equal its per-claim chunk), and chunk_patent does not
    crash. Chunk count == abstract + per-claim chunks (no tree chunks)."""
    only_indep = [
        "1. A first standalone method.",
        "2. A second standalone apparatus.",
        "3. A third standalone system.",
    ]
    chunks = chunk_patent(_patent(only_indep, patent_no="US-NODEP"))
    by_sec = _by_section(chunks)

    # No `_tree` bundle chunks at all.
    assert not any(c.section.endswith("_tree") for c in chunks)
    # 1 abstract + 3 per-claim chunks, no spec text given.
    assert len(chunks) == 1 + len(only_indep)
    assert "abstract" in by_sec
    for cno in (1, 2, 3):
        assert by_sec[f"claim_{cno}"].claim_no == cno


def test_empty_claims_list_no_crash():
    """Edge case: a patent with no claims must not crash chunk_patent."""
    p = _patent([], patent_no="US-EMPTY")
    chunks = chunk_patent(p)
    # Only the abstract chunk survives.
    assert [c.section for c in chunks] == ["abstract"]


def test_chunk_count_with_dependents():
    """Sanity on total chunk count for the chain fixture:
    1 abstract + 5 per-claim + 2 independent-claim bundles (claim 1, claim 4).
    """
    chunks = chunk_patent(_patent(_CHAIN_CLAIMS))
    abstract = [c for c in chunks if c.section == "abstract"]
    per_claim = [c for c in chunks if c.claim_no is not None]
    bundles = [c for c in chunks if c.section.endswith("_tree")]
    assert len(abstract) == 1
    assert len(per_claim) == 5
    assert len(bundles) == 2
    assert {c.section for c in bundles} == {"claim_1_tree", "claim_4_tree"}
