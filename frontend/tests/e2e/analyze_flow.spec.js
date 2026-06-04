// Analyze flow e2e — covers the three-pane workspace (Day 8E).
//
// Each test logs Alice in via the helper (mock /v1/auth/login), then mocks
// /v1/oa/analyze with the appropriate response shape (success or error) and
// asserts the pane that should react.
import { test, expect } from '@playwright/test';
import {
  mockLogin,
  mockQuota,
  mockAnalyze,
  defaultAnalysisResponse,
  loginAsAlice,
} from './helpers/mock_backend.js';

test.describe('Analyze flow — desktop', () => {
  // Desktop project gets 1440x900 by default. The `xl` breakpoint is 1280,
  // so the three-pane layout renders.
  test.skip(
    ({ viewport }) => viewport && viewport.width < 1280,
    'three-pane layout requires xl breakpoint'
  );

  test('three panes visible at desktop viewport', async ({ page }) => {
    await loginAsAlice(page);

    // Three panes use distinct sticky pane headers — each has the form
    // "XXX / English". Match the slash to disambiguate from the empty-state
    // headings ("尚無引證", "準備分析") that share Chinese prefixes.
    await expect(page.getByRole('heading', { name: /輸入 OA \/ Input/ })).toBeVisible();
    await expect(page.getByRole('heading', { name: /草稿 \/ Drafts/ })).toBeVisible();
    await expect(page.getByRole('heading', { name: /引證 \/ References/ })).toBeVisible();
  });

  test('analyze button POSTs to /v1/oa/analyze with expected body', async ({ page }) => {
    await loginAsAlice(page);
    const route = mockAnalyze(page);
    await route; // install completes

    // Two mains render (mobile + desktop, one hidden via Tailwind). Pick the
    // analyze button that is actually visible to the user so we click in the
    // pane whose React state we'll observe afterwards.
    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    const body = await route.capture;
    expect(body).toBeTruthy();
    expect(body.case_id).toBe('CASE-2025-001');
    expect(body.target_patent_no).toBe('US17123456');
    expect(typeof body.oa_text).toBe('string');
    expect(body.oa_text.length).toBeGreaterThan(50);
  });

  test('success result populates DraftsPane', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page);

    // Two mains render (mobile + desktop, one hidden via Tailwind). Pick the
    // analyze button that is actually visible to the user so we click in the
    // pane whose React state we'll observe afterwards.
    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    // The drafts pane shows the strategy + DraftEditor. The strategy default
    // in our fixture mentions "主張", which is unique to the fixture. The
    // SPA renders two inner <main> elements (mobile + desktop), one hidden
    // via Tailwind. Filter by Playwright's visible engine so we observe the
    // pane that's actually painted at this viewport.
    const visibleMain = page.locator('main').filter({ visible: true }).last();
    await expect(visibleMain.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
    await expect(visibleMain.getByText(/主張 cited prior art/).first()).toBeVisible();
    // The rejection_type chip is rendered as 103_obviousness.
    await expect(visibleMain.getByText('103_obviousness').first()).toBeVisible();
    // ReferencesPane: cited prior art numbers.
    await expect(visibleMain.getByText('US7654321').first()).toBeVisible();
  });

  test('error 500 returns ErrorBanner with retry button', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page, { status: 500, body: { detail: 'engine timeout' } });

    // Two mains render (mobile + desktop, one hidden via Tailwind). Pick the
    // analyze button that is actually visible to the user so we click in the
    // pane whose React state we'll observe afterwards.
    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    // ErrorBanner uses role="alert".
    const alert = page.getByRole('alert').first();
    await expect(alert).toBeVisible({ timeout: 10_000 });
    // Translated message for 500: "伺服器忙線中".
    await expect(alert).toContainText('伺服器忙線中');
    // Retry button label is "重試".
    await expect(alert.getByRole('button', { name: '重試' })).toBeVisible();
  });
});

test.describe('Analyze flow — mobile', () => {
  // Mobile project: iPhone X = 375x812 < xl, so MobileTabBar renders and
  // exactly one pane shows at a time.
  test.skip(
    ({ viewport }) => viewport && viewport.width >= 1280,
    'mobile tab strip only renders below xl'
  );

  test('mobile shows tab strip and one pane', async ({ page }) => {
    await loginAsAlice(page);

    // Tab strip with the three tabs.
    const inputTab = page.getByRole('button', { name: /輸入.*Input/ });
    const draftsTab = page.getByRole('button', { name: /草稿.*Drafts/ });
    const refsTab = page.getByRole('button', { name: /引證.*Refs/ });

    await expect(inputTab).toBeVisible();
    await expect(draftsTab).toBeVisible();
    await expect(refsTab).toBeVisible();

    // Only the input pane heading is visible initially.
    await expect(page.getByRole('heading', { name: /輸入/ })).toBeVisible();
    // Drafts + refs pane headers are NOT in the DOM (only one pane mounted).
    await expect(page.getByRole('heading', { name: /草稿/ })).toHaveCount(0);
  });

  test('mobile: success switches to drafts tab automatically', async ({ page }) => {
    await loginAsAlice(page);
    await mockAnalyze(page);

    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    // Per Analyze.jsx useEffect — when result lands on mobile, switch to 'drafts'.
    await expect(page.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
  });
});

// Sanity check that the response.related_prior_art correctly populates the
// references panel for the default rejection (US7654321 + US6543210 are both
// in cited_prior_art for REJ-1 in the fixture).
test('references panel filters by active rejection', async ({ page, viewport }) => {
  test.skip(viewport && viewport.width < 1280, 'desktop only');
  await loginAsAlice(page);
  await mockAnalyze(page, defaultAnalysisResponse());

  await page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true }).click();
  // ReferenceCard renders the patent_no inline. Scope to visible main so we
  // don't pick up the hidden mobile duplicate.
  const visible = page.locator('main').filter({ visible: true }).last();
  await expect(visible.getByText('US7654321').first()).toBeVisible({ timeout: 10_000 });
  await expect(visible.getByText('US6543210').first()).toBeVisible();
});

// Guard: the "loginAsAlice" helper depends on mockLogin/mockQuota working
// in isolation. Smoke that the pieces snap together.
test('login + quota fetched in sequence', async ({ page }) => {
  await mockLogin(page, 'alice');
  await mockQuota(page);

  await page.goto('/');
  await page.getByRole('button', { name: /Alice/ }).click();
  await page.waitForURL(/\/analyze/);

  // The token bar / quota panel header is "配額" — wait for it to render.
  await expect(page.getByRole('heading', { name: /配額/ }).first()).toBeVisible();
});
