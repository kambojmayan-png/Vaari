import { test, expect } from '@playwright/test';
import { execFileSync } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test('Full Phase 3 End-to-End Scenario (TESTING.md Section 7: Steps 1 to 8)', async ({
  page,
  context,
}) => {
  // Unlock operator passcode gate on Desk
  await page.goto('/desk');
  const passcodeInput = page.locator('#passcode-input');
  if (await passcodeInput.isVisible({ timeout: 2000 }).catch(() => false)) {
    await passcodeInput.fill('change-me');
    await page.locator('#passcode-submit').click();
  }
  await expect(page.locator('#desk-page')).toBeVisible({ timeout: 15000 });

  // 1. Upload the synthetic register page on /intake. The mock reader returns a 6-row draft.
  await page.locator('#btn-add-register-photo').click();
  await expect(page.locator('#intake-page')).toBeVisible();
  await expect(page.locator('#intake-privacy-banner')).toContainText(
    'No real register page may go to a hosted model',
  );
  // Part 5: the banner names the reader in use and where photos go.
  await expect(page.locator('#intake-reader-name')).toContainText('Reader in use: mock');
  await expect(page.locator('#intake-reader-destination')).toHaveText('No photo leaves this server.');

  const registerFixture = path.resolve(__dirname, '../../tests/fixtures/sample_field.jpg');
  await page.locator('#intake-file-input').setInputFiles(registerFixture);

  await expect(page.locator('#intake-draft-table')).toBeVisible({ timeout: 10000 });
  const draftRows = page.locator('#intake-draft-table tbody tr');
  await expect(draftRows).toHaveCount(6);

  // 2. Correct one low-confidence / issue cell (Row 3 has 7-digit phone "9000000" and Row 5 has acres 40) and confirm.
  const row3Phone = page.locator('#intake-phone-3');
  await row3Phone.fill('9000000103');

  const row5Acres = page.locator('#intake-acres-5');
  await row5Acres.fill('4.0');

  // Skip row 6 to verify both creation and skipping
  await page.locator('#intake-skip-6').check();

  await page.locator('#btn-confirm-rows').click();
  const confirmBanner = page.locator('#intake-confirm-banner');
  await expect(confirmBanner).toBeVisible({ timeout: 10000 });
  await expect(confirmBanner).toContainText('Created 5 requests, skipped 1');

  // 3. Return to Desk, run the scheduler, and check the Desk counts (40 seeded + 5 confirmed = 45 total).
  await page.locator('#btn-return-desk-after-confirm').click();
  await expect(page.locator('#desk-page')).toBeVisible();

  await page.locator('#btn-run-scheduler').click();
  await expect(page.locator('#summary-metrics-bar')).toContainText('45');

  // 4. Set one machine inactive. The plan reflows and a will-miss reason appears.
  await page.locator('#tab-machines').click();
  await expect(page.locator('#machines-tab')).toBeVisible();
  await page.locator('#btn-toggle-machine-2').click();
  await expect(
    page.locator('#machine-card-2 .machine-title-row .status-pill'),
  ).toHaveText('inactive');

  await page.locator('#tab-will-miss').click();
  await expect(page.locator('#will-miss-tab')).toBeVisible();
  await expect(page.locator('.will-miss-table tbody tr').first()).toBeVisible();

  // Re-activate Super Seeder 02 and reflow
  await page.locator('#tab-machines').click();
  await page.locator('#btn-toggle-machine-2').click();
  await expect(
    page.locator('#machine-card-2 .machine-title-row .status-pill'),
  ).toHaveText('active');
  await page.locator('#btn-run-scheduler').click();

  // 5. Open a slot's message. The wa.me link contains the Punjabi text and 4-digit service code.
  await page.locator('#tab-requests').click();
  await page.locator('#req-row-1').click();
  await expect(page.locator('#request-detail-panel')).toBeVisible();
  await page.locator('#btn-panel-message').click();

  const waBtn = page.locator('#btn-whatsapp-msg');
  await expect(waBtn).toBeVisible();
  const waHref = (await waBtn.getAttribute('href'))!;
  expect(waHref).toContain('https://wa.me/91');
  const decodedMsg = decodeURIComponent(new URL(waHref).searchParams.get('text') || '');
  expect(decodedMsg).toContain('ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਜੀ');
  const serviceCode = decodedMsg.match(/\b\d{4}\b/)![0];

  await page.locator('.panel-close-btn').click();
  await page.locator('#tab-machines').click();
  const driverPath = (await page
    .locator('#machine-card-1 a[href^="/driver/"]')
    .getAttribute('href'))!;

  // 6. On the Driver page: Start with a photo and position at the demo plot, then Done with a photo and service code.
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ latitude: 30.7333, longitude: 76.7794 });

  await page.goto(driverPath);
  await expect(page.locator('#driver-page')).toBeVisible();

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

  // Verify live job triggers too_fast flag in plain words on Driver view
  await expect(page.locator('#evidence-summary-ticks')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#driver-flags-list')).toContainText(
    'Finished faster than a machine can work: a person will look',
  );

  // 7. The Record page shows request -> assignment -> start -> completion -> outcome, and Verify matches.
  await page.locator('#btn-view-record-link').click();
  await expect(page.locator('#record-page')).toBeVisible();
  const timeline = page.locator('#record-timeline');
  await expect(timeline).toContainText('Step 1 • Request Intake');
  await expect(timeline).toContainText('Step 2 • Machine Assignment');
  await expect(timeline).toContainText('Step 3 • Start Evidence');
  await expect(timeline).toContainText('Step 4 • Completion Evidence');
  await expect(timeline).toContainText('Step 5 • Final Service Outcome');
  await expect(timeline).toContainText('plausible');
  await expect(timeline).toContainText('Code confirmed');

  await page.locator('#btn-verify-hash').click();
  await expect(page.locator('#verify-result-banner')).toContainText('Matches');

  // 8. The Officer dashboard's completed count has moved by one and needs_review reflects the flags.
  await page.goto('/officer');
  await expect(page.locator('#officer-page')).toBeVisible();
  await expect(page.locator('#metric-completed .metric-num')).toHaveText('1');
  const needsReviewText = await page.locator('#metric-needs-review .metric-num').textContent();
  expect(Number(needsReviewText)).toBeGreaterThanOrEqual(1);
  await expect(page.locator('#officer-flagged-jobs-table')).toContainText('VR-1');
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
  execFileSync(py, ['-c', resetPy], {
    cwd: path.resolve(__dirname, '../..'),
    env: process.env,
  });
});
