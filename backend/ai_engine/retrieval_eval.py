"""Q6-B — retrieval evaluation harness (recall@k / MRR).

Turns "is our RAG good enough?" from a vibe into a number. Q6 in
`docs/QUESTIONS.md` literally requires: take historical OA cases, check
whether the top-5 retrieval hits the examiner-cited prior-art passage; if
hit-rate < 70%, redo the chunking strategy. This module is the mechanism
that measures it.

How it works
------------
1. A small hand-labeled dataset (``data/eval/retrieval_eval_set.json``, or an
   inline fallback) lists eval cases ``{query, tenant_id, relevant: [...]}``.
   ``relevant`` entries are patent numbers (``"US7654321"``) and/or chunk
   ids (``"US7654321#claim_9"``). A hit is relevant if its ``patent_no`` OR
   its ``chunk_id`` matches ANY entry.
2. ``evaluate()`` indexes the demo patents (``backend.patent_db.seed``) into a
   dedicated eval tenant via ``rag.index_patent``, runs each query through
   ``rag.retrieve``, and computes per-case + aggregate ``recall@k`` and
   ``MRR``.
3. ``assert_quality()`` is the CI gate: it fails when aggregate recall@5 is
   below a configured floor.

IMPORTANT — mock embeddings make the absolute numbers meaningless
-----------------------------------------------------------------
With ``EMBEDDING_BACKEND=mock`` (the POC default) embeddings are deterministic
SHA-256 hashes of the text (see ``backend/ai_engine/rag.py``). Cosine scores
between unrelated texts cluster within ~0.02 and rankings are effectively
random. So the recall/MRR numbers this harness reports on the mock backend
are NOT a quality signal — do not read them as "our RAG is N% good".

The harness's value on the mock backend is twofold:
  (a) it exercises the full index → retrieve → score path so a regression
      that breaks retrieval wiring (tenant isolation, chunking, the public
      RAG API shape) shows up as a crash or a recall cliff, and
  (b) it is the CI gate / report mechanism that becomes a REAL quality
      measurement the instant ``EMBEDDING_BACKEND=bge-m3`` is set.

Thresholds
----------
``DEFAULT_MIN_RECALL_AT_5`` is deliberately LOW so the mock-backend test suite
is green (mock embeddings are near-random; a 0.70 gate would be flaky-red on
mock for no real reason). ``PROD_TARGET_RECALL_AT_5`` is the number Q6 actually
cares about (0.70). When you flip to bge-m3, ratchet the gate up to the prod
target.

Run a readable report (mirrors ``python -m backend.ai_engine.deadline``)::

    python -m backend.ai_engine.retrieval_eval
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from backend.ai_engine import rag
from backend.shared.config import DATA_DIR, settings
from backend.shared.models import Patent

# ---------------------------------------------------------------------------
# Thresholds (see module docstring).
# ---------------------------------------------------------------------------
# The Q6 doc's natural target. Production (bge-m3) MUST ratchet the gate here.
# Sourced from config (Agent H block) so the prod target lives in ONE place;
# the env default is 0.70 (the Q6 number), so this stays == 0.70 unless an
# operator overrides RAG_EVAL_TARGET_RECALL_AT_5.
PROD_TARGET_RECALL_AT_5: float = settings.RAG_EVAL_TARGET_RECALL_AT_5
# Advisory prod targets for the richer ranking metrics (informative only on a
# real embedder; mock numbers are noise).
PROD_TARGET_NDCG_AT_5: float = settings.RAG_EVAL_TARGET_NDCG_AT_5
PROD_TARGET_COVERAGE_AT_5: float = settings.RAG_EVAL_TARGET_COVERAGE_AT_5
# Default CI floor for the MOCK backend. Set low on purpose: mock embeddings
# are deterministic SHA-256 noise, so a 0.70 gate would be red for reasons
# that say nothing about RAG quality. This floor only proves the wiring is
# intact (index → retrieve → score returns *something* for the eval queries).
DEFAULT_MIN_RECALL_AT_5: float = 0.10

# Dedicated tenant for eval so we never pollute a real tenant's index.
EVAL_TENANT_ID: str = "__eval__"

_DATASET_PATH = DATA_DIR / "eval" / "retrieval_eval_set.json"


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
# Inline fallback so the harness is self-contained even if the JSON is missing
# (e.g. a stale checkout). Kept deliberately tiny — the JSON file is the
# source of truth and carries the full hand-labeled set + provenance README.
_INLINE_FALLBACK_CASES: list[dict] = [
    {
        "id": "fallback-microchannel",
        "query": (
            "microchannel cooling system for electric vehicle battery with "
            "non-uniform cross-section channels to induce turbulent flow"
        ),
        "tenant_id": "tenant_a",
        "relevant": ["US7654321"],
    },
    {
        "id": "fallback-heatsink",
        "query": "solid copper heat sink with parallel extruded fins for power electronics",
        "tenant_id": "tenant_a",
        "relevant": ["US6543210"],
    },
]


def load_dataset(path: Path | None = None) -> list[dict]:
    """Load the labeled eval cases. Falls back to the inline set if the JSON
    file is absent. Every returned case has ``query``, ``tenant_id``, and a
    non-empty ``relevant`` list."""
    path = path or _DATASET_PATH
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases = raw.get("cases", raw) if isinstance(raw, dict) else raw
    else:
        cases = _INLINE_FALLBACK_CASES
    out: list[dict] = []
    for c in cases:
        if not c.get("query") or not c.get("relevant"):
            continue
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Demo-patent loading (build Patent models from the seed dicts)
# ---------------------------------------------------------------------------
def _patent_from_seed(d: dict) -> tuple[Patent, str]:
    """Build a ``Patent`` from a seed dict, returning (patent, spec_text).

    The seed dicts carry extra keys (``tenant_id``, ``spec_text``) that aren't
    part of the ``Patent`` model, so strip them before constructing.
    """
    spec_text = d.get("spec_text", "")
    patent = Patent(
        patent_no=d["patent_no"],
        title=d["title"],
        abstract=d["abstract"],
        claims=d["claims"],
        publication_date=d["publication_date"],
        jurisdiction=d["jurisdiction"],
        is_local=d.get("is_local", False),
    )
    return patent, spec_text


def _index_demo_patents(tenant_id: str = EVAL_TENANT_ID) -> int:
    """Index every demo patent into ``tenant_id``. Returns chunk count.

    All patents go into ONE eval tenant regardless of their seed ``tenant_id``
    so cross-tenant queries (e.g. the EP patent that lives in tenant_b) can be
    evaluated in a single index. This is fine because the eval tenant is
    isolated from real tenants.
    """
    from backend.patent_db.seed import DEMO_PATENTS

    total = 0
    for d in DEMO_PATENTS:
        patent, spec_text = _patent_from_seed(d)
        total += rag.index_patent(tenant_id, patent, spec_text=spec_text)
    return total


# ---------------------------------------------------------------------------
# Metrics — pure functions, provably correct independent of embeddings.
# ---------------------------------------------------------------------------
def _is_hit_relevant(hit, relevant: set[str]) -> bool:
    """A hit matches if its patent_no OR its chunk_id is in ``relevant``."""
    if getattr(hit, "patent_no", None) in relevant:
        return True
    chunk_id = (getattr(hit, "metadata", {}) or {}).get("chunk_id")
    return chunk_id in relevant


def recall_at_k(results: list, relevant, k: int) -> float:
    """Fraction of the relevant set that appears in the top-``k`` results.

    ``results`` is an ordered list of hits (rank 0 = best). ``relevant`` is the
    set of identifiers (patent_no and/or chunk_id) that SHOULD be retrieved.

    recall@k = |relevant ids found in top-k| / |relevant ids|.

    Returns 0.0 when ``relevant`` is empty (nothing to recall).
    """
    relevant = set(relevant)
    if not relevant:
        return 0.0
    topk = results[:k]
    found: set[str] = set()
    for hit in topk:
        pno = getattr(hit, "patent_no", None)
        if pno in relevant:
            found.add(pno)
        chunk_id = (getattr(hit, "metadata", {}) or {}).get("chunk_id")
        if chunk_id in relevant:
            found.add(chunk_id)
    return len(found) / len(relevant)


def mrr(results: list, relevant) -> float:
    """Reciprocal rank of the FIRST relevant hit (1-indexed).

    MRR for a single query = 1 / rank_of_first_relevant_hit, or 0.0 if no
    relevant hit appears anywhere in ``results``. (The "mean" in MRR is taken
    across queries by the caller / aggregator.)
    """
    relevant = set(relevant)
    if not relevant:
        return 0.0
    for idx, hit in enumerate(results, start=1):
        if _is_hit_relevant(hit, relevant):
            return 1.0 / idx
    return 0.0


def ndcg_at_k(results: list, relevant, k: int) -> float:
    """Normalised Discounted Cumulative Gain at cutoff ``k`` (binary gain).

    Unlike recall@k (which ignores rank order within the top-k) and MRR (which
    only cares about the FIRST relevant hit), nDCG@k rewards placing relevant
    hits HIGHER and credits EVERY relevant hit in the cutoff with a
    log-discounted gain. This is the metric that actually distinguishes a
    retriever that puts the right passage at rank 1 from one that buries it at
    rank 5 — the quality signal Q6 cares about once embeddings are real.

    Binary relevance (gain ∈ {0, 1}); a relevant id already counted earlier in
    the ranking does not double-credit (so repeated patent chunks for the same
    relevant patent_no don't inflate the score). DCG sums gain / log2(rank+1);
    IDCG is the DCG of the ideal ranking (all relevant ids first), capped at
    ``min(|relevant|, k)``. Returns 0.0 when ``relevant`` is empty.
    """
    relevant = set(relevant)
    if not relevant:
        return 0.0
    seen: set[str] = set()
    dcg = 0.0
    for rank, hit in enumerate(results[:k], start=1):
        gain = 0.0
        pno = getattr(hit, "patent_no", None)
        cid = (getattr(hit, "metadata", {}) or {}).get("chunk_id")
        # Credit at most once per distinct relevant id, at its first appearance.
        for ident in (pno, cid):
            if ident in relevant and ident not in seen:
                seen.add(ident)
                gain = 1.0
        if gain:
            dcg += gain / math.log2(rank + 1)
    # Ideal DCG: the achievable number of distinct relevant ids placed first.
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(r + 1) for r in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def grounding_coverage(results: list, relevant) -> float:
    """Fraction of the RETURNED hits that are relevant ("precision-like").

    This is the grounding-coverage signal Q14 cares about: when the drafter is
    handed the retrieval set as its grounded citation pool, how much of that
    pool is actually on-topic? A low coverage means the drafter is grounded in
    mostly-irrelevant passages, which dilutes citation quality even if recall
    is high. Defined as |relevant hits returned| / |hits returned|.

    Returns 0.0 when ``results`` is empty (nothing was grounded on).
    """
    if not results:
        return 0.0
    relevant = set(relevant)
    if not relevant:
        return 0.0
    n_rel = sum(1 for h in results if _is_hit_relevant(h, relevant))
    return n_rel / len(results)


# ---------------------------------------------------------------------------
# End-to-end evaluation
# ---------------------------------------------------------------------------
def evaluate(dataset: list[dict] | None = None, k: int = 5) -> dict:
    """Index the demo patents and score every eval case.

    Returns::

        {
          "k": 5,
          "n_cases": 7,
          "recall@k": 0.42,          # aggregate (mean over cases)
          "mrr": 0.31,               # aggregate (mean over cases)
          "embedding_backend": "mock",
          "per_case": [ {id, query, tenant_id, recall@k, mrr, n_relevant,
                         n_retrieved, top_patent_nos, hit}, ... ],
          "failures": [ <per_case dicts where recall@k == 0.0> ],
        }

    A case is a "failure" when NONE of its relevant ids appear in the top-k —
    those are exactly the cases a human should re-label or that signal a
    chunking problem (per the Q6 spec).
    """
    cases = dataset if dataset is not None else load_dataset()
    _index_demo_patents(EVAL_TENANT_ID)

    per_case: list[dict] = []
    recall_sum = 0.0
    mrr_sum = 0.0
    ndcg_sum = 0.0
    coverage_sum = 0.0

    for c in cases:
        query = c["query"]
        # All demo patents are indexed under EVAL_TENANT_ID; the case's own
        # tenant_id is retained for reporting/traceability only.
        relevant = set(c["relevant"])
        hits = rag.retrieve(EVAL_TENANT_ID, query, top_k=max(k, 5))

        r = recall_at_k(hits, relevant, k)
        m = mrr(hits, relevant)
        nd = ndcg_at_k(hits, relevant, k)
        cov = grounding_coverage(hits[:k], relevant)
        recall_sum += r
        mrr_sum += m
        ndcg_sum += nd
        coverage_sum += cov

        per_case.append(
            {
                "id": c.get("id", query[:32]),
                "query": query,
                "tenant_id": c.get("tenant_id"),
                "recall@k": r,
                "mrr": m,
                "ndcg@k": nd,
                "grounding_coverage@k": cov,
                "n_relevant": len(relevant),
                "n_retrieved": len(hits),
                "top_patent_nos": [h.patent_no for h in hits[:k]],
                "hit": r > 0.0,
            }
        )

    n = len(cases)
    agg_recall = recall_sum / n if n else 0.0
    agg_mrr = mrr_sum / n if n else 0.0
    agg_ndcg = ndcg_sum / n if n else 0.0
    agg_coverage = coverage_sum / n if n else 0.0
    failures = [pc for pc in per_case if pc["recall@k"] == 0.0]

    return {
        "k": k,
        "n_cases": n,
        "recall@k": agg_recall,
        "mrr": agg_mrr,
        "ndcg@k": agg_ndcg,
        "grounding_coverage@k": agg_coverage,
        "embedding_backend": rag._embedder.backend,
        "per_case": per_case,
        "failures": failures,
    }


def assert_quality(
    min_recall_at_5: float = DEFAULT_MIN_RECALL_AT_5,
    dataset: list[dict] | None = None,
) -> dict:
    """Quality gate. Runs ``evaluate(k=5)`` and checks aggregate recall@5.

    Returns a structured result::

        {"passed": bool, "min_recall_at_5": float, "actual_recall_at_5": float,
         "report": <evaluate() dict>}

    Does NOT raise — the caller decides whether to ``assert result["passed"]``
    (unit tests) or branch on it (a CI script that wants to print the report
    first). This keeps the gate composable.
    """
    report = evaluate(dataset=dataset, k=5)
    actual = report["recall@k"]
    return {
        "passed": actual >= min_recall_at_5,
        "min_recall_at_5": min_recall_at_5,
        "actual_recall_at_5": actual,
        "report": report,
    }


def gate_threshold_for_backend(backend: str | None = None) -> float:
    """Auto-select the recall@5 gate for the ACTIVE embedding backend.

    The two-track gate (分冊 06 Phase 1): ``mock`` / ``lexical`` embeddings are
    NOT a quality signal (mock = deterministic SHA-256 noise; lexical = a
    dependency-free hashing vectorizer), so they may only gate at the wiring
    FLOOR (``DEFAULT_MIN_RECALL_AT_5``) — a 0.70 gate would be flaky-red for
    reasons that say nothing about RAG quality. A real semantic embedder
    (``bge-m3``) gates at the Q6 PROD target (``PROD_TARGET_RECALL_AT_5``).

    The payoff: flipping ``EMBEDDING_BACKEND=bge-m3`` AUTOMATICALLY ratchets CI
    up to the real bar — no second config change, no forgotten gate. ``backend``
    defaults to the live embedder so callers/tests can probe a hypothetical one.
    """
    b = backend if backend is not None else rag._embedder.backend
    return PROD_TARGET_RECALL_AT_5 if b == "bge-m3" else DEFAULT_MIN_RECALL_AT_5


def assert_quality_auto(dataset: list[dict] | None = None) -> dict:
    """CI entry point: ``assert_quality`` with the gate auto-selected per the
    active embedding backend (see ``gate_threshold_for_backend``).

    Green on mock/lexical (gates at the floor), and enforces the prod target the
    instant ``EMBEDDING_BACKEND=bge-m3`` is configured — without touching CI."""
    result = assert_quality(min_recall_at_5=gate_threshold_for_backend(), dataset=dataset)
    result["gate_backend"] = rag._embedder.backend
    return result


# ---------------------------------------------------------------------------
# Readable report (python -m backend.ai_engine.retrieval_eval)
# ---------------------------------------------------------------------------
def _print_report() -> None:
    report = evaluate(k=5)
    backend = report["embedding_backend"]

    print("=" * 72)
    print("Q6-B Retrieval Evaluation  (recall@5 / MRR)")
    print("=" * 72)
    print(f"embedding backend : {backend}")
    print(f"eval cases        : {report['n_cases']}")
    print(f"aggregate recall@5: {report['recall@k']:.3f}")
    print(f"aggregate MRR     : {report['mrr']:.3f}")
    print(f"aggregate nDCG@5  : {report['ndcg@k']:.3f}")
    print(
        f"aggregate cover@5 : {report['grounding_coverage@k']:.3f}  "
        f"(fraction of grounded set that is relevant)"
    )
    if backend == "mock":
        print()
        print("NOTE: mock embeddings are deterministic SHA-256 noise — these")
        print("      numbers are NOT a RAG-quality signal. They become real")
        print("      when EMBEDDING_BACKEND=bge-m3. See module docstring.")
    print("-" * 72)
    print(f"{'case':<32} {'recall@5':>9} {'mrr':>7}  top patents")
    print("-" * 72)
    for pc in report["per_case"]:
        mark = " " if pc["hit"] else "✗"
        tops = ",".join(pc["top_patent_nos"][:3])
        print(f"{mark}{pc['id']:<31} {pc['recall@k']:>9.3f} {pc['mrr']:>7.3f}  {tops}")
    print("-" * 72)

    n_fail = len(report["failures"])
    if n_fail:
        print(f"{n_fail} case(s) with ZERO relevant hits in top-5:")
        for pc in report["failures"]:
            print(f"  ✗ {pc['id']}  (relevant not in top-5)")
    else:
        print("all cases retrieved at least one relevant hit in top-5.")

    # Gate summary against BOTH the mock floor and the prod target so the
    # operator sees the gap they must close before flipping to bge-m3.
    print("-" * 72)
    gate = assert_quality(min_recall_at_5=DEFAULT_MIN_RECALL_AT_5)
    status = "PASS" if gate["passed"] else "FAIL"
    print(
        f"mock-floor gate (>= {DEFAULT_MIN_RECALL_AT_5:.2f}): {status} "
        f"(actual {gate['actual_recall_at_5']:.3f})"
    )
    auto_th = gate_threshold_for_backend(backend)
    print(
        f"active auto gate (backend={backend}, >= {auto_th:.2f}): "
        f"{'PASS' if report['recall@k'] >= auto_th else 'FAIL'}  "
        f"← ratchets to {PROD_TARGET_RECALL_AT_5:.2f} automatically on bge-m3"
    )
    prod_ok = report["recall@k"] >= PROD_TARGET_RECALL_AT_5
    print(
        f"prod target     (>= {PROD_TARGET_RECALL_AT_5:.2f}): "
        f"{'MET' if prod_ok else 'NOT MET (expected on mock backend)'}"
    )
    ndcg_ok = report["ndcg@k"] >= PROD_TARGET_NDCG_AT_5
    print(
        f"prod nDCG@5     (>= {PROD_TARGET_NDCG_AT_5:.2f}): "
        f"{'MET' if ndcg_ok else 'NOT MET (expected on mock backend)'}  "
        f"(actual {report['ndcg@k']:.3f})"
    )
    cov_ok = report["grounding_coverage@k"] >= PROD_TARGET_COVERAGE_AT_5
    print(
        f"prod coverage@5 (>= {PROD_TARGET_COVERAGE_AT_5:.2f}): "
        f"{'MET' if cov_ok else 'NOT MET (expected on mock backend)'}  "
        f"(actual {report['grounding_coverage@k']:.3f})"
    )
    print("=" * 72)


if __name__ == "__main__":
    _print_report()
