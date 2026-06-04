// OAUpload drag-drop e2e — drives the hidden <input type="file"> directly
// since DataTransfer is non-trivial to fake in Playwright. The DropZone
// click-target opens the input picker, but the file is delivered via
// setInputFiles() which fires the same onChange handler.
import { test, expect } from '@playwright/test';
import {
  loginAsAlice,
  mockUpload,
} from './helpers/mock_backend.js';

// Analyze.jsx renders BOTH a mobile <main xl:hidden> and a desktop
// <main hidden xl:grid>. Each mounts its own InputPane → OAUpload → file
// input. At desktop the mobile main is display:none and vice versa. We grab
// the file input whose ancestor <main> is the visible one — file inputs are
// `display:none` regardless, so we can't use `:visible` on them directly;
// instead, scope to the visible main first.
function fileInput(page) {
  // Filter mains by Playwright's visible engine, then drill down. Note that
  // the file input itself is `className="hidden"` (display:none) — that's
  // expected for file inputs and setInputFiles works on hidden inputs.
  return page
    .locator('main')
    .filter({ visible: true })
    .last()
    .locator('input[type="file"]');
}

// The visible-main scoper for assertions on text that may also live in the
// hidden duplicate. Use this everywhere a string like "已選擇" appears.
function visibleMain(page) {
  return page.locator('main').filter({ visible: true }).last();
}

test.describe('Upload flow', () => {
  // The mobile project still mounts OAUpload (it's inside the InputPane,
  // which renders on the default mobile tab), so these tests work on both.

  test('successful upload populates the textarea via onExtractSuccess', async ({ page }) => {
    await loginAsAlice(page);
    await mockUpload(page, {
      extracted_text: 'EXTRACTED OA TEXT for test — Claim 1 rejected under §103.',
      page_count: 3,
      char_count: 57,
      warnings: [],
      ocr_pages_used: 0,
      cost_meta: { estimated_cost_usd: 0 },
    });

    const input = fileInput(page);
    await input.setInputFiles({
      name: 'sample-oa.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4 fake pdf bytes for the e2e harness'),
    });

    // Scope to the visible main so we don't pick up the hidden mobile/desktop
    // duplicate that React also rendered (see fileInput() above).
    const main = visibleMain(page);

    // The status pane should now show the file name + an Upload button.
    await expect(main.getByText('sample-oa.pdf').first()).toBeVisible();
    const uploadBtn = main.getByRole('button', { name: /^上傳$/ });
    await expect(uploadBtn).toBeVisible();
    await uploadBtn.click();

    // After server-extracting → success, the "使用此文字" button appears.
    const useBtn = main.getByRole('button', { name: /使用此文字/ });
    await expect(useBtn).toBeVisible({ timeout: 5000 });
    await useBtn.click();

    // The textarea labelled "OA 全文" should now contain the extracted text.
    const textarea = main.locator('textarea').first();
    await expect(textarea).toHaveValue(/EXTRACTED OA TEXT/);
  });

  test('a >30MB file shows a size error', async ({ page }) => {
    await loginAsAlice(page);
    await mockUpload(page); // mocked, but the size guard fires client-side first.

    // 31 MB of zeroes — over the 30 MB hard ceiling.
    const tooBig = Buffer.alloc(31 * 1024 * 1024, 0);
    await fileInput(page).setInputFiles({
      name: 'huge-oa.pdf',
      mimeType: 'application/pdf',
      buffer: tooBig,
    });

    // The component renders the i18n string upload.too_large into a rose chip.
    await expect(visibleMain(page).getByText('檔案太大（>30MB）').first()).toBeVisible();
  });

  test('a .txt file is rejected with a type error', async ({ page }) => {
    await loginAsAlice(page);
    await mockUpload(page);

    await fileInput(page).setInputFiles({
      name: 'oa.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Office Action body text - not allowed'),
    });

    // upload.invalid_type → "只支援 PDF 或 DOCX"
    await expect(visibleMain(page).getByText('只支援 PDF 或 DOCX').first()).toBeVisible();
  });

  test('drop zone is keyboard-accessible (role=button)', async ({ page }) => {
    await loginAsAlice(page);

    // The DropZone is role=button and accepts space/enter.
    const dz = visibleMain(page)
      .getByRole('button', { name: /拖放.*PDF|browse files|瀏覽檔案/ })
      .first();
    await expect(dz).toBeVisible();
    // Ensure clickability — the click delegates to a hidden file input.
    await expect(dz).toBeEnabled();
  });
});
