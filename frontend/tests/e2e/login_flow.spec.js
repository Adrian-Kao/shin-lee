// Login flow e2e — landing page renders, role cards work, and a 401 from
// the gateway surfaces an alert on screen. All tests are hermetic via
// page.route() mocks.
import { test, expect } from '@playwright/test';
import { mockLogin, mockQuota, DEMO_USERS } from './helpers/mock_backend.js';

test.describe('Login flow', () => {
  test('landing renders with hero + role cards', async ({ page }) => {
    await page.goto('/');

    // Hero brand + tagline are visible.
    await expect(page.locator('text=PatentMind').first()).toBeVisible();

    // All four demo identity cards render. The button text is just the user
    // initial + name + role label, so a name-matcher is the most stable.
    for (const name of ['Alice', 'Bob', 'Carol', 'Dave']) {
      await expect(page.getByRole('button', { name: new RegExp(name) })).toBeVisible();
    }
  });

  test('clicking Alice navigates to /analyze', async ({ page }) => {
    await mockLogin(page, 'alice');
    await mockQuota(page);

    await page.goto('/');
    await page.getByRole('button', { name: /Alice/ }).click();

    await page.waitForURL(/\/analyze/, { timeout: 5000 });
    // The Analyze header carries the literal "PatentMind AI" brand line.
    await expect(page.locator('header').getByText('PatentMind AI')).toBeVisible();
  });

  test('Carol logs in as IT Admin with tenant_b', async ({ page, viewport }) => {
    // The display_name + tenant + role badge group lives in a `hidden sm:flex`
    // container in the TopBar. At Tailwind's `sm` breakpoint (640px) it
    // collapses — so on the 375x812 mobile viewport these chips are not
    // rendered. Skip on mobile; the role information is still verified
    // through the audit chip / role-badge assertions in other tests.
    test.skip(viewport && viewport.width < 640, 'TopBar user chip is sm: only');

    await mockLogin(page, 'carol');
    await mockQuota(page);
    // AppShell calls auditVerify on mount for it_admin / auditor — mock so it
    // doesn't error out (would otherwise show a fail chip but not crash).
    await page.route('**/api/v1/audit/verify**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ broken: [], verified: 0 }),
      })
    );

    await page.goto('/');
    await page.getByRole('button', { name: /Carol/ }).click();
    await page.waitForURL(/\/analyze/, { timeout: 5000 });

    // TopBar shows display_name in a div, tenant_id below, role badge to the
    // right via the i18n key shell.role_badge.it_admin = "IT 管理".
    const header = page.locator('header');
    await expect(header.getByText(DEMO_USERS.carol.display_name)).toBeVisible();
    await expect(header.getByText(/tenant_b/)).toBeVisible();
    // Role badge: t('shell.role_badge.it_admin') = 'IT 管理'.
    await expect(header.getByText(/IT 管理/)).toBeVisible();
  });

  test('error message appears when backend returns 401', async ({ page }) => {
    await mockLogin(page, 'alice', {
      status: 401,
      body: { detail: 'Unauthorized — demo secret mismatch' },
    });

    await page.goto('/');
    await page.getByRole('button', { name: /Alice/ }).click();

    // Login.jsx renders the error as <div role="alert"> in the login card.
    const alert = page.getByRole('alert').first();
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/Unauthorized|demo secret|401/i);

    // URL must NOT have changed.
    await expect(page).toHaveURL(/\/(login)?$|\/$/);
  });
});
