// Sign-off export e2e (Q16) — the flagship hard gate.
//
// The DraftEditor lets the attorney curate per-sentence provenance, then
// requires a mandatory "我已逐項確認 / I have reviewed each item" checkbox
// before the Export button enables. The backend additionally 409s if
// attorney_signoff is not exactly true. These tests cover:
//   1. Export button disabled until the checkbox is ticked.
//   2. A successful export after ticking (200 → assembled document shown).
//
// Desktop-only: the three-pane layout (xl >= 1280) renders DraftsPane inline.
import { test, expect } from '@playwright/test';
import { loginAsAlice, mockAnalyze, mockExportDraft } from './helpers/mock_backend.js';

test.describe('Sign-off export gate (Q16) — desktop', () => {
  test.skip(
    ({ viewport }) => viewport && viewport.width < 1280,
    'three-pane DraftEditor requires xl breakpoint'
  );

  async function runAnalysis(page) {
    await loginAsAlice(page);
    await mockAnalyze(page);
    const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
    await analyzeBtn.click();
    // Wait for the drafts pane to render the strategy + DraftEditor.
    const visibleMain = page.locator('main').filter({ visible: true }).last();
    await expect(visibleMain.getByText('答辯策略').first()).toBeVisible({ timeout: 10_000 });
    return visibleMain;
  }

  // The attorney accepts AI sentences by hovering a line and clicking 接受.
  // Lines start un-accepted; at least one accepted sentence + the ticked
  // checkbox are required before export enables.
  async function acceptFirstSentence(main) {
    // Hover the first draft line so its action buttons appear, then Accept.
    const firstAccept = main.getByRole('button', { name: '接受' }).first();
    await firstAccept.scrollIntoViewIfNeeded();
    await firstAccept.click({ force: true });
  }

  test('export button is disabled until the review checkbox is ticked', async ({ page }) => {
    const main = await runAnalysis(page);

    const checkbox = main.getByTestId('signoff-checkbox').first();
    const exportBtn = main.getByTestId('signoff-export').first();

    await expect(checkbox).toBeVisible();
    await expect(exportBtn).toBeVisible();

    // Accept a sentence so there is something to export, but DO NOT tick the
    // box yet — the export button must stay disabled (the checkbox is the gate).
    await acceptFirstSentence(main);
    await expect(exportBtn).toBeDisabled();

    // Tick it → button becomes enabled.
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await expect(exportBtn).toBeEnabled();
  });

  test('successful export after ticking shows the assembled document', async ({ page }) => {
    const main = await runAnalysis(page);
    const exportRoute = mockExportDraft(page);

    const checkbox = main.getByTestId('signoff-checkbox').first();
    const exportBtn = main.getByTestId('signoff-export').first();

    await acceptFirstSentence(main);
    await checkbox.check();
    await expect(exportBtn).toBeEnabled();
    await exportBtn.click();

    // The request the SPA sent carries attorney_signoff=true and the segments.
    const body = await exportRoute.capture;
    expect(body).toBeTruthy();
    expect(body.attorney_signoff).toBe(true);
    expect(body.case_id).toBe('CASE-2025-001');
    expect(Array.isArray(body.segments)).toBe(true);
    expect(body.segments.length).toBeGreaterThan(0);
    // Default-accepted sentences flip via the Accept buttons in real use; the
    // export request always includes every segment with its provenance tag.
    for (const seg of body.segments) {
      expect(['ai_generated', 'attorney_edited', 'attorney_added']).toContain(seg.source);
      expect(typeof seg.segment_id).toBe('string');
    }

    // The signed-off result panel renders with the returned document.
    const result = main.getByTestId('export-result').first();
    await expect(result).toBeVisible({ timeout: 10_000 });
    await expect(result.getByText(/已簽核答辯稿|Signed-off response/)).toBeVisible();
  });
});
