// Playwright config for PatentMind frontend e2e + visual regression tests.
//
// Two projects:
//   - chromium-desktop  : 1440x900 viewport (xl breakpoint, three-pane layout)
//   - chromium-mobile   : iPhone X emulation, 375x812 (mobile tab strip)
//
// CI is expected to install browsers with `npx playwright install --with-deps chromium`
// in a separate step before invoking `npx playwright test`.
import { defineConfig, devices } from '@playwright/test';

const PORT = 5173;
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Local runs hit the Vite DEV server (unbundled module graph). On Windows
  // the dev server cannot keep up with more than ~2 browser contexts doing a
  // full cold page load at once — page.goto('/') times out en masse at the
  // default worker count (empirically: 10 workers → ~60 goto timeouts,
  // 2 workers → all green). The `warmup` project below pre-transforms the
  // module graph; this cap keeps the dev server responsive. CI (Linux,
  // usually against a built preview) keeps Playwright's default count.
  workers: process.env.CI ? undefined : 2,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  // Keep snapshots under tests/e2e/__screenshots__/ so they live next to the spec.
  // Splitting by project name keeps desktop/mobile baselines apart on disk.
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}-{projectName}{ext}',
  expect: {
    // Cross-runner antialias tolerance: 5% pixel ratio per visual snapshot.
    toHaveScreenshot: {
      threshold: 0.05,
      maxDiffPixelRatio: 0.05,
      animations: 'disabled',
    },
    toMatchSnapshot: {
      threshold: 0.05,
      maxDiffPixelRatio: 0.05,
    },
  },
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      // Serial pre-pass that loads every major surface once so the Vite dev
      // server's module graph is transformed before the parallel projects
      // start (prevents mass page.goto timeouts on cold local runs).
      name: 'warmup',
      testMatch: /warmup\.setup\.js$/,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'chromium-desktop',
      dependencies: ['warmup'],
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'chromium-mobile',
      dependencies: ['warmup'],
      use: {
        // Use Chromium-based mobile emulation rather than `devices['iPhone X']`
        // (which switches the browser engine to WebKit and requires installing
        // the webkit binary in CI). Pixel 5 gives us a ~375x812-class viewport
        // with a mobile user agent.
        ...devices['Pixel 5'],
        // Force the exact viewport the trust-band / tab-strip tests expect.
        viewport: { width: 375, height: 812 },
      },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
