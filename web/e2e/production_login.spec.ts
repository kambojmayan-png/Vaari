import { test, expect } from '@playwright/test';

// Runs only in the production-mode pass of `python tasks.py e2e`
// (VAARI_ENV=production, synthetic accounts created in a temporary database).
test.skip(process.env.VAARI_E2E_MODE !== 'production', 'production-mode pass only');

const OPERATOR = { username: 'e2e-operator', password: 'e2e-operator-password-1' };
const OFFICER = { username: 'e2e-officer', password: 'e2e-officer-password-1' };

test('Production: staff sign in with accounts; the demo passcode is refused', async ({ page, request }) => {
  // The shared passcode is switched off in production.
  const viaPasscode = await request.get('/api/requests', { headers: { 'X-Vaari-Passcode': 'change-me' } });
  expect(viaPasscode.status()).toBe(401);
  const health = await (await request.get('/api/health')).json();
  expect(health.auth).toBe('accounts');
  expect(health.env).toBe('production');

  // Desk asks for a sign-in instead of opening.
  await page.goto('/desk');
  await expect(page.locator('#login-username')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#desk-page')).toHaveCount(0);

  // Wrong password: a plain message, still no data.
  await page.locator('#login-username').fill(OPERATOR.username);
  await page.locator('#login-password').fill('not-the-password');
  await page.locator('#login-submit').click();
  await expect(page.locator('#login-error')).toHaveText('Wrong username or password.');

  // Operator signs in and sees the Desk with the seed counts.
  await page.locator('#login-password').fill(OPERATOR.password);
  await page.locator('#login-submit').click();
  await expect(page.locator('#desk-page')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.metric-scheduled .metric-num')).toHaveText('28');

  // Sign out: the Desk asks again.
  await page.locator('#btn-sign-out').click();
  await expect(page.locator('#login-username')).toBeVisible({ timeout: 15000 });
});

test('Production: an officer can open Officer but not Desk', async ({ page }) => {
  await page.goto('/officer');
  await expect(page.locator('#login-username')).toBeVisible({ timeout: 15000 });
  await page.locator('#login-username').fill(OFFICER.username);
  await page.locator('#login-password').fill(OFFICER.password);
  await page.locator('#login-submit').click();
  await expect(page.locator('#officer-page')).toBeVisible({ timeout: 15000 });

  await page.goto('/desk');
  await expect(page.locator('#role-denied')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#desk-page')).toHaveCount(0);
});
