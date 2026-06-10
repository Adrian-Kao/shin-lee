# Eval playbook (mock vs real Anthropic)

This playbook is the runbook for the morning your `ANTHROPIC_API_KEY` arrives.
The eval infrastructure is already in place; this doc is what you read to
exercise it the first time.

## When you wake up tomorrow

1. **Set the key.**
   ```bash
   echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
   set -a; source .env; set +a   # or `export ANTHROPIC_API_KEY=...`
   ```

2. **Sanity check (~30 sec, ~$0.02).**
   ```bash
   python scripts/anthropic_smoke.py
   ```
   This:
   - Asserts the SDK + key work end-to-end against one short prompt
   - Asserts prompt caching fires on a second call (the single biggest cost lever)
   - Asserts our pricing table matches the reported usage
   - Asserts the confidential-routing guard refuses to call cloud for confidential cases

   If it fails, see [troubleshooting](#troubleshooting). Do NOT proceed
   to step 3 until the smoke passes.

3. **Generate the mock baseline (~0.5s, $0).**
   ```bash
   python scripts/eval_cases.py --mode mock
   # Save the output dir from the last line of stdout.
   ```

4. **Generate the real Anthropic run (~5 min, ~$2-5).**
   ```bash
   python scripts/eval_cases.py --mode anthropic
   # Will prompt for confirmation if estimated cost > $5.
   ```

5. **Compare.**
   ```bash
   python scripts/eval_compare.py <mock_dir> <anthropic_dir>
   # Then: open data/eval_compare/.../COMPARE.md
   ```

6. **Read [the interpretation guide](#interpreting-the-delta).**

## Interpreting the delta

The comparator renders five things. Read them in order.

### 1. Aggregate metrics table

| Metric | What "healthy" looks like |
|---|---|
| `rejection_type accuracy` | mock ≈ 100% on this corpus (regex parser was tuned to it). Real Anthropic should also hit ≥95%. Lower → prompt regression risk. |
| `affected_claims accuracy` | mock ≈ 73% (known limitation — regex parser drops claim sets in some range-list constructions). Real Anthropic should hit ≥90%. |
| `received_date accuracy` | mock = 100%. Real should also be 100% — these are extracted by a separate deterministic parser, not the LLM. If this drops, something else broke. |
| `deadline accuracy` | mock = 100%. Same as above — deterministic post-processing. |
| `total cost` | mock = $0 (synthetic). Real Anthropic on 30 cases ≈ $2-5 with caching. >$8 ⇒ caching not firing. |

### 2. Per-case detail table

Spot-check 3-5 rows:
- Did real-mode rejection types match mock-mode predictions?
- Are claims counts similar? (Real should be ≥ mock.)
- Per-case cost should be $0.05-0.15. Anything over $0.30 ⇒ either a giant
  OA spec was sent uncached, or caching missed.

### 3. Per-rejection-type breakdown

This is the most useful debugging surface. If `103_obviousness` drops from
82% to 50%, you know which prompt template to revise (in
`backend/ai_engine/prompts/`).

### 4. Most improved cases / Regressions

Top 5 of each. The regression list is the heart of the comparator —
these are cases where the real Anthropic run did *worse* than the mock.

If real is worse than mock on a metric, it usually means one of:

- The prompt YAML drifted (compare git history of `backend/ai_engine/prompts/`).
- Anthropic shipped a model update (e.g. `claude-sonnet-4-6` → 4-7? — check Anthropic release notes).
- A specific case's OA text contains an adversarial pattern the model overreads.

### 5. Cost projection

Linearly extrapolated from your run. The brief target:

- ~$0.06-0.10 per case with caching = $60-100/month at 1k OAs.
- ~$0.15+ per case ⇒ caching NOT firing → check the system-prompt block in
  `backend/ai_engine/llm_client.py:AnthropicLLM.achat`.

The `note:` field tells you the cost-figure trustworthiness:
- `exact` — every model resolved against the pricing table.
- `fallback` — at least one model fell through to the conservative default
  (likely a future model not yet in the table).
- `mock` — at least one model was the synthetic mock variant; cost is not
  real money.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Authentication failed` / 401 | Check `ANTHROPIC_API_KEY` is exported (not just in `.env`); no surrounding quotes on the value; key starts with `sk-ant-`. |
| `Rate limited` / 429 | New Anthropic accounts default to 5 RPM. Either request a tier bump or pass `--concurrency 1` to `eval_cases.py`. |
| `Internal token mismatch` / AI engine refuses | Day 8F locked the AI engine front door. Either set `INTERNAL_TOKEN` env to match the gateway's value, or use `LLM_MODE=mock` (which has a permit rule for this case). For the eval harness, the in-process ASGI transport bypasses HTTP entirely so this only bites when running the gateway + AI engine as separate services. |
| `Confidential case routed to cloud` | Bug — file a regression. The `AnthropicLLM.achat` guard should have raised before any network call. The smoke test specifically exercises this assertion. |
| Smoke test exit 4 (cache) | Caching is not firing on the second call. Most likely the `cache_control: ephemeral` block got dropped from the system prompt. Inspect `backend/ai_engine/llm_client.py:AnthropicLLM.achat`. |
| Smoke test exit 5 (pricing) | The model returned by Anthropic doesn't match a row in `backend/gateway/rate_limit.py:_MODEL_PRICING_USD_PER_M`. Add a row with the current public-list price. |
| Smoke test exit 6 (confidential) | The cloud-LLM guard is not firing. Search for `LOCAL_LLM_FOR_SECURITY_LEVELS` in `llm_client.py` — the check must run before any `_call_with_retry`. |
| Smoke test exits 0 with "SKIP" | Expected when `ANTHROPIC_API_KEY` is unset; the test is a no-op in that case so it's CI-safe. |

## Artefact reference

After a full run you have:

```
data/
├── eval_results/
│   ├── 20260605-093000-aaa111/    # mock baseline
│   │   ├── CASE-DEMO-001.json
│   │   ├── ... (30 case files)
│   │   ├── REPORT.md              # human-facing per-run report
│   │   └── summary.json           # machine-facing per-run metrics
│   └── 20260605-100000-bbb222/    # anthropic run, same shape
└── eval_compare/
    └── 20260605-103000-ccc333/    # comparison output
        ├── COMPARE.md             # side-by-side delta report
        └── per_case_delta.json    # machine-facing diff for downstream tooling
```

`summary.json` is the contract that `eval_compare.py` consumes. If you
ever extend `eval_cases.py` to capture new metrics, add them as new keys
in `build_summary()` — never remove an existing key (the comparator does
forwards-compat reads with `.get()`).
