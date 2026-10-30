import { test, expect } from '@playwright/test';

// Part 5: the intake screen always names the reader and says when photos go to a third party.
// The server runs the mock reader, so /api/health is replaced here to show the Gemini case.
test.skip(process.env.VAARI_E2E_MODE === 'production', 'development-mode pass only');

test('Intake banner says photos go to Google when the Gemini demo reader is on', async ({ page }) => {
  await page.route('**/api/health', async route => {
    const res = await route.fetch();
    const body = await res.json();
    body.reader = 'hosted';
    body.reader_detail = {
      name: 'gemini_demo', kind: 'hosted', provider: 'Google Gemini', model: 'example-model',
      third_party: true, demo_only: true, probe: { status: 'ok', latency_ms: 812 },
    };
    await route.fulfill({ response: res, json: body });
  });
  await page.goto('/intake');
  const banner = page.locator('#intake-privacy-banner');
  await expect(banner).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#intake-reader-name')).toHaveText(
    'Reader in use: Google Gemini (example-model), demonstration only.',
  );
  await expect(page.locator('#intake-reader-destination')).toHaveText(
    'Photos you upload here are sent to Google, a third party. Use synthetic pages only.',
  );
  await expect(banner).toHaveClass(/outcome-error/);
  // A sideways page can be turned before it is stored and read.
  await expect(page.locator('#intake-rotate')).toHaveValue('0');
});

test('Intake banner shows the type-the-rows fallback when the reader is down', async ({ page }) => {
  await page.route('**/api/health', async route => {
    const res = await route.fetch();
    const body = await res.json();
    body.reader = 'down';
    await route.fulfill({ response: res, json: body });
  });
  await page.goto('/intake');
  await expect(page.locator('#intake-reader-down')).toContainText('type the rows beside the photo');
});
