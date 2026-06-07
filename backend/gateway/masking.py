"""Data masking layer (Q10).

Strategy: PII + customer identifiers, regex + dictionary based.

Key invariants (per Q3 hybrid):
    - The mapping table NEVER leaves on-prem.
    - Outbound LLM payload only sees placeholders.
    - Response un-masking happens server-side before showing the attorney.

At-rest confidentiality of the un-redaction table (Q3/Q10 — "crown jewel"):
    - The `original` column is the reversible map back to real PII / client
      identifiers. It is ENCRYPTED AT REST with authenticated encryption
      (Fernet / AES-128-CBC + HMAC-SHA256). The on-disk SQLite file holds only
      ciphertext, so copying `redaction_mapping.db` alone is NOT enough to
      un-redact anything.
    - Encryption keys are PER-TENANT: each tenant's subkey is derived from a
      single master key (`settings.MAPPING_ENCRYPTION_KEY`) via HKDF-SHA256 with
      the tenant_id as the info parameter. A leaked tenant_a table therefore
      cannot be decrypted with tenant_b's key.
    - The master key lives OUTSIDE the database (env / secret manager), so DB
      theft alone is insufficient — you also need the master key. For the POC a
      deterministic dev key is derived when the env var is unset (a WARNING is
      logged; a real key MUST be configured in production).

A real implementation would also:
    - Run an NER model for free-text customer references
    - Let each tenant upload their own keyword dictionary
    - Hash PII with HMAC-tenant-key so the same email → same placeholder
      (lets LLM reason about co-occurrence without knowing identity)
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Pattern

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.shared.config import settings, MAPPING_DB_PATH

logger = logging.getLogger(__name__)


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


# --- At-rest encryption of the un-redaction table (Q3/Q10) ---

# Domain-separation constants for key derivation.
_HKDF_INFO_PREFIX = b"patentmind/mapping-encryption/v1/tenant="
_HKDF_SALT = b"patentmind-mapping-store"

# Emit the "no master key" boot guard once per process, not per derivation.
_dev_key_warned = False


def _master_key_bytes() -> bytes:
    """Resolve the master key for mapping-table encryption.

    Mirrors the JWT_SECRET boot-guard style: production MUST provide a real
    secret via ``MAPPING_ENCRYPTION_KEY``. For the POC / pytest / demo we derive
    a deterministic dev key so the system runs out of the box, but we log a
    WARNING (once) so the gap is visible. We DO NOT hard-fail (the demo must run).
    """
    global _dev_key_warned
    configured = (settings.MAPPING_ENCRYPTION_KEY or "").strip()
    if configured:
        return configured.encode("utf-8")

    if not _dev_key_warned:
        logger.warning(
            "MAPPING_ENCRYPTION_KEY is not set — deriving a deterministic DEV "
            "key for the redaction mapping table. The un-redaction map is the "
            "crown jewel; set MAPPING_ENCRYPTION_KEY to a real secret in "
            "production."
        )
        _dev_key_warned = True
    # Deterministic dev fallback so redact/unmask round-trips reproducibly in
    # the POC. Tied to JWT_SECRET only to vary across local installs; this is
    # explicitly NOT production-grade.
    return hashlib.sha256(
        b"patentmind-dev-mapping-master::" + settings.JWT_SECRET.encode("utf-8")
    ).digest()


def _tenant_fernet(tenant_id: str) -> Fernet:
    """Derive a per-tenant Fernet key from the master key via HKDF-SHA256.

    A tenant's ciphertext is only decryptable with that tenant's derived key, so
    a leaked single-tenant table cannot be cross-decrypted with another tenant's
    key (tenant isolation at rest).
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO_PREFIX + tenant_id.encode("utf-8"),
    )
    raw = hkdf.derive(_master_key_bytes())
    return Fernet(base64.urlsafe_b64encode(raw))


# --- Mapping table (LOCAL ONLY, never uploaded; `original` encrypted at rest) ---

class MaskingStore:
    """Append-only local mapping table.  Reversible un-mask for inbound responses.

    The `original` column stores per-tenant-encrypted ciphertext (urlsafe-b64
    Fernet token), never plaintext PII.
    """

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
        # Encrypt the original under the tenant-derived key BEFORE it touches disk.
        token = _tenant_fernet(tenant_id).encrypt(original.encode("utf-8"))
        ciphertext = token.decode("ascii")  # urlsafe-b64 Fernet token, TEXT-safe
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO mappings(tenant_id, placeholder, original, rule_id) VALUES (?, ?, ?, ?)",
                (tenant_id, placeholder, ciphertext, rule_id),
            )
            self._conn.commit()

    def get_original(self, tenant_id: str, placeholder: str) -> str | None:
        cur = self._conn.execute(
            "SELECT original FROM mappings WHERE tenant_id = ? AND placeholder = ?",
            (tenant_id, placeholder),
        )
        row = cur.fetchone()
        if not row:
            return None
        stored = row[0]
        try:
            plaintext = _tenant_fernet(tenant_id).decrypt(stored.encode("ascii"))
            return plaintext.decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            # Wrong tenant key, tampered/corrupt ciphertext, or a stray legacy
            # plaintext row. Degrade gracefully: never crash un-redaction, and
            # never leak an undecryptable original. The caller (unmask) keeps the
            # placeholder when None is returned.
            logger.warning(
                "Failed to decrypt mapping for tenant=%s placeholder=%s; "
                "returning placeholder unchanged.",
                tenant_id,
                placeholder,
            )
            return None


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

    Unicode normalisation (M-6 fix)
    -------------------------------
    The input is normalised to **NFKC** (compatibility composition) BEFORE
    any regex applies. The regex tables target ASCII characters (``a-zA-Z``,
    ``0-9``, ``@``, ``-``); without normalisation, mixed-script inputs
    bypass them entirely:

    * Fullwidth digits ``０９１２`` (U+FF10..FF19) match no ``\\d`` class
      built from ASCII brackets — a fullwidth-typed Taiwan mobile number
      slips past ``phone_tw``.
    * Halfwidth/fullwidth ligatures (e.g. ``＠`` U+FF20 for ``@``) bypass
      the email regex.
    * Compatibility decompositions (e.g. ``ｆｉ`` U+FB01 → ``fi``) bypass
      any literal substring rules a tenant dictionary might add.

    NFKC folds all these variants into their canonical ASCII forms so the
    existing regex inventory keeps working without per-rule
    Unicode-aware rewrites (which would have to be re-audited every time
    a tenant adds a rule).

    Why **NFKC** and not NFC?

    * NFC only handles canonical equivalence (composed vs decomposed
      diacritics) — it would catch the NFD-typed email case
      (``a\\u0301lice@…`` → ``álice@…``) but NOT fullwidth digits, which
      are a deliberate threat-model entry: a Taiwanese user pasting from
      a Word document that auto-corrected to fullwidth would leak phone
      numbers.
    * NFKC is a superset of NFC plus compatibility folding (fullwidth →
      halfwidth, ligatures → components, superscripts → bases). It's
      lossy in the sense that ``Ⅳ`` becomes ``IV`` — that loss is
      exactly what we want for PII detection (a roman numeral 4 in a
      patent claim is informationally identical to ``IV``).

    The mapping table stores the **normalised** form as the original, so
    when ``unmask`` reverses the placeholder it returns the canonical
    spelling. For the demo this is fine; a future refinement could keep a
    side-table mapping back to the raw bytes if any caller needs the
    pre-normalisation form (the OA preview UI does NOT — it shows the
    redaction overlay over the normalised view).
    """
    triggered: list[str] = []
    # M-6: normalise input. ``text`` becomes the NFKC form going forward; all
    # downstream operations (regex matching, placeholder storage,
    # round-trip through ``unmask``) work on this canonical form.
    redacted = unicodedata.normalize("NFKC", text)

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
