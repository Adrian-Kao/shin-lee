// Real-stack demo rehearsal + screenshot capture (Day 14 delivery eve).
// Drives the LIVE stack — vite :5173 → gateway :8010 → ai_engine :8011 →
// Dify :8088 → Ollama qwen2.5:7b — NO mocks. Saves screenshots for the
// presentation deck. Run: node real_stack_shots.mjs
import { chromium } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';

const OUT = '../docs/screenshots/delivery';
mkdirSync(OUT, { recursive: true });
const oaText = readFileSync('../data/oa_samples/sample_oa_tw.txt', 'utf-8');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const shot = (name) => page.screenshot({ path: `${OUT}/real_${name}.png`, fullPage: false });

// 1. Login page
await page.goto('http://localhost:5173/');
await page.waitForLoadState('networkidle');
await shot('01_login');

// 2. Login as alice (demo password path)
await page.getByText('Alice', { exact: false }).first().click();
await page.waitForURL(/analyze/, { timeout: 15_000 }).catch(() => {});
await page.waitForLoadState('networkidle');
await shot('02_analyze_empty');

// 3. Paste the TW OA text
const caseInput = page.getByPlaceholder(/CASE-/).first();
if (await caseInput.isVisible().catch(() => false)) {
  await caseInput.fill('CASE-2025-001');
}
const patentInput = page.getByPlaceholder(/US\d|TW\d|專利/).first();
if (await patentInput.isVisible().catch(() => false)) {
  await patentInput.fill('TW202617461');
}
const textarea = page.locator('textarea').filter({ visible: true }).first();
await textarea.fill(oaText);
await shot('03_oa_pasted');

// 4. Analyze through the REAL Dify path (~30s on qwen2.5:7b)
const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
await analyzeBtn.click();
await page.waitForTimeout(3000);
await shot('04_running');

// Wait for the drafts pane to populate (generous: qwen can take 60-120s)
const visibleMain = page.locator('main').filter({ visible: true }).last();
await visibleMain.getByText('答辯策略').first().waitFor({ timeout: 240_000 });
await shot('05_result_real_qwen');

// 5. Scroll the draft into view
const draft = visibleMain.getByText(/申復|申請人/).first();
if (await draft.isVisible().catch(() => false)) {
  await draft.scrollIntoViewIfNeeded();
  await shot('06_draft_zh_tw');
}

// 6. Audit view
await page.goto('http://localhost:5173/audit');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);
await shot('07_audit');

await browser.close();
console.log('REAL-STACK SHOTS DONE →', OUT);
