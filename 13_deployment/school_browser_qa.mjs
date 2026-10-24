import path from 'node:path';
import fs from 'node:fs';
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
  'student_history|route|ROUTE_NOT_REACHED',
  'student_history|route|LINK_NOT_VISIBLE',
  'student_history|route|LINK_CLICK_FAILED',
  'student_history|metadata_response|RESPONSE_NOT_RECEIVED',
  'student_history|metadata_response|REQUEST_NOT_STARTED',
  'student_history|metadata_response|REQUEST_FAILED',
  'student_history|metadata_response|REQUEST_PENDING_PROBE_200',
  'student_history|metadata_response|REQUEST_PENDING_PROBE_FAILED',
  'student_history|metadata_response|REQUEST_PENDING_PROBE_EVALUATION_FAILED',
  'student_history|metadata_response|REQUEST_NOT_STARTED',
  'student_history|metadata_response|REQUEST_FAILED',
  'student_history|metadata_response|HTTP_STATUS',
  'student_history|metadata_response|BODY_READ_FAILED',
  'student_history|metadata_response|ENVELOPE_INVALID',
  'student_history|metadata_response|DTO_INVALID',
  'student_history|metadata_render|ASSESSMENT_LIBRARY_NOT_VISIBLE',
  'student_history|metadata_render|ASSESSMENT_LOADING_DID_NOT_SETTLE',
  'student_history|metadata_render|CARD_COUNT_MISMATCH',
  'student_history|metadata_render|ROW_COUNT_MISMATCH',
  'student_history|metadata_render|STATUS_LABEL_MISMATCH',
  'student_history|metadata_render|ITEM_COUNT_LABEL_MISMATCH',
  'student_history|metadata_render|DATE_LABEL_MISMATCH',
  'student_history|metadata_render|NULL_TIME_LABEL_MISMATCH',
  'student_history|metadata_render|EMPTY_STATE_MISMATCH',
  'student_feedback|route|ROUTE_NOT_REACHED',
  'student_feedback|feedback_request|RESPONSE_NOT_RECEIVED',
  'student_feedback|feedback_request|HTTP_STATUS',
  'student_feedback|feedback_request|ENVELOPE_INVALID',
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

export function studentHistoryRenderedMismatch(metadata, cardTexts, emptyStateVisible) {
  if (!Array.isArray(metadata) || !Array.isArray(cardTexts)
    || typeof emptyStateVisible !== 'boolean') return 'ROW_COUNT_MISMATCH';
  if (emptyStateVisible !== (cardTexts.length === 0)) return 'EMPTY_STATE_MISMATCH';
  if (cardTexts.length < metadata.length) return 'CARD_COUNT_MISMATCH';
  const usedCards = new Set();
  const formatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
  for (const item of metadata) {
    const expectedStatus = {
      created: '待开始', in_progress: '进行中', completed: '已完成',
      abandoned: '已结束', invalid: '不可用',
    }[item.status];
    const timestamp = item.completed_at || item.started_at;
    const expectedTime = timestamp ? formatter.format(new Date(timestamp)) : '时间未提供';
    const matchingIndex = cardTexts.findIndex((text, index) => !usedCards.has(index)
      && text.includes(expectedStatus)
      && text.includes(`${item.items_answered} 项已记录`)
      && text.includes(expectedTime));
    if (matchingIndex >= 0) {
      usedCards.add(matchingIndex);
      continue;
    }
    if (!cardTexts.some((text) => text.includes(expectedStatus))) return 'STATUS_LABEL_MISMATCH';
    if (!cardTexts.some((text) => text.includes(`${item.items_answered} 项已记录`))) return 'ITEM_COUNT_LABEL_MISMATCH';
    return 'DATE_LABEL_MISMATCH';
  }
  return null;
}

function failResult() {
  return {
    status: 'FAIL',
    results: ACCOUNT_SLOTS.map((slot) => ({ slot, status: 'FAIL' })),
  };
}

export function isLoopbackBrowserOrigin(value) {
  if (typeof value !== 'string' || value.length > 80) return false;
  try {
    const url = new URL(value);
    const port = Number(url.port);
    return url.protocol === 'http:' && url.hostname === '127.0.0.1'
      && url.pathname === '/' && !url.search && !url.hash
      && !url.username && !url.password
      && /^\d{1,5}$/.test(url.port) && Number.isInteger(port)
      && port >= 1024 && port <= 65535;
  } catch {
    return false;
  }
}

export function browserBinaryPrerequisite(chromiumExecutablePath, platform = process.platform) {
  const isFile = (candidate) => {
    try { return fs.statSync(candidate).isFile(); } catch { return false; }
  };
  if (typeof chromiumExecutablePath !== 'string' || !path.isAbsolute(chromiumExecutablePath)) {
    return { status: 'FAIL', code: 'BROWSER_LAYOUT_UNRECOGNIZED' };
  }
  if (!isFile(chromiumExecutablePath)) {
    return { status: 'FAIL', code: 'CHROMIUM_EXECUTABLE_MISSING' };
  }

  const revisionDirectory = path.dirname(path.dirname(chromiumExecutablePath));
  const revisionMatch = path.basename(revisionDirectory).match(/^chromium-(\d+)$/);
  const platformDirectory = path.basename(path.dirname(chromiumExecutablePath));
  if (!revisionMatch) return { status: 'FAIL', code: 'BROWSER_LAYOUT_UNRECOGNIZED' };

  let shellDirectory;
  let shellExecutable;
  if (platform === 'win32') {
    const platformMatch = platformDirectory.match(/^chrome-(win32|win64|win-arm64)$/);
    if (!platformMatch || path.basename(chromiumExecutablePath) !== 'chrome.exe') {
      return { status: 'FAIL', code: 'BROWSER_LAYOUT_UNRECOGNIZED' };
    }
    shellDirectory = `chrome-headless-shell-${platformMatch[1]}`;
    shellExecutable = 'chrome-headless-shell.exe';
  } else if (platform === 'linux') {
    const platformMatch = platformDirectory.match(/^chrome-(linux|linux64|linux-arm64)$/);
    if (!platformMatch || path.basename(chromiumExecutablePath) !== 'chrome') {
      return { status: 'FAIL', code: 'BROWSER_LAYOUT_UNRECOGNIZED' };
    }
    shellDirectory = `chrome-headless-shell-${platformMatch[1]}`;
    shellExecutable = 'chrome-headless-shell';
  } else {
    return { status: 'FAIL', code: 'BROWSER_LAYOUT_UNRECOGNIZED' };
  }

  const shellPath = path.join(
    path.dirname(revisionDirectory),
    `chromium_headless_shell-${revisionMatch[1]}`,
    shellDirectory,
    shellExecutable,
  );
  return isFile(shellPath)
    ? { status: 'PASS', code: 'READY' }
    : { status: 'FAIL', code: 'HEADLESS_SHELL_EXECUTABLE_MISSING' };
}

function validPayload(payload) {
  if (!payload || typeof payload !== 'object') return false;
  if (!path.isAbsolute(payload.artifact_dir)) return false;
  if (!isLoopbackBrowserOrigin(payload.frontend_url) || !isLoopbackBrowserOrigin(payload.backend_url)
    || payload.frontend_url === payload.backend_url) return false;
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
  let studentHistoryCheckpoint = 'not_started';
  try {
    page = await context.newPage();
    await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
    const usernameInput = page.locator('#account');
    const passwordInput = page.locator('#password');
    await usernameInput.waitFor({ state: 'visible' });
    if ((await usernameInput.inputValue()) !== '' || (await passwordInput.inputValue()) !== '') {
      throw new Error('InitialFormNotBlank');
    }
    stages.blank_login = 'PASS';

    await usernameInput.fill(payload.credentials[slot].username);
    await passwordInput.fill(payload.credentials[slot].password);
    loginSubmitted = true;
    await page.getByRole('button', { name: '登录', exact: true }).click();

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
      await page.getByRole('button', { name: '继续', exact: true }).click();
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
      let schoolHistoryRequestObserved = false;
      let schoolHistoryRequestFailed = false;
      let schoolHistoryResponseEvent = null;
      const observeList = (request) => {
        if (request.method() !== 'GET') return;
        const pathname = new URL(request.url()).pathname;
        if (pathname === '/api/v1/assessments') legacyListRequested = true;
        if (pathname === '/api/v1/school/assessments') schoolHistoryRequestObserved = true;
      };
      page.on('request', observeList);
      page.on('requestfailed', (request) => {
        if (request.method() !== 'GET') return;
        try {
          if (new URL(request.url()).pathname === '/api/v1/school/assessments') {
            schoolHistoryRequestFailed = true;
          }
        } catch { /* Keep failure evidence limited to a boolean */ }
      });
      page.on('response', (response) => {
        if (response.request().method() !== 'GET') return;
        try {
          if (new URL(response.url()).pathname === '/api/v1/school/assessments') {
            schoolHistoryResponseEvent = response;
          }
        } catch { /* Keep failure evidence limited to the response object */ }
      });
      studentHistoryCheckpoint = 'listeners_ready';
      failureDiagnostic = safeRestoreDiagnostic(
        'student_history', 'metadata_response', 'RESPONSE_NOT_RECEIVED', safePathname(page),
      );
      const historyResponsePromise = page.waitForResponse((response) => response.request().method() === 'GET'
        && new URL(response.url()).pathname === '/api/v1/school/assessments', { timeout: 30000 }).then(
        (response) => response, () => null,
      );
      const historyLinkSelector = 'a[href="/student/history"]:visible';
      const historyLink = page.locator(historyLinkSelector).first();
      if (await page.locator(historyLinkSelector).count() === 0) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'route', 'LINK_NOT_VISIBLE', safePathname(page),
        );
        throw new Error('StudentHistoryLinkUnavailable');
      }
      studentHistoryCheckpoint = 'link_visible';
      try {
        await historyLink.click({ timeout: 10000 });
        studentHistoryCheckpoint = 'link_clicked';
      } catch {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'route', 'LINK_CLICK_FAILED', safePathname(page),
        );
        throw new Error('StudentHistoryLinkUnavailable');
      }
      await page.waitForURL((url) => url.pathname === '/student/history', { timeout: 10000 }).catch(() => {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'route', 'ROUTE_NOT_REACHED', safePathname(page),
        );
        throw new Error('StudentHistoryRouteUnavailable');
      });
      studentHistoryCheckpoint = 'route_reached';
      const historyResponse = await historyResponsePromise ?? schoolHistoryResponseEvent;
      studentHistoryCheckpoint = 'response_wait_completed';
      if (!historyResponse) {
        let failureCode = schoolHistoryRequestFailed
          ? 'REQUEST_FAILED' : schoolHistoryRequestObserved ? 'RESPONSE_NOT_RECEIVED' : 'REQUEST_NOT_STARTED';
        if (failureCode === 'RESPONSE_NOT_RECEIVED') {
          try {
            const probeStatus = await page.evaluate(async (backendUrl) => {
              const controller = new AbortController();
              const timeout = window.setTimeout(() => controller.abort(), 8000);
              try {
                const response = await fetch(`${backendUrl}/api/v1/school/assessments?limit=30&skip=0`, {
                  credentials: 'include',
                  headers: { Accept: 'application/json' },
                  signal: controller.signal,
                });
                return response.status;
              } catch {
                return 0;
              } finally {
                window.clearTimeout(timeout);
              }
            }, payload.backend_url);
            failureCode = probeStatus === 200 ? 'REQUEST_PENDING_PROBE_200' : 'REQUEST_PENDING_PROBE_FAILED';
          } catch {
            failureCode = 'REQUEST_PENDING_PROBE_EVALUATION_FAILED';
          }
        }
        studentHistoryCheckpoint = 'probe_completed';
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'metadata_response', failureCode, safePathname(page),
        );
        throw new Error('StudentHistoryUnavailable');
      }
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
      studentHistoryCheckpoint = 'response_validated';
      const historyMetadata = historyEnvelope.data.map((item) => ({
        status: item.status,
        items_answered: item.items_answered,
        started_at: item.started_at,
        completed_at: item.completed_at,
      }));
      const assessmentLibrary = page.locator('.assessment-library');
      failureDiagnostic = safeRestoreDiagnostic(
        'student_history', 'metadata_render', 'ASSESSMENT_LIBRARY_NOT_VISIBLE', safePathname(page),
      );
      try {
        await assessmentLibrary.waitFor({ state: 'visible' });
      } catch {
        throw new Error('StudentHistoryUnavailable');
      }
      studentHistoryCheckpoint = 'assessment_library_visible';
      failureDiagnostic = safeRestoreDiagnostic(
        'student_history', 'metadata_render', 'ASSESSMENT_LOADING_DID_NOT_SETTLE', safePathname(page),
      );
      try {
        await assessmentLibrary.locator('.assessment-loading').waitFor({ state: 'hidden' });
      } catch {
        throw new Error('StudentHistoryUnavailable');
      }
      studentHistoryCheckpoint = 'assessment_library_loaded';
      const historyCards = assessmentLibrary.locator('.assessment-card');
      const cardTexts = await historyCards.allInnerTexts();
      const emptyStateVisible = await assessmentLibrary.locator('.assessment-empty').isVisible().catch(() => false);
      const renderFailure = studentHistoryRenderedMismatch(
        historyMetadata, cardTexts, emptyStateVisible,
      );
      if (renderFailure !== null) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_history', 'metadata_render', renderFailure, safePathname(page),
        );
        throw new Error('StudentHistoryUnavailable');
      }
      failureDiagnostic = null;
      await page.screenshot({ path: path.join(payload.artifact_dir, 'student-history.png'),
        fullPage: true, animations: 'disabled', mask: [page.locator('.account-menu')] });
      failureDiagnostic = safeRestoreDiagnostic(
        'student_feedback', 'route', 'ROUTE_NOT_REACHED', safePathname(page),
      );
      const feedbackResponsePromise = page.waitForResponse((response) => response.request().method() === 'GET'
        && new URL(response.url()).pathname === '/api/v1/school/feedback/student', { timeout: 30000 }).then(
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
      const feedbackResponse = await feedbackResponsePromise;
      if (!feedbackResponse) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'feedback_request', 'RESPONSE_NOT_RECEIVED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      if (feedbackResponse.status() !== 200) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'feedback_request', 'HTTP_STATUS', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      let feedbackEnvelope;
      try { feedbackEnvelope = await feedbackResponse.json(); }
      catch {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'feedback_request', 'ENVELOPE_INVALID', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      const feedbackData = feedbackEnvelope?.data;
      if (!Array.isArray(feedbackData?.items) || !Number.isSafeInteger(feedbackData?.total)
        || feedbackData.total < feedbackData.items.length) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'feedback_request', 'ENVELOPE_INVALID', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      await page.locator('#published-feedback-title').waitFor({ state: 'visible' });
      await page.locator('.history-library__count').waitFor({ state: 'visible' });
      const feedbackRows = page.locator('.history-library__cards .history-library__card');
      const feedbackEmpty = page.locator('.history-library__empty');
      if (await feedbackRows.count() === 0 && !(await feedbackEmpty.isVisible())) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'content_state', 'CONTENT_NOT_RENDERED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
      if (feedbackData.items.length > 0 && await feedbackRows.count() === 0) {
        failureDiagnostic = safeRestoreDiagnostic(
          'student_feedback', 'content_state', 'CONTENT_NOT_RENDERED', safePathname(page),
        );
        throw new Error('StudentFeedbackUnavailable');
      }
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
      (await page.locator('#account').inputValue()) !== '' ||
      (await page.locator('#password').inputValue()) !== ''
    ) throw new Error('LoginFormNotRestoredBlank');
    stages.blank_restore = 'PASS';

    output.status = 'PASS';
    output.screenshot = screenshot;
    output.expected_role = expected.role;
    output.expected_path = expected.path;
  } catch {
    // Retain only fixed stage booleans; do not return exception details.
    if (failureDiagnostic) {
      output.diagnostic = failureDiagnostic;
      if (failureDiagnostic.stage === 'student_history') {
        output.diagnostic.checkpoint = studentHistoryCheckpoint;
      }
    }
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
  let browserPrerequisite;
  try {
    browserPrerequisite = browserBinaryPrerequisite(chromium.executablePath());
  } catch {
    browserPrerequisite = { status: 'FAIL', code: 'BROWSER_LAYOUT_UNRECOGNIZED' };
  }
  if (browserPrerequisite.status !== 'PASS') {
    process.stdout.write(`${JSON.stringify({
      ...failResult(),
      browser_prerequisite: browserPrerequisite,
    })}\n`);
    process.exitCode = 2;
    return;
  }

  let browserLaunchFailureCode;
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
    browserLaunchFailureCode = 'BROWSER_LAUNCH_FAILED';
    for (const slot of ACCOUNT_SLOTS) {
      if (!results.some((item) => item.slot === slot)) results.push({ slot, status: 'FAIL' });
    }
  } finally {
    if (browser) await browser.close().catch(() => undefined);
  }

  const passed = results.filter((item) => item.status === 'PASS').length;
  process.stdout.write(`${JSON.stringify({
    status: passed === ACCOUNT_SLOTS.length ? 'PASS' : 'FAIL',
    browser_prerequisite: browserPrerequisite,
    ...(browserLaunchFailureCode ? { browser_launch_failure_code: browserLaunchFailureCode } : {}),
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
