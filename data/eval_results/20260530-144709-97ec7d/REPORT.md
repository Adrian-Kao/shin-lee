# PatentMind eval — 20260530-144709

Mode: mock
Cases: 1 (1 complete, 0 failed to execute)
Concurrency: 4
Wall time: 0.0s
Total tokens: input=3711 output=1199 (mock mode = 0 real tokens)
Estimated cost: $0.03 (mock = $0 actual)

## Classification accuracy

|                          | Pass | Fail | Rate  |
|--------------------------|------|------|-------|
| rejection_type           |    1 |    0 | 100.0% |
| affected_claims (per rej)|    1 |    0 | 100.0% |
| received_date            |    1 |    0 | 100.0% |
| deadline                 |    1 |    0 | 100.0% |

## Per-rejection-type breakdown

| Type                | Count | Pass rate | Mean confidence |
|---------------------|-------|-----------|-----------------|
| antecedent_basis    |     1 |   100.0% |            0.93 |

## Per-case detail

| case_id       | rej_pred                  | rej_expected              | OK | deadline           | draft_lines | tokens | latency |
|---------------|---------------------------|---------------------------|----|--------------------|-------------|--------|---------|
| CASE-DEMO-001 | antecedent_basis          | antecedent_basis          | OK | 2025-07-28         |           9 |   4910 |   0.02s |

