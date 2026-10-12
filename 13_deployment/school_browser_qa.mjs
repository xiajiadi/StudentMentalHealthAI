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
const CURRENT_PATH_CODES = new Map([
  ['/login', 'login'], ['/student/home', 'student_home'], ['/student/assessments', 'student_assessments'],
  ['/student/history', 'student_history'], ['/student/feedback', 'student_feedback'],
  ['/teacher/overview', 'teacher_overview'], ['/specialist/overview', 'specialist_overview'],
  ['/admin/overview', 'admin_overview'], ['/reviewer/queue', 'reviewer_queue'],
]);
const FORBIDDEN_ROUTE_FAILURES = new Map([
  ['direct_navigation', 'NAVIGATION_FAILED'],
  ['role_redirect', 'ROLE_REDIRECT_NOT_COMPLETED'],
  ['destination_check', 'UNEXPECTED_DESTINATION'],
]);
const RESTORE_DIAGNOSTIC_FAILURES = new Set([
  'student_history|metadata_response|RESPONSE_NOT_RECEIVED',
  'student_history|metadata_response|HTTP_STATUS',
  'student_history|metadata_response|BODY_READ_FAILED',
  'student_history|metadata_response|ENVELOPE_INVALID',
  'student_history|metadata_response|DTO_INVALID',
  'student_history|metadata_render|ROW_COUNT_MISMATCH',
  'student_history|metadata_render|STATUS_LABEL_MISMATCH',
  'student_history|metadata_render|ITEM_COUNT_LABEL_MISMATCH',
  'student_history|metadata_render|DATE_LABEL_MISMATCH',
  'student_history|metadata_render|NULL_TIME_LABEL_MISMATCH',
  'student_history|metadata_render|EMPTY_STATE_MISMATCH',
  'student_feedback|route|ROUTE_NOT_REACHED',
  'student_feedback|assessment_request|RESPONSE_NOT_RECEIVED',
  'student_feedback|assessment_request|HTTP_STATUS',
  'student_feedback|reports_request|RESPONSE_NOT_RECEIVED',
  'student_feedback|reports_request|HTTP_STATUS',
  'student_feedback|content_state|CONTENT_NOT_RENDERED',
]);
const safeMetadataDate = (value) => typeof value === 'string' && value.length <= 64
  && Number.isFinite(Date.parse(value));

export function classifyCurrentPath(pathname) {
  return typeof pathname === 'string' ? CURRENT_PATH_CODES.get(pathname) ?? 'other' : 'unknown';
}

export function safeForbiddenRouteDiagnostic(substage, code, pathname) {
  if (FORBIDDEN_ROUTE_FAILURES.get(substage) !== code) return null;
  return {
    stage: 'forbidden_route', substage, code,
    current_path: classifyCurrentPath(pathname),
  };
}

export function safeRestoreDiagnostic(stage, substage, code, pathname) {
  if (!RESTORE_DIAGNOSTIC_FAILURES.has(`${stage}|${substage}|${code}`)) return null;
  return { stage, substage, code, current_path: classifyCurrentPath(pathname) };
}

export function studentHistoryMetadataFailureCode(responseStatus, envelope) {
  if (responseStatus !== 200) return 'HTTP_STATUS';
  if (!envelope || typeof envelope !== 'object' || Array.isArray(envelope)
    || !Object.hasOwn(envelope, 'data')) return 'ENVELOPE_INVALID';
  const rows = envelope.data;
  if (!Array.isArray(rows)) return 'ENVELOPE_INVALID';
  const seen = new Set();
  for (const row of rows) {
    if (!row || typeof row !== 'object' || Array.isArray(row)
      || Object.keys(row).sort().join('|') !== [
        'assessment_id', 'status', 'items_answered', 'started_at', 'completed_at',
      ].sort().join('|')) return 'DTO_INVALID';
    if (typeof row.assessment_id !== 'string' || !/^ASSESS_[A-Za-z0-9_.-]{1,120}$/.test(row.assessment_id)
      || seen.has(row.assessment_id) || !['created', 'in_progress', 'completed', 'abandoned', 'invalid'].includes(row.status)
      || !Number.isSafeInteger(row.items_answered) || row.items_answered < 0
      || (row.started_at !== null && !safeMetadataDate(row.started_at))
      || (row.completed_at !== null && !safeMetadataDate(row.completed_at))) return 'DTO_INVALID';
    seen.add(row.assessment_id);
  }
  return null;
}

export function studentHistoryRenderedMismatch(metadata, statusLabels, summaries, expectedTimes) {
  if (!Array.isArray(metadata) || !Array.isArray(statusLabels) || !Array.isArray(summaries)
    || !Array.isArray(expectedTimes) || metadata.length !== statusLabels.length
    || metadata.length !== summaries.length || metadata.length !== expectedTimes.length) return 'ROW_COUNT_MISMATCH';
  for (let index = 0; index < metadata.length; index += 1) {
    const item = metadata[index];
    const expectedStatus = item.status === 'completed'
      ? '已完成的合成测评' : item.status === 'created' ? '尚未开始的合成测评' : '测评记录';
    if (statusLabels[index] !== expectedStatus) return 'STATUS_LABEL_MISMATCH';
    const prefix = `${item.items_answered} 项已记录 · `;
    const summary = summaries[index];
    if (typeof summary !== 'string' || !summary.startsWith(prefix)) return 'ITEM_COUNT_LABEL_MISMATCH';
    if (summary.slice(prefix.length) !== expectedTimes[index]) {
      const nullTime = (item.status === 'created' && item.started_at === null)
        || (item.started_at === null && item.completed_at === null);
      return nullTime ? 'NULL_TIME_LABEL_MISMATCH' : 'DATE_LABEL_MISMATCH';
    }
  }
  return null;
}

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
  let failureDiagnostic = null;
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

    if (slot === 'alpha.student') {
      const welcome = await page.locator('#student-home-title').innerText();
      if (!welcome.includes('同学') || /(?:USER|SYNTHETIC)_/i.test(welcome)) {
        throw new Error('StudentWelcomeShowsTechnicalIdentity');
      }
    }

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
      failureDiagnostic = safeRestoreDiagnostic(
        'student_history', 'metadata_response', 'RESPONSE_NOT_RECEIVED', safePathname(page),
      );
      const historyResponsePromise = page.waitForResponse((response) => response.request().method() === 'GET'
        && new URL(response.url()).pathname === '/api/v1/school/assessments', { timeout: 30000 }).then(
        (response) => response, () => null,
      );
      await page.getByRole('link', { name: '我的记录', exact: true }).click();
      const historyResponse = await historyResponsePromise;
      if (!historyResponse) throw new Error('StudentHistoryUnavailable');
      const historyStatus = historyResponse.status();
      if (historyStatus !== 200) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'metadata_response', 'HTTP_STATUS', safePathname(page),
        );
        throw new Error('StudentHistoryUnavailable');
      }
      let historyEnvelope;
      try { historyEnvelope = await historyResponse.json(); }
      catch {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'metadata_response', 'BODY_READ_FAILED', safePathname(page),
        );
        throw new Error('StudentHistoryUnavailable');
      }
      const metadataFailure = studentHistoryMetadataFailureCode(historyStatus, historyEnvelope);
      if (metadataFailure !== null) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'metadata_response', metadataFailure, safePathname(page),
        );
        throw new Error('StudentHistoryUnavailable');
      }
      const historyMetadata = historyEnvelope.data.map((item) => ({
        status: item.status,
        items_answered: item.items_answered,
        started_at: item.started_at,
        completed_at: item.completed_at,
      }));
      await page.locator('#assessment-history-title').waitFor({ state: 'visible' });
      await page.locator('.student-loading').waitFor({ state: 'hidden' });
      const historySection = page.locator('section[aria-labelledby="assessment-history-title"]');
      const historyRows = historySection.locator('.history-row');
      const actualRowCount = await historyRows.count();
      if (actualRowCount !== historyMetadata.length) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'metadata_render', 'ROW_COUNT_MISMATCH', safePathname(page),
        );
        throw new Error('StudentHistoryUnavailable');
      }
      if (historyMetadata.length === 0) {
        if (await historySection.locator('.history-empty').count() !== 1) {
          failureDiagnostic = safeRestoreDiagnostic(
            'student_history', 'metadata_render', 'EMPTY_STATE_MISMATCH', safePathname(page),
          );
          throw new Error('StudentHistoryUnavailable');
        }
        await historySection.locator('.history-empty').waitFor({ state: 'visible' });
      } else {
        await historyRows.first().waitFor({ state: 'visible' });
        if (await historySection.locator('.history-empty').count() !== 0) {
          failureDiagnostic = safeRestoreDiagnostic(
            'student_history', 'metadata_render', 'EMPTY_STATE_MISMATCH', safePathname(page),
          );
          throw new Error('StudentHistoryUnavailable');
        }
        const expectedTimes = await page.evaluate((items) => {
          const formatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
          const formatHistoryDate = (value) => {
            if (!value) return '时间未提供';
            const parsed = new Date(value);
            if (Number.isNaN(parsed.getTime())) return '时间暂不可用';
            return formatter.format(parsed);
          };
          return items.map((item) => item.status === 'created' && !item.started_at
            ? '尚未开始' : formatHistoryDate(item.completed_at || item.started_at));
        }, historyMetadata);
        const actualStatusLabels = (await historyRows.locator('.history-row__copy strong').allInnerTexts())
          .map((value) => value.trim());
        const summaries = (await historyRows.locator('.history-row__copy > span').allInnerTexts())
          .map((value) => value.trim());
        const renderFailure = studentHistoryRenderedMismatch(
          historyMetadata, actualStatusLabels, summaries, expectedTimes,
        );
        if (renderFailure !== null) {
          failureDiagnostic = safeRestoreDiagnostic(
            'student_history', 'metadata_render', renderFailure, safePathname(page),
          );
          throw new Error('StudentHistoryUnavailable');
        }
      }
      failureDiagnostic = null;
      await page.screenshot({ path: path.join(payload.artifact_dir, 'student-history.png'),
        fullPage: true, animations: 'disabled', mask: [page.locator('.account-menu')] });
      failureDiagnostic = safeRestoreDiagnostic(
        'student_feedback', 'route', 'ROUTE_NOT_REACHED', safePathname(page),
      );
      const feedbackAssessmentPromise = page.waitForResponse((response) => response.request().method() === 'GET'
        && new URL(response.url()).pathname === '/api/v1/school/assessments', { timeout: 30000 }).then(
        (response) => response, () => null,
      );
      const feedbackReportsPromise = page.waitForResponse((response) => response.request().method() === 'GET'
        && new URL(response.url()).pathname === '/api/v1/reports', { timeout: 30000 }).then(
        (response) => response, () => null,
      );
      await page.getByRole('link', { name: '测评反馈', exact: true }).click();
      try { await page.waitForURL((url) => url.pathname === '/student/feedback', { timeout: 20000 }); }
      catch {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'route', 'ROUTE_NOT_REACHED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      const [feedbackAssessmentResponse, feedbackReportsResponse] = await Promise.all([
        feedbackAssessmentPromise, feedbackReportsPromise,
      ]);
      if (!feedbackAssessmentResponse) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'assessment_request', 'RESPONSE_NOT_RECEIVED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      if (!feedbackReportsResponse) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'reports_request', 'RESPONSE_NOT_RECEIVED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      if (feedbackAssessmentResponse.status() !== 200) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'assessment_request', 'HTTP_STATUS', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      if (feedbackReportsResponse.status() !== 200) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'reports_request', 'HTTP_STATUS', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      await page.locator('#reports-title').waitFor({ state: 'visible' });
      await page.locator('.feedback-loading').waitFor({ state: 'hidden' });
      if (await page.locator('.feedback-row, .feedback-empty').count() === 0) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'content_state', 'CONTENT_NOT_RENDERED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      await page.locator('.feedback-row, .feedback-empty').first().waitFor({ state: 'visible' });
      if (legacyListRequested) throw new Error('LegacyPrivateListRequested');
      failureDiagnostic = null;
      await page.screenshot({ path: path.join(payload.artifact_dir, 'student-feedback.png'),
        fullPage: true, animations: 'disabled', mask: [page.locator('.account-menu')] });
      page.off('request', observeList);
    }

    const forbiddenPath = FORBIDDEN_PATHS[slot];
    try {
      await page.goto(`${payload.frontend_url}${forbiddenPath}`, { waitUntil: 'domcontentloaded' });
    } catch {
      failureDiagnostic = safeForbiddenRouteDiagnostic(
        'direct_navigation', 'NAVIGATION_FAILED', safePathname(page),
      );
      throw new Error('ForbiddenRouteCheckFailed');
    }
    try {
      await page.waitForURL((url) => url.pathname === expected.path, { timeout: 10000 });
    } catch {
      failureDiagnostic = safeForbiddenRouteDiagnostic(
        'role_redirect', 'ROLE_REDIRECT_NOT_COMPLETED', safePathname(page),
      );
      throw new Error('ForbiddenRouteCheckFailed');
    }
    if (safePathname(page) !== expected.path) {
      failureDiagnostic = safeForbiddenRouteDiagnostic(
        'destination_check', 'UNEXPECTED_DESTINATION', safePathname(page),
      );
      throw new Error('ForbiddenRouteCheckFailed');
    }
    stages.forbidden_route = 'PASS';
    failureDiagnostic = null;
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
    if (failureDiagnostic) output.diagnostic = failureDiagnostic;
  } finally {
    await bestEffortSessionLogout(page, payload.backend_url, loginSubmitted, logoutConfirmed);
    await context.close();
  }
  return output;
}

function safePathname(page) {
  try { return new URL(page.url()).pathname; } catch { return null; }
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

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => {
    process.stdout.write(`${JSON.stringify(failResult())}\n`);
    process.exitCode = 2;
  });
}
