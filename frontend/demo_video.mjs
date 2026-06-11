// Demo video raw footage recorder — v2 (PDF upload edition).
// Drives the LIVE stack at 1920×1080: login → drop a real TIPO OA PDF →
// auto-extract → AI analyze (real qwen2.5:7b) → guided results tour
// (rejections → draft → citations/deadline) → audit chain verify.
// Phase timestamps go to marks.json for scripts/make_demo_video.py.
// Run: node demo_video.mjs
import { chromium } from '@playwright/test';
import { writeFileSync, mkdirSync, readdirSync, rmSync } from 'node:fs';

const OUT = 'demo_video_out';
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
const PDF = '../docs/初審審查意見通知函.pdf';
// CASE-2025-002: alice has ACL; different case key → no cache hit → real run
const CASE_ID = 'CASE-2025-002';

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();

// synthetic cursor (Playwright renders none)
await page.addInitScript(() => {
  window.addEventListener('DOMContentLoaded', () => {
    const dot = document.createElement('div');
    dot.style.cssText =
      'position:fixed;z-index:99999;width:24px;height:24px;border-radius:50%;' +
      'background:rgba(245,176,32,.9);border:3px solid #fff;' +
      'box-shadow:0 2px 12px rgba(0,0,0,.4);pointer-events:none;' +
      'transition:transform .06s;left:0;top:0;transform:translate(-100px,-100px)';
    document.body.appendChild(dot);
    window.addEventListener('mousemove', (e) => {
      dot.style.transform = `translate(${e.clientX - 12}px, ${e.clientY - 12}px)`;
    }, { passive: true });
  });
});

const t0 = Date.now();
const marks = {};
const mark = (k) => { marks[k] = (Date.now() - t0) / 1000; console.log(k, marks[k].toFixed(1)); };
const glide = async (loc) => {
  const b = await loc.boundingBox();
  if (b) await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 28 });
};

// ---- 1. login ----
await page.goto('http://localhost:5173/');
await page.waitForLoadState('networkidle');
mark('login_page');
await page.waitForTimeout(1100);
const alice = page.getByText('Alice', { exact: false }).first();
await glide(alice);
await page.waitForTimeout(500);
await alice.click();
await page.waitForURL(/analyze/, { timeout: 15000 }).catch(() => {});
await page.waitForLoadState('networkidle');
mark('logged_in');
await page.waitForTimeout(1000);

// ---- 2. case id + drop the real PDF ----
const caseInput = page.getByPlaceholder(/CASE-/).first();
if (await caseInput.isVisible().catch(() => false)) {
  await glide(caseInput);
  await caseInput.fill(CASE_ID);
}
const patentInput = page.getByPlaceholder(/US\d|TW\d|專利/).first();
if (await patentInput.isVisible().catch(() => false)) {
  await patentInput.fill('TW202617461');
}
await page.waitForTimeout(500);
mark('pdf_dropping');
// two file inputs exist (duplicate layouts) — the LAST one is live
await page.locator('input[type="file"]').last().setInputFiles(PDF);
await page.waitForTimeout(1100);
// step 1: press 上傳 (upload + server-side extraction)
const uploadBtn = page.getByRole('button', { name: /^上傳$|^Upload$/ })
  .filter({ visible: true }).first();
await uploadBtn.waitFor({ timeout: 10000 });
await glide(uploadBtn);
await page.waitForTimeout(400);
await uploadBtn.click();
mark('upload_clicked');
// step 2: extraction done ⇔ 「使用此文字」 appears; clicking it moves the
// extracted PDF text into the analyze form
const acceptBtn = page.getByRole('button', { name: /使用此文字|use this text/i })
  .filter({ visible: true }).first();
await acceptBtn.waitFor({ timeout: 60000 });
await page.waitForTimeout(1400);          // let the preview register on film
mark('pdf_extracted');
await glide(acceptBtn);
await page.waitForTimeout(500);
await acceptBtn.click();
mark('text_accepted');
await page.waitForTimeout(1400);

// ---- 3. analyze (real inference — time-lapsed in post) ----
const analyzeBtn = page.getByRole('button', { name: /^分析 OA/ }).filter({ visible: true });
await glide(analyzeBtn);
await page.waitForTimeout(500);
await analyzeBtn.click();
mark('analyze_clicked');
const visibleMain = page.locator('main').filter({ visible: true }).last();
await visibleMain.getByText('答辯策略').first().waitFor({ timeout: 300000 });
mark('result_ready');

// ---- 4a. rejections / strategy ----
await page.waitForTimeout(800);
const strategy = visibleMain.getByText('答辯策略').first();
await glide(strategy);
await page.waitForTimeout(2600);
mark('rejections_viewed');

// ---- 4b. draft ----
const draft = visibleMain.getByText(/申復|申請人/).first();
if (await draft.isVisible().catch(() => false)) {
  await glide(draft);
  await draft.scrollIntoViewIfNeeded();
}
await page.waitForTimeout(1600);
await page.mouse.wheel(0, 380);
await page.waitForTimeout(1800);
mark('draft_viewed');

// ---- 4c. citations + deadline (right pane) ----
const refs = visibleMain.getByText(/引證|前案|期限/).first();
if (await refs.isVisible().catch(() => false)) {
  await glide(refs);
}
await page.mouse.wheel(0, 380);
await page.waitForTimeout(2400);
mark('deadline_viewed');

// ---- 5. audit chain verify ----
await page.goto('http://localhost:5173/audit');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1300);
const verifyBtn = page.getByRole('button', { name: /驗證|verify/i }).first();
if (await verifyBtn.isVisible().catch(() => false)) {
  await glide(verifyBtn);
  await page.waitForTimeout(500);
  await verifyBtn.click();
  await page.waitForTimeout(2600);
} else {
  await page.waitForTimeout(2600);
}
mark('audit_done');
await page.waitForTimeout(600);
mark('end');

await context.close();
await browser.close();
const vid = readdirSync(OUT).find((f) => f.endsWith('.webm'));
writeFileSync(`${OUT}/marks.json`, JSON.stringify({ video: vid, marks }, null, 2));
console.log('RAW FOOTAGE →', `${OUT}/${vid}`);
