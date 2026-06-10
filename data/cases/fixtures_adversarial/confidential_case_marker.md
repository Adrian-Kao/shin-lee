# confidential_case_marker.txt

## What it tests
A case tagged `CASE-2025-001-CONF` — the `-CONF` suffix is the documented
signal for the orchestrator to route to a LOCAL LLM only (Q15
`LOCAL_LLM_FOR_SECURITY_LEVELS`). The OA also contains tempting PII
(home phone, SSN) and strategic notes that must NEVER leave the
on-prem deployment.

## Expected behavior
- A user without `-CONF` in their `_CASE_ACL` set:
  POST `/v1/oa/upload` with `X-Case-Id: CASE-2025-001-CONF` →
  **403** ("Confidential case requires manual text" or similar policy
  message — current behavior in `backend/gateway/main.py`).
- A user with the ACL entry granted (test-only) AND `LLM_MODE=mock` →
  the orchestrator dispatches to the `local` model (mock router treats
  `-CONF` suffix as `security_level=confidential`).
- The audit row's `policy_decisions` should include
  `confidential_routing=True` and `model_used` should be the local
  model name.

## Consumed by
- `tests/integration/test_adversarial_inputs.py::test_confidential_case_upload_rejected_403`
