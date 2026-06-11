"""Compatibility invariants for the future digiRunner + Dify migration.

Each test enforces a rule that would silently break the migration if
violated. Right now we have one invariant — "prompts live in YAML, not
in Python string constants" — but the file is named broadly so more
invariants (D1: gateway never calls LLM directly, D2: AI engine writes
no business state, etc.) can be added next to it.
"""

from __future__ import annotations

import ast
from pathlib import Path

# tests/unit/test_compat_invariants.py → repo root is two parents up.
_REPO = Path(__file__).resolve().parents[2]
_OA_ANALYZER = _REPO / "backend" / "ai_engine" / "oa_analyzer.py"
_LLM_CLIENT = _REPO / "backend" / "ai_engine" / "llm_client.py"

# Threshold above which a Python string literal is "prompt-sized" and
# therefore should live in a YAML, not inline in the module.
_PROMPT_CHAR_THRESHOLD = 500


def _find_long_string_constants(
    source: str, min_chars: int = _PROMPT_CHAR_THRESHOLD
) -> list[tuple[str, int]]:
    """Return (name, length) for every top-level / class-level module
    assignment of a plain string literal whose body is ≥ min_chars.

    Module docstrings, function docstrings, f-strings, .format() chains
    and string concatenations are all excluded — we only care about the
    classic ``NAME = "<huge prompt>"`` pattern that this refactor is
    eliminating.
    """
    tree = ast.parse(source)
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if len(value.value) >= min_chars:
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    for n in names:
                        hits.append((n, len(value.value)))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and len(value.value) >= min_chars
                and isinstance(node.target, ast.Name)
            ):
                hits.append((node.target.id, len(value.value)))
    return hits


def test_no_long_prompt_constants_in_oa_analyzer():
    """D3 invariant: prompts must live in backend/ai_engine/prompts/*.yaml,
    not as Python string constants. Catches new prompts being added inline.

    Catches honest reintroduction of long inline prompts. Adversarial
    concatenation (``'x' * 1000``, f-strings, runtime str.join) bypasses —
    accepted as best-effort guard.
    """
    text = _OA_ANALYZER.read_text(encoding="utf-8")
    matches = _find_long_string_constants(text)
    assert not matches, (
        f"Found {len(matches)} long string constants in oa_analyzer.py — "
        "move to backend/ai_engine/prompts/*.yaml per the Compat Refactor 1 "
        "invariant. Offenders: " + ", ".join(f"{name} ({n} chars)" for name, n in matches)
    )


def test_no_long_prompt_constants_in_llm_client():
    """Same invariant for llm_client.py — keep prompt logic out of the
    router. If llm_client ever sprouts a prompt constant it belongs in
    a YAML alongside the others.
    """
    text = _LLM_CLIENT.read_text(encoding="utf-8")
    matches = _find_long_string_constants(text)
    assert not matches, (
        f"Found {len(matches)} long string constants in llm_client.py — "
        "move to backend/ai_engine/prompts/*.yaml. Offenders: "
        + ", ".join(f"{name} ({n} chars)" for name, n in matches)
    )
