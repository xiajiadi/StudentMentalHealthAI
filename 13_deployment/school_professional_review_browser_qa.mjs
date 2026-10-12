import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const WORKFLOW = 'school-professional-review';
export const WORKSPACE = 'D:\\Projects\\.StudentMentalHealthAI-school-workspace-20261011';
export const FRONTEND_URL = 'http://127.0.0.1:4178';
export const BACKEND_URL = 'http://127.0.0.1:8088';
export const SCHOOL_REF = 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1';
export const REVIEW_NOTE = '合成演示复核记录，仅记录工作流状态。';
export const SCREENSHOTS = [
  'admin-professional-assignment.png',
  'specialist-professional-review-desktop.png',
  'specialist-professional-review-mobile.png',
];
export const SCREENSHOT_STAGES = {
  'admin-professional-assignment.png': 'admin_assignment_screenshot',
  'specialist-professional-review-desktop.png': 'desktop_screenshot',
  'specialist-professional-review-mobile.png': 'mobile_screenshot',
};
export const ADMIN_SCREENSHOT_MASK_SELECTORS = [
  '.account-menu',
  'input, textarea, select',
  '.school-task__enrollments',
  '#school-student-select',
  '#school-teacher-select',
  '.school-class-roster',
  '.school-roster',
];
export const SCREENSHOT_MASK_SELECTORS = [
  '.account-menu',
  '#professional-review-note',
  '.terminal-summary',
  'input, textarea, select',
];
export const UI_STAGE_KEYS = [
  'admin_login',
  'admin_class_and_task_selected',
  'assignment_post_confirmed',
  'admin_assignment_screenshot',
  'specialist_login',
  'assigned_task_matched_to_api_order',
  'completed_enrollment_selected',
  'case_created',
  'case_opened',
  'decision_saved',
  'reload_persisted_note_verified',
  'desktop_screenshot',
  'mobile_screenshot',
  'admin_revoke_confirmed',
  'specialist_cache_cleared',
  'specialist_task_disappeared',
  'sessions_cleaned',
];
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError',
  'ProtocolError', 'TargetClosedError', 'WorkflowResponseError',
];
export const REVIEW_NOTE_SELECTOR = '.terminal-summary';

const REF_PATTERNS = {
  class_ref: /^CLASS_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/,
  task_ref: /^TASK_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/,
  enrollment_ref: /^ENROLL_[A-Za-z0-9][A-Za-z0-9_.-]{0,121}$/,
};
const CREDENTIAL_SLOTS = ['alpha.admin', 'alpha.psychological_specialist'];
const FAILED_STAGES = () => Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));

function isWithinWorkspace(candidate) {
  const base = path.resolve(WORKSPACE);
  const target = path.resolve(candidate);
  const relative = path.relative(base, target);
  const parts = relative.split(path.sep);
  return parts.length === 2
    && parts[0] === 'browser-qa'
    && /^\d{8}T\d{6}Z-[a-f0-9]{32}$/.test(parts[1])
    && !path.isAbsolute(relative);
}

export function validProfessionalReviewPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  if (Object.keys(payload).sort().join('|') !== 'artifact_dir|backend_url|credentials|frontend_url|setup') return false;
  if (payload.frontend_url !== FRONTEND_URL || payload.backend_url !== BACKEND_URL
    || typeof payload.artifact_dir !== 'string' || !isWithinWorkspace(payload.artifact_dir)) return false;
  const setup = payload.setup;
  if (!setup || typeof setup !== 'object' || Array.isArray(setup)
    || Object.keys(setup).sort().join('|') !== 'class_ref|enrollment_ref|task_ref') return false;
  for (const [key, pattern] of Object.entries(REF_PATTERNS)) {
    if (typeof setup[key] !== 'string' || !pattern.test(setup[key])) return false;
  }
  if (new Set(Object.values(setup)).size !== Object.keys(REF_PATTERNS).length) return false;
  const credentials = payload.credentials;
  if (!credentials || typeof credentials !== 'object' || Array.isArray(credentials)
    || Object.keys(credentials).sort().join('|') !== [...CREDENTIAL_SLOTS].sort().join('|')) return false;
  return CREDENTIAL_SLOTS.every((slot) => {
    const account = credentials[slot];
    return account && typeof account === 'object' && !Array.isArray(account)
      && Object.keys(account).sort().join('|') === 'password|username'
      && typeof account.username === 'string' && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(account.username)
      && typeof account.password === 'string' && account.password.length >= 16 && account.password.length <= 512;
  });
}

export function professionalReviewTaskIndex(data, taskRef) {
  if (!Array.isArray(data) || typeof taskRef !== 'string' || !REF_PATTERNS.task_ref.test(taskRef)) return -1;
  const matches = data.flatMap((item, index) => item?.task_ref === taskRef ? [index] : []);
  return matches.length === 1 ? matches[0] : -1;
}

export function professionalReviewEnrollmentIndex(data, enrollmentRef) {
  if (!Array.isArray(data) || typeof enrollmentRef !== 'string' || !REF_PATTERNS.enrollment_ref.test(enrollmentRef)) return -1;
  const matches = data.flatMap((item, index) => item?.enrollment_ref === enrollmentRef ? [index] : []);
  return matches.length === 1 ? matches[0] : -1;
}

export function professionalReviewCaseIndex(data, caseRef) {
  if (!Array.isArray(data) || typeof caseRef !== 'string' || !/^PCR_[A-Za-z0-9][A-Za-z0-9_.-]{0,123}$/.test(caseRef)) return -1;
  const matches = data.flatMap((item, index) => item?.case_ref === caseRef ? [index] : []);
  return matches.length === 1 ? matches[0] : -1;
}

export function summarizeProfessionalReviewWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null) {
  const exactStages = stages && typeof stages === 'object' && !Array.isArray(stages)
    && Object.keys(stages).length === UI_STAGE_KEYS.length
    && UI_STAGE_KEYS.every((key) => Object.hasOwn(stages, key) && (stages[key] === 'PASS' || stages[key] === 'FAIL'));
  const safeStages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [
    key, exactStages && stages[key] === 'PASS' ? 'PASS' : 'FAIL',
  ]));
  const namesValid = Array.isArray(screenshotFiles)
    && screenshotFiles.length === SCREENSHOTS.length
    && new Set(screenshotFiles).size === SCREENSHOTS.length
    && SCREENSHOTS.every((name) => screenshotFiles.includes(name));
  for (const [name, stage] of Object.entries(SCREENSHOT_STAGES)) {
    let filePresent = false;
    try { filePresent = namesValid && require('node:fs').statSync(path.join(artifactDir, name)).isFile(); } catch { /* fixed failure */ }
    if (!filePresent) safeStages[stage] = 'FAIL';
  }
  const passed = runnerExitCode === 0 && exactStages && namesValid
    && UI_STAGE_KEYS.every((key) => safeStages[key] === 'PASS');
  const result = {
    workflow: WORKFLOW,
    status: passed ? 'PASS' : 'FAIL',
    stages: safeStages,
    screenshots: passed ? [...SCREENSHOTS] : [],
  };
  if (!passed && failure && UI_STAGE_KEYS.includes(failure.stage)) {
    result.failure = {
      stage: failure.stage,
      error_class: SAFE_FAILURE_CLASSES.includes(failure.error_class) ? failure.error_class : 'Error',
    };
  }
  return result;
}

const safeExceptionClass = (error) => {
  const name = error && typeof error === 'object' && typeof error.name === 'string' ? error.name : '';
  return SAFE_FAILURE_CLASSES.includes(name) ? name : 'Error';
};

async function readInput() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  const raw = Buffer.concat(chunks);
  try { return JSON.parse(raw.toString('utf8')); } catch { return null; }
  finally {
    raw.fill(0);
    for (const chunk of chunks) chunk.fill(0);
  }
}

async function apiActor(page, backendUrl) {
  return page.evaluate(async (base) => {
    const response = await fetch(`${base}/api/v1/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' } });
    if (!response.ok) return { status: response.status, actor: null };
    const envelope = await response.json();
    return { status: response.status, actor: envelope?.data?.actor ?? envelope?.data };
  }, backendUrl);
}

async function createRoleSession(browser, slot) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  const page = await context.newPage();
  const session = { context, page, loginSubmitted: false, slot, specialistIds: [] };
  page.on('response', (response) => {
    if (responseMatches(response, 'GET', '/api/v1/school/professional-reviews/specialists')) {
      session.specialistIds.push(response.status());
    }
  });
  return session;
}

export async function loginRole(session, payload, expectedRole, expectedPath) {
  const page = session.page;
  await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
  const username = page.getByRole('textbox', { name: 'Username' });
  const password = page.locator('#password');
  await username.waitFor({ state: 'visible', timeout: 10000 });
  if ((await username.inputValue()) !== '' || (await password.inputValue()) !== '') throw new Error('LoginFormNotBlank');
  await username.fill(payload.credentials[session.slot].username);
  await password.fill(payload.credentials[session.slot].password);
  session.loginSubmitted = true;
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  const contextPicker = page.locator('#school-context');
  if (await contextPicker.isVisible({ timeout: 1200 }).catch(() => false)) {
    const choices = await contextPicker.locator('option:not([disabled])').evaluateAll((items) => items.map((item) => item.value));
    if (choices.length !== 1 || !choices[0]) throw new Error('SchoolContextMismatch');
    await contextPicker.selectOption(choices[0]);
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
  }
  await page.waitForURL((url) => url.pathname === expectedPath, { timeout: 20000 });
  if (await password.isVisible().catch(() => false) && (await password.inputValue()) !== '') throw new Error('LoginPasswordNotCleared');
  const authenticated = await apiActor(page, payload.backend_url);
  if (authenticated.status !== 200
    || authenticated.actor?.active_context?.role !== expectedRole
    || authenticated.actor?.active_context?.school_ref !== SCHOOL_REF) throw new Error('AuthenticatedRoleMismatch');
  session.actorUserId = authenticated.actor?.user_id ?? authenticated.actor?.userId ?? null;
  if (session.slot === 'alpha.psychological_specialist'
    && (typeof session.actorUserId !== 'string' || !/^USER_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$/.test(session.actorUserId))) {
    throw new Error('SpecialistIdentityUnavailable');
  }
  return session;
}

async function logoutSession(session, backendUrl) {
  let logout = !session.loginSubmitted;
  let closed = false;
  if (session.loginSubmitted) {
    try {
      await session.page.locator('.account-menu > summary').click({ timeout: 3000 });
      await session.page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 3000 });
      await session.page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
      logout = true;
    } catch {
      try {
        logout = await session.page.evaluate(async (base) => {
          const csrf = await fetch(`${base}/api/v1/auth/csrf`, { credentials: 'include', headers: { Accept: 'application/json' } });
          if (!csrf.ok) return false;
          const envelope = await csrf.json();
          const token = envelope?.data?.csrf_token;
          if (typeof token !== 'string' || !token) return false;
          const response = await fetch(`${base}/api/v1/auth/logout`, {
            method: 'POST', credentials: 'include', headers: { Accept: 'application/json', 'X-CSRF-Token': token },
          });
          return response.ok;
        }, backendUrl);
      } catch { logout = false; }
    }
  }
  try { await session.context.close(); closed = true; } catch { closed = false; }
  return logout && closed;
}

function responseMatches(response, method, pathname, query = null) {
  const request = response.request();
  const url = new URL(response.url());
  const pathMatches = pathname instanceof RegExp ? pathname.test(url.pathname) : url.pathname === pathname;
  return url.origin === BACKEND_URL && request.method() === method && pathMatches
    && (!query || Object.entries(query).every(([key, value]) => url.searchParams.get(key) === String(value)));
}

const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

async function captureWrite(page, predicate, action, acceptedStatuses) {
  const responsePromise = page.waitForResponse(predicate, { timeout: 20000 });
  await action();
  const response = await responsePromise;
  if (!acceptedStatuses.includes(response.status())) {
    const error = new Error('WorkflowWriteNotConfirmed');
    error.name = 'WorkflowResponseError';
    throw error;
  }
  return response;
}

function responseData(envelope) {
  const value = envelope?.data?.data ?? envelope?.data;
  if (value === undefined) throw new Error('WorkflowResponseShapeMismatch');
  return value;
}

function clearPayloadCredentials(payload) {
  const credentials = payload && typeof payload === 'object' ? payload.credentials : null;
  if (credentials && typeof credentials === 'object') {
    for (const account of Object.values(credentials)) {
      if (account && typeof account === 'object') {
        account.username = '';
        account.password = '';
      }
    }
  }
  if (payload && typeof payload === 'object') {
    payload.credentials = undefined;
    payload.setup = undefined;
  }
}

async function getTasksAndIndex(page, payload) {
  const responsePromise = page.waitForResponse((response) => responseMatches(
    response, 'GET', '/api/v1/school/professional-reviews/tasks',
  ), { timeout: 15000 });
  await page.goto(`${payload.frontend_url}/specialist/tasks`, { waitUntil: 'domcontentloaded' });
  const response = await responsePromise;
  if (!response.ok()) throw new Error('SpecialistTaskReadFailed');
  const data = responseData(await response.json());
  const index = professionalReviewTaskIndex(data, payload.setup.task_ref);
  if (index < 0) return { tasks: Array.isArray(data) ? data : [], targetIndex: -1 };
  const buttons = page.locator('.task-option');
  await buttons.nth(index).waitFor({ state: 'visible', timeout: 15000 });
  if (await buttons.count() !== data.length) throw new Error('TaskApiUiOrderMismatch');
  const firstEnrollmentPromise = page.waitForResponse((item) => responseMatches(
    item,
    'GET',
    `/api/v1/school/professional-reviews/tasks/${encodeURIComponent(payload.setup.task_ref)}/eligible-enrollments`,
    { offset: 0, limit: 10 },
  ), { timeout: 15000 });
  await buttons.nth(index).click();
  const firstEnrollmentResponse = await firstEnrollmentPromise;
  return { tasks: data, targetIndex: index, firstEnrollmentResponse };
}

async function findEnrollmentOnCurrentPage(page, payload, offset, firstResponse = null, expectExistingCase = false) {
  const responsePromise = firstResponse ?? page.waitForResponse((response) => responseMatches(
    response,
    'GET',
    `/api/v1/school/professional-reviews/tasks/${encodeURIComponent(payload.setup.task_ref)}/eligible-enrollments`,
    { offset, limit: 10 },
  ), { timeout: 15000 });
  if (offset > 0) await page.getByRole('button', { name: '下一页完成记录', exact: true }).click();
  const response = await responsePromise;
  if (!response.ok()) throw new Error('EligibleEnrollmentReadFailed');
  const pageData = responseData(await response.json());
  if (!pageData || !Array.isArray(pageData.items) || !Number.isInteger(pageData.total)) throw new Error('EnrollmentPageShapeMismatch');
  const index = professionalReviewEnrollmentIndex(pageData.items, payload.setup.enrollment_ref);
  if (index >= 0) {
    const recordButton = page.locator('.record-option').nth(index);
    await recordButton.waitFor({ state: 'visible', timeout: 10000 });
    const label = await recordButton.innerText();
    if (expectExistingCase ? !label.includes('已有记录') : !label.includes('可建立')) {
      throw new Error(expectExistingCase ? 'ExistingReviewCaseUnavailable' : 'EnrollmentAlreadyReviewed');
    }
    await recordButton.click();
    return { found: true, total: pageData.total };
  }
  return { found: false, total: pageData.total, visible: pageData.items.length };
}

async function selectCompletedEnrollment(page, payload, firstResponse, expectExistingCase = false) {
  let offset = 0;
  for (let pageNumber = 0; pageNumber < 100; pageNumber += 1) {
    const found = await findEnrollmentOnCurrentPage(
      page, payload, offset, pageNumber === 0 ? firstResponse : null, expectExistingCase,
    );
    if (found.found) return true;
    if (offset + found.visible >= found.total || found.visible === 0) break;
    offset += found.visible;
  }
  throw new Error('PreparedCompletedEnrollmentUnavailable');
}

async function assignSpecialist(page, adminSession, specialistUserId, payload) {
  await page.locator('#school-operations-title').waitFor({ state: 'visible', timeout: 15000 });
  const specialistsPromise = page.waitForResponse((response) => responseMatches(
    response, 'GET', '/api/v1/school/professional-reviews/specialists',
  ), { timeout: 15000 });
  await page.locator('#school-class-select').selectOption(payload.setup.class_ref);
  const taskSelect = page.locator('#professional-assignment-task');
  await taskSelect.waitFor({ state: 'visible', timeout: 15000 });
  await taskSelect.selectOption(payload.setup.task_ref);
  const specialistSelect = page.locator('#professional-assignment-specialist');
  await specialistSelect.waitFor({ state: 'visible', timeout: 15000 });
  const specialistsResponseStatus = (await specialistsPromise).status();
  if (specialistsResponseStatus !== 200) throw new Error('SameSchoolSpecialistsNotConfirmed');
  await specialistSelect.locator(`option[value="${specialistUserId}"]`).waitFor({ state: 'attached', timeout: 15000 });
  const selected = await specialistSelect.locator('option').evaluateAll((options, expectedId) => {
    const eligible = options.find((option) => option.value === expectedId && !option.disabled);
    return eligible ? { value: eligible.value, label: eligible.textContent?.trim() ?? '' } : null;
  }, specialistUserId);
  if (!selected?.value || !selected.label) throw new Error('SameSchoolSpecialistUnavailable');
  await specialistSelect.selectOption(selected.value);
  if (await page.locator('#school-class-select').inputValue() !== payload.setup.class_ref
    || await taskSelect.inputValue() !== payload.setup.task_ref) throw new Error('AdminScopeSelectionMismatch');
  const endpoint = `/api/v1/school/professional-reviews/tasks/${encodeURIComponent(payload.setup.task_ref)}/assignments`;
  await captureWrite(
    page,
    (response) => responseMatches(response, 'POST', endpoint),
    () => page.locator('.professional-assignments').getByRole('button', { name: '分配', exact: true }).click(),
    [200],
  );
  await page.getByText('专员已分配到任务。', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  return selected.label;
}

async function runSpecialistWorkflow(page, payload, stages, screenshotFiles, setFailureStage) {
  setFailureStage('assigned_task_matched_to_api_order');
  const { targetIndex, firstEnrollmentResponse } = await getTasksAndIndex(page, payload);
  if (targetIndex < 0) throw new Error('AssignedTaskMissingFromApi');
  stages.assigned_task_matched_to_api_order = 'PASS';
  setFailureStage('completed_enrollment_selected');
  await selectCompletedEnrollment(page, payload, firstEnrollmentResponse);
  stages.completed_enrollment_selected = 'PASS';

  const taskPath = `/api/v1/school/professional-reviews/tasks/${encodeURIComponent(payload.setup.task_ref)}`;
  setFailureStage('case_created');
  await captureWrite(
    page,
    (response) => responseMatches(response, 'POST', `${taskPath}/cases`),
    () => page.getByRole('button', { name: '建立复核记录', exact: true }).click(),
    [200],
  );
  await page.getByRole('button', { name: '开始处理', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  stages.case_created = 'PASS';

  await captureWrite(
    page,
    (response) => responseMatches(response, 'POST', new RegExp(`^${escapeRegex(taskPath)}/cases/PCR_[A-Za-z0-9][A-Za-z0-9_.-]{0,123}/open$`)),
    () => page.getByRole('button', { name: '开始处理', exact: true }).click(),
    [200],
  );
  await page.locator('#professional-review-note').waitFor({ state: 'visible', timeout: 15000 });
  stages.case_opened = 'PASS';
  setFailureStage('decision_saved');
  await page.locator('#professional-review-note').fill(REVIEW_NOTE);
  await captureWrite(
    page,
    (response) => {
      const request = response.request();
      return responseMatches(
        response,
        'POST',
        new RegExp(`^${escapeRegex(taskPath)}/cases/PCR_[A-Za-z0-9][A-Za-z0-9_.-]{0,123}/decision$`),
      ) && request.method() === 'POST';
    },
    () => page.getByRole('button', { name: '确认完成', exact: true }).click(),
    [200],
  );
  await page.locator('.terminal-summary').getByText(REVIEW_NOTE, { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  await page.getByText('报告状态：未发布。此工作流操作不会向学生端发布内容。', { exact: true }).waitFor({ state: 'visible' });
  stages.decision_saved = 'PASS';

  setFailureStage('reload_persisted_note_verified');
  await page.reload({ waitUntil: 'domcontentloaded' });
  const { targetIndex: reloadedIndex, firstEnrollmentResponse: reloadedEnrollmentResponse } = await getTasksAndIndex(page, payload);
  if (reloadedIndex < 0) throw new Error('AssignedTaskMissingAfterReload');
  const enrollment = await selectCompletedEnrollment(page, payload, reloadedEnrollmentResponse, true);
  if (!enrollment) throw new Error('ReviewedEnrollmentMissingAfterReload');
  await page.locator('.terminal-summary').getByText(REVIEW_NOTE, { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  stages.reload_persisted_note_verified = 'PASS';

  setFailureStage('desktop_screenshot');
  await captureScreenshot(page, payload, SCREENSHOTS[1], 1365, 900);
  screenshotFiles.push(SCREENSHOTS[1]);
  stages.desktop_screenshot = 'PASS';
  setFailureStage('mobile_screenshot');
  await captureScreenshot(page, payload, SCREENSHOTS[2], 390, 844);
  screenshotFiles.push(SCREENSHOTS[2]);
  stages.mobile_screenshot = 'PASS';
}

async function captureScreenshot(page, payload, name, width, height) {
  if (!SCREENSHOTS.includes(name)) throw new Error('UnexpectedScreenshotName');
  await page.setViewportSize({ width, height });
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
  });
  await page.screenshot({
    path: path.join(payload.artifact_dir, name),
    fullPage: true,
    animations: 'disabled',
    mask: SCREENSHOT_MASK_SELECTORS.map((selector) => page.locator(selector)),
  });
}

async function captureAdminAssignmentScreenshot(page, payload) {
  const name = SCREENSHOTS[0];
  if (name !== 'admin-professional-assignment.png') throw new Error('UnexpectedScreenshotName');
  await page.setViewportSize({ width: 1365, height: 900 });
  await page.screenshot({
    path: path.join(payload.artifact_dir, name),
    fullPage: true,
    animations: 'disabled',
    mask: ADMIN_SCREENSHOT_MASK_SELECTORS.map((selector) => page.locator(selector)),
  });
}

async function revokeAssignment(page, payload, specialistLabel) {
  await page.locator('#school-operations-title').waitFor({ state: 'visible', timeout: 15000 });
  await page.locator('#school-class-select').selectOption(payload.setup.class_ref);
  const taskSelect = page.locator('#professional-assignment-task');
  await taskSelect.selectOption(payload.setup.task_ref);
  const row = page.locator('.professional-assignments__row')
    .filter({ hasText: specialistLabel }).filter({ hasText: '当前有效' });
  if (await row.count() !== 1) throw new Error('TargetAssignmentNotUnique');
  await row.waitFor({ state: 'visible', timeout: 15000 });
  const endpoint = new RegExp(`^/api/v1/school/professional-reviews/tasks/${encodeURIComponent(payload.setup.task_ref)}/assignments/ASSIGN_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}/revoke$`);
  await captureWrite(
    page,
    (response) => responseMatches(response, 'POST', endpoint),
    () => row.getByRole('button', { name: '撤销分配', exact: true }).click(),
    [200],
  );
  const updatedRow = page.locator('.professional-assignments__row').filter({ hasText: specialistLabel });
  await updatedRow.getByText('已撤销', { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}

export async function runProfessionalReviewWorkflow(payload, { chromium } = {}) {
  const stages = FAILED_STAGES();
  const screenshotFiles = [];
  const sessions = [];
  let browser = null;
  let failure = null;
  let failureStage = 'admin_login';
  try {
    browser ??= await chromium.launch({ headless: true });
    const adminSession = await createRoleSession(browser, 'alpha.admin');
    sessions.push(adminSession);
    await loginRole(adminSession, payload, 'ADMIN', '/admin/overview');
    stages.admin_login = 'PASS';

    failureStage = 'specialist_login';
    const specialistSession = await createRoleSession(browser, 'alpha.psychological_specialist');
    sessions.push(specialistSession);
    await loginRole(specialistSession, payload, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/overview');
    specialistSession.specialistUserId = specialistSession.actorUserId;
    stages.specialist_login = 'PASS';

    failureStage = 'admin_class_and_task_selected';
    const specialistLabel = await assignSpecialist(adminSession.page, adminSession, specialistSession.specialistUserId, payload);
    stages.admin_class_and_task_selected = 'PASS';
    stages.assignment_post_confirmed = 'PASS';
    failureStage = 'admin_assignment_screenshot';
    await captureAdminAssignmentScreenshot(adminSession.page, payload);
    screenshotFiles.push(SCREENSHOTS[0]);
    stages.admin_assignment_screenshot = 'PASS';

    await runSpecialistWorkflow(
      specialistSession.page,
      payload,
      stages,
      screenshotFiles,
      (stage) => { failureStage = stage; },
    );

    failureStage = 'admin_revoke_confirmed';
    await revokeAssignment(adminSession.page, payload, specialistLabel);
    stages.admin_revoke_confirmed = 'PASS';

    failureStage = 'specialist_task_disappeared';
    const refreshPromise = specialistSession.page.waitForResponse((response) => responseMatches(
      response, 'GET', '/api/v1/school/professional-reviews/tasks',
    ), { timeout: 15000 });
    await specialistSession.page.getByRole('button', { name: '刷新任务', exact: true }).click();
    const refreshed = await refreshPromise;
    if (!refreshed.ok()) throw new Error('RevokedTaskRefreshFailed');
    const remainingTasks = responseData(await refreshed.json());
    if (!Array.isArray(remainingTasks)
      || remainingTasks.some((task) => task?.task_ref === payload.setup.task_ref)) throw new Error('RevokedTaskStillInApi');
    await specialistSession.page.getByText('任务访问状态已变化，已清除本页缓存。请确认当前指派后重新选择任务。', { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 });
    const visibleText = await specialistSession.page.locator('body').innerText();
    if (visibleText.includes(REVIEW_NOTE)
      || await specialistSession.page.locator(REVIEW_NOTE_SELECTOR).count() !== 0
      || await specialistSession.page.locator('#professional-review-note').count() !== 0) {
      throw new Error('RevokedNoteStillVisible');
    }
    stages.specialist_cache_cleared = 'PASS';
    if (await specialistSession.page.locator('.task-option').count() !== remainingTasks.length) throw new Error('RemainingTaskCountMismatch');
    if (remainingTasks.length === 0) {
      await specialistSession.page.getByText('当前没有可显示的已指派任务。', { exact: true })
        .waitFor({ state: 'visible', timeout: 15000 });
    }
    stages.specialist_task_disappeared = 'PASS';
  } catch (error) {
    failure = { stage: failureStage, error_class: safeExceptionClass(error) };
  } finally {
    let cleanupOk = true;
    for (const session of sessions.reverse()) {
      const cleaned = await logoutSession(session, payload.backend_url);
      if (!cleaned) cleanupOk = false;
    }
    stages.sessions_cleaned = cleanupOk ? 'PASS' : 'FAIL';
    if (browser) {
      try { await browser.close(); } catch { cleanupOk = false; stages.sessions_cleaned = 'FAIL'; }
    }
    if (!cleanupOk && !failure) failure = { stage: 'sessions_cleaned', error_class: 'Error' };
  }
  return summarizeProfessionalReviewWorkflow(stages, screenshotFiles, payload.artifact_dir, failure ? 2 : 0, failure);
}

async function main() {
  const payload = await readInput();
  if (!validProfessionalReviewPayload(payload)) {
    clearPayloadCredentials(payload);
    process.stdout.write(`${JSON.stringify({ workflow: WORKFLOW, status: 'FAIL', stages: FAILED_STAGES(), screenshots: [] })}\n`);
    process.exitCode = 2;
    return;
  }
  let result;
  try {
    const { chromium } = require('@playwright/test');
    result = await runProfessionalReviewWorkflow(payload, { chromium });
  } catch {
    result = {
      workflow: WORKFLOW,
      status: 'FAIL',
      stages: FAILED_STAGES(),
      screenshots: [],
      failure: { stage: 'admin_login', error_class: 'Error' },
    };
  } finally {
    clearPayloadCredentials(payload);
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.status === 'PASS' ? 0 : 2;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main().catch(() => {
    process.stdout.write(`${JSON.stringify({ workflow: WORKFLOW, status: 'FAIL', stages: FAILED_STAGES(), screenshots: [] })}\n`);
    process.exitCode = 2;
  });
}
