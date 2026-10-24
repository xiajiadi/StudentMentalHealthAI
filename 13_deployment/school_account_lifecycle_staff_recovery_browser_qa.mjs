import { randomBytes } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');
const STAGES = [
  'admin_login', 'admin_route', 'staff_row', 'recovery_dialog', 'recovery_issued',
    'recovery_dialog_mobile', 'secret_not_rendered', 'handoff_mobile', 'encrypted_download',
    'reset_completed', 'replay_rejected', 'staff_login', 'logout',
];

function readInput() {
  return new Promise((resolve) => {
    let raw = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { raw += chunk; });
    process.stdin.on('end', () => {
      try { resolve(JSON.parse(raw)); } catch { resolve(null); }
    });
  });
}

function validPayload(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value)
    && value.frontend_url === 'http://127.0.0.1:4178'
    && value.backend_url === 'http://127.0.0.1:8088'
    && value.school_ref === 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1'
    && typeof value.artifact_dir === 'string' && path.isAbsolute(value.artifact_dir)
    && typeof value.employee_ref === 'string' && /^LCQA-UI-RESET-[A-F0-9]{12}$/.test(value.employee_ref)
    && typeof value.staff_login_name === 'string' && /^STAFF_[a-f0-9]{12}_[a-f0-9]{32}$/.test(value.staff_login_name)
    && typeof value.staff_user_id === 'string' && /^USER_[A-Za-z0-9_-]{16,}$/.test(value.staff_user_id)
    && value.admin && typeof value.admin.username === 'string' && value.admin.username.startsWith('SYNTHETIC_')
    && typeof value.admin.password === 'string' && value.admin.password.length >= 16);
}

function fail(output, stage, code, httpStatus) {
  output.status = 'FAIL';
  output.failure = { stage, code, ...(Number.isInteger(httpStatus) ? { http_status: httpStatus } : {}) };
  throw new Error('QA_STOP');
}

async function apiData(response) {
  try {
    const envelope = await response.json();
    return envelope?.data ?? null;
  } catch {
    return null;
  }
}

async function main() {
  const payload = await readInput();
  if (!validPayload(payload)) {
    process.stdout.write(JSON.stringify({ status: 'FAIL', failure: { stage: 'payload', code: 'INVALID_TEST_CONTEXT' } }));
    process.exitCode = 2;
    return;
  }
  const output = {
    status: 'FAIL',
    stages: Object.fromEntries(STAGES.map((stage) => [stage, 'FAIL'])),
  };
  let browser;
  let page;
  let recoveryCredential = '';
  let newPassword = '';
  let downloadedPath = '';
  let checkpoint = 'browser_launch';
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: true });
    page = await context.newPage({ viewport: { width: 1440, height: 900 } });
    checkpoint = 'login_page';
    await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.locator('#account').waitFor({ state: 'visible', timeout: 15000 });
    await page.locator('#account').fill(payload.admin.username);
    await page.locator('#password').fill(payload.admin.password);
    checkpoint = 'login_submit';
    await page.getByRole('button', { name: '登录', exact: true }).click();
    const contextPicker = page.locator('#school-context');
    if (await contextPicker.isVisible({ timeout: 2500 }).catch(() => false)) {
      const target = await contextPicker.locator('option:not([disabled])').evaluateAll((options, schoolRef) => {
        const match = options.filter((option) => option.textContent?.includes(schoolRef)
          && option.textContent?.includes('学校管理员'));
        return match.length === 1 ? match[0].value : null;
      }, payload.school_ref);
      if (!target) fail(output, 'admin_login', 'ADMIN_CONTEXT_AMBIGUOUS');
      await contextPicker.selectOption(target);
      await page.getByRole('button', { name: '继续', exact: true }).click();
    }
    await page.waitForURL((url) => url.pathname === '/admin/overview', { timeout: 20000 });
    output.stages.admin_login = 'PASS';

    checkpoint = 'admin_route';
    await page.getByRole('link', { name: '账号管理', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/admin/users', { timeout: 15000 });
    await page.locator('#lifecycle-title').waitFor({ state: 'visible', timeout: 15000 });
    output.stages.admin_route = 'PASS';

    await page.getByRole('tab', { name: '教职工邀请', exact: true }).click();
    const invitation = page.locator('.lifecycle__invitation').filter({ hasText: payload.employee_ref });
    await invitation.waitFor({ state: 'visible', timeout: 15000 });
    if (await invitation.count() !== 1) fail(output, 'staff_row', 'STAFF_ROW_NOT_UNIQUE');
    output.stages.staff_row = 'PASS';
    await page.locator('input[autocomplete="current-password"]').fill(payload.admin.password);
    await invitation.getByRole('button', { name: '重置凭据', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ state: 'visible', timeout: 10000 });
    await dialog.locator('select').selectOption('IN_PERSON');
    await dialog.locator('input[type="checkbox"]').check();
    await page.screenshot({
      path: path.join(payload.artifact_dir, 'staff-recovery-dialog.png'),
      fullPage: false,
      animations: 'disabled',
    });
    output.stages.recovery_dialog = 'PASS';
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    await page.screenshot({ path: path.join(payload.artifact_dir, 'staff-recovery-dialog-390.png'), fullPage: false, animations: 'disabled' });
    if (documentWidth > 390) {
      fail(output, 'recovery_dialog_mobile', 'MOBILE_DOCUMENT_OVERFLOW');
    }
    output.stages.recovery_dialog_mobile = 'PASS';
    await page.setViewportSize({ width: 1440, height: 900 });

    const resetResponsePromise = page.waitForResponse((response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/v1/school/admin/staff/${payload.staff_user_id}/recovery-credential`,
    { timeout: 30000 });
    checkpoint = 'staff_reset';
    await dialog.getByRole('button', { name: '签发一次性凭据', exact: true }).click();
    const resetResponse = await resetResponsePromise;
    if (resetResponse.status() !== 200) fail(output, 'recovery_issued', 'RESET_HTTP_STATUS', resetResponse.status());
    const reset = await apiData(resetResponse);
    recoveryCredential = typeof reset?.credential === 'string' ? reset.credential : '';
    if (reset?.status !== 'ISSUED' || reset?.delivery_channel !== 'MANUAL_HANDOFF_REQUIRED'
      || !recoveryCredential || reset?.login_name !== payload.staff_login_name) {
      fail(output, 'recovery_issued', 'RESET_RESULT_MISMATCH');
    }
    output.stages.recovery_issued = 'PASS';

    const visibleText = await page.locator('body').innerText();
    if (visibleText.includes(recoveryCredential)) fail(output, 'secret_not_rendered', 'CREDENTIAL_RENDERED_IN_UI');
    await page.getByRole('tab', { name: '一次性凭据', exact: true }).waitFor({ state: 'visible', timeout: 10000 });
    await page.setViewportSize({ width: 390, height: 844 });
    const handoffWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    if (handoffWidth > 390) fail(output, 'handoff_mobile', 'MOBILE_OVERFLOW');
    await page.screenshot({
      path: path.join(payload.artifact_dir, 'staff-recovery-handoff-390.png'),
      fullPage: false,
      animations: 'disabled',
    });
    output.stages.handoff_mobile = 'PASS';
    output.stages.secret_not_rendered = 'PASS';

    const passphrase = `${randomBytes(32).toString('base64url')}Qx8!`;
    await page.locator('input[autocomplete="new-password"]').fill(passphrase);
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
    await page.getByRole('button', { name: '加密下载', exact: true }).click();
    const download = await downloadPromise;
    downloadedPath = await download.path() ?? '';
    if (!downloadedPath) fail(output, 'encrypted_download', 'DOWNLOAD_PATH_UNAVAILABLE');
    const bytes = await fs.readFile(downloadedPath);
    const fileText = bytes.toString('utf8');
    let encrypted;
    try { encrypted = JSON.parse(fileText); } catch { fail(output, 'encrypted_download', 'ENCRYPTED_FORMAT_INVALID'); }
    if (encrypted?.format !== 'psynova-credentials-encrypted-v1'
      || encrypted?.algorithm !== 'AES-256-GCM' || encrypted?.kdf !== 'PBKDF2-SHA-256'
      || fileText.includes(recoveryCredential)) fail(output, 'encrypted_download', 'ENCRYPTED_FORMAT_INVALID');
    await fs.unlink(downloadedPath).catch(() => {});
    downloadedPath = '';
    output.stages.encrypted_download = 'PASS';

    newPassword = `${randomBytes(32).toString('base64url')}Yc5!`;
    checkpoint = 'reset_complete';
    const completeBody = {
      school_ref: payload.school_ref,
      username: payload.staff_login_name,
      credential: recoveryCredential,
      new_password: newPassword,
      confirm_password: newPassword,
    };
    const complete = await fetch(`${payload.backend_url}/api/v1/auth/password/reset/complete`, {
      method: 'POST',
      headers: { Origin: payload.frontend_url, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(completeBody),
    });
    if (complete.status !== 200) fail(output, 'reset_completed', 'RESET_COMPLETE_HTTP_STATUS', complete.status);
    output.stages.reset_completed = 'PASS';
    const replay = await fetch(`${payload.backend_url}/api/v1/auth/password/reset/complete`, {
      method: 'POST',
      headers: { Origin: payload.frontend_url, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(completeBody),
    });
    if (![401, 409].includes(replay.status)) fail(output, 'replay_rejected', 'RESET_REPLAY_NOT_REJECTED', replay.status);
    output.stages.replay_rejected = 'PASS';

    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    await page.locator('#account').fill(payload.staff_login_name);
    await page.locator('#password').fill(newPassword);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/teacher/overview', { timeout: 20000 });
    const actor = await page.evaluate(async (backendUrl) => {
      const response = await fetch(`${backendUrl}/api/v1/auth/me`, { credentials: 'include' });
      let envelope = null;
      try { envelope = await response.json(); } catch { /* Keep result minimal */ }
      return { status: response.status, role: envelope?.data?.role, school: envelope?.data?.active_context?.school_ref };
    }, payload.backend_url);
    if (actor.status !== 200 || actor.role !== 'TEACHER' || actor.school !== payload.school_ref) {
      fail(output, 'staff_login', 'STAFF_SESSION_MISMATCH');
    }
    output.stages.staff_login = 'PASS';
    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    output.stages.logout = 'PASS';
    output.status = 'PASS';
  } catch (error) {
    if (!output.failure) {
      const known = error?.message === 'QA_STOP' ? null : error;
      output.failure = {
        stage: checkpoint,
        code: known?.name === 'TimeoutError' ? 'ACTION_TIMEOUT' : 'BROWSER_ACTION_FAILED',
      };
    }
  } finally {
    if (downloadedPath) await fs.unlink(downloadedPath).catch(() => {});
    recoveryCredential = '';
    newPassword = '';
    if (browser) await browser.close().catch(() => {});
  }
  output.status = output.status === 'PASS' && STAGES.every((stage) => output.stages[stage] === 'PASS') ? 'PASS' : 'FAIL';
  process.stdout.write(JSON.stringify(output));
  if (output.status !== 'PASS') process.exitCode = 2;
}

await main();
