Day 9C — CHUNK-1 + CHUNK-8 visual reference (ASCII)
====================================================

Headless screenshot infra not available in the worktree sandbox; below is
the rendered layout at 1440x900 (chromium-desktop project).

The real screenshots will be regenerated on the first CI run that ships
with Playwright's `screenshot: 'only-on-failure'` hook flipped to
`screenshot: 'on'` for the trust_band.spec.js test.

------------------------------------------------------------
LOGIN (route: /, unauthenticated)
------------------------------------------------------------
+--------------------------------+--------------------------------+
| NAVY 800 → 900 → SLATE GRADIENT|        WHITE PANEL             |
|                                |                                |
|   [PM] PatentMind AI  [POC]    |  Pick a demo identity          |
|                                |  POC has no password...        |
|   AI 輔助專利答辯草擬            |                                |
|                                |  +--------------------------+  |
|   [icon] Auto-classify ...     |  | (A) Alice  Attorney      |  |
|   [icon] RAG-grounded ...      |  +--------------------------+  |
|   [icon] Auto deadlines ...    |  | (B) Bob    Paralegal     |  |
|   [icon] Auto redaction ...    |  +--------------------------+  |
|                                |  | (C) Carol  IT Admin      |  |
|                                |  +--------------------------+  |
|   POC · v0.3 · internal demo   |  | (D) Dave   Auditor       |  |
+--------------------------------+--------------------------------+

Key changes vs Day 8: navy gradient (was indigo); lucide icons (was emoji
bullets); navy-700 focus ring (was indigo-500).

------------------------------------------------------------
ANALYZE (route: /analyze, three-pane desktop)
------------------------------------------------------------
+-----------------------------------------------------------------------+
| [PM] PatentMind AI [POC]          [Shield ✓ Chain · 1,247] Alice [Att]|  ← top bar (navy.900)
+-----------------------------------------------------------------------+
| [Shield] Auto-mask 14 entities  [Server] Mapping on-prem  [Cloud] Auto|  ← TRUST BAND
+----+------------------------+--------------+------------+-------------+
|    | INPUT (30%)            | DRAFTS (40%) | REFS (30%) |             |
|nav | Case ID                | tabs         | hits       |             |
|rail| Target patent          | strategy     |            |             |
|    | [Paperclip] Upload     | draft text   |            |             |
| 분 | OA textarea            | [GROUNDED_…] |            |             |
| 分 | [preview] [分析 OA]    |              |            |             |
| 案 | claim tree             |              |            |             |
| 件 | quota bars             |              |            |             |
| 稽 |                        |              |            |             |
| 核 |                        |              |            |             |
+----+------------------------+--------------+------------+-------------+

Width 64px collapsed → 240px expanded via the chevron at rail foot.

------------------------------------------------------------
AUDIT (route: /audit)
------------------------------------------------------------
+-----------------------------------------------------------------------+
| [PM] PatentMind AI [POC]          [Shield ✓ Chain · 1,247] Dave [Aud] |
+-----------------------------------------------------------------------+
| [Shield] Auto-mask active  [Server] Mapping on-prem  [Cloud] Auto     |
+----+------------------------------------------------------------------+
|    | +------------------- HERO METRICS -------------------+ [Verify]  |
|nav | | Audit rows | Mismatches | Last verified            |           |
|rail| | 1,247      | 0          | 2026-06-05 03:14:18 UTC  |           |
|    | +-----------------------------------------------------+           |
|    |                                                                  |
|    | [Audit Log]                              [Refresh]               |
|    | ✓ All 1247 rows passed hash verification — no tampering.        |
|    |                                                                  |
|    | TIME (UTC) | USER  | CASE        | ENDPOINT     | … | POLICY    |
|    | ---------- | ----- | ----------- | ------------ | … | --------- |
|    | 2026-06-05 | alice | CASE-...001 | /v1/oa/anal… | … | authz ✓   |
|    | 2026-06-05 | alice | CASE-...001 | /v1/quota    | … | authz ✓   |
+----+------------------------------------------------------------------+

Hero block uses JetBrains Mono for the three numbers (tabular-nums).
Numbers render emerald.700 when allPass; rose.700 when broken > 0.
