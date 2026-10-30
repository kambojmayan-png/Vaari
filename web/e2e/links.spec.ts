import { test, expect } from '@playwright/test';

// Pilot item A4: driver links can be turned off and replaced from the Desk.
// Uses machine 3 (Baler 01, in repair in the seed) so the other specs keep their links.
test.skip(process.env.VAARI_E2E_MODE === 'production', 'development-mode pass only');

test('Driver link: turn off shows a plain message, New link brings it back', async ({ page, request }) => {
  page.on('dialog', d => d.accept());
  // A5: the Content-Security-Policy must not block anything the app itself loads.
  const cspViolations: string[] = [];
  page.on('console', msg => {
    if (/Content Security Policy|Refused to/i.test(msg.text())) cspViolations.push(msg.text());
  });
  await page.goto('/desk');
  await expect(page.locator('#desk-page')).toBeVisible({ timeout: 15000 });
  await page.locator('#tab-machines').click();
  await expect(page.locator('#driver-link-state-3')).toContainText('link active');

  const oldPath = await page.locator('#machine-card-3 .driver-url-input').inputValue();
  await page.locator('#btn-revoke-link-3').click();
  await expect(page.locator('#driver-link-state-3')).toContainText('link turned off');

  const res = await request.get('/api/driver/' + oldPath.split('/driver/')[1]);
  expect(res.status()).toBe(410);
  await page.goto(new URL(oldPath).pathname);
  await expect(page.getByText('This link has expired or was turned off')).toBeVisible({ timeout: 15000 });

  await page.goto('/desk');
  await page.locator('#tab-machines').click();
  await page.locator('#btn-rotate-link-3').click();
  await expect(page.locator('#driver-link-state-3')).toContainText('link active');
  const newPath = await page.locator('#machine-card-3 .driver-url-input').inputValue();
  expect(newPath).not.toBe(oldPath);
  expect(cspViolations).toEqual([]);
});
