# Security Policy

PatentMind AI is a reference architecture for **secure, audited LLM pipelines
in regulated domains**. We take security reports seriously and appreciate
responsible disclosure.

## ⚠️ Project status: Proof of Concept

This repository is a **POC**. Several controls are intentionally mocked or
stubbed and are **not safe to expose beyond localhost** as-is. Notably:

- Demo login (`/v1/auth/login`) issues a JWT for any known demo user with **no
  password / no IdP** — it is a demo affordance, not authentication.
- The AI Engine (`:8001`) assumes a trusted intra-VPC caller.
- LLM, vector store, cache, and audit archive default to in-memory / mock.

A full self-audit with `file:line` evidence lives in
[`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md). The hardening checklist is
in [`CLAUDE.md`](CLAUDE.md) §3 and §5. **Do not deploy to a shared or public
network without completing that hardening.**

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, report privately via one of:

- **GitHub Security Advisories** — use the *"Report a vulnerability"* button
  under the repository's **Security** tab (preferred).
- **Email** the maintainers (see commit history / repository owner contact).

Please include:

- A description of the issue and the impact you believe it has.
- Steps to reproduce (a minimal PoC, `file:line` references, or a request
  sequence).
- Any suggested remediation, if you have one.

We aim to acknowledge reports within **5 business days** and to provide a
remediation timeline after triage. Please give us reasonable time to fix the
issue before any public disclosure.

## Scope

In scope:

- The eight design invariants in [`CLAUDE.md` §4](CLAUDE.md) — any bypass
  (redaction skip, ungrounded citation, missing audit row, cross-tenant leak,
  `case_id` ACL bypass, confidential-case routing to a cloud LLM, quota/cost
  circuit-breaker bypass).
- Authentication / authorization, tenant isolation, audit chain integrity,
  PII masking, prompt-injection escaping `<untrusted_input>`.

Out of scope (known POC limitations — already documented, not new findings):

- Mock auth / mock LLM / in-memory stores behaving as documented above.
- Anything already listed in [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md)
  (open a PR to fix instead).

## Handling sensitive data

This project exists *because* client patent data must never leak. Accordingly:

- **Never commit real or unpublished Office Actions, patents, examiner
  contact details, customer names, or secrets.** All fixtures must be
  synthetic (`data/cases/synthetic_cases.py`).
- If you discover sensitive data committed to the repo or its history, treat
  it as a security report and contact the maintainers privately so it can be
  scrubbed from history.
