import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');

export const FRONTEND_URL = 'http://127.0.0.1:4178';
export const BACKEND_URL = 'http://127.0.0.1:8088';
export const SAFETY_URL = 'http://127.0.0.1:8190';
export const RAG_URL = 'http://127.0.0.1:8170';
export const WORKSPACE = 'D:\\Projects\\.StudentMentalHealthAI-school-workspace-20261011';
export const SCHOOL_REF = 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1';
export const SCREENSHOTS = [
  'student-independent-conversation-desktop.png',
  'student-independent-conversation-mobile.png',
];
export const SCREENSHOT_STAGES = {
  'student-independent-conversation-desktop.png': 'desktop_screenshot',
  'student-independent-conversation-mobile.png': 'mobile_screenshot',
};
export const SCREENSHOT_MASK_SELECTORS = [
  '.account-menu',
  '.conversation-message--student',
  'input, textarea, select',
];
export const UI_STAGE_KEYS = [
  'safety_ready',
  'rag_ready',
  'browser_start',
  'student_login',
  'support_open',
  'conversation_created',
  'message_sent',
  'abstention_body_verified',
  'citations_absent',
  'reload_history_verified',
  'first_logout',
  'fresh_student_login',
  'fresh_support_open',
  'fresh_login_history_verified',
  'desktop_screenshot',
  'mobile_screenshot',
  'logout',
];
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError',
  'ProtocolError', 'TargetClosedError', 'WorkflowResponseError',
];

const EXPECTED_SCHOOL = SCHOOL_REF;
const ABSTENTION_LABEL = '资料不足，暂不提供建议';
const ABSTENTION_SUMMARY = '目前没有找到适用的已审核资料，因此暂时无法提供基于资料的建议。';
const QUERY = '大学生学习时怎么安排休息比较合适？';
const CONVERSATION_ID = /^CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/;

const failedStages = () => Object.fromEntries(UI_STAGE_KEYS.map((stage) => [stage, 'FAIL']));

export function safeConversationId(envelope) {
  const value = envelope?.data?.conversation_id;
  return typeof value === 'string' && CONVERSATION_ID.test(value) ? value : null;
}

export function conversationItemSelector(conversationId) {
  if (typeof conversationId !== 'string' || !CONVERSATION_ID.test(conversationId)) return null;
  return `.conversation-list__item[data-conversation-id="${conversationId}"]`;
}

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

export function validConversationPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  if (Object.keys(payload).sort().join('|') !== 'artifact_dir|backend_url|frontend_url|school_ref|student') return false;
  const student = payload.student;
  return payload.frontend_url === FRONTEND_URL
    && payload.backend_url === BACKEND_URL
    && payload.school_ref === EXPECTED_SCHOOL
    && typeof payload.artifact_dir === 'string'
    && isWithinWorkspace(payload.artifact_dir)
    && student && typeof student === 'object' && !Array.isArray(student)
    && Object.keys(student).sort().join('|') === 'password|username'
    && typeof student.username === 'string'
    && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(student.username)
    && typeof student.password === 'string'
    && student.password.length >= 16
    && student.password.length <= 512;
}

export function summarizeConversationWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null) {
  const exactStages = stages && typeof stages === 'object'
    && Object.keys(stages).length === UI_STAGE_KEYS.length
    && UI_STAGE_KEYS.every((stage) => Object.hasOwn(stages, stage)
      && (stages[stage] === 'PASS' || stages[stage] === 'FAIL'));
  const safeStages = Object.fromEntries(UI_STAGE_KEYS.map((stage) => [
    stage,
    exactStages && stages[stage] === 'PASS' ? 'PASS' : 'FAIL',
  ]));
  const screenshotsOk = Array.isArray(screenshotFiles)
    && screenshotFiles.length === SCREENSHOTS.length
    && new Set(screenshotFiles).size === SCREENSHOTS.length
    && SCREENSHOTS.every((name) => screenshotFiles.includes(name)
      && existsSync(path.join(artifactDir, name)));
  const screenshotManifestOk = Array.isArray(screenshotFiles)
    && screenshotFiles.length === SCREENSHOTS.length
    && new Set(screenshotFiles).size === SCREENSHOTS.length
    && SCREENSHOTS.every((name) => screenshotFiles.includes(name));
  for (const [name, stage] of Object.entries(SCREENSHOT_STAGES)) {
    if (!screenshotManifestOk || !screenshotFiles.includes(name)
      || !existsSync(path.join(artifactDir, name))) safeStages[stage] = 'FAIL';
  }
  const runnerOk = Number.isInteger(runnerExitCode) && runnerExitCode === 0;
  const passed = runnerOk && exactStages && screenshotsOk
    && UI_STAGE_KEYS.every((stage) => safeStages[stage] === 'PASS');
  const result = {
    workflow: 'school-independent-conversation',
    status: passed ? 'PASS' : 'FAIL',
    stages: safeStages,
    screenshots: passed ? SCREENSHOTS : [],
  };
  if (failure && typeof failure === 'object'
    && UI_STAGE_KEYS.includes(failure.stage)) {
    result.failure = {
      stage: failure.stage,
      error_class: SAFE_FAILURE_CLASSES.includes(failure.error_class) ? failure.error_class : 'Error',
    };
  }
  return result;
}

async function readInput() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  const raw = Buffer.concat(chunks);
  try {
    return JSON.parse(raw.toString('utf8'));
  } catch {
    return null;
  } finally {
    raw.fill(0);
    for (const chunk of chunks) chunk.fill(0);
  }
}

async function requireReady(baseUrl) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(`${baseUrl}/health/ready`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error('ServiceNotReady');
    const health = await response.json();
    if (health?.status !== 'READY') throw new Error('ServiceNotReady');
  } finally {
    clearTimeout(timeout);
  }
}

async function apiActor(page) {
  return page.evaluate(async (backendUrl) => {
    const response = await fetch(`${backendUrl}/api/v1/auth/me`, {
      credentials: 'include', headers: { Accept: 'application/json' },
    });
    if (!response.ok) return { status: response.status, actor: null };
    const envelope = await response.json();
    const data = envelope?.data?.actor ?? envelope?.data;
    return { status: response.status, actor: data };
  }, BACKEND_URL);
}

async function enterStudent(page, username, password) {
  await page.goto(`${FRONTEND_URL}/login`, { waitUntil: 'domcontentloaded' });
  const usernameInput = page.getByRole('textbox', { name: 'Username' });
  const passwordInput = page.locator('#password');
  await usernameInput.waitFor({ state: 'visible', timeout: 10000 });
  if ((await usernameInput.inputValue()) !== '' || (await passwordInput.inputValue()) !== '') {
    throw new Error('LoginFormNotBlank');
  }
  await usernameInput.fill(username);
  await passwordInput.fill(password);
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  const picker = page.locator('#school-context');
  if (await picker.isVisible({ timeout: 1500 }).catch(() => false)) {
    const choices = await picker.locator('option:not([disabled])').evaluateAll((options) => options.map((item) => item.value));
    if (choices.length !== 1 || !choices[0]) throw new Error('SchoolContextMismatch');
    await picker.selectOption(choices[0]);
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
  }
  await page.waitForURL((url) => url.pathname === '/student/home', { timeout: 20000 });
  if (await passwordInput.isVisible().catch(() => false) && (await passwordInput.inputValue()) !== '') {
    await passwordInput.fill('');
    throw new Error('LoginPasswordNotCleared');
  }
  const authenticated = await apiActor(page);
  if (authenticated.status !== 200
    || authenticated.actor?.active_context?.role !== 'STUDENT'
    || authenticated.actor?.active_context?.school_ref !== EXPECTED_SCHOOL) {
    throw new Error('AuthenticatedRoleMismatch');
  }
}

async function openSupport(page) {
  await page.getByRole('link', { name: '教育支持', exact: true }).click();
  await page.waitForURL((url) => url.pathname === '/student/support', { timeout: 10000 });
  await page.getByRole('heading', { name: '教育支持', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}

async function waitForWrite(page, predicate, acceptedStatuses) {
  const response = await page.waitForResponse((item) => {
    const url = new URL(item.url());
    return url.origin === BACKEND_URL && predicate(url, item.request().method());
  }, { timeout: 30000 });
  if (!acceptedStatuses.includes(response.status())) throw new Error('ConversationWriteFailed');
  return response;
}

async function createConversation(page) {
  const created = waitForWrite(
    page,
    (url, method) => method === 'POST' && url.pathname === '/api/v1/student/conversations',
    [201],
  );
  await page.locator('.conversation-sidebar').getByRole('button', { name: '新建会话', exact: true }).click();
  const response = await created;
  const conversationId = safeConversationId(await response.json());
  if (!conversationId) throw new Error('ConversationIdentifierUnavailable');
  await page.locator('.conversation-panel').getByRole('heading').waitFor({ state: 'visible', timeout: 20000 });
  await page.locator('#support-message').waitFor({ state: 'visible', timeout: 15000 });
  return conversationId;
}

async function submitSyntheticMessage(page, conversationId) {
  const messagePath = `/api/v1/student/conversations/${conversationId}/messages`;
  let messagePosts = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST') {
      try {
        const url = new URL(request.url());
        if (url.origin === BACKEND_URL && url.pathname === messagePath) messagePosts += 1;
      } catch {
        // Invalid or non-HTTP request details are not retained.
      }
    }
  });
  const submitted = waitForWrite(
    page,
    (url, method) => method === 'POST' && url.pathname === messagePath,
    [200, 202],
  );
  await page.locator('#support-message').fill(QUERY);
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await submitted;
  if (messagePosts !== 1) throw new Error('UnexpectedMessageRequestCount');
}

async function openConversation(page, conversationId) {
  const selector = conversationItemSelector(conversationId);
  if (!selector) throw new Error('ConversationIdentifierUnavailable');
  const item = page.locator(selector);
  await item.waitFor({ state: 'visible', timeout: 15000 });
  if (await item.count() !== 1) throw new Error('ConversationHistoryNotUnique');
  await item.click();
  await page.locator('.conversation-thread').waitFor({ state: 'visible', timeout: 15000 });
  await page.getByText(QUERY, { exact: true }).waitFor({ state: 'visible', timeout: 15000 });
}

async function abstentionIsVisible(page) {
  const assistant = page.locator('.conversation-message--assistant').last();
  if (await assistant.count() === 0) return false;
  const state = (await assistant.locator('.conversation-message__state').textContent().catch(() => ''))?.trim() ?? '';
  if (state !== ABSTENTION_LABEL) return false;
  const body = (await assistant.locator('.conversation-message__text').first().textContent().catch(() => ''))?.trim() ?? '';
  if (body !== ABSTENTION_SUMMARY) return false;
  if (await page.locator('.conversation-message--assistant .conversation-citations').count() !== 0) {
    throw new Error('AbstentionUnexpectedCitation');
  }
  return true;
}

async function waitForPersistedAbstention(page, conversationId) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    if (await abstentionIsVisible(page)) return;
    await page.waitForTimeout(1200);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await openConversation(page, conversationId);
  }
  throw new Error('AbstentionNotPersisted');
}

async function logout(page) {
  if (!page || page.isClosed()) return;
  await page.locator('.account-menu > summary').click({ timeout: 5000 });
  await page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 5000 });
  await page.waitForURL((url) => url.pathname === '/login', { timeout: 12000 });
}

async function bestEffortLogout(page) {
  if (!page || page.isClosed()) return;
  try {
    await page.evaluate(async (backendUrl) => {
      const csrf = await fetch(`${backendUrl}/api/v1/auth/csrf`, { credentials: 'include' });
      if (!csrf.ok) return;
      const envelope = await csrf.json();
      const token = envelope?.data?.csrf_token;
      if (typeof token !== 'string' || !token) return;
      await fetch(`${backendUrl}/api/v1/auth/logout`, {
        method: 'POST', credentials: 'include', headers: { 'X-CSRF-Token': token },
      });
    }, BACKEND_URL);
  } catch {
    // Network details and response bodies are intentionally discarded.
  }
}

async function saveScreenshot(page, artifactDir, name, viewport) {
  await page.setViewportSize(viewport);
  await page.waitForTimeout(250);
  await page.screenshot({
    path: path.join(artifactDir, name),
    fullPage: false,
    animations: 'disabled',
    mask: SCREENSHOT_MASK_SELECTORS.map((selector) => page.locator(selector)),
  });
}

async function runConversation(payload) {
  const stages = failedStages();
  const browserContexts = [];
  let browser;
  let currentStage = 'safety_ready';
  let pageA;
  let pageB;
  let conversationId = '';
  let password = payload.student.password;
  try {
    await requireReady(SAFETY_URL);
    stages.safety_ready = 'PASS';
    currentStage = 'rag_ready';
    await requireReady(RAG_URL);
    stages.rag_ready = 'PASS';

    currentStage = 'browser_start';
    browser = await chromium.launch({ headless: true });
    stages.browser_start = 'PASS';
    const contextA = await browser.newContext({ serviceWorkers: 'block' });
    browserContexts.push(contextA);
    pageA = await contextA.newPage();
    currentStage = 'student_login';
    await enterStudent(pageA, payload.student.username, password);
    stages.student_login = 'PASS';

    currentStage = 'support_open';
    await openSupport(pageA);
    stages.support_open = 'PASS';

    currentStage = 'conversation_created';
    conversationId = await createConversation(pageA);
    stages.conversation_created = 'PASS';

    currentStage = 'message_sent';
    await submitSyntheticMessage(pageA, conversationId);
    stages.message_sent = 'PASS';

    currentStage = 'abstention_body_verified';
    await waitForPersistedAbstention(pageA, conversationId);
    stages.abstention_body_verified = 'PASS';
    stages.citations_absent = 'PASS';
    currentStage = 'reload_history_verified';
    await pageA.reload({ waitUntil: 'domcontentloaded' });
    await openConversation(pageA, conversationId);
    if (!(await abstentionIsVisible(pageA))) throw new Error('ReloadHistoryMissing');
    stages.reload_history_verified = 'PASS';

    currentStage = 'first_logout';
    await logout(pageA);
    stages.first_logout = 'PASS';
    const contextB = await browser.newContext({ serviceWorkers: 'block' });
    browserContexts.push(contextB);
    pageB = await contextB.newPage();
    currentStage = 'fresh_student_login';
    await enterStudent(pageB, payload.student.username, password);
    password = '';
    payload.student.password = '';
    stages.student_login = 'PASS';
    stages.fresh_student_login = 'PASS';
    currentStage = 'fresh_support_open';
    await openSupport(pageB);
    stages.fresh_support_open = 'PASS';
    currentStage = 'fresh_login_history_verified';
    await openConversation(pageB, conversationId);
    if (!(await abstentionIsVisible(pageB))) throw new Error('HistoryAbstentionMissing');
    stages.fresh_login_history_verified = 'PASS';

    currentStage = 'desktop_screenshot';
    await saveScreenshot(pageB, payload.artifact_dir, SCREENSHOTS[0], { width: 1280, height: 800 });
    stages.desktop_screenshot = 'PASS';

    currentStage = 'mobile_screenshot';
    await saveScreenshot(pageB, payload.artifact_dir, SCREENSHOTS[1], { width: 390, height: 844 });
    stages.mobile_screenshot = 'PASS';

    currentStage = 'logout';
    await logout(pageB);
    stages.logout = 'PASS';
  } catch (error) {
    const diagnosticPage = pageB || pageA;
    if (diagnosticPage && new URL(diagnosticPage.url()).pathname === '/student/support') {
      await diagnosticPage.screenshot({
        path: path.join(payload.artifact_dir, 'failure-support.png'),
        fullPage: true,
        animations: 'disabled',
        mask: SCREENSHOT_MASK_SELECTORS.map((selector) => diagnosticPage.locator(selector)),
      }).catch(() => undefined);
    }
    const name = typeof error?.name === 'string' && SAFE_FAILURE_CLASSES.includes(error.name)
      ? error.name
      : 'Error';
    return { stages, failure: { stage: currentStage, error_class: name } };
  } finally {
    password = '';
    conversationId = '';
    if (payload.student) {
      payload.student.username = '';
      payload.student.password = '';
    }
    if (pageA) await bestEffortLogout(pageA);
    if (pageB) await bestEffortLogout(pageB);
    for (const context of browserContexts) await context.close().catch(() => undefined);
    if (browser) await browser.close().catch(() => undefined);
  }
  return { stages, screenshots: SCREENSHOTS };
}

async function main() {
  const payload = await readInput();
  if (!validConversationPayload(payload)) {
    process.stdout.write(`${JSON.stringify({
      workflow: 'school-independent-conversation', status: 'FAIL', stages: failedStages(), screenshots: [],
      failure: { stage: 'student_login', error_class: 'Error' },
    })}\n`);
    process.exitCode = 2;
    return;
  }
  const run = await runConversation(payload);
  const result = summarizeConversationWorkflow(
    run.stages,
    run.screenshots ?? [],
    payload.artifact_dir,
    run.failure ? 2 : 0,
    run.failure ?? null,
  );
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.status === 'PASS' ? 0 : 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => {
    process.stdout.write(`${JSON.stringify({
      workflow: 'school-independent-conversation', status: 'FAIL', stages: failedStages(), screenshots: [],
      failure: { stage: 'safety_ready', error_class: 'Error' },
    })}\n`);
    process.exitCode = 2;
  });
}
