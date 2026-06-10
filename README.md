# PatentMind AI

> **A reference architecture for secure, audited LLM pipelines in regulated
> domains — demonstrated on patent Office Action (OA) response.**

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Node 20+](https://img.shields.io/badge/node-20%2B-green)](frontend/package.json)
[![Status: PoC](https://img.shields.io/badge/status-proof--of--concept-orange)](#status)

*NCCU GDGoC × Computex 2026 · [繁體中文 README](README.zh-TW.md)*

PatentMind semi-automates the drafting of patent OA responses **without ever
letting client data leak to a public LLM** — and makes every AI claim
verifiable, every action auditable, and the attorney accountable for the final
draft. The interesting part for most people isn't the patent workflow; it's the
**security/trust gateway pattern** underneath it, which applies to any
AI feature handling confidential, compliance-sensitive data.

---

## Why it exists

Law firms answering a patent Office Action today, by hand:

- **Slow** — reading the OA, finding prior art, and writing the response is
  **8–12 hours per case**.
- **Hallucination risk** — citing the wrong statute or a fabricated case is a
  professional-liability event.
- **Deadline risk** — miscalculating the statutory deadline can forfeit the
  patent. There is no undo.
- **Confidentiality** — client matter data must never go to a public LLM, which
  is exactly why firms can't just paste it into ChatGPT.

PatentMind addresses all four — and the attorney still signs off on every
sentence.

## What makes it different (the trust layer)

These are enforced **invariants**, not features you can toggle off
(see [`CLAUDE.md` §4](CLAUDE.md)):

| Guarantee | How |
|---|---|
| 🛡️ **No data leak** | Mandatory PII/customer redaction before *any* LLM call; reversal map stays on-prem |
| 🏠 **Confidential → local** | Confidential cases auto-route to an on-prem LLM, never the cloud |
| 🎯 **No hallucinated citations** | Two-stage generate→verify; citations not in the grounded set are stripped, and the UI shows *what* was stripped + which model verified |
| 🧾 **Tamper-evident audit** | Every request writes exactly one append-only, hash-chained audit row — user-verifiable, not vendor-attested |
| 👤 **Per-case access control** | `case_id` ACL checked on every request; multi-tenant isolation |
| ✍️ **Human accountability** | Sentence-level provenance (AI / paralegal / attorney) + a hard attorney sign-off gate before export |

A general-purpose chatbot can't offer the first five. That's the moat.

## Quickstart

Prerequisites: **Python 3.11+**, **Node 20+**. Runs fully in **mock mode** — no
API keys required.

```bash
# Backend (full POC) — gateway :8010 + ai_engine :8011, seeds demo data
bash scripts/start_backend.sh

# End-to-end verification — must print "ALL CHECKS PASSED"
bash scripts/verify.sh

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Demo login passwords are `demo-<user>` (e.g. `demo-alice`); see `.env.example`.

## Try it (decision → demo)

| Try | Action | What to watch |
|---|---|---|
| Case ACL (Q12) | Log in as Carol → analyze `CASE-2025-001` | 403 — Carol isn't on that case |
| Redaction (Q10) | Alice → "Preview redaction" | email / phone / case-no replaced with placeholders |
| Grounded cites (Q14) | Run analysis → open a `[GROUNDED_REF_1]` pill | shows source patent + section + text; unverified cites shown as removed |
| Sign-off (Q16) | Accept/Edit each sentence in the draft | purple = AI, green = attorney; export gated until all signed |
| Audit (Q13) | Log in as Dave → Audit page | mask-rule log + green "verify hash chain" |
| Confidential routing (Q15) | Re-run with a `-CONF` case_id | audit row's model flips to the local model |
| Cache (Q9) | Analyze the same OA + case twice | 2nd audit row: model=`cache`, tokens=0 |
| Deadline (Q17) | See the deadline → click "Why" | weekend/holiday roll-forward, with the calculation basis |

## Architecture

```
Vite SPA  ──/api──▶  [optional: digiRunner OSS :18080 front-line gateway]
                       │
                       ▼
                     Gateway :8010  ("thick" gateway)
                       ├─ Auth (Q12)         JWT + case_id ACL + revocation/logout
                       ├─ RateLimit (Q18)    RPM + quota + cost circuit breaker
                       ├─ Mask (Q3+Q10)      regex + dict, reversible on-prem
                       ├─ Cache (Q9)         tenant:user:case scoped
                       ├─ Orchestrator (Q1)  6-step business flow
                       └─ Audit (Q13)        append-only + hash chain
                       │  HTTP (intra-VPC)
                       ▼
                  AI Engine :8011  (single-step inference, no business state)
                       ├─ parse_oa (Q11)  ├─ retrieve (Q6+Q7)  ├─ draft (Q14)
                       ├─ verify (Q14)    └─ deadline (Q17)
                       └─ llm_client (Q15 router: mock | anthropic | local | dify)
                       │  LLM_MODE=dify
                       ▼
                  Dify CE :8088  (patentmind-analyze-oa workflow → Ollama qwen2.5:7b)
```

**Real digiRunner + Dify integration** (delivered 2026-06-11): the stack runs
behind [digiRunner OSS](https://github.com/TPIsoftware/digirunner-open-source)
with auto-registered routes (`bash scripts/start_digirunner.sh`), and AI
inference flows through a self-hosted Dify CE workflow on local Ollama
(`python scripts/setup_dify.py`, then `LLM_MODE=dify`). The citation verifier
(Q14) stays in our code as the un-bypassable hard wall. See
[`docs/DELIVERY_RUNBOOK.md`](docs/DELIVERY_RUNBOOK.md).

Two rules keep the security boundary clean: **the gateway never calls an LLM
directly**, and **the AI engine holds no business state**. Full decision→code
map in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Tech stack

FastAPI · React 18 + Vite · TanStack Query · Tailwind · react-i18next (zh-TW/EN)
· Playwright + pytest. Vector store / cache / LLM are abstracted so mock ↔
production swaps by env (`LLM_MODE`, `VECTOR_BACKEND`, `CACHE_BACKEND`).

## Documentation

- [`docs/DECISIONS.md`](docs/DECISIONS.md) — the 20 architectural decisions (read first)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — each decision → which code, and why
- [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) — security self-audit
- [`CLAUDE.md`](CLAUDE.md) — agent/maintainer handoff + hardening TODO list

## Demo accounts

| User | Role | Tenant | Cases | Use |
|---|---|---|---|---|
| `alice` | attorney | tenant_a | CASE-2025-001..003 | analyze, sign off |
| `bob` | paralegal | tenant_a | CASE-2025-001..002 | analyze, assist drafting |
| `carol` | it_admin | tenant_b | (none) | dashboard, quota |
| `audit_dave` | auditor | tenant_a | * | audit, verify chain |

## Status

This is a **proof of concept**. It is **not safe to expose beyond localhost**
without the hardening in [`SECURITY.md`](SECURITY.md) and [`CLAUDE.md`](CLAUDE.md)
§3/§5. Mocked/stubbed for now: real LLM backend, Qdrant, Redis, OIDC/SAML,
S3 Object Lock audit archive, Redis-backed JWT revocation + RS256. Changes are
tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Contributing & security

- Start with [CONTRIBUTING.md](CONTRIBUTING.md) and our
  [Code of Conduct](CODE_OF_CONDUCT.md).
- **Never commit real, unpublished, or personally-identifiable patent data** —
  all fixtures are synthetic (`data/cases/`). This is the very problem the
  project exists to solve.
- Report vulnerabilities privately per [SECURITY.md](SECURITY.md) — do not open
  a public issue.

## License

[Apache License 2.0](LICENSE) — free to use, modify, and distribute, with an
explicit patent grant.
