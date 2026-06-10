# PatentMind eval — 20260605-023345

Mode: mock
Cases: 80 (80 complete, 0 failed to execute)
Concurrency: 4
Wall time: 1.3s
Total tokens: input=329552 output=49021 (mock mode = 0 real tokens)
Estimated cost: $1.72 (mock = $0 actual)

## Classification accuracy

|                          | Pass | Fail | Rate  |
|--------------------------|------|------|-------|
| rejection_type           |   77 |    3 | 96.2% |
| affected_claims (per rej)|   61 |   35 | 63.5% |
| received_date            |   80 |    0 | 100.0% |
| deadline                 |   80 |    0 | 100.0% |

## Per-rejection-type breakdown

| Type                | Count | Pass rate | Mean confidence |
|---------------------|-------|-----------|-----------------|
| 101_subject_matter  |     4 |    75.0% |            0.86 |
| 102_novelty         |    18 |    83.3% |            0.90 |
| 103_obviousness     |    37 |    75.7% |            0.88 |
| antecedent_basis    |    17 |     0.0% |            0.93 |
| other               |    20 |    75.0% |            0.84 |

## Per-case detail

| case_id       | rej_pred                  | rej_expected              | OK | deadline           | draft_lines | tokens | latency |
|---------------|---------------------------|---------------------------|----|--------------------|-------------|--------|---------|
| CASE-DEMO-001 | antecedent_basis          | antecedent_basis          | OK | 2025-07-28         |           9 |   4798 |   0.08s |
| CASE-DEMO-002 | 103_obviousness           | 103_obviousness           | OK | 2025-08-14         |           1 |   3960 |   0.08s |
| CASE-DEMO-003 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2025-06-09         |          10 |   7733 |   0.08s |
| CASE-DEMO-004 | 102_novelty               | 102_novelty               | OK | 2025-10-07         |           1 |   3931 |   0.08s |
| CASE-DEMO-005 | 103_obviousness           | 103_obviousness           | OK | 2026-02-06         |           1 |   4030 |   0.06s |
| CASE-DEMO-006 | other                     | other                     | OK | 2025-11-17         |           1 |   3947 |   0.06s |
| CASE-DEMO-007 | 103_obviousness           | 103_obviousness           | OK | 2024-11-11         |           1 |   4126 |   0.06s |
| CASE-DEMO-008 | 103_obviousness           | 103_obviousness           | OK | 2026-03-10         |           1 |   3932 |   0.08s |
| CASE-DEMO-009 | other                     | other                     | OK | 2025-09-22         |           1 |   4097 |   0.08s |
| CASE-DEMO-010 | 103_obviousness           | 103_obviousness           | OK | 2025-05-27         |           1 |   3923 |   0.09s |
| CASE-DEMO-011 | 102_novelty               | 102_novelty               | OK | 2026-04-13         |           1 |   4118 |   0.09s |
| CASE-DEMO-012 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2025-01-14         |          10 |   7705 |   0.08s |
| CASE-DEMO-013 | 101_subject_matter        | 101_subject_matter        | OK | 2025-07-07         |           1 |   3992 |   0.05s |
| CASE-DEMO-014 | 103_obviousness           | 103_obviousness           | OK | 2025-10-20         |           1 |   4101 |   0.06s |
| CASE-DEMO-015 | antecedent_basis          | antecedent_basis          | OK | 2026-01-26         |           9 |   4793 |   0.08s |
| CASE-DEMO-016 | 103_obviousness           | 103_obviousness           | OK | 2025-04-21         |           1 |   4092 |   0.09s |
| CASE-DEMO-017 | other                     | other                     | OK | 2025-12-15         |           1 |   3936 |   0.06s |
| CASE-DEMO-018 | 103_obviousness           | 103_obviousness           | OK | 2026-05-06         |           1 |   3947 |   0.05s |
| CASE-DEMO-019 | 102_novelty               | 102_novelty               | OK | 2025-07-14         |           1 |   3962 |   0.03s |
| CASE-DEMO-020 | 103_obviousness           | 103_obviousness           | OK | 2026-04-28         |           1 |   4315 |   0.05s |
| CASE-DEMO-021 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2025-08-29         |          10 |   7692 |   0.06s |
| CASE-DEMO-022 | 102_novelty               | 102_novelty               | OK | 2026-03-18         |           1 |   4277 |   0.08s |
| CASE-DEMO-023 | 103_obviousness           | 103_obviousness           | OK | 2025-06-24         |           1 |   3943 |   0.08s |
| CASE-DEMO-024 | 103_obviousness           | 103_obviousness           | OK | 2026-04-06         |           1 |   4147 |   0.05s |
| CASE-DEMO-025 | other                     | other                     | OK | 2025-09-08         |           1 |   4082 |   0.03s |
| CASE-DEMO-026 | 103_obviousness           | 103_obviousness           | OK | 2025-03-24         |           1 |   3915 |   0.05s |
| CASE-DEMO-027 | 102_novelty               | 102_novelty               | OK | 2025-04-08         |           1 |   4014 |   0.06s |
| CASE-DEMO-028 | 103_obviousness           | 103_obviousness           | OK | 2026-05-14         |           1 |   3918 |   0.08s |
| CASE-DEMO-029 | antecedent_basis          | antecedent_basis          | OK | 2026-03-31         |           9 |   4812 |   0.06s |
| CASE-DEMO-030 | 103_obviousness,other     | 103_obviousness,other     | OK | 2025-01-06         |           2 |   6770 |   0.05s |
| CASE-DEMO-031 | 103_obviousness           | 103_obviousness           | OK | 2026-04-15         |           1 |   4118 |   0.05s |
| CASE-DEMO-032 | 103_obviousness           | 103_obviousness           | OK | 2026-05-04         |           1 |   3995 |   0.05s |
| CASE-DEMO-033 | 103_obviousness           | 103_obviousness           | OK | 2026-06-11         |           1 |   3933 |   0.05s |
| CASE-DEMO-034 | 103_obviousness           | 103_obviousness           | OK | 2026-07-08         |           1 |   4103 |   0.06s |
| CASE-DEMO-035 | 103_obviousness           | 103_obviousness           | OK | 2025-11-17         |           1 |   4309 |   0.05s |
| CASE-DEMO-036 | 103_obviousness           | 103_obviousness           | OK | 2026-03-23         |           1 |   4068 |   0.06s |
| CASE-DEMO-037 | 103_obviousness           | 103_obviousness           | OK | 2026-08-03         |           1 |   4081 |   0.05s |
| CASE-DEMO-038 | 103_obviousness           | 103_obviousness           | OK | 2026-01-19         |           1 |   3939 |   0.05s |
| CASE-DEMO-039 | 103_obviousness           | 103_obviousness           | OK | 2026-02-09         |           1 |   4114 |   0.05s |
| CASE-DEMO-040 | 103_obviousness           | 103_obviousness           | OK | 2025-12-16         |           1 |   3965 |   0.05s |
| CASE-DEMO-041 | 102_novelty               | 102_novelty               | OK | 2026-04-29         |           1 |   3957 |   0.03s |
| CASE-DEMO-042 | 102_novelty               | 102_novelty               | OK | 2026-05-18         |           1 |   4156 |   0.05s |
| CASE-DEMO-043 | 102_novelty               | 102_novelty               | OK | 2025-12-08         |           1 |   3880 |   0.05s |
| CASE-DEMO-044 | 102_novelty               | 102_novelty               | OK | 2026-06-24         |           1 |   4213 |   0.06s |
| CASE-DEMO-045 | 102_novelty               | 102_novelty               | OK | 2026-07-21         |           1 |   4009 |   0.06s |
| CASE-DEMO-046 | 102_novelty               | 102_novelty               | OK | 2026-08-11         |           1 |   3909 |   0.05s |
| CASE-DEMO-047 | 102_novelty               | 102_novelty               | OK | 2026-08-26         |           1 |   3904 |   0.05s |
| CASE-DEMO-048 | 102_novelty               | 102_novelty               | OK | 2026-09-07         |           1 |   4006 |   0.03s |
| CASE-DEMO-049 | antecedent_basis          | antecedent_basis          | OK | 2026-06-08         |           9 |   4791 |   0.05s |
| CASE-DEMO-050 | antecedent_basis          | antecedent_basis          | OK | 2026-07-13         |           9 |   4790 |   0.05s |
| CASE-DEMO-051 | antecedent_basis          | antecedent_basis          | OK | 2026-08-05         |           9 |   4790 |   0.06s |
| CASE-DEMO-052 | 103_obviousness           | antecedent_basis          | -- | 2026-08-31         |           1 |   3902 |   0.05s |
| CASE-DEMO-053 | antecedent_basis          | antecedent_basis          | OK | 2026-09-17         |           9 |   4792 |   0.05s |
| CASE-DEMO-054 | antecedent_basis          | antecedent_basis          | OK | 2026-10-05         |           9 |   4791 |   0.03s |
| CASE-DEMO-055 | other                     | other                     | OK | 2026-05-27         |           1 |   4042 |   0.06s |
| CASE-DEMO-056 | other                     | other                     | OK | 2026-07-01         |           1 |   4039 |   0.06s |
| CASE-DEMO-057 | other                     | other                     | OK | 2026-08-17         |           1 |   4037 |   0.05s |
| CASE-DEMO-058 | other                     | other                     | OK | 2026-09-07         |           1 |   4044 |   0.05s |
| CASE-DEMO-059 | other                     | other                     | OK | 2026-09-23         |           1 |   3905 |   0.05s |
| CASE-DEMO-060 | other                     | other                     | OK | 2026-10-12         |           1 |   3901 |   0.03s |
| CASE-DEMO-061 | other                     | other                     | OK | 2026-10-27         |           1 |   3904 |   0.06s |
| CASE-DEMO-062 | other                     | other                     | OK | 2026-11-09         |           1 |   3905 |   0.05s |
| CASE-DEMO-063 | 101_subject_matter        | 101_subject_matter        | OK | 2026-06-17         |           1 |   3972 |   0.05s |
| CASE-DEMO-064 | 101_subject_matter        | 101_subject_matter        | OK | 2026-07-13         |           1 |   3968 |   0.05s |
| CASE-DEMO-065 | other                     | other                     | OK | 2026-07-29         |           1 |   3900 |   0.11s |
| CASE-DEMO-066 | other                     | other                     | OK | 2026-08-24         |           1 |   3898 |   0.08s |
| CASE-DEMO-067 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2026-04-20         |          10 |   7499 |   0.11s |
| CASE-DEMO-068 | 102_novelty               | 102_novelty,antecedent_ba | -- | 2026-05-20         |           1 |   3988 |   0.09s |
| CASE-DEMO-069 | 103_obviousness,other     | 103_obviousness,other     | OK | 2026-06-15         |           2 |   7247 |   0.08s |
| CASE-DEMO-070 | 103_obviousness,other     | 103_obviousness,other     | OK | 2026-07-20         |           2 |   6637 |   0.06s |
| CASE-DEMO-071 | 102_novelty,103_obviousne | 102_novelty,103_obviousne | OK | 2026-09-21         |          11 |  10273 |   0.11s |
| CASE-DEMO-072 | 103_obviousness,anteceden | 103_obviousness,anteceden | OK | 2026-10-26         |          11 |  10470 |   0.11s |
| CASE-DEMO-073 | 103_obviousness           | 103_obviousness           | OK | 2025-12-22         |           1 |   4290 |   0.11s |
| CASE-DEMO-074 | 103_obviousness           | 103_obviousness           | OK | 2026-03-18         |           1 |   4106 |   0.09s |
| CASE-DEMO-075 | 103_obviousness           | 103_obviousness           | OK | 2026-08-10         |           1 |   4128 |   0.06s |
| CASE-DEMO-076 | 103_obviousness           | 103_obviousness           | OK | 2026-01-19         |           1 |   4197 |   0.05s |
| CASE-DEMO-077 | 102_novelty               | 102_novelty               | OK | 2026-06-02         |           1 |   4052 |   0.06s |
| CASE-DEMO-078 | 102_novelty               | 102_novelty               | OK | 2026-09-14         |           1 |   4010 |   0.06s |
| CASE-DEMO-079 | 103_obviousness           |                           | -- | 2025-10-13         |           1 |   3856 |   0.08s |
| CASE-DEMO-080 | 101_subject_matter,102_no | 101_subject_matter,102_no | OK | 2026-06-01         |          14 |  18782 |   0.08s |

## Worst-performing cases (top 5)

### CASE-DEMO-068
- Failure mode: predicted=['102_novelty'], expected=['102_novelty', 'antecedent_basis']
- Claims mismatch: 0/2 rejections had exact claim sets
- Latency: 0.09s
- Tokens: 3988

### CASE-DEMO-080
- Claims mismatch: 0/6 rejections had exact claim sets
- Latency: 0.08s
- Tokens: 18782

### CASE-DEMO-052
- Failure mode: predicted=['103_obviousness'], expected=['antecedent_basis']
- Claims mismatch: 0/1 rejections had exact claim sets
- Latency: 0.05s
- Tokens: 3902

### CASE-DEMO-079
- Failure mode: predicted=['103_obviousness'], expected=[]
- Latency: 0.08s
- Tokens: 3856

### CASE-DEMO-071
- Claims mismatch: 0/3 rejections had exact claim sets
- Latency: 0.11s
- Tokens: 10273

