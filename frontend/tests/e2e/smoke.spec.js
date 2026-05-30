// Frontend smoke test: confirm the Vite dev server boots and the Login
// component renders the product name. Anything richer (real login flow,
// API mocking) is left for Phase 2 once the backend is reachable from CI.
import { test, expect } from '@playwright/test';

test('login screen renders product name', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('text=PatentMind').first()).toBeVisible();
});
