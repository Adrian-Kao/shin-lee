<!--
Thanks for contributing! Keep PRs to one logical change. See CONTRIBUTING.md.
Never commit real/unpublished/PII patent data — fixtures must be synthetic.
-->

## What & why

<!-- What does this change and what problem does it solve? Link issues: Closes #N -->

## Security / invariant impact

<!-- Required, even if "none". Does it touch any CLAUDE.md §4 invariant
     (redaction, grounded verifier, audit row, case_id ACL, confidential
     routing, quota/cost gate, tenant isolation, AI-engine statelessness)?
     How is the invariant preserved? -->

## How tested

- [ ] `ruff check .`
- [ ] `pytest tests/unit tests/integration -v` (env: `LLM_MODE=mock VECTOR_BACKEND=memory EMBEDDING_BACKEND=mock CACHE_BACKEND=memory`)
- [ ] `bash scripts/verify.sh` prints **ALL CHECKS PASSED**
- [ ] Frontend: `npm run build` + `npx playwright test` (if frontend changed)
- [ ] Added/updated tests for the change

## Checklist

- [ ] No real / unpublished / PII data added (all fixtures synthetic)
- [ ] Docs updated if behaviour changed (`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `CHANGELOG.md`)
- [ ] One logical change; diff is reviewable
