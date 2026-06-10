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

  test('verification banner surfaces stripped citations + verifier model', async ({ page }) => {
    // ★3 hallucination-defense panel, rich path: the backend (orchestrator)
    // now passes the verifier's invalid_citations + verifier_model through, so
    // the attorney sees exactly what the AI tried to cite (and got stripped)
    // and which model vetted it — not just an anonymous [CITATION_REMOVED].
    await loginAsAlice(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        drafts: [
          {
            rejection_id: 'REJ-1',
            strategy: '主張 cited prior art 並未揭露非均勻截面。 [GROUNDED_REF_1]',
            draft_text:
              'Applicant respectfully traverses. [GROUNDED_REF_1] does not teach the ' +
              'limitation. The examiner cited [CITATION_REMOVED] which is unsupported.',
            grounded_citations: ['[GROUNDED_REF_1]'],
            confidence: 0.82,
            requires_attorney_review: true,
            // Q14 verifier transparency fields surfaced by the orchestrator.
            invalid_citations: ['US9999999', 'Smith v. Jones, 999 F.3d 1234'],
            verifier_confidence: 0.91,
            verifier_model: 'mock-haiku-verifier',
          },
        ],
      })
    );

    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    const banner = page.getByTestId('verification-banner').filter({ visible: true }).first();
    await expect(banner).toBeVisible({ timeout: 10_000 });
    // Real invalid_citations count (2), not a placeholder-derived guess.
    await expect(banner).toContainText('2 citation(s) removed');
    // The actual stripped citation strings are listed for the attorney.
    await expect(banner).toContainText('US9999999');
    await expect(banner).toContainText('Smith v. Jones, 999 F.3d 1234');
    // The verifier model is named — the trust signal ChatGPT can't offer.
    await expect(banner).toContainText('mock-haiku-verifier');
  });

  test('degraded result shows an unmissable amber alert banner', async ({ page }) => {
    // P2-2: when the LLM backend is down the AI engine degrades to the mock
    // engine and tags the model label with -DEGRADED-. A fabricated legal
    // analysis must never look like a real one — the DraftsPane surfaces a
    // role=alert banner, not just the metadata suffix.
    await loginAsAlice(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        cost_meta: {
          model: 'dify/qwen2.5:7b-DEGRADED-mock',
          prompt_tokens: 0,
          completion_tokens: 0,
          estimated_cost_usd: 0,
          cache_hit: false,
        },
      })
    );

    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    const alert = page.getByRole('alert').filter({ visible: true }).first();
    await expect(alert).toBeVisible({ timeout: 10_000 });
    await expect(alert).toContainText('AI 服務降級中');
  });

  test('deadline summary explains the calculation basis on demand', async ({ page }) => {
    // ★ deadline 可解釋：the backend returns the roll-forward reason, the
    // recommended internal deadline and the holiday-calendar version; the
    // summary bar must let the attorney see WHY a date is what it is (a wrong
    // deadline = lost patent rights).
    await loginAsAlice(page);
    await mockAnalyze(
      page,
      defaultAnalysisResponse({
        deadline_summary: {
          received_date: '2025-04-15T00:00:00Z',
          statutory_deadline: '2025-07-15T00:00:00Z',
          recommended_internal_deadline: '2025-07-08T00:00:00Z',
          days_remaining: 42,
          holiday_calendar_version: '2025.1',
          warnings: ['截止日落在週六，依規則順延至下一個工作日'],
        },
      })
    );

    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();

    // Wait for the result, then reveal the deadline calculation basis.
    const whyBtn = page.getByRole('button', { name: /計算依據 \/ Why/ }).filter({ visible: true });
    await expect(whyBtn.first()).toBeVisible({ timeout: 10_000 });
    await whyBtn.first().click();

    const details = page.getByTestId('deadline-details').filter({ visible: true }).first();
    await expect(details).toBeVisible();
    // The recommended internal deadline + holiday-calendar version are surfaced.
    await expect(details).toContainText('建議內部完成');
    await expect(details).toContainText('2025.1');
    // The roll-forward reason (warning) is shown verbatim.
    await expect(details).toContainText('順延至下一個工作日');
  });

  test('language switch to EN translates the analyze surface', async ({ page }) => {
    // The AppShell language toggle now drives the whole analyze flow, not just
    // the shell: InputPane + DraftsPane strings were migrated into i18n.
    await loginAsAlice(page);
    await mockAnalyze(page);

    // Switch UI language to English.
    await page
      .getByRole('group', { name: 'Language' })
      .getByRole('button', { name: 'EN' })
      .click();

    // InputPane: the analyze button is now English ("Analyze OA", not "分析 OA").
    const analyzeBtn = page.getByRole('button', { name: /^Analyze OA/ }).filter({ visible: true });
    await expect(analyzeBtn.first()).toBeVisible();
    await analyzeBtn.first().click();

    // DraftsPane: the strategy label is translated ("Response strategy").
    const visibleMain = page.locator('main').filter({ visible: true }).last();
    await expect(visibleMain.getByText('Response strategy').first()).toBeVisible({
      timeout: 10_000,
    });
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

    // Tab strip with the three tabs. The strip is an ARIA tablist, so the tabs
    // expose role="tab" (Day 12E a11y pass) rather than the generic button role.
    const inputTab = page.getByRole('tab', { name: /輸入.*Input/ });
    const draftsTab = page.getByRole('tab', { name: /草稿.*Drafts/ });
    const refsTab = page.getByRole('tab', { name: /引證.*Refs/ });

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
