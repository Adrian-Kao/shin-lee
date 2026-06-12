#!/usr/bin/env python3
"""Bulk-import patents into the per-tenant RAG index (customer onboarding).

Closes Gap #1 of docs/OPERATIONS_AND_ONBOARDING.md §11: walks a folder of
patent files and indexes each one through the AI Engine's existing
``POST /v1/index/patent`` endpoint (the same path ``backend/patent_db/seed.py``
uses) — chosen over importing ``rag.py`` directly because the HTTP path indexes
into the RUNNING engine's vector store; a direct import would build vectors in
this script's own process and, on the in-memory backend, throw them away.

Supported inputs (mixable in one folder):

  *.json — one object or a list of objects with the /v1/index/patent fields:
           patent_no, title, abstract, claims[], publication_date,
           jurisdiction, is_local?, spec_text?
           (see backend/patent_db/seed.py for examples; tenant_id is always
           overridden by --tenant)

  *.txt  — TIPO 公報-style text (the data/cases/*/patent.txt layout):
           公開編號：<patent_no>      → patent_no  (fallback: [公開公報] line)
           【名稱】…                  → title
           【摘要】…                  → abstract
           【申請專利範圍】請求項 N：… → claims
           公開日：…（西元 YYYY-MM-DD）→ publication_date
           everything else            → spec_text

Usage:
    export INTERNAL_TOKEN=...   # the AI Engine's X-Internal-Token (from .env)
    python scripts/import_patents.py --tenant tenant_a --dir /path/to/patents
    python scripts/import_patents.py --tenant tenant_a --dir data/cases --recursive --dry-run

Behaviour contract:
  * one bad file/record NEVER aborts the batch — failures are collected and
    listed at the end;
  * exit 0 when every record indexed (or validated, with --dry-run),
    exit 1 when any record failed, exit 2 for usage errors (bad --dir).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

DEFAULT_ENGINE_URL = os.getenv("AI_ENGINE_URL", "http://localhost:8011")

_KNOWN_JURISDICTIONS = ("TW", "US", "JP", "EP", "CN", "KR")

# --- TIPO 公報-style text parsing -------------------------------------------

_RE_PUB_NO = re.compile(r"公[開告]編號[:：]\s*([A-Z]{2}[A-Z0-9]+)")
_RE_HEADER_NO = re.compile(r"^\[[^\]]*公報\]\s*([A-Z]{2}[A-Z0-9]+)", re.M)
_RE_TITLE = re.compile(r"【名稱】\s*(.+)")
_RE_WESTERN_DATE = re.compile(r"西元\s*(\d{4}-\d{2}-\d{2})")
_RE_ISO_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_RE_CLAIM = re.compile(r"^請求項\s*\d+\s*[:：]\s*(.+)$", re.M)
_RE_SECTION = re.compile(r"【([^】]+)】")


def _section(text: str, name: str) -> str:
    """Return the body of a 【name】 section (up to the next 【…】 or EOF)."""
    m = re.search(rf"【{re.escape(name)}】\s*", text)
    if not m:
        return ""
    rest = text[m.end() :]
    nxt = _RE_SECTION.search(rest)
    return (rest[: nxt.start()] if nxt else rest).strip()


def parse_tipo_txt(text: str, *, default_jurisdiction: str | None = None) -> tuple[dict, list[str]]:
    """Parse a TIPO 公報-style text file into the /v1/index/patent payload.

    Returns ``(payload, warnings)``. Raises ``ValueError`` when the document
    is missing the load-bearing fields (patent_no / title) — that record is a
    batch error, not a crash.
    """
    warnings: list[str] = []

    m = _RE_PUB_NO.search(text) or _RE_HEADER_NO.search(text)
    if not m:
        raise ValueError("no patent number found (公開編號 / [公開公報] header)")
    patent_no = m.group(1)

    tm = _RE_TITLE.search(text)
    if not tm:
        raise ValueError("no 【名稱】 title section")
    title = tm.group(1).strip()

    abstract = _section(text, "摘要")
    if not abstract:
        warnings.append("no 【摘要】 abstract — indexing without one")

    claims_block = _section(text, "申請專利範圍")
    claims = [c.strip() for c in _RE_CLAIM.findall(claims_block)] if claims_block else []
    if not claims and claims_block:
        # Claims section exists but no 請求項 N： lines — keep the raw block as
        # one claim rather than silently dropping the legal heart of the doc.
        claims = [claims_block]
    if not claims:
        warnings.append("no 【申請專利範圍】 claims found")

    dm = _RE_WESTERN_DATE.search(text)
    if dm:
        publication_date = dm.group(1)
    else:
        line = next((ln for ln in text.splitlines() if "公開日" in ln or "公告日" in ln), "")
        im = _RE_ISO_DATE.search(line)
        if im:
            publication_date = im.group(1)
        else:
            publication_date = "1970-01-01"
            warnings.append("no parsable publication date — defaulting to 1970-01-01")

    jurisdiction = patent_no[:2] if patent_no[:2] in _KNOWN_JURISDICTIONS else None
    if jurisdiction is None:
        jurisdiction = default_jurisdiction or "TW"
        warnings.append(
            f"jurisdiction not derivable from patent_no {patent_no!r} — using {jurisdiction}"
        )

    # spec_text: the descriptive body. Strip the claims section (indexed as
    # structured claims already) but keep everything else verbatim so the
    # rag.py chunker sees the same prose an attorney would.
    spec_text = text
    cs = re.search(r"【申請專利範圍】", spec_text)
    if cs:
        spec_text = spec_text[: cs.start()].rstrip()

    return (
        {
            "patent_no": patent_no,
            "title": title,
            "abstract": abstract or title,
            "claims": claims,
            "publication_date": publication_date,
            "jurisdiction": jurisdiction,
            "is_local": False,
            "spec_text": spec_text,
        },
        warnings,
    )


# --- JSON parsing ------------------------------------------------------------

_REQUIRED_JSON_FIELDS = ("patent_no", "title", "abstract", "claims", "publication_date")


def parse_json_records(text: str) -> list[dict]:
    """Parse a .json file into a list of payload dicts (object or array)."""
    data = json.loads(text)
    records = data if isinstance(data, list) else [data]
    out = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise ValueError(f"record #{i} is not an object")
        missing = [f for f in _REQUIRED_JSON_FIELDS if not rec.get(f)]
        if missing:
            raise ValueError(f"record #{i} ({rec.get('patent_no', '?')}) missing: {missing}")
        if not isinstance(rec["claims"], list):
            raise ValueError(f"record #{i} 'claims' must be a list")
        rec.setdefault("jurisdiction", "TW")
        rec.setdefault("is_local", False)
        rec.setdefault("spec_text", "")
        out.append(rec)
    return out


# --- batch runner --------------------------------------------------------------


@dataclass
class ImportResult:
    indexed: list[dict] = field(default_factory=list)  # {file, patent_no, chunks}
    errors: list[dict] = field(default_factory=list)  # {file, patent_no?, error}
    warnings: list[dict] = field(default_factory=list)  # {file, warning}


def _collect_files(root: Path, recursive: bool) -> list[Path]:
    it = root.rglob("*") if recursive else root.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in (".json", ".txt"))


def run_import(
    *,
    tenant: str,
    src_dir: Path,
    engine_url: str,
    internal_token: str,
    dry_run: bool,
    recursive: bool,
    default_jurisdiction: str | None,
    timeout: float = 60.0,
) -> ImportResult:
    result = ImportResult()
    files = _collect_files(src_dir, recursive)
    if not files:
        result.errors.append({"file": str(src_dir), "error": "no .json or .txt files found"})
        return result

    headers = {"X-Internal-Token": internal_token} if internal_token else {}
    url = f"{engine_url.rstrip('/')}/v1/index/patent"

    with httpx.Client(timeout=timeout) as client:
        for path in files:
            rel = str(path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                result.errors.append({"file": rel, "error": f"read failed: {exc}"})
                continue

            try:
                if path.suffix.lower() == ".json":
                    payloads = parse_json_records(text)
                else:
                    payload, warns = parse_tipo_txt(text, default_jurisdiction=default_jurisdiction)
                    payloads = [payload]
                    for w in warns:
                        result.warnings.append({"file": rel, "warning": w})
            except (ValueError, json.JSONDecodeError) as exc:
                result.errors.append({"file": rel, "error": f"parse failed: {exc}"})
                continue

            for payload in payloads:
                payload["tenant_id"] = tenant  # --tenant always wins
                patent_no = payload.get("patent_no", "?")
                if dry_run:
                    result.indexed.append({"file": rel, "patent_no": patent_no, "chunks": None})
                    continue
                try:
                    r = client.post(url, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    result.errors.append(
                        {"file": rel, "patent_no": patent_no, "error": f"http: {exc}"}
                    )
                    continue
                if r.status_code != 200:
                    result.errors.append(
                        {
                            "file": rel,
                            "patent_no": patent_no,
                            "error": f"HTTP {r.status_code}: {r.text[:300]}",
                        }
                    )
                    continue
                chunks = r.json().get("chunks_indexed")
                result.indexed.append({"file": rel, "patent_no": patent_no, "chunks": chunks})

    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="import_patents.py",
        description="Bulk-import patents (.json / TIPO-style .txt) into the per-tenant RAG index.",
    )
    parser.add_argument("--tenant", required=True, help="tenant_id to index under (e.g. tenant_a)")
    parser.add_argument("--dir", required=True, help="folder containing .json / .txt patent files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse + validate only; no requests are sent to the AI Engine",
    )
    parser.add_argument("--recursive", action="store_true", help="recurse into sub-folders")
    parser.add_argument(
        "--engine-url",
        default=DEFAULT_ENGINE_URL,
        help=f"AI Engine base URL (default: $AI_ENGINE_URL or {DEFAULT_ENGINE_URL})",
    )
    parser.add_argument(
        "--jurisdiction",
        default=None,
        help="fallback jurisdiction for .txt files whose patent_no prefix is not recognised",
    )
    parser.add_argument(
        "--csv",
        default=None,
        metavar="PATH",
        help="also write a (file, patent_no, chunks_indexed, status) CSV report",
    )
    args = parser.parse_args(argv)

    src = Path(args.dir)
    if not src.is_dir():
        print(f"error: --dir {src} is not a directory", file=sys.stderr)
        return 2

    # The AI Engine refuses requests without a matching X-Internal-Token
    # whenever INTERNAL_TOKEN is configured server-side. Read it from the
    # environment (source your .env first); never passed on the CLI so it
    # can't leak into shell history / process listings.
    internal_token = os.getenv("INTERNAL_TOKEN", "")
    if not internal_token and not args.dry_run:
        print(
            "warning: INTERNAL_TOKEN is not set — only an unsecured (local mock) "
            "AI Engine will accept these requests.",
            file=sys.stderr,
        )

    result = run_import(
        tenant=args.tenant,
        src_dir=src,
        engine_url=args.engine_url,
        internal_token=internal_token,
        dry_run=args.dry_run,
        recursive=args.recursive,
        default_jurisdiction=args.jurisdiction,
    )

    verb = "validated" if args.dry_run else "indexed"
    for row in result.indexed:
        chunks = "" if row["chunks"] is None else f" ({row['chunks']} chunks)"
        print(f"  ok   {row['patent_no']}{chunks}  <- {row['file']}")
    for row in result.warnings:
        print(f"  warn {row['file']}: {row['warning']}")

    if result.errors:
        print(f"\n{len(result.errors)} FAILED (batch continued past each):", file=sys.stderr)
        for row in result.errors:
            who = f" {row['patent_no']}" if row.get("patent_no") else ""
            print(f"  fail{who} {row['file']}: {row['error']}", file=sys.stderr)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "patent_no", "chunks_indexed", "status"])
            for row in result.indexed:
                w.writerow([row["file"], row["patent_no"], row["chunks"], "ok"])
            for row in result.errors:
                w.writerow([row["file"], row.get("patent_no", ""), "", row["error"]])

    print(
        f"\nDone: {len(result.indexed)} {verb}, {len(result.errors)} failed, "
        f"{len(result.warnings)} warnings (tenant={args.tenant})."
    )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
