import { randomBytes } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');
const VIEWPORTS = [1440, 1024, 768, 390];
const CHECKPOINTS = new Set([
  'browser_launch', 'login_page', 'admin_login', 'admin_workspace', 'responsive_capture', 'keyboard_tabs',
  'first_login_mode', 'first_login_form', 'first_login_submit', 'first_login_click',
  'first_login_response', 'first_login_result', 'return_to_login', 'student_login',
  'student_home', 'role_denial', 'responsive_capture', 'logout', 'credential_replay',
]);

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
  return Boolean(value && typeof value === 'object'
    && typeof value.frontend_url === 'string' && value.frontend_url === 'http://127.0.0.1:4178'
    && typeof value.backend_url === 'string' && value.backend_url === 'http://127.0.0.1:8088'
    && value.school_ref === 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1'
    && typeof value.username === 'string'
    && /^SYNTHETIC_ROSTER_[A-Za-z0-9_]+_[a-f0-9]{12}_[a-f0-9]{32}$/.test(value.username)
    && typeof value.credential === 'string' && value.credential.length >= 32
    && value.admin && typeof value.admin.username === 'string' && value.admin.username.startsWith('SYNTHETIC_')
    && typeof value.admin.password === 'string' && value.admin.password.length >= 16
    && path.isAbsolute(value.artifact_dir));
}

async function main() {
  const payload = await readInput();
  if (!validPayload(payload)) {
    process.stdout.write(JSON.stringify({ status: 'FAIL', failure: { stage: 'payload', code: 'INVALID_TEST_CONTEXT' } }));
    process.exitCode = 2;
    return;
  }

  const result = {
    status: 'FAIL',
    stages: {
      admin_login: 'FAIL', admin_workspace: 'FAIL', keyboard_tabs: 'FAIL', first_login_mobile: 'FAIL',
      first_login: 'FAIL', student_login: 'FAIL', role_denied: 'FAIL',
      viewport_1440: 'FAIL', viewport_1024: 'FAIL', viewport_768: 'FAIL', viewport_390: 'FAIL',
      logout: 'FAIL', credential_replay_rejected: 'FAIL',
    },
    viewport_widths: {}, student_viewport_widths: {}, screenshots: {},
  };
  let browser;
  let page;
  let checkpoint = 'browser_launch';
  let initialCredential = payload.credential;
  let adminPassword = payload.admin.password;
  let firstPassword = '';
  let firstLoginRequestSeen = false;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    page = await context.newPage({ viewport: { width: 1440, height: 900 } });
    page.on('request', (request) => {
      try {
        if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/auth/first-login') {
          firstLoginRequestSeen = true;
        }
      } catch { /* keep diagnostics limited to a boolean */ }
    });
    checkpoint = 'login_page';
    await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.locator('#account').fill(payload.admin.username);
    await page.locator('#password').fill(adminPassword);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    const contextPicker = page.locator('#school-context');
    if (await contextPicker.isVisible({ timeout: 2500 }).catch(() => false)) {
      const matchingOption = await contextPicker.locator('option:not([disabled])').evaluateAll(
        (options, schoolRef) => {
          const matches = options.filter((option) => option.textContent?.includes(schoolRef)
            && option.textContent?.includes('学校管理员'));
          return matches.length === 1 ? matches[0].value : null;
        },
        payload.school_ref,
      );
      if (!matchingOption) {
        result.failure = { stage: 'admin_login', code: 'ADMIN_CONTEXT_AMBIGUOUS' };
        throw new Error('QA_STOP');
      }
      await contextPicker.selectOption(matchingOption);
      await page.getByRole('button', { name: '继续', exact: true }).click();
    }
    checkpoint = 'admin_login';
    await page.waitForURL((url) => url.pathname === '/admin/overview', { timeout: 20000 });
    result.stages.admin_login = 'PASS';

    checkpoint = 'admin_workspace';
    await page.getByRole('link', { name: '账号管理', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/admin/users', { timeout: 15000 });
    await page.locator('#lifecycle-title').waitFor({ state: 'visible', timeout: 15000 });
    await page.locator('.lifecycle__metrics').waitFor({ state: 'visible', timeout: 15000 });
    result.stages.admin_workspace = 'PASS';

    checkpoint = 'responsive_capture';
    for (const width of VIEWPORTS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : width === 768 ? 1024 : 900 });
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      result.viewport_widths[String(width)] = scrollWidth;
      result.stages[`viewport_${width}`] = scrollWidth <= width ? 'PASS' : 'FAIL';
      const screenshotPath = path.join(payload.artifact_dir, `account-lifecycle-admin-${width}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true, animations: 'disabled' });
      result.screenshots[`admin_${width}`] = screenshotPath;
      if (scrollWidth > width) {
        result.failure = { stage: `viewport_${width}`, code: 'HORIZONTAL_OVERFLOW' };
        throw new Error('QA_STOP');
      }
    }
    checkpoint = 'keyboard_tabs';
    const tabs = page.getByRole('tab');
    const tabCount = await tabs.count();
    if (tabCount !== 6) {
      result.failure = { stage: 'keyboard_tabs', code: 'TAB_COUNT_MISMATCH' };
      throw new Error('QA_STOP');
    }
    await tabs.first().focus();
    await page.keyboard.press('End');
    if (await tabs.last().getAttribute('aria-selected') !== 'true') {
      result.failure = { stage: 'keyboard_tabs', code: 'END_KEY_NAVIGATION_FAILED' };
      throw new Error('QA_STOP');
    }
    result.stages.keyboard_tabs = 'PASS';

    checkpoint = 'logout';
    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });

    checkpoint = 'first_login_mode';
    await page.getByRole('button', { name: '首次登录', exact: true }).click();
    checkpoint = 'first_login_form';
    await page.getByRole('heading', { name: '首次登录', exact: true }).waitFor({ state: 'visible', timeout: 10000 });
    await page.setViewportSize({ width: 390, height: 844 });
    const firstLoginWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    result.stages.first_login_mobile = firstLoginWidth <= 390 ? 'PASS' : 'FAIL';
    result.first_login_mobile_width = firstLoginWidth;
    if (firstLoginWidth > 390) {
      result.failure = { stage: 'first_login_mobile', code: 'HORIZONTAL_OVERFLOW' };
      throw new Error('QA_STOP');
    }
    const firstLoginScreenshot = path.join(payload.artifact_dir, 'account-lifecycle-first-login-390.png');
    await page.screenshot({ path: firstLoginScreenshot, fullPage: true, animations: 'disabled' });
    result.screenshots.first_login_390 = firstLoginScreenshot;
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByLabel('学校编号', { exact: true }).fill(payload.school_ref);
    await page.getByLabel('账号', { exact: true }).fill(payload.username);
    await page.getByLabel('一次性凭据', { exact: true }).fill(initialCredential);
    firstPassword = `${randomBytes(24).toString('base64url')}Aa1!`;
    await page.getByLabel('新密码', { exact: true }).fill(firstPassword);
    await page.getByLabel('确认新密码', { exact: true }).fill(firstPassword);
    checkpoint = 'first_login_click';
    const firstLoginResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/first-login',
    { timeout: 30000 });
    await page.getByRole('button', { name: '提交', exact: true }).click();
    checkpoint = 'first_login_response';
    const firstLogin = await firstLoginResponse;
    if (firstLogin.status() !== 200) {
      result.failure = { stage: 'first_login', code: 'FIRST_LOGIN_HTTP_STATUS', http_status: firstLogin.status() };
      throw new Error('QA_STOP');
    }
    checkpoint = 'first_login_result';
    await page.getByText('密码已更新，请返回登录', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
    result.stages.first_login = 'PASS';

    checkpoint = 'return_to_login';
    await page.getByRole('button', { name: '返回登录', exact: true }).click();
    checkpoint = 'student_login';
    await page.locator('#account').fill(payload.username);
    await page.locator('#password').fill(firstPassword);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/student/home', { timeout: 20000 });
    checkpoint = 'student_home';
    const actor = await page.evaluate(async (backendUrl) => {
      const response = await fetch(`${backendUrl}/api/v1/auth/me`, { credentials: 'include' });
      let body = null;
      try { body = await response.json(); } catch { /* use fixed result below */ }
      return { status: response.status, actor: body?.data?.actor ?? body?.data };
    }, payload.backend_url);
    if (actor.status !== 200 || actor.actor?.role !== 'STUDENT'
      || actor.actor?.active_context?.school_ref !== payload.school_ref) {
      result.failure = { stage: 'student_login', code: 'STUDENT_SESSION_MISMATCH' };
      throw new Error('QA_STOP');
    }
    result.stages.student_login = 'PASS';

    checkpoint = 'role_denial';
    const denial = await page.evaluate(async (backendUrl) => {
      const response = await fetch(`${backendUrl}/api/v1/school/admin/accounts/summary`, {
        credentials: 'include', headers: { Accept: 'application/json' },
      });
      return response.status;
    }, payload.backend_url);
    if (denial !== 403) {
      result.failure = { stage: 'role_denied', code: 'ADMIN_ENDPOINT_NOT_FORBIDDEN', http_status: denial };
      throw new Error('QA_STOP');
    }
    await page.goto(`${payload.frontend_url}/admin/overview`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL((url) => url.pathname === '/student/home', { timeout: 10000 });
    result.stages.role_denied = 'PASS';

    checkpoint = 'responsive_capture';
    for (const width of VIEWPORTS) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : width === 768 ? 1024 : 900 });
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      result.student_viewport_widths[String(width)] = scrollWidth;
      result.stages[`viewport_${width}`] = scrollWidth <= width ? 'PASS' : 'FAIL';
      const screenshotPath = path.join(payload.artifact_dir, `account-lifecycle-student-${width}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true, animations: 'disabled', mask: [page.locator('.account-menu')] });
      result.screenshots[`student_${width}`] = screenshotPath;
      if (scrollWidth > width) {
        result.failure = { stage: `viewport_${width}`, code: 'HORIZONTAL_OVERFLOW' };
        throw new Error('QA_STOP');
      }
    }

    checkpoint = 'logout';
    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    result.stages.logout = 'PASS';

    checkpoint = 'credential_replay';
    await page.getByRole('button', { name: '首次登录', exact: true }).click();
    await page.getByLabel('学校编号', { exact: true }).fill(payload.school_ref);
    await page.getByLabel('账号', { exact: true }).fill(payload.username);
    await page.getByLabel('一次性凭据', { exact: true }).fill(initialCredential);
    const replayPassword = `${randomBytes(24).toString('base64url')}Bb2!`;
    await page.getByLabel('新密码', { exact: true }).fill(replayPassword);
    await page.getByLabel('确认新密码', { exact: true }).fill(replayPassword);
    const replayResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/first-login',
    { timeout: 30000 });
    await page.getByRole('button', { name: '提交', exact: true }).click();
    const replay = await replayResponsePromise;
    if (![401, 409].includes(replay.status())) {
      result.failure = { stage: 'credential_replay_rejected', code: 'USED_CREDENTIAL_ACCEPTED', http_status: replay.status() };
      throw new Error('QA_STOP');
    }
    await page.getByRole('alert').waitFor({ state: 'visible', timeout: 10000 });
    result.stages.credential_replay_rejected = 'PASS';
    result.status = Object.values(result.stages).every((status) => status === 'PASS') ? 'PASS' : 'FAIL';
  } catch (error) {
    if (!result.failure) {
      const code = error instanceof Error && error.name === 'TimeoutError' ? 'ACTION_TIMEOUT' : 'BROWSER_ACTION_FAILED';
      result.failure = { stage: checkpoint, code };
      if (checkpoint === 'first_login_click' || checkpoint === 'first_login_response') {
        result.failure.request_seen = firstLoginRequestSeen;
      }
    }
  } finally {
    initialCredential = '';
    adminPassword = '';
    firstPassword = '';
    if (browser) await browser.close().catch(() => undefined);
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.status === 'PASS' ? 0 : 2;
}

async function preflight() {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    await browser.close();
    process.stdout.write(`${JSON.stringify({ status: 'PASS' })}\n`);
    process.exitCode = 0;
  } catch {
    if (browser) await browser.close().catch(() => undefined);
    process.stdout.write(`${JSON.stringify({ status: 'FAIL', code: 'BROWSER_PREFLIGHT_FAILED' })}\n`);
    process.exitCode = 2;
  }
}

if (process.argv[2] === '--preflight') {
  preflight();
} else {
  main().catch(() => {
    process.stdout.write(`${JSON.stringify({ status: 'FAIL', failure: { stage: 'browser_runner', code: 'UNHANDLED_FAILURE' } })}\n`);
    process.exitCode = 2;
  });
}
