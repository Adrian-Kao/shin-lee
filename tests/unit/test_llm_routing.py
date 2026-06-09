"""Q15 adversarial routing proof: confidential text NEVER touches the cloud.

The Q15 decision (docs/DECISIONS.md) is "多模型 + 機密案件強制走地端" — a
multi-model router where any case whose ``security_level`` is in
``settings.LOCAL_LLM_FOR_SECURITY_LEVELS`` is FORCED onto the local LLM,
regardless of intent or cost-circuit state. CLAUDE.md §4 enshrines this as
invariant #7 ("Confidential cases auto-route to local LLM").

There is a deliberate tension with Q11/Q18 (DECISIONS.md "衝突與取捨"): the
cost circuit breaker DEGRADES the reasoning model down to the cheap *cloud*
model when the daily budget trips. This suite's headline job is to prove that
the degrade path can NEVER override the confidential→local guard — i.e. a
tripped circuit breaker must not become a side-channel that leaks privileged
text to the cloud.

The proof has belt-and-braces layers, each tested here:

  1. ``route_model`` — the routing decision itself, over the FULL matrix of
     security_level × intent × circuit_open.
  2. ``chat(security_level="confidential")`` with LLM_MODE="anthropic" — the
     call-layer guard refuses rather than calling out.
  3. ``AnthropicLLM.achat(security_level="confidential")`` — the backend's own
     first-line guard, proven to raise BEFORE any network I/O.
  4. ``vision_ocr`` — the OCR router refuses confidential too.
  5. LLM_MODE="local" short-circuit — everything routes local.

Hermetic by construction: settings are monkeypatched and restored by pytest's
``monkeypatch`` fixture; the anthropic singleton is reset in teardown of every
mode-mutating test; NO real network call is ever made (the achat guard fires
before the SDK client is touched).
"""
from __future__ import annotations

import asyncio

import pytest

from backend.ai_engine import llm_client
from backend.shared.config import settings


# Intents the router knows about. classify_security exercises the
# "everything else → cheap" tail of route_model.
ALL_INTENTS = ("parse_oa", "draft_response", "verify_citations", "classify_security")
REASONING_INTENTS = ("parse_oa", "draft_response")
ALL_SECURITY_LEVELS = ("public", "confidential", "top_secret")
# Confidential-class levels = anything in LOCAL_LLM_FOR_SECURITY_LEVELS.
CONFIDENTIAL_LEVELS = settings.LOCAL_LLM_FOR_SECURITY_LEVELS  # ("confidential", "top_secret")
CIRCUIT_STATES = (False, True)


@pytest.fixture
def anthropic_mode(monkeypatch):
    """Put the client in anthropic mode with a dummy key, hermetically.

    Resets the AnthropicLLM singleton both before and after so a client built
    under a different env in another test can't leak in (and ours can't leak
    out). monkeypatch restores LLM_MODE / ANTHROPIC_API_KEY automatically.
    """
    llm_client.reset_anthropic_singleton()
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key-not-real-no-network")
    try:
        yield
    finally:
        llm_client.reset_anthropic_singleton()


# ---------------------------------------------------------------------------
# 1. FULL ROUTING MATRIX
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("security_level", ALL_SECURITY_LEVELS)
@pytest.mark.parametrize("intent", ALL_INTENTS)
@pytest.mark.parametrize("circuit_open", CIRCUIT_STATES)
def test_routing_matrix(security_level, intent, circuit_open):
    """Exhaustive 3 × 4 × 2 = 24-cell routing matrix.

    The single non-negotiable rule: a confidential-class level ALWAYS routes
    local, for EVERY intent and BOTH circuit states. Public cells follow the
    documented intent/degrade logic.
    """
    model = llm_client.route_model(
        intent=intent,
        security_level=security_level,
        circuit_open=circuit_open,
    )

    if security_level in CONFIDENTIAL_LEVELS:
        # CORE INVARIANT — confidential/top_secret never leaves the box.
        assert model == settings.LLM_MODEL_LOCAL, (
            f"CONFIDENTIAL LEAK: level={security_level!r} intent={intent!r} "
            f"circuit_open={circuit_open} routed to {model!r}, expected "
            f"LLM_MODEL_LOCAL={settings.LLM_MODEL_LOCAL!r}"
        )
        return

    # ----- public path -----
    if intent == "verify_citations":
        assert model == settings.LLM_MODEL_VERIFIER
    elif intent in REASONING_INTENTS:
        if circuit_open:
            assert model == settings.LLM_MODEL_CHEAP  # cost-circuit degrade
        else:
            assert model == settings.LLM_MODEL_REASONING
    else:  # classify_security and any other tail intent → cheap
        assert model == settings.LLM_MODEL_CHEAP


def test_confidential_every_cell_routes_local():
    """Belt-and-braces aggregate: assert the WHOLE confidential sub-matrix is
    local in one shot, so a future change that special-cases one intent can't
    slip a single cloud cell past the per-cell parametrization above."""
    leaks = []
    for level in CONFIDENTIAL_LEVELS:
        for intent in ALL_INTENTS:
            for circuit_open in CIRCUIT_STATES:
                model = llm_client.route_model(
                    intent=intent, security_level=level, circuit_open=circuit_open
                )
                if model != settings.LLM_MODEL_LOCAL:
                    leaks.append((level, intent, circuit_open, model))
    assert not leaks, f"confidential cells that did NOT route local: {leaks}"


@pytest.mark.parametrize("intent", REASONING_INTENTS)
def test_public_reasoning_uses_reasoning_model(intent):
    model = llm_client.route_model(
        intent=intent, security_level="public", circuit_open=False
    )
    assert model == settings.LLM_MODEL_REASONING


@pytest.mark.parametrize("intent", REASONING_INTENTS)
def test_public_reasoning_degrades_when_circuit_open(intent):
    model = llm_client.route_model(
        intent=intent, security_level="public", circuit_open=True
    )
    assert model == settings.LLM_MODEL_CHEAP


def test_verifier_intent_routes_verifier_and_differs_from_reasoning():
    """verify_citations → dedicated verifier model, distinct from the reasoning
    model (Q14: the verifier MUST be a different model than the drafter so it
    is an independent check, not the same model grading its own homework)."""
    for circuit_open in CIRCUIT_STATES:
        model = llm_client.route_model(
            intent="verify_citations", security_level="public", circuit_open=circuit_open
        )
        assert model == settings.LLM_MODEL_VERIFIER
    assert settings.LLM_MODEL_VERIFIER != settings.LLM_MODEL_REASONING


# ---------------------------------------------------------------------------
# 2. HEADLINE ADVERSARIAL CASE — degrade can't leak confidential to cloud
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", CONFIDENTIAL_LEVELS)
@pytest.mark.parametrize("intent", REASONING_INTENTS)
def test_circuit_breaker_degrade_cannot_leak_confidential(level, intent):
    """THE adversarial test (Q11 × Q15 tension).

    When the cost circuit breaker trips, public reasoning calls DEGRADE to the
    cheap *cloud* model. If the security check did not strictly precede the
    degrade branch in route_model, a confidential case with circuit_open=True
    could fall through to LLM_MODEL_CHEAP — a privileged-text-to-cloud leak.

    Prove it cannot: confidential + circuit_open=True still routes LOCAL, and
    crucially does NOT route to the cheap cloud model the degrade path uses.
    """
    open_model = llm_client.route_model(
        intent=intent, security_level=level, circuit_open=True
    )
    closed_model = llm_client.route_model(
        intent=intent, security_level=level, circuit_open=False
    )
    assert open_model == settings.LLM_MODEL_LOCAL, (
        f"DEGRADE LEAK: {level!r}/{intent!r} with circuit_open=True routed "
        f"{open_model!r} — the cost-breaker degrade overrode the confidential→local "
        f"guard. Expected LLM_MODEL_LOCAL."
    )
    # The circuit state must be irrelevant for confidential — same model both ways.
    assert open_model == closed_model
    # And explicitly NOT the cheap cloud model that the public degrade path emits.
    assert open_model != settings.LLM_MODEL_CHEAP


# ---------------------------------------------------------------------------
# 3. BELT-AND-BRACES AT THE CALL LAYER (anthropic mode)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", CONFIDENTIAL_LEVELS)
def test_chat_refuses_confidential_in_anthropic_mode(anthropic_mode, level):
    """`chat(security_level="confidential")` in anthropic mode must RAISE
    rather than call the cloud. route_model already steers confidential to
    LLM_MODEL_LOCAL, but chat() has its own explicit guard (defense in depth)
    so even a router bug can't push privileged text out."""
    with pytest.raises(RuntimeError) as exc:
        llm_client.chat(
            system="sys",
            user="privileged client invention disclosure",
            intent="parse_oa",
            security_level=level,
            circuit_open=False,
        )
    msg = str(exc.value).lower()
    assert "confidential" in msg or "security_level" in msg or "local" in msg


@pytest.mark.parametrize("level", CONFIDENTIAL_LEVELS)
def test_achat_guard_raises_before_any_network_call(anthropic_mode, level):
    """`AnthropicLLM.achat(security_level="confidential")` raises its OWN guard
    BEFORE touching the network.

    We prove "no network call" structurally: the guard is literally the first
    statement in achat (it precedes _call_with_retry / the SDK client). To make
    the proof airtight we also sabotage the SDK client so that IF the guard were
    ever bypassed and execution reached the network layer, the test would fail
    with a DIFFERENT, loud error instead of silently passing. We construct the
    client with a dummy key (no real key, no real network), then assert the
    raised error is the confidential guard — not the sabotage, not a 401.
    """
    llm = llm_client.AnthropicLLM(api_key="dummy-key-no-network")

    # Sabotage: replace the underlying SDK client's network call with a
    # tripwire. Reaching it means the guard was bypassed.
    class _Tripwire:
        async def create(self, **kwargs):  # pragma: no cover - must never run
            raise AssertionError(
                "NETWORK REACHED: achat made a cloud call for a confidential "
                "case — the guard was bypassed."
            )

    class _Messages:
        messages = _Tripwire()

    llm._client = _Messages()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm.achat(
                system="sys",
                user="privileged client invention disclosure",
                intent="parse_oa",
                model_hint=settings.LLM_MODEL_REASONING,
                security_level=level,
            )
        )
    msg = str(exc.value).lower()
    # It must be the confidential guard, NOT the network tripwire (which would
    # be an AssertionError and thus not caught by pytest.raises(RuntimeError)).
    assert "refusing to call cloud" in msg or "must route to the local" in msg, (
        f"expected the confidential cloud-refusal guard, got: {exc.value!r}"
    )


def test_chat_allows_public_in_anthropic_mode_reaches_client(anthropic_mode, monkeypatch):
    """Sanity counter-test: a PUBLIC call in anthropic mode does NOT hit the
    confidential guard and proceeds to the (stubbed) client. This proves the
    refusal above is specific to confidential, not a blanket anthropic-mode
    failure. We stub the SDK call so no real network I/O happens."""
    captured = {}

    def _fake_chat(self, system, user, intent, model_hint, *, security_level="public"):
        captured["model_hint"] = model_hint
        captured["security_level"] = security_level
        return llm_client.LLMResponse(
            text="{}", model=model_hint, prompt_tokens=1, completion_tokens=1, latency_ms=1
        )

    monkeypatch.setattr(llm_client.AnthropicLLM, "chat", _fake_chat)

    resp = llm_client.chat(
        system="sys",
        user="public OA text",
        intent="parse_oa",
        security_level="public",
        circuit_open=False,
    )
    assert resp.model == settings.LLM_MODEL_REASONING
    assert captured["security_level"] == "public"
    assert captured["model_hint"] == settings.LLM_MODEL_REASONING


# ---------------------------------------------------------------------------
# 4. vision_ocr refuses confidential
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", CONFIDENTIAL_LEVELS)
def test_vision_ocr_router_refuses_confidential(level):
    """The public vision_ocr router raises for confidential levels regardless
    of LLM_MODE — pages of a confidential case must never reach cloud OCR."""
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm_client.vision_ocr(
                image_bytes=b"\x89PNG fake page bytes",
                mime="image/png",
                security_level=level,
            )
        )
    assert "must not" in str(exc.value).lower() or "refused" in str(exc.value).lower()


@pytest.mark.parametrize("level", CONFIDENTIAL_LEVELS)
def test_anthropic_vision_ocr_guard_before_network(level):
    """AnthropicLLM.vision_ocr has its own confidential guard that fires before
    any network call. Sabotage the SDK client to prove the guard precedes it."""
    llm = llm_client.AnthropicLLM(api_key="dummy-key-no-network")

    class _Tripwire:
        async def create(self, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("NETWORK REACHED in vision_ocr for confidential")

    class _Messages:
        messages = _Tripwire()

    llm._client = _Messages()  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm.vision_ocr(b"\x89PNG bytes", "image/png", security_level=level)
        )
    assert "refusing vision ocr" in str(exc.value).lower() or "must not" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 5. LLM_MODE="local" short-circuit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("security_level", ALL_SECURITY_LEVELS)
@pytest.mark.parametrize("intent", ALL_INTENTS)
@pytest.mark.parametrize("circuit_open", CIRCUIT_STATES)
def test_local_mode_routes_everything_local(monkeypatch, security_level, intent, circuit_open):
    """With LLM_MODE="local" there is exactly one model, so route_model
    short-circuits to LLM_MODEL_LOCAL for every cell — public included. This is
    the on-prem Ollama deployment shape."""
    monkeypatch.setattr(settings, "LLM_MODE", "local")
    model = llm_client.route_model(
        intent=intent, security_level=security_level, circuit_open=circuit_open
    )
    assert model == settings.LLM_MODEL_LOCAL
