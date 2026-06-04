// Day 9C — CHUNK-8 trust band.
//
// PRODUCT_STRATEGY §10 + CLAUDE.md §4 invariants #3 / #6 / #7 demand that
// three things be VISIBLE on every authenticated page:
//
//   1. Redaction status (Q10 / invariant #3)
//   2. Mapping-table residency (CLAUDE.md §9 — never leaves on-prem)
//   3. Routing decision (Q15 / invariant #7 — confidential → local LLM)
//
// These assertions are the regression net for the trust band: if a future
// PR drops the band from the shell, or if the case-id → confidential
// detection breaks, this test must catch it.
import { test, expect } from '@playwright/test';
import {
  mockLogin,
  mockQuota,
  mockAnalyze,
  mockRedactionPreview,
  mockAuditRecent,
  mockAuditVerify,
  defaultAnalysisResponse,
  loginAsAlice,
} from './helpers/mock_backend.js';

const TRUST_CHIPS = ['trust-redaction', 'trust-mapping', 'trust-routing'];

test.describe('Trust band (Day 9C CHUNK-8)', () => {
  test('three trust chips render on Analyze immediately after login', async ({ page }) => {
    await loginAsAlice(page);
    await mockAuditVerify(page);
    // Band lives in the shell — must be present on the analyze landing.
    const band = page.getByTestId('trust-band');
    await expect(band).toBeVisible();
    for (const id of TRUST_CHIPS) {
      await expect(band.getByTestId(id)).toBeVisible();
    }
  });

  test('three trust chips also render on the Audit route', async ({ page }) => {
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page);
    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    await page.waitForURL(/\/analyze/);
    await page.getByRole('button', { name: /^Audit$/ }).click();
    await page.waitForURL(/\/audit/);

    const band = page.getByTestId('trust-band');
    await expect(band).toBeVisible();
    for (const id of TRUST_CHIPS) {
      await expect(band.getByTestId(id)).toBeVisible();
    }
  });

  test('routing chip flips to confidential when case_id ends in -CONF', async ({ page }) => {
    await loginAsAlice(page);
    await mockAuditVerify(page);
    await mockRedactionPreview(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        redaction_summary: { masked_entity_count: 7, rules_triggered: ['EMAIL', 'PHONE'] },
      })
    );

    // Drop a -CONF case id into the Case ID input. The trust band's routing
    // chip is driven by the live case id, not a backend response, so this
    // exercises the SPA-side detection (Q15 mirroring).
    const caseInput = page.locator('input').first();
    await caseInput.fill('CASE-2025-001-CONF');

    // Wait one tick for the trust context push to land.
    await expect(page.getByTestId('trust-routing')).toContainText(/Local LLM|本地 LLM/);
  });

  test('chain-verify chip is present in the top bar', async ({ page }) => {
    await loginAsAlice(page);
    await mockAuditVerify(page);
    // Attorney role doesn't poll, but the chip is rendered as the "Chain
    // verified" neutral chip variant. testid is stable across variants.
    await expect(page.getByTestId('trust-chain-chip')).toBeVisible();
  });
});
