// Stack-status footer (delivery polish) — the AppShell footer shows one chip
// per infrastructure tier (Gateway / AI Engine / digiRunner / Dify).
//
//   - Gateway is probed through the same-origin /api/v1/health (JSON body).
//   - The other three are opaque `no-cors` reachability probes: any HTTP
//     response = green "up"; connection refused / timeout = gray "unknown".
//
// All probes are mocked via mockStackProbes so the assertions are hermetic —
// a real digiRunner running on the dev machine must not change the outcome.
import { test, expect } from '@playwright/test';
import { loginAsAlice, mockStackProbes } from './helpers/mock_backend.js';

test.describe('Stack status footer', () => {
  test('renders all four service chips after login', async ({ page }) => {
    await mockStackProbes(page);
    await loginAsAlice(page);

    const footer = page.getByTestId('stack-status');
    await expect(footer).toBeVisible();
    for (const label of ['Gateway', 'AI Engine', 'digiRunner', 'Dify']) {
      await expect(footer.getByText(label)).toBeVisible();
    }
  });

  test('gateway green, unreachable externals gray', async ({ page }) => {
    await mockStackProbes(page, {
      gateway: true,
      aiEngine: false,
      digirunner: false,
      dify: false,
    });
    await loginAsAlice(page);

    await expect(page.getByTestId('stack-status-gateway')).toHaveAttribute('data-status', 'up');
    // Aborted probes settle to "unknown" — never an error banner.
    await expect(page.getByTestId('stack-status-ai-engine')).toHaveAttribute(
      'data-status',
      'unknown'
    );
    await expect(page.getByTestId('stack-status-digirunner')).toHaveAttribute(
      'data-status',
      'unknown'
    );
    await expect(page.getByTestId('stack-status-dify')).toHaveAttribute('data-status', 'unknown');
    // No error UI appears because of unreachable probes.
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('all chips green when every tier responds', async ({ page }) => {
    await mockStackProbes(page, {
      gateway: true,
      aiEngine: true,
      digirunner: true,
      dify: true,
    });
    await loginAsAlice(page);

    for (const id of ['gateway', 'ai-engine', 'digirunner', 'dify']) {
      await expect(page.getByTestId(`stack-status-${id}`)).toHaveAttribute('data-status', 'up');
    }
  });

  test('gateway 503 degrades to gray, not an error', async ({ page }) => {
    await mockStackProbes(page, { gateway: false });
    await loginAsAlice(page);

    await expect(page.getByTestId('stack-status-gateway')).toHaveAttribute(
      'data-status',
      'unknown'
    );
    await expect(page.getByRole('alert')).toHaveCount(0);
  });
});
