// Frontend-service hardening — server-side session death handling.
//
// When ANY authed call returns 401 (expired JWT or jti revoked by a logout
// elsewhere), the api client emits a single session-expired event; App.jsx
// logs out and explains why. Before this, every query just failed silently
// in place and the user stared at a dead workspace.
//
// A 401 on the LOGIN call itself (bad credentials) must NOT trigger this —
// the event only fires for calls that carried a Bearer token.
import { test, expect } from '@playwright/test';
import { loginAsAlice } from './helpers/mock_backend.js';

test.describe('Session expiry (401 on authed call)', () => {
  test('revoked session bounces to login with an explanation toast', async ({ page }) => {
    await loginAsAlice(page);

    // From now on the gateway considers the token dead: the quota poll (an
    // authed GET that AnalyzeRoute fires) starts returning 401.
    await page.route('**/api/v1/quota**', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'token revoked' }),
      })
    );
    // TanStack Query refetches the quota on window focus — that authed GET
    // hits the 401 and the app must bounce to login on its own (no clicks:
    // by the time a user could react, the workspace is already gone).
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));

    // Back at the login screen, with the session-expired explanation.
    await expect(page.getByText(/請選擇身分登入|Choose an identity/).first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/登入已過期|session has expired/i).first()).toBeVisible();
  });
});
