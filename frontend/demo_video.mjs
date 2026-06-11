// 30-second demo video — raw footage recorder.
// Drives the LIVE stack (vite :5173 → gateway :8010 → ai_engine :8011 →
// Dify :8088 → Ollama qwen2.5:7b) at 1920×1080 with video recording and a
// synthetic cursor dot. Phase timestamps are written to marks.json so
// scripts/make_demo_video.py can cut/speed segments precisely.
// Run: node demo_video.mjs
import { chromium } from '@playwright/test';
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';

const OUT = 'demo_video_out';
mkdirSync(OUT, { recursive: true });
const oaBase = readFileSync('../data/oa_samples/sample_oa_tw.txt', 'utf-8');
const oaText = `參考編號 V${Date.now()}\n${oaBase}`; // cache-buster → real inference

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();

// synthetic cursor that follows the mouse (Playwright renders no cursor)
await page.addInitScript(() => {
  window.addEventListener('DOMContentLoaded', () => {
    const dot = document.createElement('div');
    dot.style.cssText =
      'position:fixed;z-index:99999;width:22px;height:22px;border-radius:50%;' +
      'background:rgba(245,176,32,.85);border:3px solid #fff;' +
      'box-shadow:0 2px 10px rgba(0,0,0,.35);pointer-events:none;' +
      'transition:transform .06s;left:0;top:0;transform:translate(-100px,-100px)';
    document.body.appendChild(dot);
    window.addEventListener('mousemove', (e) => {
      dot.style.transform = `translate(${e.clientX - 11}px, ${e.clientY - 11}px)`;
    }, { passive: true });
  });
});

const t0 = Date.now();
const marks = {};
const mark = (k) => { marks[k] = (Date.now() - t0) / 1000; console.log(k, marks[k].toFixed(1)); };
const glide = async (loc) => {           // human-ish mouse move onto an element
  const b = await loc.boundingBox();
  if (b) await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 25 });
};

// ---- phase 1: login ----
await page.goto('http://localhost:5173/');
await page.waitForLoadState('networkidle');
mark('login_page');
await page.waitForTimeout(900);
const alice = page.getByText('Alice', { exact: false }).first();
await glide(alice);
await page.waitForTimeout(400);
await alice.click();
await page.waitForURL(/analyze/, { timeout: 15000 }).catch(() => {});
await page.waitForLoadState('networkidle');
mark('logged_in');
await page.waitForTimeout(900);

// ---- phase 2: input ----
const caseInput = page.getByPlaceholder(/CASE-/).first();
if (await caseInput.isVisible().catch(() => false)) {
  await glide(caseInput);
  await caseInput.fill('CASE-2025-001');
}
const patentInput = page.getByPlaceholder(/US\d|TW\d|專利/).first();
if (await patentInput.isVisible().catch(() => false)) {
  await patentInput.fill('TW202617461');
}
const textarea = page.locator('textarea').filter({ visible: true }).first();
await glide(textarea);
await textarea.fill(oaText);
mark('oa_pasted');
await page.waitForTimeout(900);

// ---- phase 3: analyze (real qwen2.5:7b — sped up in post) ----
const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
await glide(analyzeBtn);
await page.waitForTimeout(400);
await analyzeBtn.click();
mark('analyze_clicked');
const visibleMain = page.locator('main').filter({ visible: true }).last();
await visibleMain.getByText('答辯策略').first().waitFor({ timeout: 240000 });
mark('result_ready');
await page.waitForTimeout(1200);

// ---- phase 4: results tour ----
const draft = visibleMain.getByText(/申復|申請人/).first();
if (await draft.isVisible().catch(() => false)) {
  await draft.scrollIntoViewIfNeeded();
}
await page.waitForTimeout(1400);
await page.mouse.wheel(0, 420);
await page.waitForTimeout(1400);
await page.mouse.wheel(0, 420);
await page.waitForTimeout(1400);
mark('results_done');

// ---- phase 5: audit + chain verify ----
await page.goto('http://localhost:5173/audit');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1100);
const verifyBtn = page.getByRole('button', { name: /驗證|verify/i }).first();
if (await verifyBtn.isVisible().catch(() => false)) {
  await glide(verifyBtn);
  await page.waitForTimeout(400);
  await verifyBtn.click();
  await page.waitForTimeout(2200);
} else {
  await page.waitForTimeout(2200);
}
mark('audit_done');
await page.waitForTimeout(700);
mark('end');

await context.close();   // flushes video
await browser.close();
const vid = readdirSync(OUT).find((f) => f.endsWith('.webm'));
writeFileSync(`${OUT}/marks.json`, JSON.stringify({ video: vid, marks }, null, 2));
console.log('RAW FOOTAGE →', `${OUT}/${vid}`);
