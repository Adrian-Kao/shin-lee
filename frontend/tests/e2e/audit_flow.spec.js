// Audit view e2e — Dave (auditor) sees rows + can verify the hash chain.
//
// Non-auditor users (Carol, Bob) can navigate to /audit, but the gateway
// rejects /v1/audit/recent with 403. The frontend then surfaces an
// ErrorBanner via classifyError(403).
import { test, expect } from '@playwright/test';
import {
  mockLogin,
  mockQuota,
  mockAuditRecent,
  mockAuditVerify,
  defaultAuditRows,
  loginAsAlice,
} from './helpers/mock_backend.js';

test.describe('Audit flow', () => {
  test('Dave can view audit rows', async ({ page }) => {
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    // AuditView kicks off runVerify on mount; mock so it doesn't 404.
    await mockAuditVerify(page);
    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    await page.waitForURL(/\/analyze/, { timeout: 5000 });

    // Click the Audit nav link to switch.
    // AppShell nav rail uses i18n key nav.audit (zh-TW resolves to "Audit").
    await page
      .locator('nav[aria-label="Primary"]')
      .getByRole('button', { name: /^Audit$/ })
      .click();
    await page.waitForURL(/\/audit/);

    // Table headers from AuditView.
    await expect(page.getByRole('heading', { name: /Audit Log/ })).toBeVisible();
    await expect(page.locator('th', { hasText: /User/ })).toBeVisible();
    await expect(page.locator('th', { hasText: /Endpoint/ })).toBeVisible();

    // First fixture row is alice's analyze call.
    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();
    // The masked-rule chip CASE_REF appears in the Mask 規則 column.
    await expect(page.locator('span', { hasText: /^CASE_REF$/ }).first()).toBeVisible();
  });

  test('non-auditor receives 403 and shows an error banner', async ({ page }) => {
    // Carol (it_admin / tenant_b) cannot read tenant_a audit logs.
    await mockLogin(page, 'carol');
    await mockQuota(page);
    await mockAuditRecent(page, [], {
      status: 403,
      body: { detail: 'forbidden: audit role required' },
    });
    // AuditView also kicks off /v1/audit/verify on mount — return 403 there too.
    await page.route('**/api/v1/audit/verify**', (route) => {
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'forbidden' }),
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: /Carol/ }).click();
    await page.waitForURL(/\/analyze/, { timeout: 5000 });
    // AppShell nav rail uses i18n key nav.audit (zh-TW resolves to "Audit").
    await page
      .locator('nav[aria-label="Primary"]')
      .getByRole('button', { name: /^Audit$/ })
      .click();
    await page.waitForURL(/\/audit/);

    const alert = page.getByRole('alert').first();
    await expect(alert).toBeVisible({ timeout: 5000 });
    // classifyError(403) → "您沒有此案件的存取權限。請確認 case_id 與您的登入身分相符"
    await expect(alert).toContainText('您沒有此案件的存取權限');
  });

  test('verify chain button renders green banner', async ({ page }) => {
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page, [], 2);
    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    await page.waitForURL(/\/analyze/);
    // AppShell nav rail uses i18n key nav.audit (zh-TW resolves to "Audit").
    await page
      .locator('nav[aria-label="Primary"]')
      .getByRole('button', { name: /^Audit$/ })
      .click();
    await page.waitForURL(/\/audit/);

    // Wait for the table to render (rows from defaultAuditRows).
    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();

    // The verify button uses data-testid="audit-verify-now". The label text is
    // either "立即驗證鏈" (idle) or "驗證中…" (in-flight).
    await page.getByTestId('audit-verify-now').click();

    // i18n key audit.verify_passed: "{{rows}} 筆紀錄全部驗證通過，未發現竄改。"
    await expect(page.getByText(/全部驗證通過/)).toBeVisible({ timeout: 5000 });
  });

  test('verify chain reports broken rows', async ({ page }) => {
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page, ['AUD-0042', 'AUD-0044'], 50);

    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    await page.waitForURL(/\/analyze/);
    // AppShell nav rail uses i18n key nav.audit (zh-TW resolves to "Audit").
    await page
      .locator('nav[aria-label="Primary"]')
      .getByRole('button', { name: /^Audit$/ })
      .click();
    await page.waitForURL(/\/audit/);

    await page.getByTestId('audit-verify-now').click();

    // i18n key audit.verify_failed: "發現 {{count}} 筆紀錄遭竄改：{{rows}}"
    await expect(page.getByText(/發現 2 筆紀錄遭竄改/)).toBeVisible({ timeout: 5000 });
  });

  test('alice (attorney) can also view the audit page', async ({ page }) => {
    // The gateway in the POC does not strictly restrict /v1/audit/recent to
    // auditors — that's a Q13 backend decision. The frontend simply renders
    // whatever rows come back. Sanity check that login as Alice → Audit
    // works the same as Dave's flow.
    await loginAsAlice(page);
    await mockAuditRecent(page, defaultAuditRows());
    await mockAuditVerify(page);

    // AppShell nav rail uses i18n key nav.audit (zh-TW resolves to "Audit").
    await page
      .locator('nav[aria-label="Primary"]')
      .getByRole('button', { name: /^Audit$/ })
      .click();
    await page.waitForURL(/\/audit/);
    await expect(page.locator('td', { hasText: '/v1/oa/analyze' }).first()).toBeVisible();
  });
});
