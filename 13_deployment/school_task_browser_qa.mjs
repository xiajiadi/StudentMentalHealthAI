import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const WORKFLOW = 'school-tasks';
const WORKSPACE_PREFIX = '.StudentMentalHealthAI-school-workspace-20261011';
const ACCOUNT_ROUTES = {
  'alpha.admin': { role: 'SCHOOL_ADMIN', api_role: 'ADMIN', path: '/admin/overview' },
  'alpha.student': { role: 'STUDENT', api_role: 'STUDENT', path: '/student/home' },
  'alpha.teacher': { role: 'TEACHER', api_role: 'TEACHER', path: '/teacher/overview' },
};
export const TASK_STAGE_KEYS = [
  'admin_login',
  'class_created',
  'student_assigned',
  'teacher_assigned',
  'task_published',
  'student_login',
  'cat_started',
  'cat_completed',
  'student_completed_history',
  'teacher_login',
  'teacher_completed_aggregate',
  'admin_revoke',
  'student_revoked_history',
  'result_detail_request_blocked',
  'sessions_cleaned',
  'screenshots',
];
export const REQUIRED_SCREENSHOTS = [
  'admin-task-published.png',
  'student-completed-history.png',
  'teacher-task-summary.png',
  'admin-task-revoked.png',
  'student-revoked-history.png',
];
export const FAILURE_SCREENSHOT_NAME = 'admin-school-operations-failure.png';
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError',
  'ProtocolError', 'TargetClosedError', 'WorkflowResponseError',
];
export const FAILURE_ROUTE_MODES = [
  'login', 'student_home', 'student_assessments', 'student_assessment_new',
  'student_assessment_session', 'student_assessment_result', 'teacher_overview',
  'admin_overview', 'other',
];
export const CAT_FAILURE_SUBSTAGES = [
  'task_row', 'task_click', 'task_route', 'question_ready', 'progress', 'submit', 'complete',
];
export const CAT_QUESTION_COMPLETION_SELECTOR = 'button[aria-label="完成测评"]';
export const CAT_CARD_COMPLETION_SELECTOR = '.assessment-complete-card .question-card__footer button';
export const CAT_COMPLETION_BUTTON_SELECTOR =
  `${CAT_QUESTION_COMPLETION_SELECTOR}, ${CAT_CARD_COMPLETION_SELECTOR}`;
export const FAILURE_SELECTOR_KEYS = [
  'assessment_page', 'assessment_loading', 'question_title', 'question_card',
  'assessment_complete_card', 'assessment_error', 'assigned_task',
];
export const SAFE_DIAGNOSTIC_ENDPOINTS = [
  '/api/v1/school/tasks/{task_ref}/start',
  '/api/v1/assessments/{assessment_id}/state',
  '/api/v1/assessments/{assessment_id}/responses',
  '/api/v1/assessments/{assessment_id}/complete',
];

const failResult = () => ({
  workflow: WORKFLOW,
  status: 'FAIL',
  stages: Object.fromEntries(TASK_STAGE_KEYS.map((key) => [key, 'FAIL'])),
  screenshots: [],
});

export function validTaskPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  if (typeof payload.artifact_dir !== 'string' || !path.isAbsolute(payload.artifact_dir)) return false;
  const parts = path.resolve(payload.artifact_dir).split(path.sep);
  const workspaceIndex = parts.indexOf(WORKSPACE_PREFIX);
  if (workspaceIndex < 0) return false;
  const workspace = path.resolve(parts.slice(0, workspaceIndex + 1).join(path.sep));
  const artifactRelative = path.relative(workspace, path.resolve(payload.artifact_dir));
  const artifactParts = artifactRelative.split(path.sep);
  if (path.isAbsolute(artifactRelative) || artifactParts.length !== 2 || artifactParts[0] !== 'browser-qa') return false;
  if (payload.frontend_url !== 'http://127.0.0.1:4178' || payload.backend_url !== 'http://127.0.0.1:8088') return false;
  for (const [slot, expected] of Object.entries(ACCOUNT_ROUTES)) {
    const account = payload.credentials?.[slot];
    const configured = payload.accounts?.[slot];
    if (!account || typeof account.username !== 'string' || !account.username.startsWith('SYNTHETIC_')
      || typeof account.password !== 'string' || account.password.length < 16
      || !configured || configured.role !== expected.role || configured.api_role !== expected.api_role
      || configured.path !== expected.path) return false;
  }
  return true;
}

export function summarizeTaskWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null) {
  const stageObject = stages && typeof stages === 'object' && !Array.isArray(stages);
  const exactStages = stageObject
    && Object.keys(stages).length === TASK_STAGE_KEYS.length
    && TASK_STAGE_KEYS.every((key) => stages[key] === 'PASS');
  const screenshots = Array.isArray(screenshotFiles) ? screenshotFiles : [];
  const exactScreenshots = screenshots.length === REQUIRED_SCREENSHOTS.length
    && REQUIRED_SCREENSHOTS.every((name) => screenshots.includes(name))
    && screenshots.every((name) => typeof name === 'string' && path.basename(name) === name);
  const filesExist = exactScreenshots && REQUIRED_SCREENSHOTS.every((name) => {
    try { return require('node:fs').statSync(path.join(artifactDir, name)).isFile(); } catch { return false; }
  });
  const safeFailure = failure && TASK_STAGE_KEYS.includes(failure.stage)
    && SAFE_FAILURE_CLASSES.includes(failure.error_class)
    ? {
      stage: failure.stage,
      error_class: failure.error_class,
      ...(failure.screenshot === FAILURE_SCREENSHOT_NAME
        && require('node:fs').existsSync(path.join(artifactDir, FAILURE_SCREENSHOT_NAME))
        ? { screenshot: FAILURE_SCREENSHOT_NAME }
        : {}),
      ...sanitizePageDiagnostics(failure.diagnostics),
    }
    : null;
  const passed = runnerExitCode === 0 && exactStages && filesExist;
  return {
    workflow: WORKFLOW,
    status: passed ? 'PASS' : 'FAIL',
    stages: Object.fromEntries(TASK_STAGE_KEYS.map((key) => [key, stageObject && stages[key] === 'PASS' ? 'PASS' : 'FAIL'])),
    screenshots: passed ? [...REQUIRED_SCREENSHOTS] : [],
    ...(!passed && safeFailure ? { failure: safeFailure } : {}),
  };
}

const safeExceptionClass = (error) => {
  const name = error && typeof error === 'object' && typeof error.name === 'string' ? error.name : '';
  return SAFE_FAILURE_CLASSES.includes(name) ? name : 'Error';
};

function routeMode(pathname) {
  if (pathname === '/login') return 'login';
  if (pathname === '/student/home') return 'student_home';
  if (pathname === '/student/assessments') return 'student_assessments';
  if (pathname === '/student/assessment') return 'student_assessment_new';
  if (/^\/student\/assessment\/[^/]+\/result$/.test(pathname)) return 'student_assessment_result';
  if (/^\/student\/assessment\/[^/]+$/.test(pathname)) return 'student_assessment_session';
  if (pathname === '/teacher/overview') return 'teacher_overview';
  if (pathname === '/admin/overview') return 'admin_overview';
  return 'other';
}

function sanitizePageDiagnostics(diagnostics) {
  if (!diagnostics || typeof diagnostics !== 'object') return {};
  const safe = {};
  if (FAILURE_ROUTE_MODES.includes(diagnostics.route_mode)) safe.route_mode = diagnostics.route_mode;
  if (CAT_FAILURE_SUBSTAGES.includes(diagnostics.cat_substage)) safe.cat_substage = diagnostics.cat_substage;
  const selectors = diagnostics.selectors;
  if (selectors && typeof selectors === 'object' && FAILURE_SELECTOR_KEYS.every((key) => typeof selectors[key] === 'boolean')) {
    safe.selectors = Object.fromEntries(FAILURE_SELECTOR_KEYS.map((key) => [key, selectors[key]]));
  }
  const responses = diagnostics.responses;
  if (Array.isArray(responses)) {
    safe.responses = responses.slice(-12).flatMap((response) => {
      if (!response || typeof response !== 'object'
        || !['GET', 'POST'].includes(response.method)
        || !Number.isInteger(response.status) || response.status < 100 || response.status > 599
        || !SAFE_DIAGNOSTIC_ENDPOINTS.includes(response.endpoint)) return [];
      return [{ method: response.method, status: response.status, endpoint: response.endpoint }];
    });
  }
  return safe;
}

export async function cleanupRoleSession(page, context, {
  loginSubmitted = true,
  logout = uiLogout,
  fallbackLogout = bestEffortSessionLogout,
} = {}) {
  let logoutStatus = loginSubmitted ? 'FAIL' : 'PASS';
  let contextStatus = 'FAIL';
  if (loginSubmitted && page) {
    try {
      await logout(page);
      logoutStatus = 'PASS';
    } catch {
      try { logoutStatus = await fallbackLogout(page) ? 'PASS' : 'FAIL'; } catch { logoutStatus = 'FAIL'; }
    }
  }
  try {
    await context?.close();
    contextStatus = 'PASS';
  } catch {
    // A failed context close must keep the workflow gate closed.
  }
  return { logout: logoutStatus, context: contextStatus };
}

async function readInput() {
  let raw = '';
  for await (const chunk of process.stdin) raw += chunk;
  try {
    const parsed = JSON.parse(raw);
    raw = '';
    return parsed;
  } catch {
    raw = '';
    return null;
  }
}

async function uiLogout(page) {
  await page.locator('.account-menu > summary').click({ timeout: 3000 });
  await page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 3000 });
  await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
}

async function bestEffortSessionLogout(page) {
  if (!page) return false;
  try {
    return await page.evaluate(async (backendUrl) => {
      const csrfResponse = await fetch(`${backendUrl}/api/v1/auth/csrf`, {
        credentials: 'include', headers: { Accept: 'application/json' },
      });
      if (!csrfResponse.ok) return false;
      const csrfBody = await csrfResponse.json();
      const token = csrfBody?.data?.csrf_token;
      if (typeof token !== 'string' || !token) return false;
      const logoutResponse = await fetch(`${backendUrl}/api/v1/auth/logout`, {
        method: 'POST', credentials: 'include',
        headers: { Accept: 'application/json', 'X-CSRF-Token': token },
      });
      return logoutResponse.ok;
    }, 'http://127.0.0.1:8088');
  } catch {
    return false;
  }
}

async function withRoleSession(browser, payload, slot, task, onLogin) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  let page = null;
  let loginSubmitted = false;
  let taskSucceeded = true;
  let failureClass = null;
  let failureScreenshot = null;
  let diagnostics = null;
  let catSubstage = null;
  const responseDiagnostics = [];
  let cleanup = { logout: 'FAIL', context: 'FAIL' };
  try {
    page = await context.newPage();
    if (slot === 'alpha.student') {
      page.on('response', (response) => {
        const endpoint = safeEndpointTemplate(response.url());
        const request = response.request();
        const method = request.method();
        const status = response.status();
        if (endpoint && (method === 'GET' || method === 'POST') && Number.isInteger(status)) {
          responseDiagnostics.push({ method, status, endpoint });
          if (responseDiagnostics.length > 12) responseDiagnostics.shift();
        }
      });
    }
    await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
    const username = page.getByRole('textbox', { name: 'Username' });
    const password = page.getByLabel('Password');
    await username.waitFor({ state: 'visible' });
    await username.fill(payload.credentials[slot].username);
    await password.fill(payload.credentials[slot].password);
    loginSubmitted = true;
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    const picker = page.locator('#school-context');
    if (await picker.isVisible({ timeout: 1200 }).catch(() => false)) {
      const values = await picker.locator('option:not([disabled])').evaluateAll((items) => items.map((item) => item.value));
      if (values.length !== 1 || !values[0]) throw new Error('ContextSelectionFailed');
      await picker.selectOption(values[0]);
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
    }
    await page.waitForURL((url) => url.pathname === payload.accounts[slot].path, { timeout: 20000 });
    const passwordStillVisible = await password.isVisible().catch(() => false);
    if (passwordStillVisible && (await password.inputValue()) !== '') throw new Error('PasswordNotCleared');
    onLogin?.(page);
    await task(page, (substage) => {
      if (CAT_FAILURE_SUBSTAGES.includes(substage)) catSubstage = substage;
    });
  } catch (error) {
    taskSucceeded = false;
    failureClass = safeExceptionClass(error);
    if (slot === 'alpha.student' && page) {
      try {
        diagnostics = await readPageDiagnostics(page, responseDiagnostics, catSubstage);
      } catch {
        // Diagnostics must never replace the fixed failure class from the actual workflow error.
        diagnostics = null;
      }
    }
    if (slot === 'alpha.admin' && page && loginSubmitted) {
      try {
        await page.screenshot({
          path: path.join(payload.artifact_dir, FAILURE_SCREENSHOT_NAME),
          fullPage: true,
          animations: 'disabled',
          mask: [
            page.locator('.account-menu'),
            page.locator('input'),
            page.locator('select'),
            page.locator('.status-callout'),
            page.locator('.school-task__enrollments'),
            page.locator('.question-card'),
            page.locator('.assigned-tasks'),
            page.locator('.task-history'),
            page.locator('.assessment-result'),
          ],
        });
        failureScreenshot = FAILURE_SCREENSHOT_NAME;
      } catch {
        failureScreenshot = null;
      }
    }
  } finally {
    cleanup = await cleanupRoleSession(page, context, { loginSubmitted });
  }
  return { ...cleanup, taskSucceeded, failureClass, failureScreenshot, diagnostics };
}

function safeEndpointTemplate(rawUrl) {
  let pathname;
  try { pathname = new URL(rawUrl).pathname; } catch { return null; }
  if (/^\/api\/v1\/school\/tasks\/[^/]+\/start$/.test(pathname)) return '/api/v1/school/tasks/{task_ref}/start';
  if (/^\/api\/v1\/assessments\/[^/]+\/state$/.test(pathname)) return '/api/v1/assessments/{assessment_id}/state';
  if (/^\/api\/v1\/assessments\/[^/]+\/responses$/.test(pathname)) return '/api/v1/assessments/{assessment_id}/responses';
  if (/^\/api\/v1\/assessments\/[^/]+\/complete$/.test(pathname)) return '/api/v1/assessments/{assessment_id}/complete';
  return null;
}

async function readPageDiagnostics(page, responses, catSubstage) {
  let mode = 'other';
  try { mode = routeMode(new URL(page.url()).pathname); } catch { /* fixed fallback */ }
  const visible = async (selector) => page.locator(selector).isVisible().catch(() => false);
  const selectors = {
    assessment_page: await visible('.assessment-page'),
    assessment_loading: await visible('.assessment-loading'),
    question_title: await visible('#question-title'),
    question_card: await visible('.question-card'),
    assessment_complete_card: await visible('.assessment-complete-card'),
    assessment_error: await page.getByText('测评会话暂时不可用', { exact: true }).isVisible().catch(() => false),
    assigned_task: (await page.locator('.assigned-task').count().catch(() => 0)) > 0,
  };
  return { route_mode: mode, selectors, responses: [...responses], cat_substage };
}

const screenshot = async (page, artifactDir, name, extraMasks = []) => {
  if (!REQUIRED_SCREENSHOTS.includes(name)) throw new Error('UnexpectedScreenshotName');
  await page.screenshot({
    path: path.join(artifactDir, name),
    fullPage: true,
    animations: 'disabled',
    mask: [page.locator('.account-menu'), ...extraMasks],
  });
};

const localInputDate = (date) => {
  const pad = (part) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

async function assignSelectedMember(page, classRef, role) {
  const selectId = role === 'student' ? '#school-student-select' : '#school-teacher-select';
  const select = page.locator(selectId);
  await select.waitFor({ state: 'visible' });
  if (await select.locator('option').count() < 2) throw new Error('NoEligibleMember');
  await select.selectOption({ index: 1 });
  const endpoint = `/api/v1/school/classes/${encodeURIComponent(classRef)}/${role === 'student' ? 'students' : 'teachers'}`;
  const responsePromise = page.waitForResponse((response) => {
    const request = response.request();
    return request.method() === 'POST' && new URL(response.url()).pathname === endpoint;
  }, { timeout: 15000 });
  await select.locator('xpath=..').getByRole('button', { name: '分配', exact: true }).click();
  const response = await responsePromise;
  if (!response.ok()) {
    const error = new Error('School membership operation failed.');
    error.name = 'WorkflowResponseError';
    throw error;
  }
  const successMessage = role === 'student' ? '学生已加入班级。' : '教师已分配到班级。';
  await page.getByText(successMessage, { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}

async function createClassThroughUi(page) {
  const classSelect = page.locator('#school-class-select');
  await classSelect.waitFor({ state: 'visible', timeout: 15000 });
  const previousClassRef = await classSelect.inputValue();
  const responsePromise = page.waitForResponse((response) => {
    const request = response.request();
    return request.method() === 'POST' && new URL(response.url()).pathname === '/api/v1/school/classes';
  }, { timeout: 15000 });
  await page.getByRole('button', { name: '创建班级', exact: true }).click();
  const response = await responsePromise;
  if (response.status() !== 201) {
    const error = new Error('School class creation failed.');
    error.name = 'WorkflowResponseError';
    throw error;
  }
  await page.getByText('已收到服务端确认', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction((previous) => {
    const select = document.querySelector('#school-class-select');
    return Boolean(select && select.value !== previous && /^CLASS_/.test(select.value));
  }, previousClassRef, { timeout: 15000 });
  const classRef = await classSelect.inputValue();
  if (!classRef.startsWith('CLASS_') || classRef === previousClassRef) throw new Error('ClassCreationNotConfirmed');
  return classRef;
}

async function publishTask(page) {
  const opens = new Date(Date.now() - 5 * 60 * 1000);
  const due = new Date(Date.now() + 3 * 60 * 60 * 1000);
  await page.locator('#school-task-opens').fill(localInputDate(opens));
  await page.locator('#school-task-due').fill(localInputDate(due));
  await page.getByRole('button', { name: '发布任务', exact: true }).click();
  const task = page.locator('.school-task').first();
  await task.waitFor({ state: 'visible', timeout: 15000 });
  const summary = task.locator('small');
  await summary.waitFor({ state: 'visible' });
  const text = await summary.innerText();
  if (!/报名\s+1\s+·\s+有效\s+1\s+·\s+已撤销\s+0/.test(text)) throw new Error('PublicationRosterMismatch');
  const taskHeading = (await task.locator('strong').innerText()).trim();
  const match = taskHeading.match(/^任务\s+([A-Za-z0-9]{6})$/);
  if (!match) throw new Error('TaskReferenceUnavailable');
  return match[1];
}

const taskLabel = (taskShortRef) => `任务 ${taskShortRef}`;

async function completeCat(page, payload, taskShortRef, stages, setSubstage) {
  setSubstage('task_row');
  await page.goto(`${payload.frontend_url}/student/assessments`, { waitUntil: 'domcontentloaded' });
  const targetTask = page.locator('.assigned-task').filter({
    has: page.getByRole('heading', { name: taskLabel(taskShortRef), exact: true }),
  });
  await targetTask.first().waitFor({ state: 'visible', timeout: 15000 });
  if (await targetTask.count() !== 1) throw new Error('PublishedTaskNotUnique');
  setSubstage('task_click');
  await targetTask.getByRole('button', { name: '开始任务', exact: true }).click();
  setSubstage('task_route');
  await page.waitForURL((url) => /^\/student\/assessment\/[^/]+$/.test(url.pathname), { timeout: 15000 });
  setSubstage('question_ready');
  await page.locator('#question-title').waitFor({ state: 'visible', timeout: 15000 });
  stages.cat_started = 'PASS';

  let completedButton = page.locator(CAT_COMPLETION_BUTTON_SELECTOR).first();
  for (let index = 0; index < 12; index += 1) {
    setSubstage('progress');
    if (await completedButton.isVisible().catch(() => false)) break;
    const progress = page.getByRole('progressbar');
    const before = Number(await progress.getAttribute('aria-valuenow'));
    const options = page.locator('.answer-option');
    if (await options.count() < 1) throw new Error('CATQuestionUnavailable');
    await options.first().click();
    setSubstage('submit');
    await page.getByRole('button', { name: '下一题', exact: true }).click();
    setSubstage('progress');
    await page.waitForFunction(({ previous, questionSelector, cardSelector }) => {
      const bar = document.querySelector('[role="progressbar"]');
      const questionComplete = document.querySelector(questionSelector);
      const cardComplete = document.querySelector(cardSelector);
      return Boolean(questionComplete || cardComplete)
        || Number(bar?.getAttribute('aria-valuenow')) > previous;
    }, {
      previous: before,
      questionSelector: CAT_QUESTION_COMPLETION_SELECTOR,
      cardSelector: CAT_CARD_COMPLETION_SELECTOR,
    }, { timeout: 10000 });
    completedButton = page.locator(CAT_COMPLETION_BUTTON_SELECTOR).first();
  }
  setSubstage('complete');
  if (!(await completedButton.isVisible().catch(() => false))) throw new Error('CATCompletionGateUnavailable');

  let resultReadBlocked = 0;
  let signalResultReadBlocked;
  const blocked = new Promise((resolve) => { signalResultReadBlocked = resolve; });
  await page.route('**/api/v1/assessments/*', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === 'GET' && /^\/api\/v1\/assessments\/[^/]+$/.test(pathname)) {
      resultReadBlocked += 1;
      signalResultReadBlocked();
      await route.abort();
      return;
    }
    await route.continue();
  });
  const completeResponsePromise = page.waitForResponse((response) => {
    const request = response.request();
    return request.method() === 'POST'
      && /^\/api\/v1\/assessments\/[^/]+\/complete$/.test(new URL(response.url()).pathname);
  }, { timeout: 15000 });
  setSubstage('complete');
  await completedButton.click();
  const completeResponse = await completeResponsePromise;
  if (!completeResponse.ok()) {
    const error = new Error('Assessment completion was not accepted.');
    error.name = 'WorkflowResponseError';
    throw error;
  }
  await page.waitForURL((url) => /^\/student\/assessment\/[^/]+\/result$/.test(url.pathname), { timeout: 15000 });
  await Promise.race([blocked, new Promise((resolve) => setTimeout(resolve, 3000))]);
  if (resultReadBlocked !== 1) throw new Error('ResultDetailRequestWasNotBlocked');
  // This confirms only the browser intercepted the result-detail request. It is not a backend authorization test.
  stages.result_detail_request_blocked = 'PASS';

  await page.goto(`${payload.frontend_url}/student/assessments`, { waitUntil: 'domcontentloaded' });
  const completedHistory = page.locator('.task-history__entry').filter({
    has: page.getByRole('heading', { name: taskLabel(taskShortRef), exact: true }),
  });
  await completedHistory.waitFor({ state: 'visible', timeout: 15000 });
  if (await completedHistory.count() !== 1 || !(await completedHistory.innerText()).includes('已完成')) {
    throw new Error('CompletedTaskHistoryMismatch');
  }
  stages.cat_completed = 'PASS';
  stages.student_completed_history = 'PASS';
  await screenshot(page, payload.artifact_dir, 'student-completed-history.png');
}

async function checkTeacherAggregate(page, classRef, taskShortRef) {
  const row = page.locator('.task-progress-row')
    .filter({ has: page.getByText(`班级 ${classRef.slice(-6)}`, { exact: true }) })
    .filter({ has: page.getByRole('heading', { name: taskLabel(taskShortRef), exact: true }) });
  await row.waitFor({ state: 'visible', timeout: 15000 });
  if (await row.count() !== 1) throw new Error('TeacherTaskNotUnique');
  const completedCount = row.locator('dl > div').filter({
    has: page.getByText('已完成', { exact: true }),
  }).locator('dd');
  await completedCount.waitFor({ state: 'visible' });
  if ((await completedCount.innerText()).trim() !== '1') throw new Error('TeacherAggregateMismatch');
  const labels = await row.locator('dl dt').allTextContents();
  const expected = ['报名总数', '当前有效', '未开始', '准备中', '进行中', '已完成', '已结束', '不可继续', '已撤销'];
  if (JSON.stringify(labels) !== JSON.stringify(expected)) throw new Error('TeacherAggregateFieldsMismatch');
}

async function revokeTask(page, payload, classRef, taskShortRef) {
  await page.goto(`${payload.frontend_url}/admin/overview`, { waitUntil: 'domcontentloaded' });
  await page.locator('#school-class-select').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('#school-class-select').selectOption(classRef);
  const task = page.locator('.school-task').filter({
    has: page.getByText(taskLabel(taskShortRef), { exact: true }),
  });
  await task.waitFor({ state: 'visible', timeout: 15000 });
  if (await task.count() !== 1) throw new Error('PublishedTaskNotUnique');
  await task.getByRole('button', { name: '管理报名', exact: true }).click();
  const enrollment = task.locator('.school-task__enrollment').first();
  await enrollment.waitFor({ state: 'visible', timeout: 15000 });
  await enrollment.getByRole('button', { name: '撤销', exact: true }).click();
  await enrollment.getByText('已撤销', { exact: false }).waitFor({ state: 'visible', timeout: 15000 });
}

async function checkRevokedStudentHistory(page, payload, taskShortRef) {
  await page.goto(`${payload.frontend_url}/student/assessments`, { waitUntil: 'domcontentloaded' });
  const revoked = page.locator('.task-history__entry').filter({
    has: page.getByRole('heading', { name: taskLabel(taskShortRef), exact: true }),
  });
  await revoked.waitFor({ state: 'visible', timeout: 15000 });
  if (await revoked.count() !== 1 || !(await revoked.innerText()).includes('报名已撤销')) {
    throw new Error('RevokedTaskHistoryMismatch');
  }
  await screenshot(page, payload.artifact_dir, 'student-revoked-history.png');
  return true;
}

export async function runTaskWorkflow(payload, { chromium } = {}) {
  const stages = Object.fromEntries(TASK_STAGE_KEYS.map((key) => [key, 'FAIL']));
  const screenshotFiles = [];
  let browser = null;
  let classRef = '';
  let taskShortRef = '';
  let failure = null;
  let sessionsCleaned = true;
  const runRole = async (slot, loginStage, step) => {
    const cleanup = await withRoleSession(browser, payload, slot, step, () => { stages[loginStage] = 'PASS'; });
    if (cleanup.logout !== 'PASS' || cleanup.context !== 'PASS') sessionsCleaned = false;
    if (!cleanup.taskSucceeded) {
      const stage = TASK_STAGE_KEYS.find((key) => stages[key] !== 'PASS') ?? 'sessions_cleaned';
      failure = {
        stage,
        error_class: cleanup.failureClass ?? 'Error',
        ...(cleanup.failureScreenshot ? { screenshot: cleanup.failureScreenshot } : {}),
        ...(cleanup.diagnostics ? { diagnostics: cleanup.diagnostics } : {}),
      };
      throw new Error('RoleWorkflowFailed');
    }
  };
  try {
    browser ??= await chromium.launch({ headless: true });
    await runRole('alpha.admin', 'admin_login', async (page) => {
      await page.locator('#school-operations-title').waitFor({ state: 'visible', timeout: 15000 });
      classRef = await createClassThroughUi(page);
      stages.class_created = 'PASS';
      const classSelect = page.locator('#school-class-select');

      await assignSelectedMember(page, classRef, 'student');
      const selectedClass = classSelect.locator('option:checked');
      await selectedClass.waitFor({ state: 'attached' });
      await page.waitForFunction(() => /学生\s+1/.test(document.querySelector('#school-class-select option:checked')?.textContent ?? ''), undefined, { timeout: 15000 });
      if (!/学生\s+1/.test(await selectedClass.innerText())) throw new Error('StudentAssignmentNotConfirmed');
      stages.student_assigned = 'PASS';
      await assignSelectedMember(page, classRef, 'teacher');
      await page.waitForFunction(() => /教师\s+1/.test(document.querySelector('#school-class-select option:checked')?.textContent ?? ''), undefined, { timeout: 15000 });
      if (!/教师\s+1/.test(await selectedClass.innerText())) throw new Error('TeacherAssignmentNotConfirmed');
      stages.teacher_assigned = 'PASS';

      taskShortRef = await publishTask(page);
      stages.task_published = 'PASS';
      await screenshot(page, payload.artifact_dir, 'admin-task-published.png', [
        page.locator('#school-student-select'), page.locator('#school-teacher-select'),
        page.locator('.school-task__enrollments'),
      ]);
      screenshotFiles.push('admin-task-published.png');
    });

    await runRole('alpha.student', 'student_login', async (page, setSubstage) => {
      await completeCat(page, payload, taskShortRef, stages, setSubstage);
      screenshotFiles.push('student-completed-history.png');
    });

    await runRole('alpha.teacher', 'teacher_login', async (page) => {
      await checkTeacherAggregate(page, classRef, taskShortRef);
      stages.teacher_completed_aggregate = 'PASS';
      await screenshot(page, payload.artifact_dir, 'teacher-task-summary.png');
      screenshotFiles.push('teacher-task-summary.png');
    });

    await runRole('alpha.admin', 'admin_login', async (page) => {
      await page.locator('#school-operations-title').waitFor({ state: 'visible', timeout: 15000 });
      await revokeTask(page, payload, classRef, taskShortRef);
      stages.admin_revoke = 'PASS';
      await screenshot(page, payload.artifact_dir, 'admin-task-revoked.png', [
        page.locator('#school-student-select'), page.locator('#school-teacher-select'),
        page.locator('.school-task__enrollments'),
      ]);
      screenshotFiles.push('admin-task-revoked.png');
    });

    await runRole('alpha.student', 'student_login', async (page) => {
      await checkRevokedStudentHistory(page, payload, taskShortRef);
      stages.student_revoked_history = 'PASS';
      screenshotFiles.push('student-revoked-history.png');
    });
  } catch (error) {
    // Never forward browser errors, request bodies, prompt text, or credential-derived messages.
    if (!failure) {
      const stage = TASK_STAGE_KEYS.find((key) => stages[key] !== 'PASS') ?? 'sessions_cleaned';
      failure = { stage, error_class: safeExceptionClass(error) };
    }
  } finally {
    if (browser) {
      try { await browser.close(); } catch { sessionsCleaned = false; }
    }
    stages.sessions_cleaned = sessionsCleaned ? 'PASS' : 'FAIL';
    if (!sessionsCleaned && !failure) failure = { stage: 'sessions_cleaned', error_class: 'Error' };
    stages.screenshots = screenshotFiles.length === REQUIRED_SCREENSHOTS.length ? 'PASS' : 'FAIL';
  }
  return summarizeTaskWorkflow(stages, screenshotFiles, payload.artifact_dir, 0, failure);
}

async function main() {
  const payload = await readInput();
  if (!validTaskPayload(payload)) {
    process.stdout.write(`${JSON.stringify(failResult())}\n`);
    process.exitCode = 2;
    return;
  }
  let result = failResult();
  try {
    const { chromium } = require('@playwright/test');
    result = await runTaskWorkflow(payload, { chromium });
  } catch {
    result = failResult();
  }
  if (payload?.credentials) payload.credentials = undefined;
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.status === 'PASS' ? 0 : 2;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main().catch(() => {
    process.stdout.write(`${JSON.stringify(failResult())}\n`);
    process.exitCode = 2;
  });
}
