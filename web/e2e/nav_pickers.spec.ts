import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PHOTO = fs.readFileSync(path.resolve(__dirname, '../../tests/fixtures/start_field.jpg'));
const PASS = { 'X-Vaari-Passcode': 'change-me' };

// The navbar's Driver View and Record View used to open made-up tokens and always showed
// "not found". They now open pickers that list real machines and real completed jobs.
test.skip(process.env.VAARI_E2E_MODE === 'production', 'development-mode pass only');

test('Driver View lists machines and opens a real driver page', async ({ page }) => {
  await page.goto('/desk');
  await page.locator('#nav-driver').click();
  await expect(page).toHaveURL(/\/driver$/);
  await expect(page.locator('#driver-picker-page')).toBeVisible({ timeout: 15000 });
  await page.locator('#open-driver-1').click();
  await expect(page).toHaveURL(/\/driver\/[A-Za-z0-9_-]{16,}/);
  await expect(page.locator('#driver-header')).toBeVisible({ timeout: 15000 });
});

test('A wrong driver link says the link is not working, not a connection issue', async ({ page }) => {
  await page.goto('/driver/not-a-real-token');
  await expect(page.locator('#driver-error-title')).toHaveText('Link not working', { timeout: 15000 });
  await expect(page.getByText('This driver link does not exist')).toBeVisible();
});

test('Record View lists completed jobs and opens a real record', async ({ page, request }) => {
  // Finish one scheduled job through the API so a record exists.
  const slots = await (await request.get('/api/slots', { headers: PASS })).json();
  const slot = slots.find((s: { status: string }) => s.status === 'scheduled');
  expect(slot).toBeTruthy();
  const photo = { name: 'p.jpg', mimeType: 'image/jpeg', buffer: PHOTO };
  expect((await request.post(`/api/slots/${slot.id}/start`, { headers: PASS, multipart: { photo } })).status()).toBe(200);
  expect((await request.post(`/api/slots/${slot.id}/done`, { headers: PASS, multipart: { photo } })).status()).toBe(200);

  await page.goto('/desk');
  await page.locator('#nav-record').click();
  await expect(page).toHaveURL(/\/record$/);
  await expect(page.locator('#record-picker-page')).toBeVisible({ timeout: 15000 });
  const first = page.locator(`#open-record-${slot.id}`);
  await expect(first).toBeVisible({ timeout: 15000 });
  await first.click();
  await expect(page).toHaveURL(/\/record\/[A-Za-z0-9_-]{16,}/);
  await expect(page.getByText('Service Record Not Found')).toHaveCount(0);
});
