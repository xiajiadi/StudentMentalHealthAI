import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');
const ACCOUNT_SLOTS = [
  'alpha.student',
  'alpha.teacher',
  'alpha.psychological_specialist',
  'alpha.admin',
];
const FORBIDDEN_PATHS = {
  'alpha.student': '/admin/overview',
  'alpha.teacher': '/student/home',
  'alpha.psychological_specialist': '/teacher/overview',
  'alpha.admin': '/specialist/overview',
};

function failResult() {
  return {
    status: 'FAIL',
    results: ACCOUNT_SLOTS.map((slot) => ({ slot, status: 'FAIL' })),
  };
}

function validPayload(payload) {
  if (!payload || typeof payload !== 'object') return false;
  if (!path.isAbsolute(payload.artifact_dir)) return false;
  const allowedTargets = [
    ['http://127.0.0.1:4178', 'http://127.0.0.1:8088'],
    ['http://127.0.0.1:4179', 'http://127.0.0.1:8089'],
  ];
  if (!allowedTargets.some(([frontend, backend]) =>
    payload.frontend_url === frontend && payload.backend_url === backend)) return false;
  for (const slot of ACCOUNT_SLOTS) {
    const account = payload.credentials?.[slot];
    const expected = payload.accounts?.[slot];
    if (
      !account || typeof account.username !== 'string' ||
      !account.username.startsWith('SYNTHETIC_') ||
      typeof account.password !== 'string' || account.password.length < 16 ||
      !expected || typeof expected.role !== 'string' ||
      typeof expected.api_role !== 'string' || typeof expected.path !== 'string'
    ) return false;
  }
  return true;
}

async function readInput() {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function browserActor(page, backendUrl) {
  return page.evaluate(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/api/v1/auth/me`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    let body = null;
    try { body = await response.json(); } catch { /* fixed caller failure */ }
    return { status: response.status, body };
  }, backendUrl);
}

async function teacherAuthorization(page, backendUrl) {
  return page.evaluate(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/api/v1/teacher/overview`, {
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    return response.status;
  }, backendUrl);
}

async function bestEffortSessionLogout(page, backendUrl, loginSubmitted, logoutConfirmed) {
  if (!page || !loginSubmitted || logoutConfirmed) return;
  try {
    // Cleanup uses the normal authenticated CSRF and logout endpoints. The
    // token and response remain in this page evaluation's memory only.
    await page.evaluate(async (baseUrl) => {
      const csrfResponse = await fetch(`${baseUrl}/api/v1/auth/csrf`, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });
      if (!csrfResponse.ok) return;
      const csrfBody = await csrfResponse.json();
      const token = csrfBody?.data?.csrf_token;
      if (typeof token !== 'string' || !token) return;
      await fetch(`${baseUrl}/api/v1/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'X-CSRF-Token': token },
      });
    }, backendUrl);
  } catch {
    // Cleanup is best effort; never expose session or response details.
  }
}

async function checkAccount(browser, payload, slot) {
  const stages = {
    blank_login: 'FAIL',
    real_login: 'FAIL',
    role_route: 'FAIL',
    auth_me: 'FAIL',
    screenshot: 'FAIL',
    forbidden_route: 'FAIL',
    forbidden_api: 'FAIL',
    ui_logout: 'FAIL',
    blank_restore: 'FAIL',
  };
  const output = { slot, status: 'FAIL', stages };
  const context = await browser.newContext({ serviceWorkers: 'block' });
  let page;
  let loginSubmitted = false;
  let logoutConfirmed = false;
  try {
    page = await context.newPage();
    await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
    const usernameInput = page.getByRole('textbox', { name: 'Username' });
    const passwordInput = page.getByLabel('Password');
    await usernameInput.waitFor({ state: 'visible' });
    if ((await usernameInput.inputValue()) !== '' || (await passwordInput.inputValue()) !== '') {
      throw new Error('InitialFormNotBlank');
    }
    stages.blank_login = 'PASS';

    await usernameInput.fill(payload.credentials[slot].username);
    await passwordInput.fill(payload.credentials[slot].password);
    loginSubmitted = true;
    await page.getByRole('button', { name: 'Continue', exact: true }).click();

    // Some deployments activate the single registered role in the API adapter;
    // if the actual UI presents its sole context, select it through that UI.
    const contextPicker = page.locator('#school-context');
    if (await contextPicker.isVisible({ timeout: 1500 }).catch(() => false)) {
      const contextValues = await contextPicker.locator('option:not([disabled])').evaluateAll(
        (options) => options.map((option) => option.value),
      );
      if (contextValues.length !== 1 || !contextValues[0]) {
        throw new Error('ExpectedSingleSchoolContext');
      }
      await contextPicker.selectOption(contextValues[0]);
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
    }
    stages.real_login = 'PASS';

    const expected = payload.accounts[slot];
    await page.waitForURL((url) => url.pathname === expected.path, { timeout: 20000 });
    stages.role_route = 'PASS';
    const passwordStillVisible = await page.locator('#password').isVisible().catch(() => false);
    if (passwordStillVisible && (await page.locator('#password').inputValue()) !== '') {
      await page.locator('#password').fill('');
      throw new Error('PasswordFieldNotCleared');
    }

    const actorResponse = await browserActor(page, payload.backend_url);
    const actor = actorResponse?.body?.data?.actor ?? actorResponse?.body?.data;
    if (
      actorResponse?.status !== 200 ||
      actor?.role !== expected.api_role ||
      actor?.active_context?.role !== expected.api_role
    ) {
      throw new Error('AuthenticatedActorMismatch');
    }
    const activeSchool = actor?.active_context?.school_ref;
    if (activeSchool !== 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1') {
      throw new Error('ActiveSchoolMismatch');
    }
    stages.auth_me = 'PASS';

    const screenshot = path.join(payload.artifact_dir, `${slot.replaceAll('.', '-')}.png`);
    const screenshotMasks = [page.locator('.account-menu')];
    if (await page.locator('#student-home-title').count()) {
      screenshotMasks.push(page.locator('#student-home-title'));
    }
    await page.screenshot({
      path: screenshot,
      fullPage: true,
      animations: 'disabled',
      mask: screenshotMasks,
    });
    stages.screenshot = 'PASS';

    if (slot === 'alpha.student') {
      let legacyListRequested = false;
      const observeList = (request) => {
        if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/v1/assessments') {
          legacyListRequested = true;
        }
      };
      page.on('request', observeList);
      const historyResponse = page.waitForResponse((response) =>
        new URL(response.url()).pathname === '/api/v1/school/assessments');
      await page.getByRole('link', { name: '我的记录', exact: true }).click();
      if ((await historyResponse).status() !== 200) throw new Error('StudentHistoryUnavailable');
      await page.locator('#assessment-history-title').waitFor({ state: 'visible' });
      await page.locator('.history-row').first().waitFor({ state: 'visible' });
      await page.getByText('尚未开始的合成测评', { exact: true }).waitFor({ state: 'visible' });
      await page.screenshot({ path: path.join(payload.artifact_dir, 'student-history.png'),
        fullPage: true, animations: 'disabled', mask: [page.locator('.account-menu')] });
      const feedbackResponse = page.waitForResponse((response) =>
        new URL(response.url()).pathname === '/api/v1/school/assessments');
      await page.getByRole('link', { name: '测评反馈', exact: true }).click();
      if ((await feedbackResponse).status() !== 200) throw new Error('StudentFeedbackUnavailable');
      await page.locator('#reports-title').waitFor({ state: 'visible' });
      await page.locator('.feedback-loading').waitFor({ state: 'hidden' });
      if (await page.getByText('测评反馈暂时无法加载', { exact: true }).isVisible()) {
        throw new Error('StudentFeedbackUnavailable');
      }
      await page.locator('.feedback-row, .feedback-empty').first().waitFor({ state: 'visible' });
      if (legacyListRequested) throw new Error('LegacyPrivateListRequested');
      await page.screenshot({ path: path.join(payload.artifact_dir, 'student-feedback.png'),
        fullPage: true, animations: 'disabled', mask: [page.locator('.account-menu')] });
      page.off('request', observeList);
    }

    const forbiddenPath = FORBIDDEN_PATHS[slot];
    await page.goto(`${payload.frontend_url}${forbiddenPath}`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL((url) => url.pathname === expected.path, { timeout: 10000 });
    if (new URL(page.url()).pathname !== expected.path) throw new Error('ForbiddenRouteRendered');
    stages.forbidden_route = 'PASS';
    const teacherStatus = await teacherAuthorization(page, payload.backend_url);
    const expectedTeacherStatus = expected.role === 'TEACHER' ? 200 : 403;
    if (teacherStatus !== expectedTeacherStatus) throw new Error('ForbiddenApiAuthorizationMismatch');
    stages.forbidden_api = 'PASS';

    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    logoutConfirmed = true;
    stages.ui_logout = 'PASS';
    const meAfterLogout = await browserActor(page, payload.backend_url);
    if (meAfterLogout?.status !== 401) throw new Error('LogoutSessionStillAuthorized');
    if (
      (await page.getByRole('textbox', { name: 'Username' }).inputValue()) !== '' ||
      (await page.getByLabel('Password').inputValue()) !== ''
    ) throw new Error('LoginFormNotRestoredBlank');
    stages.blank_restore = 'PASS';

    output.status = 'PASS';
    output.screenshot = screenshot;
    output.expected_role = expected.role;
    output.expected_path = expected.path;
  } catch {
    // Retain only fixed stage booleans; do not return exception details.
  } finally {
    await bestEffortSessionLogout(page, payload.backend_url, loginSubmitted, logoutConfirmed);
    await context.close();
  }
  return output;
}

async function main() {
  const payload = await readInput();
  if (!validPayload(payload)) {
    process.stdout.write(`${JSON.stringify(failResult())}\n`);
    process.exitCode = 2;
    return;
  }

  let browser;
  const results = [];
  try {
    browser = await chromium.launch({ headless: true });
    for (const slot of ACCOUNT_SLOTS) {
      try {
        results.push(await checkAccount(browser, payload, slot));
      } catch {
        // Playwright and HTTP errors can contain submitted input or response
        // text. Only a fixed failure marker leaves this process.
        results.push({ slot, status: 'FAIL', stages: {} });
      }
    }
  } catch {
    for (const slot of ACCOUNT_SLOTS) {
      if (!results.some((item) => item.slot === slot)) results.push({ slot, status: 'FAIL' });
    }
  } finally {
    if (browser) await browser.close().catch(() => undefined);
  }

  const passed = results.filter((item) => item.status === 'PASS').length;
  process.stdout.write(`${JSON.stringify({
    status: passed === ACCOUNT_SLOTS.length ? 'PASS' : 'FAIL',
    results,
  })}\n`);
  // The JSON report carries per-account failures; reserve a nonzero exit for
  // an unhandled runner failure so the wrapper can retain partial slot counts.
  process.exitCode = 0;
}

main().catch(() => {
  process.stdout.write(`${JSON.stringify(failResult())}\n`);
  process.exitCode = 2;
});
