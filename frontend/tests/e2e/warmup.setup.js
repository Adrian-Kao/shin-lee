// Vite dev-server warm-up — runs once before both browser projects
// (see `dependencies` in playwright.config.js).
//
// Local e2e runs hit the DEV server, which transforms ~1900 modules on the
// first page load. On Windows that cold transform cannot serve 5-10 parallel
// browser contexts — page.goto('/') times out across the whole suite. This
// single serial pass loads every major surface (login → analyze → audit) so
// the module graph is fully transformed and cached before the real tests
// fan out.
import { test } from '@playwright/test';
import {
  loginAsAlice,
  mockAuditRecent,
  mockAuditVerify,
  mockStackProbes,
} from './helpers/mock_backend.js';

test('warm the vite module graph', async ({ page }) => {
  test.setTimeout(180_000);
  page.setDefaultNavigationTimeout(150_000);

  await mockStackProbes(page);
  await mockAuditRecent(page);
  await mockAuditVerify(page);
  await loginAsAlice(page); // goto('/') → login → /analyze (loads the heavy panes)

  // Touch the audit surface too — AuditView + table modules.
  await page.getByTestId('nav-rail').getByRole('button', { name: /Audit/ }).click();
  await page.waitForURL(/\/audit/, { timeout: 30_000 });
  await page.getByText('Audit Log').first().waitFor({ timeout: 30_000 });
});
