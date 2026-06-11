"""Day 12B — Anthropic production-path unit tests (Agent B).

Exercises the `LLM_MODE=anthropic` code path in backend.ai_engine.llm_client
WITHOUT any network I/O. A fake AsyncAnthropic client is monkeypatched onto an
AnthropicLLM instance; the real anthropic SDK is only imported for its error
CLASSES (RateLimitError, APIConnectionError, APITimeoutError, APIStatusError,
BadRequestError) so our retry taxonomy matches the SDK's exception hierarchy
exactly.

Coverage:
  * successful call → real token + cost accounting from the usage object,
    folded into module-level _session_usage.
  * retry-then-success (transient RateLimitError / server 5xx / timeout /
    connection error, then a good response).
  * retry exhaustion → the final transient error propagates.
  * non-transient 4xx (BadRequestError) → NO retry, surfaced immediately.
  * timeout handling (APITimeoutError is transient).
  * Q14 verifier model == drafter model guard
    (llm_client.assert_verifier_independence + via oa_analyzer.verify_citations).
  * Q14 hard wall: verify_citations rejects an ungrounded citation regardless
    of LLM mode (deterministic, offline).
  * Q15 confidential routing: anthropic backend refuses confidential before
    any network call.

All retry tests set LLM_RETRY_* knobs so backoff is fast and deterministic
(jitter 0, base 0) — no real sleeping, no flakes.
"""

from __future__ import annotations

import asyncio

import anthropic
import pytest

from backend.ai_engine import llm_client
from backend.ai_engine.llm_client import AnthropicLLM, LLMResponse
from backend.shared.config import settings

# ---------------------------------------------------------------------------
# Fakes — a minimal stand-in for AsyncAnthropic.messages.create
# ---------------------------------------------------------------------------


class _Usage:
    """Mimics the SDK usage object surfaced on msg.usage."""

    def __init__(
        self,
        *,
        input_tokens,
        output_tokens,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _TextBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text, usage):
        self.content = [_TextBlock(text)]
        self.usage = usage


def _make_response_error(cls, status_code):
    """Construct an SDK APIStatusError subclass without a real HTTP round trip.

    The SDK's APIStatusError.__init__ wants (message, *, response, body) and
    internally reads response.request. We fabricate a tiny response object
    exposing .headers / .status_code / .request so the retry helper's
    Retry-After read + status check work.
    """
    resp = type(
        "_Resp",
        (),
        {
            "status_code": status_code,
            "headers": {},
            "request": None,
        },
    )()
    return cls("boom", response=resp, body=None)


class _FakeMessages:
    """Programmable fake for client.messages — a scripted sequence of outcomes.

    Each entry in `script` is either an Exception instance (raised) or a
    _FakeMessage (returned). `calls` counts invocations.
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        outcome = self._script.pop(0) if self._script else self._script_default()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @staticmethod
    def _script_default():
        return _FakeMessage("{}", _Usage(input_tokens=1, output_tokens=1))


class _FakeClient:
    def __init__(self, script):
        self.messages = _FakeMessages(script)


def _ok_message(text="{}", **usage_kw):
    usage = _Usage(
        input_tokens=usage_kw.get("input_tokens", 100),
        output_tokens=usage_kw.get("output_tokens", 20),
        cache_read_input_tokens=usage_kw.get("cache_read_input_tokens", 0),
        cache_creation_input_tokens=usage_kw.get("cache_creation_input_tokens", 0),
    )
    return _FakeMessage(text, usage)


@pytest.fixture
def anthropic_llm(monkeypatch):
    """Build an AnthropicLLM with a dummy key and fast/deterministic retries.

    Returns a factory: pass a `script` (list of outcomes) and get back an
    AnthropicLLM whose ._client is the fake. Session usage is reset before each
    test so accounting assertions are isolated.
    """
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SEC", 0.0)
    monkeypatch.setattr(settings, "LLM_RETRY_JITTER_SEC", 0.0)
    monkeypatch.setattr(settings, "LLM_RETRY_MAX_SLEEP_SEC", 0.0)
    llm_client.reset_session_usage()

    def _make(script, *, max_retries=None):
        if max_retries is not None:
            monkeypatch.setattr(settings, "LLM_MAX_RETRIES", max_retries)
        llm = AnthropicLLM(api_key="dummy-key-no-network")
        llm._client = _FakeClient(script)  # type: ignore[attr-defined]
        return llm

    return _make


# ---------------------------------------------------------------------------
# 1. Successful call + real usage / cost accounting
# ---------------------------------------------------------------------------


def test_successful_call_accounts_tokens(anthropic_llm):
    llm = anthropic_llm(
        [
            _ok_message(
                text='{"ok": true}',
                input_tokens=500,
                output_tokens=120,
                cache_read_input_tokens=300,
                cache_creation_input_tokens=40,
            )
        ]
    )

    resp = asyncio.run(
        llm.achat(
            system="sys",
            user="user",
            intent="parse_oa",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )

    assert isinstance(resp, LLMResponse)
    assert resp.text == '{"ok": true}'
    assert resp.model == settings.LLM_MODEL_REASONING
    # completion_tokens comes straight off usage.output_tokens
    assert resp.completion_tokens == 120
    # prompt_tokens = input + cache_read + cache_create (the AnthropicLLM contract)
    assert resp.prompt_tokens == 500 + 300 + 40
    assert resp.cache_read_input_tokens == 300
    assert resp.cache_creation_input_tokens == 40

    usage = llm_client.get_session_usage()
    assert usage["input_tokens"] == 500
    assert usage["output_tokens"] == 120
    assert usage["cache_read_input_tokens"] == 300
    assert usage["cache_creation_input_tokens"] == 40
    assert usage["calls"] == 1
    assert usage["errors"] == 0


def test_successful_call_sends_cached_system_block(anthropic_llm):
    """Prompt caching (cost lever) is wired: the system prompt goes out as a
    cache_control ephemeral block and exactly one user message is sent."""
    llm = anthropic_llm([_ok_message()])
    asyncio.run(
        llm.achat(
            system="SYSTEM PROMPT",
            user="hi",
            intent="draft_response",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )
    kwargs = llm._client.messages.last_kwargs
    assert kwargs["model"] == settings.LLM_MODEL_REASONING
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["system"][0]["text"] == "SYSTEM PROMPT"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# 2. Retry-then-success (each transient class)
# ---------------------------------------------------------------------------


def test_retry_then_success_on_rate_limit(anthropic_llm):
    err = _make_response_error(anthropic.RateLimitError, 429)
    llm = anthropic_llm([err, err, _ok_message(text='{"after": "retry"}')], max_retries=3)
    resp = asyncio.run(
        llm.achat(
            system="s",
            user="u",
            intent="parse_oa",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )
    assert resp.text == '{"after": "retry"}'
    assert llm._client.messages.calls == 3  # 2 failures + 1 success
    # The successful call still records usage once.
    assert llm_client.get_session_usage()["calls"] == 1


def test_retry_then_success_on_server_5xx(anthropic_llm):
    err = _make_response_error(anthropic.InternalServerError, 500)
    llm = anthropic_llm([err, _ok_message()], max_retries=3)
    asyncio.run(
        llm.achat(
            system="s",
            user="u",
            intent="parse_oa",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )
    assert llm._client.messages.calls == 2


def test_retry_then_success_on_overloaded_529(anthropic_llm):
    # 529 (overloaded) has no dedicated class in anthropic 0.39.0 — a generic
    # APIStatusError with status_code 529 exercises the same >=500 retry branch.
    err = _make_response_error(anthropic.APIStatusError, 529)
    llm = anthropic_llm([err, _ok_message()], max_retries=3)
    asyncio.run(
        llm.achat(
            system="s",
            user="u",
            intent="parse_oa",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )
    assert llm._client.messages.calls == 2


def test_retry_then_success_on_connection_error(anthropic_llm):
    err = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    llm = anthropic_llm([err, _ok_message()], max_retries=3)
    asyncio.run(
        llm.achat(
            system="s",
            user="u",
            intent="parse_oa",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )
    assert llm._client.messages.calls == 2


def test_retry_then_success_on_timeout(anthropic_llm):
    err = anthropic.APITimeoutError(request=None)  # type: ignore[arg-type]
    llm = anthropic_llm([err, _ok_message()], max_retries=3)
    resp = asyncio.run(
        llm.achat(
            system="s",
            user="u",
            intent="parse_oa",
            model_hint=settings.LLM_MODEL_REASONING,
            security_level="public",
        )
    )
    assert resp.text == "{}"
    assert llm._client.messages.calls == 2


# ---------------------------------------------------------------------------
# 3. Retry exhaustion → the transient error propagates
# ---------------------------------------------------------------------------


def test_retry_exhaustion_raises_last_error(anthropic_llm):
    err = _make_response_error(anthropic.RateLimitError, 429)
    # All attempts fail. With max_retries=2 → 3 attempts total, all raise.
    llm = anthropic_llm([err, err, err], max_retries=2)
    with pytest.raises(anthropic.RateLimitError):
        asyncio.run(
            llm.achat(
                system="s",
                user="u",
                intent="parse_oa",
                model_hint=settings.LLM_MODEL_REASONING,
                security_level="public",
            )
        )
    assert llm._client.messages.calls == 3  # max_retries(2) + 1
    # The exhausting failure is accounted as one error/call.
    usage = llm_client.get_session_usage()
    assert usage["errors"] == 1
    assert usage["calls"] == 1


def test_server_error_exhaustion_raises(anthropic_llm):
    err = _make_response_error(anthropic.APIStatusError, 529)
    llm = anthropic_llm([err, err], max_retries=1)
    with pytest.raises(anthropic.APIStatusError):
        asyncio.run(
            llm.achat(
                system="s",
                user="u",
                intent="parse_oa",
                model_hint=settings.LLM_MODEL_REASONING,
                security_level="public",
            )
        )
    assert llm._client.messages.calls == 2  # max_retries(1) + 1


# ---------------------------------------------------------------------------
# 4. Non-transient 4xx is NOT retried
# ---------------------------------------------------------------------------


def test_bad_request_not_retried(anthropic_llm):
    err = _make_response_error(anthropic.BadRequestError, 400)
    llm = anthropic_llm([err, _ok_message()], max_retries=3)
    with pytest.raises(anthropic.BadRequestError):
        asyncio.run(
            llm.achat(
                system="s",
                user="u",
                intent="parse_oa",
                model_hint=settings.LLM_MODEL_REASONING,
                security_level="public",
            )
        )
    # Exactly ONE attempt — 400 is a caller error; retrying can't help.
    assert llm._client.messages.calls == 1
    assert llm_client.get_session_usage()["errors"] == 1


def test_context_too_long_bad_request_gives_friendly_error(anthropic_llm):
    """A 400 whose message mentions context/too-long is rewrapped into a
    recovery-oriented RuntimeError by achat (not retried)."""
    resp = type("_Resp", (), {"status_code": 400, "headers": {}, "request": None})()
    err = anthropic.BadRequestError(
        "input is too long for the model context window",
        response=resp,
        body=None,
    )
    llm = anthropic_llm([err], max_retries=3)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm.achat(
                system="s",
                user="u",
                intent="parse_oa",
                model_hint=settings.LLM_MODEL_REASONING,
                security_level="public",
            )
        )
    assert "context exceeded" in str(exc.value).lower()
    assert llm._client.messages.calls == 1


# ---------------------------------------------------------------------------
# 5. Q15 confidential routing — backend refuses before any network call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", settings.LOCAL_LLM_FOR_SECURITY_LEVELS)
def test_confidential_refused_before_network(anthropic_llm, level):
    # Script a tripwire: if the guard were bypassed, calling create() returns a
    # message and the test would wrongly pass — so assert the guard raised AND
    # that create() was never reached (calls == 0).
    llm = anthropic_llm([_ok_message()])
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm.achat(
                system="s",
                user="privileged invention disclosure",
                intent="parse_oa",
                model_hint=settings.LLM_MODEL_REASONING,
                security_level=level,
            )
        )
    assert "refusing to call cloud" in str(exc.value).lower()
    assert llm._client.messages.calls == 0


# ---------------------------------------------------------------------------
# 6. Q14 verifier independence guard
# ---------------------------------------------------------------------------


def test_assert_verifier_independence_noop_in_mock(monkeypatch):
    """In mock mode the guard is a no-op even if the model strings coincide —
    the deterministic _mock_verify is itself the independent check."""
    monkeypatch.setattr(settings, "LLM_MODE", "mock")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", settings.LLM_MODEL_REASONING)
    # Must NOT raise.
    llm_client.assert_verifier_independence()


def test_assert_verifier_independence_default_prod_config_passes(monkeypatch):
    """The DEFAULT prod config — reasoning=Sonnet, cheap=verifier=Haiku — passes.

    The verifier (Haiku) differs from the PRIMARY drafter (Sonnet), which is
    what independence requires. That the verifier shares a tier with the
    *cost-degraded* drafter (also Haiku, only when the Q18 breaker trips) is an
    accepted documented tradeoff, NOT an independence violation — so the guard
    must not fire here, or it would break the real anthropic path entirely."""
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "LLM_MODEL_REASONING", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_CHEAP", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "claude-haiku-4-5-20251001")
    llm_client.assert_verifier_independence()  # must NOT raise


def test_assert_verifier_independence_clean_when_no_collision(monkeypatch):
    """When the verifier differs from BOTH the full and degraded drafter, the
    guard passes."""
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "LLM_MODEL_REASONING", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_CHEAP", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "claude-haiku-4-5-20251001")
    llm_client.assert_verifier_independence()  # must not raise


def test_assert_verifier_independence_raises_when_same_as_reasoning(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "LLM_MODEL_REASONING", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_CHEAP", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "claude-sonnet-4-6")
    with pytest.raises(llm_client.VerifierIndependenceError) as exc:
        llm_client.assert_verifier_independence()
    assert "independence" in str(exc.value).lower()


def test_verify_citations_invokes_independence_guard(monkeypatch):
    """oa_analyzer.verify_citations calls the guard before the verifier LLM:
    a misconfigured cloud deployment (verifier == drafter) fails LOUD."""
    from backend.ai_engine import oa_analyzer
    from backend.shared.models import DraftResponse, RetrievalHit

    monkeypatch.setattr(settings, "LLM_MODE", "anthropic")
    monkeypatch.setattr(settings, "LLM_MODEL_REASONING", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "LLM_MODEL_CHEAP", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "claude-sonnet-4-6")

    draft = DraftResponse(
        rejection_id="rej-1",
        strategy="s",
        draft_text="See [GROUNDED_REF_1].",
        grounded_citations=["[GROUNDED_REF_1]"],
        confidence=0.8,
        requires_attorney_review=True,
    )
    hit = RetrievalHit(patent_no="US1", section="spec", text="t", score=0.9)
    with pytest.raises(llm_client.VerifierIndependenceError):
        oa_analyzer.verify_citations(draft, [hit])


# ---------------------------------------------------------------------------
# 7. Q14 hard wall — ungrounded citation rejected regardless of verifier output
# ---------------------------------------------------------------------------


def test_verify_citations_hard_wall_rejects_ungrounded(monkeypatch):
    """Even though the (mock) verifier LLM returns a benign result, an
    ungrounded external patent number is stripped and the result is invalid.
    This proves the regex stage — not the LLM — owns the verdict."""
    from backend.ai_engine import oa_analyzer
    from backend.shared.models import DraftResponse, RetrievalHit

    monkeypatch.setattr(settings, "LLM_MODE", "mock")  # offline, deterministic

    draft = DraftResponse(
        rejection_id="rej-1",
        strategy="s",
        draft_text="Distinguish over US9999999, never retrieved. See [GROUNDED_REF_1].",
        grounded_citations=["[GROUNDED_REF_1]"],
        confidence=0.8,
        requires_attorney_review=True,
    )
    hit = RetrievalHit(patent_no="US1", section="spec", text="t", score=0.9)
    result, _meta = oa_analyzer.verify_citations(draft, [hit])

    assert result["valid"] is False
    assert any("9999999" in c for c in result["invalid_citations"])
    assert "[GROUNDED_REF_1]" in result["valid_citations"]
    # The fabricated cite is scrubbed from the cleaned text.
    assert "US9999999" not in result["cleaned_draft_text"]
    assert "[CITATION_REMOVED]" in result["cleaned_draft_text"]


# ---------------------------------------------------------------------------
# 8. Backoff schedule helper — jitter + cap + Retry-After honoured
# ---------------------------------------------------------------------------


def test_backoff_honours_retry_after_and_cap(monkeypatch):
    monkeypatch.setattr(settings, "LLM_RETRY_JITTER_SEC", 0.0)
    monkeypatch.setattr(settings, "LLM_RETRY_MAX_SLEEP_SEC", 60.0)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SEC", 1.0)
    # No Retry-After → exponential base.
    assert llm_client._backoff_seconds(0) == 1.0
    assert llm_client._backoff_seconds(2) == 4.0
    # Retry-After overrides base, still capped.
    assert llm_client._backoff_seconds(0, retry_after=5.0) == 5.0
    assert llm_client._backoff_seconds(0, retry_after=999.0) == 60.0


def test_backoff_jitter_bounded(monkeypatch):
    monkeypatch.setattr(settings, "LLM_RETRY_JITTER_SEC", 2.0)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SEC", 1.0)
    monkeypatch.setattr(settings, "LLM_RETRY_MAX_SLEEP_SEC", 60.0)
    for _ in range(50):
        w = llm_client._backoff_seconds(0)
        # base(1.0) <= w <= base(1.0) + jitter(2.0)
        assert 1.0 <= w <= 3.0
