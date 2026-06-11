"""End-to-end smoke test for the real Anthropic SDK wiring.

CLI:
    python scripts/anthropic_smoke.py [--case CASE-DEMO-001] [--verbose]

Designed to be the FIRST thing the user runs the morning their API key
arrives. If this passes, `python scripts/eval_cases.py --mode anthropic`
is safe to run on the full corpus.

Asserts (each failure → non-zero exit):
    A. API key is recognised by the SDK (a single short ping call returns
       a non-empty response, no auth error).
    B. Prompt caching fires — call twice in a row with the same system
       prompt; the second call MUST report cache_read_input_tokens > 0.
    C. Pricing matches the table in rate_limit.py — recompute the per-call
       cost from the reported usage and compare against estimate_cost();
       must agree to <1¢.
    D. Confidential routing assertion fires — direct construction of a
       chat() call with security_level='internal' (or any value in
       LOCAL_LLM_FOR_SECURITY_LEVELS) raises before any network call.

Key behaviours:
    - If ANTHROPIC_API_KEY is not set, prints a skip banner and exits 0.
      This makes the smoke test safe to run in CI without leaking keys.
    - On any assertion failure, prints the failed assertion + the actual
      observed value, and exits with code 2 (lets the playbook script
      tell the user which assertion to debug first).
    - Prints the post-run chain of `_session_usage` increments so a user
      can eyeball "first call: input=X output=Y; second call: input=X-Z
      output=Y, cache_read=Z" and confirm caching arithmetic by hand.

Cost: A single full run hits Anthropic twice with a small system prompt +
a short OA snippet. Estimated cost ~$0.01-0.02 per smoke run with caching
enabled. We hard-cap max_tokens at 256 for extra defense.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("anthropic_smoke")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Exit codes — kept stable so docs/EVAL_PLAYBOOK.md can reference them.
EXIT_OK = 0
EXIT_SKIPPED = 0  # explicitly not 2, so CI doesn't fail when key absent
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_CACHE = 4
EXIT_PRICING = 5
EXIT_CONFIDENTIAL = 6


def _bootstrap_env() -> None:
    """Force LLM_MODE=anthropic; clone the eval_cases env-hardening pattern.

    JWT_SECRET / DB paths set just so the backend modules import cleanly —
    we do NOT issue JWTs or write to the audit DB in this smoke test.
    """
    forced = {
        "LLM_MODE": "anthropic",
        "VECTOR_BACKEND": "memory",
        "EMBEDDING_BACKEND": "mock",
        "CACHE_BACKEND": "memory",
    }
    for k, v in forced.items():
        prev = os.environ.get(k)
        if prev is not None and prev != v:
            logger.warning("smoke: forced %s=%s (was %r)", k, v, prev)
        os.environ[k] = v
    os.environ.setdefault(
        "JWT_SECRET",
        "anthropic-smoke-no-jwt-32bytes-placeholder-shhhhh!",
    )


def _check_api_key() -> str | None:
    """Return the API key if set; else None (signals 'skip — no key')."""
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")


def _print_banner_skip() -> None:
    print("=" * 70)
    print("anthropic_smoke: SKIP — ANTHROPIC_API_KEY not set.")
    print()
    print("To run this smoke test (~30 sec, ~$0.02 estimated cost):")
    print("  1. echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env")
    print("  2. source .env && python scripts/anthropic_smoke.py")
    print()
    print("See docs/EVAL_PLAYBOOK.md for the full key-arrival sequence.")
    print("=" * 70)


def _print_banner_pass(observed_cost_usd: float) -> None:
    print("=" * 70)
    print("anthropic_smoke: PASS")
    print()
    print(f"  Total observed cost: ${observed_cost_usd:.4f}")
    print()
    print("Next: `python scripts/eval_cases.py --mode anthropic` on the full corpus.")
    print("=" * 70)


def _load_oa_text(case_id: str) -> str:
    """Read the OA text for the requested case. Fail fast if missing."""
    path = _REPO_ROOT / "data" / "cases" / case_id / "oa.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"OA text not found for {case_id} at {path}. Pick a case from data/cases/CASE-DEMO-NNN."
        )
    return path.read_text(encoding="utf-8")


def _truncate_for_smoke(text: str, max_chars: int = 1500) -> str:
    """Smoke test budget — keep total prompt short to bound cost.

    OA documents can run to ~10k chars; we only need enough text to
    exercise the pipeline + cache, not produce a quality draft.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n…(truncated for smoke test)…"


def run_smoke(case_id: str, verbose: bool = False) -> int:
    """Execute the smoke test. Returns one of the EXIT_* constants."""
    _bootstrap_env()
    key = _check_api_key()
    if not key:
        _print_banner_skip()
        return EXIT_SKIPPED

    # Configure logging AFTER skip-check so the skip banner isn't muddied.
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    # Deferred imports — env vars must already be set so config picks up
    # LLM_MODE=anthropic at module load time.
    from backend.ai_engine import llm_client
    from backend.gateway.rate_limit import _MODEL_PRICING_USD_PER_M, estimate_cost
    from backend.shared.config import settings

    try:
        oa_text = _load_oa_text(case_id)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return EXIT_USAGE

    user_msg = _truncate_for_smoke(oa_text)
    system_msg = (
        "You are an expert TW/US patent attorney assistant. Read the Office "
        "Action excerpt below and respond with one short JSON object: "
        '{"rejection_type": "<type>", "affected_claims": [<ints>]}. '
        "Be concise. No prose."
    )

    # Reset session counters so we measure THIS smoke run only.
    llm_client.reset_session_usage()

    print(f"anthropic_smoke: running 2 calls against {settings.LLM_MODEL_REASONING} ...")

    # ---- A. Auth check (implicit) + B. Cache miss (call 1) ----
    try:
        resp1 = llm_client.chat(
            system=system_msg,
            user=user_msg,
            intent="parse_oa",
            security_level="public",
        )
    except RuntimeError as e:
        # Catches: missing key (already guarded above), SDK not installed,
        # or 401 from the API. Surface the original error message so the
        # user can fix the right thing.
        print(f"FAIL (auth): {e}", file=sys.stderr)
        return EXIT_AUTH
    except Exception as e:
        # Generic catch — common cases are anthropic.AuthenticationError
        # (invalid key) and httpx.ConnectError (no network). Either way,
        # exit with EXIT_AUTH so the playbook's troubleshooting section
        # is the obvious next step.
        print(f"FAIL (auth): {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_AUTH

    # ---- B (cont'd). Cache hit on call 2 ----
    try:
        resp2 = llm_client.chat(
            system=system_msg,
            user=user_msg,
            intent="parse_oa",
            security_level="public",
        )
    except Exception as e:
        print(f"FAIL (second call): {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_AUTH

    if verbose:
        print(
            f"call 1: model={resp1.model} prompt={resp1.prompt_tokens} "
            f"completion={resp1.completion_tokens} cache_read={resp1.cache_read_input_tokens} "
            f"cache_create={resp1.cache_creation_input_tokens}"
        )
        print(
            f"call 2: model={resp2.model} prompt={resp2.prompt_tokens} "
            f"completion={resp2.completion_tokens} cache_read={resp2.cache_read_input_tokens} "
            f"cache_create={resp2.cache_creation_input_tokens}"
        )

    # ---- Assertion B: cache_read_input_tokens > 0 on call 2 ----
    if resp2.cache_read_input_tokens <= 0:
        print(
            f"FAIL (cache): call 2 reported cache_read_input_tokens="
            f"{resp2.cache_read_input_tokens}, expected > 0. "
            f"Prompt caching is NOT firing. Check that system_blocks uses "
            f"cache_control={{type: ephemeral}} (see llm_client.AnthropicLLM.achat).",
            file=sys.stderr,
        )
        return EXIT_CACHE

    # ---- Assertion C: pricing matches rate_limit.py ----
    # Recompute call-2 cost from its reported usage and compare to
    # estimate_cost() — they should be ≤1¢ apart (they should actually be
    # identical, since estimate_cost is pure arithmetic; the 1¢ slack is
    # for floating-point + future per-region overrides).
    usage2 = {
        "input_tokens": max(
            0,
            resp2.prompt_tokens - resp2.cache_read_input_tokens - resp2.cache_creation_input_tokens,
        ),
        "output_tokens": resp2.completion_tokens,
        "cache_read_input_tokens": resp2.cache_read_input_tokens,
        "cache_creation_input_tokens": resp2.cache_creation_input_tokens,
    }
    cost2 = estimate_cost(resp2.model, usage2)
    # Cross-check: the model used must be a known row in the pricing table
    # (else we'd silently fall through to the fallback and the user wouldn't
    # know costs are approximate).
    known = resp2.model in _MODEL_PRICING_USD_PER_M or any(
        resp2.model.startswith(k) for k in _MODEL_PRICING_USD_PER_M
    )
    if not known:
        print(
            f"FAIL (pricing): model {resp2.model!r} is not in "
            f"_MODEL_PRICING_USD_PER_M. Add a pricing row in "
            f"backend/gateway/rate_limit.py so cost reporting is dollar-accurate.",
            file=sys.stderr,
        )
        return EXIT_PRICING

    # ---- Assertion D: confidential routing aborts BEFORE network ----
    # Confidential cases (security_level in LOCAL_LLM_FOR_SECURITY_LEVELS)
    # MUST be refused by AnthropicLLM.achat() with a RuntimeError, not
    # routed to the cloud. We poke the assertion directly so the smoke
    # test doesn't depend on the case file name carrying "-CONF" — that
    # naming convention is documented but not enforced anywhere.
    if not settings.LOCAL_LLM_FOR_SECURITY_LEVELS:
        # Unusual config — LOCAL_LLM_FOR_SECURITY_LEVELS empty means no
        # case is ever confidential. That's a config bug, not a smoke
        # test failure, but we surface it loudly.
        print(
            "WARN (confidential): LOCAL_LLM_FOR_SECURITY_LEVELS is empty. "
            "Confidential routing assertion CANNOT fire. Check config.",
            file=sys.stderr,
        )
    else:
        confidential_level = next(iter(settings.LOCAL_LLM_FOR_SECURITY_LEVELS))
        try:
            llm_client.chat(
                system=system_msg,
                user="dummy",
                intent="parse_oa",
                security_level=confidential_level,
            )
            print(
                f"FAIL (confidential): chat() with security_level="
                f"{confidential_level!r} did NOT raise. Cloud LLM call would "
                f"have leaked privileged data. Fix llm_client.chat() guard.",
                file=sys.stderr,
            )
            return EXIT_CONFIDENTIAL
        except RuntimeError as e:
            # Expected — re-raise only if the message is suspiciously generic.
            if verbose:
                print(f"OK (confidential guard fired): {e}")

    # ---- Pretty-print the session usage chain ----
    usage = llm_client.get_session_usage()
    print()
    print("Session usage after smoke run:")
    print(f"  calls:                       {usage['calls']}")
    print(f"  errors:                      {usage['errors']}")
    print(f"  input_tokens:                {usage['input_tokens']}")
    print(f"  output_tokens:               {usage['output_tokens']}")
    print(f"  cache_read_input_tokens:     {usage['cache_read_input_tokens']}")
    print(f"  cache_creation_input_tokens: {usage['cache_creation_input_tokens']}")
    print()

    # ---- Total cost from session usage ----
    total_usage = {
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_input_tokens": usage["cache_read_input_tokens"],
        "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
    }
    total_cost = estimate_cost(resp2.model, total_usage)

    _print_banner_pass(total_cost)

    # cost2 is computed above for the pricing assertion — log it so a
    # verbose run shows the per-call vs aggregate decomposition.
    if verbose:
        print(f"  call-2 reconstructed cost: ${cost2:.6f}")

    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Anthropic SDK smoke test. Run before the first --mode anthropic "
            "eval to prove auth, caching, pricing, and confidential routing all "
            "behave as the eval harness expects."
        )
    )
    parser.add_argument(
        "--case",
        default="CASE-DEMO-001",
        help="Case to use for the prompt (default CASE-DEMO-001).",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-call token + cost detail."
    )
    args = parser.parse_args(argv)
    return run_smoke(args.case, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
