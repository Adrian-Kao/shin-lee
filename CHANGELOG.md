# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Status: **Proof of Concept.** APIs, schemas, and behaviour may change without
> a major-version bump while the project is pre-1.0.

## [Unreleased]

### Added
- **Open-source readiness**: `LICENSE` (Apache-2.0), `NOTICE`, `CONTRIBUTING.md`,
  `SECURITY.md`, `CODE_OF_CONDUCT.md`, GitHub issue / PR templates.
- **JWT lifecycle hardening (security H-5)**: issuer/audience (`iss`/`aud`)
  pinning, a `jti` revocation list, and `POST /v1/auth/logout` (kill switch);
  magic-link vs session token separation enforced in `verify_token`.
- **Verifier transparency**: `DraftResponse` now carries `invalid_citations`,
  `verifier_confidence`, and `verifier_model`, surfaced in the UI as a
  hallucination-defense panel (what the verifier stripped + which model vetted).
- **Multi-person provenance**: `paralegal_edited` / `paralegal_added` provenance
  sources so the responsibility chain (paralegal drafts → attorney signs) is
  visible per sentence and counted separately in the export summary + audit row.
- **Frontend**: deadline calculation is now explainable (roll-forward reason,
  recommended internal deadline, holiday-calendar version); full i18n coverage
  of the analyze flow with a working zh-TW / EN switcher; dark mode (theme
  toggle + `dark:` variants across the app).
- **Frontend architecture**: TanStack Query server-state layer (cache, retry,
  de-dupe) — the audit chain-verify request is now shared between the AppShell
  chip and the AuditView page instead of being issued twice.

### Fixed
- Test isolation: a unit test reloaded `backend.shared.config` in-process,
  desynchronising the `settings` singleton and causing order-dependent failures
  across the suite (passed alone, failed together). Now reads a fresh `Settings`
  instance instead of reloading the module.
- Documentation: corrected stale gateway/AI-engine ports (`:8000`/`:8001` →
  `:8010`/`:8011`) to match `scripts/start_backend.sh`.

### Security
- See `docs/SECURITY_AUDIT.md` for the full self-audit. As of this changelog,
  the original 4 Critical + 8 High findings are closed except H-5 (now also
  addressed here for the POC; production still needs Redis-backed revocation
  and RS256 — tracked in that document).

## [0.2.0]

- POC baseline: end-to-end gateway → AI-engine flow (mock backends), the 20
  architectural decisions in `docs/DECISIONS.md` each backed by runnable code,
  and the React SPA (login → analyze → sign-off → audit). See `README.md`.
