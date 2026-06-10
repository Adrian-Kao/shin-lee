// Visual regression baselines. These tests take screenshots of key states
// and compare against committed baselines under tests/e2e/__screenshots__/.
//
// First run on a new platform must use `--update-snapshots` to seed.
// The threshold/maxDiffPixelRatio (5%) is set globally in playwright.config.js.
//
// Linux (CI) vs Windows (dev) can produce mildly different rasterisation;
// when a snapshot disagreement is purely font/AA, the 5% tolerance absorbs it.
// For larger structural differences, scope the test with process.platform.
import { test, expect } from '@playwright/test';
import {
  mockLogin,
  mockQuota,
  mockAnalyze,
  mockAuditRecent,
  mockAuditVerify,
  mockStackProbes,
  loginAsAlice,
} from './helpers/mock_backend.js';

// Mask dynamic regions (timestamps, request_id slices, animated spinners) so
// the diff is stable across runs.
function dynamicMaskLocators(page) {
  return [
    // The "request: <8-char-uuid>…" text in DraftsPane.
    page.locator('text=/request:\\s+[a-f0-9]{8}/'),
    // The deadline date in the summary bar (uses Date.now-derived rendering on some paths).
    page.locator('text=/期日/').locator('..'),
  ];
}

const screenshotOpts = (page) => ({
  fullPage: false,
  animations: 'disabled',
  caret: 'hide',
  // mask: dynamicMaskLocators(page),  // enable if AA + timing causes flakiness
});

// The AppShell footer's stack chips start in a pulsing "checking" state and
// settle asynchronously (mocked probes settle in <100ms, but the screenshot
// must not race that transition). Call after login, before toHaveScreenshot.
async function waitForStackSettled(page) {
  for (const id of ['gateway', 'ai-engine', 'digirunner', 'dify']) {
    await expect(page.getByTestId(`stack-status-${id}`)).not.toHaveAttribute(
      'data-status',
      'checking'
    );
  }
}

test.describe('Visual regression', () => {
  test.beforeEach(async ({ page }) => {
    // The AppShell footer probes Gateway/AI Engine/digiRunner/Dify on mount.
    // Pin all four to a deterministic state (gateway green, externals gray)
    // so the baselines don't depend on what happens to listen on the dev box.
    await mockStackProbes(page);
  });

  test('landing — desktop', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop snapshot');
    await page.goto('/');
    // Wait for hero text to render — it's the latest-painted element.
    await expect(page.locator('text=PatentMind').first()).toBeVisible();
    await expect(page).toHaveScreenshot('landing_desktop_1440.png', screenshotOpts(page));
  });

  test('landing — mobile', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width >= 1280, 'mobile snapshot');
    await page.goto('/');
    await expect(page.locator('text=PatentMind').first()).toBeVisible();
    await expect(page).toHaveScreenshot('landing_mobile_375.png', screenshotOpts(page));
  });

  test('analyze — three panes, no result (desktop)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'three-pane is desktop only');
    await loginAsAlice(page);
    // Make sure quota panel resolved so layout is stable (no skeleton flicker).
    await expect(page.getByRole('heading', { name: /配額/ }).first()).toBeVisible();
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('analyze_empty_desktop.png', screenshotOpts(page));
  });

  test('analyze — with mocked result (desktop)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'three-pane is desktop only');
    await loginAsAlice(page);
    await mockAnalyze(page);
    await page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true }).click();
    // Wait until the strategy text from the fixture is visible (drafts pane).
    // Two mains render (mobile xl:hidden + desktop); after a successful analyze
    // the mobile main auto-switches to its drafts tab too, so it also contains
    // 答辯策略 — but hidden on desktop. Target the visible (desktop) copy.
    await expect(
      page.getByText('答辯策略').filter({ visible: true }).first()
    ).toBeVisible({ timeout: 10_000 });
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('analyze_result_desktop.png', screenshotOpts(page));
  });

  test('analyze — 500 error banner (desktop)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop snapshot');
    await loginAsAlice(page);
    await mockAnalyze(page, { status: 500, body: { detail: 'engine timeout' } });
    await page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true }).click();

    const alert = page.getByRole('alert').first();
    await expect(alert).toBeVisible({ timeout: 5000 });
    await expect(alert).toHaveScreenshot('error_banner_desktop.png', {
      animations: 'disabled',
      caret: 'hide',
    });
  });

  test('mobile — tab bar visible after login', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width >= 1280, 'mobile snapshot');
    await loginAsAlice(page);
    // Wait for any of the three tabs to be rendered. The mobile tab strip is
    // an ARIA tablist (Day 12E), so the tabs expose role="tab".
    await expect(page.getByRole('tab', { name: /輸入.*Input/ })).toBeVisible();
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('mobile_tab_bar.png', screenshotOpts(page));
  });
});

// ---------------------------------------------------------------------------
// Day 12E — dark-mode visual regression.
//
// The ThemeProvider reads `localStorage.theme` on mount and toggles the `dark`
// class on <html> before first paint, so seeding it via addInitScript gives a
// deterministic dark render without depending on the (sm:+ only) toggle button
// or its hover/focus timing. These baselines lock in the dark palette across
// the two surfaces an attorney actually works in: the three-pane analyze grid
// and the audit table.
// ---------------------------------------------------------------------------
test.describe('Visual regression — dark mode', () => {
  test.beforeEach(async ({ page }) => {
    await mockStackProbes(page); // deterministic footer chips (see above)
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem('theme', 'dark');
      } catch {
        /* private mode — non-fatal */
      }
    });
  });

  test('analyze — three panes, no result (desktop, dark)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'three-pane is desktop only');
    await loginAsAlice(page);
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
    await expect(page.getByRole('heading', { name: /配額/ }).first()).toBeVisible();
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('analyze_empty_desktop_dark.png', screenshotOpts(page));
  });

  test('analyze — with mocked result (desktop, dark)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'three-pane is desktop only');
    await loginAsAlice(page);
    await mockAnalyze(page);
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
    await page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true }).click();
    await expect(
      page.getByText('答辯策略').filter({ visible: true }).first()
    ).toBeVisible({ timeout: 10_000 });
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('analyze_result_desktop_dark.png', screenshotOpts(page));
  });

  test('audit — table + hero metrics (desktop, dark)', async ({ page, viewport }) => {
    test.skip(viewport && viewport.width < 1280, 'desktop snapshot');
    await mockLogin(page, 'audit_dave');
    await mockQuota(page);
    await mockAuditRecent(page);
    await mockAuditVerify(page);
    await page.goto('/');
    await page.getByRole('button', { name: /Dave/ }).click();
    await page.waitForURL(/\/audit/);
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
    await expect(page.getByRole('heading', { name: /Audit Log/ })).toBeVisible();
    await waitForStackSettled(page);
    await expect(page).toHaveScreenshot('audit_table_desktop_dark.png', screenshotOpts(page));
  });
});
