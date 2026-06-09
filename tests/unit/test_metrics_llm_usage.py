"""Unit tests for metrics.record_llm_usage (Q19 LLM token/route/error bridge)."""
from __future__ import annotations

from backend.shared import metrics


def setup_function(_fn):
    metrics.REGISTRY.reset()


def test_record_llm_usage_counts_tokens_and_route():
    meta = {
        "model_used": "claude-haiku",
        "usage": {"prompt_tokens": 100, "completion_tokens": 40},
    }
    metrics.record_llm_usage(meta)
    assert metrics.LLM_TOKENS.get({"model": "claude-haiku", "kind": "prompt"}) == 100.0
    assert metrics.LLM_TOKENS.get({"model": "claude-haiku", "kind": "completion"}) == 40.0
    assert metrics.LLM_ROUTE.get({"model": "claude-haiku"}) == 1.0


def test_record_llm_usage_flat_token_keys():
    # Some metas carry token counts at the root rather than under `usage`.
    metrics.record_llm_usage(
        {"model": "llama-local", "prompt_tokens": 5, "completion_tokens": 7}
    )
    assert metrics.LLM_TOKENS.get({"model": "llama-local", "kind": "prompt"}) == 5.0
    assert metrics.LLM_ROUTE.get({"model": "llama-local"}) == 1.0


def test_record_llm_usage_error_flag_counts_llm_error():
    metrics.record_llm_usage({"model_used": "claude-sonnet", "llm_error": True})
    assert metrics.LLM_ERRORS.get({"model": "claude-sonnet"}) == 1.0


def test_record_llm_usage_no_model_no_route_inflation():
    # A pure-lookup endpoint returns model_used=None + zero tokens; must NOT
    # bump the route counter (avoid inflating the routing mix with non-LLM calls).
    metrics.record_llm_usage(
        {"model_used": None, "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
    )
    assert metrics.LLM_ROUTE.get({"model": "unknown"}) == 0.0
    assert metrics.LLM_TOKENS.get({"model": "unknown", "kind": "prompt"}) == 0.0


def test_record_llm_usage_none_and_garbage_are_noops():
    metrics.record_llm_usage(None)          # type: ignore[arg-type]
    metrics.record_llm_usage({})            # empty
    metrics.record_llm_usage("not a dict")  # type: ignore[arg-type]
    # Nothing recorded, nothing raised.
    assert metrics.LLM_ROUTE.get({"model": "unknown"}) == 0.0


def test_record_llm_usage_caps_model_label_length():
    huge = "m" * 500
    metrics.record_llm_usage({"model_used": huge, "prompt_tokens": 1})
    # Model label is capped at 64 chars to bound cardinality / line length.
    assert metrics.LLM_ROUTE.get({"model": huge[:64]}) == 1.0
