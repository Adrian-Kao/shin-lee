// Sign-off export e2e (Q16) — the flagship hard gate.
//
// The DraftEditor lets the attorney curate per-sentence provenance with a
// three-state decision (accept / exclude / pending, with undo). Export
// requires: every line decided + the mandatory "我已逐項確認 / I have
// reviewed each item" checkbox + at least one accepted line. The backend
// additionally 409s if attorney_signoff is not exactly true. These tests
// cover:
//   1. Export stays disabled until BOTH the checkbox is ticked AND every
//      line is decided.
//   2. A successful export after full review (200 → assembled document shown).
//   3. The three-state flow: bulk accept, undo, exclude.
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

  // Per-line action buttons are always visible (touch-friendly); accepting a
  // line removes its accept button, so `.first()` walks down the draft.
  async function acceptNextSentence(main) {
    const accept = main.getByTestId('line-accept').first();
    await accept.scrollIntoViewIfNeeded();
    await accept.click();
  }

  test('export unlocks only after checkbox AND every line decided', async ({ page }) => {
    const main = await runAnalysis(page);

    const checkbox = main.getByTestId('signoff-checkbox').first();
    const exportBtn = main.getByTestId('signoff-export').first();

    await expect(checkbox).toBeVisible();
    await expect(exportBtn).toBeVisible();

    // Accept one sentence; checkbox unticked → export disabled.
    await acceptNextSentence(main);
    await expect(exportBtn).toBeDisabled();

    // Tick the checkbox — STILL disabled: the second sentence is undecided
    // (the gate is "every line decided", not "at least one").
    await checkbox.check();
    await expect(checkbox).toBeChecked();
    await expect(exportBtn).toBeDisabled();

    // Decide the remaining sentence → export enables.
    await acceptNextSentence(main);
    await expect(exportBtn).toBeEnabled();
  });

  test('successful export after full review shows the assembled document', async ({ page }) => {
    const main = await runAnalysis(page);
    const exportRoute = mockExportDraft(page);

    const checkbox = main.getByTestId('signoff-checkbox').first();
    const exportBtn = main.getByTestId('signoff-export').first();

    // Bulk-accept everything (the "accept remaining N" affordance), then sign.
    await main.getByTestId('signoff-accept-all').first().click();
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
    // Every segment ships with its provenance tag and an explicit accepted flag.
    for (const seg of body.segments) {
      expect(['ai_generated', 'attorney_edited', 'attorney_added']).toContain(seg.source);
      expect(typeof seg.segment_id).toBe('string');
      expect(typeof seg.accepted).toBe('boolean');
      expect(seg.accepted).toBe(true); // bulk-accepted above
    }

    // The signed-off result panel renders with the returned document.
    const result = main.getByTestId('export-result').first();
    await expect(result).toBeVisible({ timeout: 10_000 });
    await expect(result.getByText(/已簽核答辯稿|Signed-off response/)).toBeVisible();
  });

  test('three-state flow: bulk accept, undo, exclude — excluded still exports accepted=false', async ({
    page,
  }) => {
    const main = await runAnalysis(page);
    const exportRoute = mockExportDraft(page);

    const checkbox = main.getByTestId('signoff-checkbox').first();
    const exportBtn = main.getByTestId('signoff-export').first();

    // Bulk accept, then change our mind about the first sentence: undo → exclude.
    await main.getByTestId('signoff-accept-all').first().click();
    await main.getByTestId('line-undo').first().click();
    await expect(exportBtn).toBeDisabled(); // one line back to pending
    await main.getByTestId('line-exclude').first().click();
    await expect(main.getByText('已排除').first()).toBeVisible();

    await checkbox.check();
    await expect(exportBtn).toBeEnabled(); // all decided again (1 excluded + 1 accepted)
    await exportBtn.click();

    const body = await exportRoute.capture;
    expect(body.segments.length).toBe(2);
    const flags = body.segments.map((s) => s.accepted);
    expect(flags).toContain(false); // the excluded sentence travels with accepted=false
    expect(flags).toContain(true);
  });
});
