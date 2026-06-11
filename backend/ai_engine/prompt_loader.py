"""Load externalized prompts from backend/ai_engine/prompts/*.yaml.

Single source of truth for AI engine prompts. The prompts live in YAML so
that a future Dify workflow migration can paste-import them without us
having to reverse-engineer Python string constants. The Python side keeps
the same callsites by going through ``render_system`` / ``load_prompt``.

``lru_cache`` keeps repeated reads cheap. Lookups fall back loudly
(``KeyError``) when an intent is unknown so a typo doesn't silently get a
``None`` prompt that the LLM then "helpfully" interprets.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Mandatory top-level keys every prompt YAML must declare. ``description`` is
# documentation-only so we don't enforce it. ``format_vars`` is optional and
# only required when a caller wants to use ``render_system`` with kwargs.
_REQUIRED_KEYS = ("intent", "version", "language", "system")


@functools.cache
def load_prompt(intent: str) -> dict:
    """Return the parsed YAML for ``intent``.

    Raises:
        KeyError: when no ``{intent}.yaml`` file exists in the prompts dir.
        ValueError: when the YAML is missing a mandatory key (see
            ``_REQUIRED_KEYS``) or did not parse to a mapping.
    """
    path = _PROMPTS_DIR / f"{intent}.yaml"
    if not path.exists():
        raise KeyError(f"No prompt YAML for intent '{intent}' at {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Prompt {intent}.yaml did not parse to a mapping")
    for k in _REQUIRED_KEYS:
        if k not in data:
            raise ValueError(f"Prompt {intent}.yaml missing required key: {k}")
    return data


def render_system(intent: str, **vars: object) -> str:
    """Return the system prompt, optionally with format-string vars filled in.

    Two modes:

    * **Verbatim** (no kwargs): the system text is returned exactly as
      authored. This is the common case — none of the shipped prompts are
      parameterised today.
    * **Format**: the YAML must declare a ``format_vars: [name, ...]``
      whitelist. Only those placeholders are treated as substitutable; every
      other literal ``{`` / ``}`` in the body is escaped before ``.format()``
      so JSON-schema fragments and few-shot examples (which legitimately
      contain braces) don't blow up with ``KeyError``.

    Raises:
        ValueError: if kwargs are passed but the YAML doesn't declare
            ``format_vars``, or a passed kwarg isn't in that whitelist.
    """
    p = load_prompt(intent)
    system: str = p["system"]
    if not vars:
        return system
    declared = set(p.get("format_vars") or [])
    if not declared:
        raise ValueError(
            f"Prompt '{intent}' does not declare `format_vars:` in its YAML. "
            f"Got kwargs={list(vars)}; either remove them or add `format_vars:` "
            f"to the YAML to opt in to .format() substitution."
        )
    unknown = set(vars) - declared
    if unknown:
        raise ValueError(
            f"Prompt '{intent}' got unknown vars: {sorted(unknown)}. "
            f"Declared format_vars: {sorted(declared)}"
        )
    # Escape every literal brace, then re-open only the declared placeholders.
    # This lets prompts contain JSON examples like `{"k": 1}` without exploding
    # in .format()'s KeyError path.
    escaped = system.replace("{", "{{").replace("}", "}}")
    for name in declared:
        escaped = escaped.replace("{{" + name + "}}", "{" + name + "}")
    return escaped.format(**vars)


@functools.lru_cache(maxsize=1)
def list_intents() -> list[str]:
    """Return all known prompt intents, sorted alphabetically."""
    return sorted(p.stem for p in _PROMPTS_DIR.glob("*.yaml"))
