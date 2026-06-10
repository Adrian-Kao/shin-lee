# PatentMind eval — 20260530-164557

Mode: mock
Cases: 30 (30 complete, 0 failed to execute)
Concurrency: 4
Wall time: 0.3s
Total tokens: input=124122 output=17971 (mock mode = 0 real tokens)
Estimated cost: $0.64 (mock = $0 actual)

## Classification accuracy

|                          | Pass | Fail | Rate  |
|--------------------------|------|------|-------|
| rejection_type           |   30 |    0 | 100.0% |
| affected_claims (per rej)|   25 |    9 | 73.5% |
| received_date            |   30 |    0 | 100.0% |
| deadline                 |   30 |    0 | 100.0% |

## Per-rejection-type breakdown

| Type                | Count | Pass rate | Mean confidence |
|---------------------|-------|-----------|-----------------|
| 101_subject_matter  |     1 |   100.0% |            0.86 |
| 102_novelty         |     5 |   100.0% |            0.90 |
| 103_obviousness     |    17 |    82.4% |            0.88 |
| antecedent_basis    |     6 |     0.0% |            0.93 |
| other               |     5 |   100.0% |            0.84 |

## Per-case detail

| case_id       | rej_pred                  | rej_expected              | OK | deadline           | draft_lines | tokens | latency |
|---------------|---------------------------|---------------------------|----|--------------------|-------------|--------|---------|
| CASE-DEMO-001 | antecedent_basis          | antecedent_basis          | OK | 2025-07-28         |           9 |   4921 |   0.06s |
| CASE-DEMO-002 | 103_obviousness           | 103_obviousness           | OK | 2025-08-14         |           1 |   4328 |   0.05s |
| CASE-DEMO-003 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2025-06-09         |          10 |   8230 |   0.05s |
| CASE-DEMO-004 | 102_novelty               | 102_novelty               | OK | 2025-10-07         |           1 |   3963 |   0.05s |
| CASE-DEMO-005 | 103_obviousness           | 103_obviousness           | OK | 2026-02-06         |           1 |   4015 |   0.02s |
| CASE-DEMO-006 | other                     | other                     | OK | 2025-11-17         |           1 |   4314 |   0.05s |
| CASE-DEMO-007 | 103_obviousness           | 103_obviousness           | OK | 2024-11-11         |           1 |   4263 |   0.03s |
| CASE-DEMO-008 | 103_obviousness           | 103_obviousness           | OK | 2026-03-10         |           1 |   4093 |   0.03s |
| CASE-DEMO-009 | other                     | other                     | OK | 2025-09-22         |           1 |   3970 |   0.03s |
| CASE-DEMO-010 | 103_obviousness           | 103_obviousness           | OK | 2025-05-27         |           1 |   4313 |   0.02s |
| CASE-DEMO-011 | 102_novelty               | 102_novelty               | OK | 2026-04-13         |           1 |   4124 |   0.01s |
| CASE-DEMO-012 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2025-01-14         |          10 |   8324 |   0.05s |
| CASE-DEMO-013 | 101_subject_matter        | 101_subject_matter        | OK | 2025-07-07         |           1 |   4114 |   0.05s |
| CASE-DEMO-014 | 103_obviousness           | 103_obviousness           | OK | 2025-10-20         |           1 |   4226 |   0.05s |
| CASE-DEMO-015 | antecedent_basis          | antecedent_basis          | OK | 2026-01-26         |           9 |   4918 |   0.03s |
| CASE-DEMO-016 | 103_obviousness           | 103_obviousness           | OK | 2025-04-21         |           1 |   4012 |   0.02s |
| CASE-DEMO-017 | other                     | other                     | OK | 2025-12-15         |           1 |   4303 |   0.03s |
| CASE-DEMO-018 | 103_obviousness           | 103_obviousness           | OK | 2026-05-06         |           1 |   4230 |   0.02s |
| CASE-DEMO-019 | 102_novelty               | 102_novelty               | OK | 2025-07-14         |           1 |   3947 |   0.03s |
| CASE-DEMO-020 | 103_obviousness           | 103_obviousness           | OK | 2026-04-28         |           1 |   4086 |   0.03s |
| CASE-DEMO-021 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2025-08-29         |          10 |   7861 |   0.03s |
| CASE-DEMO-022 | 102_novelty               | 102_novelty               | OK | 2026-03-18         |           1 |   4232 |   0.02s |
| CASE-DEMO-023 | 103_obviousness           | 103_obviousness           | OK | 2025-06-24         |           1 |   4246 |   0.03s |
| CASE-DEMO-024 | 103_obviousness           | 103_obviousness           | OK | 2026-04-06         |           1 |   4137 |   0.02s |
| CASE-DEMO-025 | other                     | other                     | OK | 2025-09-08         |           1 |   3955 |   0.03s |
| CASE-DEMO-026 | 103_obviousness           | 103_obviousness           | OK | 2025-03-24         |           1 |   4121 |   0.02s |
| CASE-DEMO-027 | 102_novelty               | 102_novelty               | OK | 2025-04-08         |           1 |   4145 |   0.03s |
| CASE-DEMO-028 | 103_obviousness           | 103_obviousness           | OK | 2026-05-14         |           1 |   4472 |   0.01s |
| CASE-DEMO-029 | antecedent_basis          | antecedent_basis          | OK | 2026-03-31         |           9 |   4937 |   0.03s |
| CASE-DEMO-030 | 103_obviousness,other     | 103_obviousness,other     | OK | 2025-01-06         |           2 |   7293 |   0.03s |

## Worst-performing cases (top 5)

### CASE-DEMO-003
- Claims mismatch: 0/2 rejections had exact claim sets
- Latency: 0.05s
- Tokens: 8230

### CASE-DEMO-021
- Claims mismatch: 0/2 rejections had exact claim sets
- Latency: 0.03s
- Tokens: 7861

### CASE-DEMO-001
- Claims mismatch: 0/1 rejections had exact claim sets
- Latency: 0.06s
- Tokens: 4921

### CASE-DEMO-012
- Claims mismatch: 1/2 rejections had exact claim sets
- Latency: 0.05s
- Tokens: 8324

### CASE-DEMO-015
- Claims mismatch: 0/1 rejections had exact claim sets
- Latency: 0.03s
- Tokens: 4918

