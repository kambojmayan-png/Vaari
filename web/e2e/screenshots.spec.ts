import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const screenshotsDir = path.resolve(__dirname, '../../docs/screenshots');

test('Capture application screenshots for documentation', async ({ page, context }) => {
  if (!fs.existsSync(screenshotsDir)) {
    fs.mkdirSync(screenshotsDir, { recursive: true });
  }

  // 1. Operator Desk
  await page.goto('/desk');
  const passcodeInput = page.locator('#passcode-input');
  if (await passcodeInput.isVisible({ timeout: 2000 }).catch(() => false)) {
    await passcodeInput.fill('change-me');
    await page.locator('#passcode-submit').click();
  }
  await expect(page.locator('#desk-page')).toBeVisible({ timeout: 15000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(screenshotsDir, 'desk.png'), fullPage: false });

  // 2. Register Intake
  await page.locator('#btn-add-register-photo').click();
  await expect(page.locator('#intake-page')).toBeVisible();
  const registerFixture = path.resolve(__dirname, '../../tests/fixtures/sample_field.jpg');
  await page.locator('#intake-file-input').setInputFiles(registerFixture);
  await expect(page.locator('#intake-draft-table')).toBeVisible({ timeout: 10000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(screenshotsDir, 'intake.png'), fullPage: false });

  // Correct and confirm row so we have a clean pipeline and a machine link
  const row3Phone = page.locator('#intake-phone-3');
  await row3Phone.fill('9000000103');
  const row5Acres = page.locator('#intake-acres-5');
  await row5Acres.fill('4.0');
  await page.locator('#intake-skip-6').check();
  await page.locator('#btn-confirm-rows').click();
  await expect(page.locator('#intake-confirm-banner')).toBeVisible({ timeout: 10000 });

  await page.locator('#btn-return-desk-after-confirm').click();
  await expect(page.locator('#desk-page')).toBeVisible();

  await page.locator('#tab-requests').click();
  await page.locator('#req-row-1').click();
  await expect(page.locator('#request-detail-panel')).toBeVisible();
  await page.locator('#btn-panel-message').click();
  const waBtn = page.locator('#btn-whatsapp-msg');
  await expect(waBtn).toBeVisible();
  const waHref = (await waBtn.getAttribute('href'))!;
  const decodedMsg = decodeURIComponent(new URL(waHref).searchParams.get('text') || '');
  const serviceCode = decodedMsg.match(/\b\d{4}\b/)![0];

  await page.locator('.panel-close-btn').click();
  await page.locator('#tab-machines').click();
  const driverPath = (await page
    .locator('#machine-card-1 a[href^="/driver/"]')
    .getAttribute('href'))!;

  // 3. Driver Execution Portal
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ latitude: 30.7333, longitude: 76.7794 });
  await page.goto(driverPath);
  await expect(page.locator('#driver-page')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(screenshotsDir, 'driver.png'), fullPage: false });

  // Complete job to generate service record
  await page.locator('.driver-job-card.card-status-scheduled').first().click();
  const startFixture = path.resolve(__dirname, '../../tests/fixtures/start_field.jpg');
  await page.locator('#driver-camera-input').setInputFiles(startFixture);
  await page.locator('#btn-start-job').click();
  await expect(page.locator('#evidence-summary-ticks')).toBeVisible({ timeout: 15000 });
  await page.locator('#btn-continue-job').click();

  const doneFixture = path.resolve(__dirname, '../../tests/fixtures/done_field.jpg');
  await page.locator('#driver-camera-input-done').setInputFiles(doneFixture);
  await page.locator('#farmer-code-input').fill(serviceCode);
  await page.locator('#btn-done-job').click();
  await expect(page.locator('#evidence-summary-ticks')).toBeVisible({ timeout: 15000 });

  // 4. Audit Service Record
  await page.locator('#btn-view-record-link').click();
  await expect(page.locator('#record-page')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(screenshotsDir, 'record.png'), fullPage: false });

  // 5. Officer Dashboard
  await page.goto('/officer');
  await expect(page.locator('#officer-page')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(screenshotsDir, 'officer.png'), fullPage: false });
});

test.afterAll(async () => {
  // tasks.py e2e passes the Python it runs the server with. CI has no .venv, so the old
  // hard-coded .venv path failed there and left the database half-reset for later specs.
  const py =
    process.env.VAARI_PYTHON ||
    (process.platform === 'win32'
      ? path.resolve(__dirname, '../../.venv/Scripts/python.exe')
      : path.resolve(__dirname, '../../.venv/bin/python'));
  const resetPy = `
from app.db import get_engine, get_session_factory
from app.seed.seed import seed_data
from sqlalchemy import text
from pathlib import Path
import shutil
from app.config import settings

engine = get_engine()
with engine.begin() as conn:
    conn.execute(text("PRAGMA foreign_keys = OFF;"))
    tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")).fetchall()
    for (t,) in tables:
        conn.execute(text(f'DROP TABLE IF EXISTS "{t}";'))
    conn.execute(text("PRAGMA foreign_keys = ON;"))

from app.migrate import ensure_schema
ensure_schema(engine)  # rebuild through the migrations, as the server expects
with get_session_factory()() as session:
    seed_data(session)

data_dir = Path(settings.data_dir)
for sub in ["photos", "register_pages"]:
    target = data_dir / sub
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
`;
  const { execFileSync } = await import('child_process');
  execFileSync(py, ['-c', resetPy], {
    cwd: path.resolve(__dirname, '../..'),
    env: process.env,
  });
});
