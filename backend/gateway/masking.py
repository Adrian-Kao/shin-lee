"""Data masking layer (Q10).

Strategy: PII + customer identifiers, regex + dictionary based.

Key invariants (per Q3 hybrid):
    - The mapping table NEVER leaves on-prem.
    - Outbound LLM payload only sees placeholders.
    - Response un-masking happens server-side before showing the attorney.

A real implementation would also:
    - Run an NER model for free-text customer references
    - Let each tenant upload their own keyword dictionary
    - Hash PII with HMAC-tenant-key so the same email → same placeholder
      (lets LLM reason about co-occurrence without knowing identity)
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Pattern

from backend.shared.config import settings, MAPPING_DB_PATH


@dataclass(frozen=True)
class MaskRule:
    rule_id: str
    pattern: Pattern[str]
    placeholder_prefix: str
    description: str


# --- Built-in PII rules (Q10 layer 1) ---

PII_RULES: list[MaskRule] = [
    MaskRule(
        rule_id="email",
        pattern=re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        placeholder_prefix="EMAIL",
        description="email address",
    ),
    MaskRule(
        rule_id="phone_tw",
        pattern=re.compile(r"\b09\d{2}[-\s]?\d{3}[-\s]?\d{3}\b"),
        placeholder_prefix="PHONE",
        description="Taiwan mobile phone",
    ),
    MaskRule(
        rule_id="phone_us",
        pattern=re.compile(r"\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        placeholder_prefix="PHONE",
        description="US phone (loose)",
    ),
    MaskRule(
        rule_id="tw_id",
        pattern=re.compile(r"\b[A-Z][12]\d{8}\b"),
        placeholder_prefix="TW_ID",
        description="Taiwan national ID",
    ),
    MaskRule(
        rule_id="ssn",
        pattern=re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        placeholder_prefix="SSN",
        description="US SSN",
    ),
]

# --- Customer identifier rules (Q10 layer 2) ---
# Each tenant provides its own.  POC ships demo dictionaries.

TENANT_DICTIONARIES: dict[str, list[MaskRule]] = {
    "tenant_a": [
        MaskRule(
            rule_id="apex_case_no",
            pattern=re.compile(r"\bAPEX-\d{4}-\d{3,5}\b"),
            placeholder_prefix="CASE_REF",
            description="Apex internal case number",
        ),
        MaskRule(
            rule_id="apex_client_code",
            pattern=re.compile(r"\bCL-[A-Z]{2,4}\d{2,4}\b"),
            placeholder_prefix="CLIENT_CODE",
            description="Apex client code",
        ),
    ],
    "tenant_b": [
        MaskRule(
            rule_id="beta_proj_code",
            pattern=re.compile(r"\bBL-PRJ-\d{4}\b"),
            placeholder_prefix="PROJ",
            description="BetaLegal project code",
        ),
    ],
}


# --- Mapping table (LOCAL ONLY, never uploaded) ---

class MaskingStore:
    """Append-only local mapping table.  Reversible un-mask for inbound responses."""

    def __init__(self, path: Path = MAPPING_DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mappings (
                tenant_id TEXT NOT NULL,
                placeholder TEXT NOT NULL,
                original TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, placeholder)
            )
            """
        )
        self._conn.commit()

    def remember(self, tenant_id: str, placeholder: str, original: str, rule_id: str):
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO mappings(tenant_id, placeholder, original, rule_id) VALUES (?, ?, ?, ?)",
                (tenant_id, placeholder, original, rule_id),
            )
            self._conn.commit()

    def get_original(self, tenant_id: str, placeholder: str) -> str | None:
        cur = self._conn.execute(
            "SELECT original FROM mappings WHERE tenant_id = ? AND placeholder = ?",
            (tenant_id, placeholder),
        )
        row = cur.fetchone()
        return row[0] if row else None


_store = MaskingStore()


def _stable_id(text: str, salt: str) -> str:
    """Generate deterministic short id so same value → same placeholder per tenant.

    Lets LLM reason about co-occurrence (same email shows up twice = related)
    without ever seeing the real value.
    """
    return hashlib.sha256(f"{salt}:{text}".encode()).hexdigest()[:8].upper()


def redact(text: str, tenant_id: str) -> tuple[str, list[str]]:
    """Replace all matches with reversible placeholders.

    Returns (redacted_text, list_of_rule_ids_triggered).

    Q11 spotlight handling is in oa_analyzer; this layer is purely pattern-based.
    """
    triggered: list[str] = []
    redacted = text

    rules = list(PII_RULES) + TENANT_DICTIONARIES.get(tenant_id, [])

    for rule in rules:
        def _sub(match: re.Match) -> str:
            original = match.group(0)
            sid = _stable_id(original, salt=tenant_id)
            placeholder = f"[{rule.placeholder_prefix}_{sid}]"
            _store.remember(tenant_id, placeholder, original, rule.rule_id)
            if rule.rule_id not in triggered:
                triggered.append(rule.rule_id)
            return placeholder

        redacted = rule.pattern.sub(_sub, redacted)

    return redacted, triggered


def unmask(text: str, tenant_id: str) -> str:
    """Reverse redaction for inbound responses.  Server-side only."""
    placeholder_pattern = re.compile(r"\[([A-Z_]+)_([0-9A-F]{8})\]")

    def _sub(match: re.Match) -> str:
        placeholder = match.group(0)
        original = _store.get_original(tenant_id, placeholder)
        return original if original is not None else placeholder

    return placeholder_pattern.sub(_sub, text)
