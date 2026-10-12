import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { randomBytes } from 'node:crypto';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');
const FRONTEND_URL = 'http://127.0.0.1:4178';
const BACKEND_URL = 'http://127.0.0.1:8088';
const WORKSPACE = 'D:\\Projects\\.StudentMentalHealthAI-school-workspace-20261011';
const SCHOOL_REF = 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1';
const STAGE_KEYS = [
  'admin_login',
  'directory_open',
  'school_name_configure',
  'school_name_restore',
  'csv_select',
  'csv_preview',
  'csv_import',
  'directory_screenshot',
  'student_cancel_clears_password',
  'student_activate',
  'teacher_activate',
  'student_login',
  'student_role_ui',
  'teacher_login',
  'teacher_role_ui',
  'session_cleanup',
  'screenshots',
];
const SCREENSHOTS = [
  'school-directory-import.png',
  'new-student-home.png',
  'new-teacher-overview.png',
];
const ACCOUNT_ROLES = {
  student: { apiRole: 'STUDENT', path: '/student/home', landmark: '#student-home-title' },
  teacher: { apiRole: 'TEACHER', path: '/teacher/overview', landmark: 'heading:班级任务进度' },
};

const failedStages = () => Object.fromEntries(STAGE_KEYS.map((stage) => [stage, 'FAIL']));

function validPayload(payload) {
  return Boolean(payload && typeof payload === 'object'
    && payload.frontend_url === FRONTEND_URL
    && payload.backend_url === BACKEND_URL
    && typeof payload.artifact_dir === 'string'
    && path.resolve(payload.artifact_dir).startsWith(`${path.resolve(WORKSPACE)}${path.sep}`)
    && payload.admin
    && typeof payload.admin.username === 'string'
    && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(payload.admin.username)
    && typeof payload.admin.password === 'string'
    && payload.admin.password.length >= 16);
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

async function enterWithCredentials(page, username, password, role, expectedSchool) {
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

  await page.waitForURL((url) => url.pathname === role.path, { timeout: 20000 });
  if (await passwordInput.isVisible().catch(() => false) && (await passwordInput.inputValue()) !== '') {
    await passwordInput.fill('');
    throw new Error('LoginPasswordNotCleared');
  }
  const authenticated = await apiActor(page);
  if (authenticated.status !== 200
    || authenticated.actor?.active_context?.role !== role.apiRole
    || authenticated.actor?.active_context?.school_ref !== expectedSchool) {
    throw new Error('AuthenticatedRoleMismatch');
  }
}

async function uiLogout(page) {
  if (!page || page.isClosed()) return;
  await page.locator('.account-menu > summary').click({ timeout: 3000 });
  await page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 3000 });
  await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
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
    // Do not return network details or response bodies.
  }
}

function masksFor(page) {
  return [
    page.locator('input, textarea, select'),
    page.locator('.account-menu'),
    page.locator('.directory-name-row'),
    page.locator('.directory-account-row'),
    page.locator('#school-account-new-password'),
    page.locator('#student-home-title'),
    page.locator('.task-progress-row'),
  ];
}

async function saveScreenshot(page, artifactDir, fileName, sensitiveTexts = []) {
  const textMasks = sensitiveTexts.map((text) => page.getByText(text, { exact: true }))
  await page.screenshot({
    path: path.join(artifactDir, fileName),
    fullPage: true,
    animations: 'disabled',
    mask: [...masksFor(page), ...textMasks],
  });
}

function createPassword() {
  return `Synthetic-${randomBytes(24).toString('base64url')}-7!`;
}

async function waitForWrite(page, suffix, statusCodes) {
  const response = await page.waitForResponse((item) => {
    const url = new URL(item.url());
    return item.request().method() === 'POST'
      && url.origin === BACKEND_URL
      && url.pathname.endsWith(suffix);
  }, { timeout: 20000 });
  if (!statusCodes.includes(response.status())) throw new Error('DirectoryWriteFailed');
  return response;
}

async function runDirectory(payload) {
  const stages = failedStages();
  const screenshots = [];
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false });
  let adminPage;
  let schoolNameBefore = '';
  let schoolNameChanged = false;
  let workflowError = false;
  let studentPassword = '';
  let teacherPassword = '';
  try {
    adminPage = await context.newPage();
    const admin = payload.admin;
    try {
      await enterWithCredentials(adminPage, admin.username, admin.password,
        { apiRole: 'ADMIN', path: '/admin/overview' }, SCHOOL_REF);
      stages.admin_login = 'PASS';
    } finally {
      admin.password = '';
      admin.username = '';
      delete payload.admin;
    }

    await adminPage.getByRole('link', { name: '用户与角色', exact: true }).click();
    await adminPage.waitForURL((url) => url.pathname === '/admin/users', { timeout: 10000 });
    await adminPage.locator('#school-display-name').waitFor({ state: 'visible', timeout: 15000 });
    stages.directory_open = 'PASS';

    const nameInput = adminPage.locator('#school-display-name');
    schoolNameBefore = await nameInput.inputValue();
    if (schoolNameBefore.length > 120) throw new Error('SchoolNameUnavailable');
    const configuredName = schoolNameBefore
      ? `${schoolNameBefore.slice(0, 90)} QA ${randomBytes(5).toString('hex')}`
      : '合成示范学校 A';
    const schoolNameResponse = waitForWrite(adminPage, '/api/v1/school/admin/school/name', [200]);
    await nameInput.fill(configuredName);
    await adminPage.locator('#school-display-name').locator('xpath=following-sibling::button').click();
    await schoolNameResponse;
    if (schoolNameBefore) schoolNameChanged = true;
    await adminPage.getByText('名称已保存。', { exact: true }).waitFor({ state: 'visible' });
    if ((await adminPage.locator('#school-display-name').inputValue()) !== configuredName) throw new Error('SchoolRenameNotVisible');
    stages.school_name_configure = 'PASS';
    if (schoolNameBefore) {
      await restoreSchoolName(adminPage, schoolNameBefore);
      schoolNameChanged = false;
      stages.school_name_restore = 'PASS';
    } else {
      stages.school_name_restore = 'SKIPPED_NULL_ORIGINAL';
    }

    const runId = randomBytes(8).toString('hex');
    const studentLogin = `SYNTHETIC_DIRQA_S_${runId}`;
    const teacherLogin = `SYNTHETIC_DIRQA_T_${runId}`;
    const studentName = `目录验证学生 ${runId.slice(-6)}`;
    const teacherName = `目录验证教师 ${runId.slice(-6)}`;
    let csv = [
      'login_name,display_name,role',
      `${studentLogin},${studentName},student`,
      `${teacherLogin},${teacherName},teacher`,
    ].join('\r\n');
    const csvBuffer = Buffer.from(csv, 'utf8');
    csv = '';
    try {
      await adminPage.locator('#school-account-csv').setInputFiles({
        name: 'synthetic-school-directory.csv',
        mimeType: 'text/csv',
        buffer: csvBuffer,
      });
    } finally {
      csvBuffer.fill(0);
    }
    await adminPage.getByText('CSV 格式有效，共 2 行；预览后才能导入。', { exact: true }).waitFor({ state: 'visible' });
    stages.csv_select = 'PASS';

    const previewResponse = waitForWrite(adminPage, '/api/v1/school/admin/accounts/preview', [200]);
    await adminPage.getByRole('button', { name: '服务端预览', exact: true }).click();
    await previewResponse;
    await adminPage.getByText('服务端验证通过，共 2 行。', { exact: true }).waitFor({ state: 'visible' });
    stages.csv_preview = 'PASS';

    const importResponse = waitForWrite(adminPage, '/api/v1/school/admin/accounts/import', [200, 201]);
    await adminPage.getByRole('button', { name: '整批导入', exact: true }).click();
    await importResponse;
    await adminPage.getByText('服务端已一次性创建 2 个待激活账号。', { exact: true }).waitFor({ state: 'visible' });
    await adminPage.getByText(studentName, { exact: true }).waitFor({ state: 'visible' });
    await adminPage.getByText(teacherName, { exact: true }).waitFor({ state: 'visible' });
    stages.csv_import = 'PASS';

    const afterImportPath = path.join(payload.artifact_dir, SCREENSHOTS[0]);
    await saveScreenshot(adminPage, payload.artifact_dir, SCREENSHOTS[0]);
    screenshots.push(path.basename(afterImportPath));
    stages.directory_screenshot = 'PASS';

    const studentRow = adminPage.locator('.directory-account-row').filter({ hasText: studentName });
    await studentRow.getByRole('button', { name: '设置登录密码', exact: true }).click();
    let cancelPassword = createPassword();
    await adminPage.locator('#school-account-new-password').fill(cancelPassword);
    await adminPage.locator('.directory-activation').getByRole('button', { name: '取消', exact: true }).click();
    if (await adminPage.locator('#school-account-new-password').count() !== 0) throw new Error('CancelDidNotClearPassword');
    cancelPassword = '';
    stages.student_cancel_clears_password = 'PASS';

    studentPassword = createPassword();
    await studentRow.getByRole('button', { name: '设置登录密码', exact: true }).click();
    await adminPage.locator('#school-account-new-password').fill(studentPassword);
    const studentActivation = waitForWrite(adminPage, '/activate', [200]);
    await adminPage.locator('.directory-activation').getByRole('button', { name: '激活账号', exact: true }).click();
    const studentActivationResponse = await studentActivation;
    if (!new URL(studentActivationResponse.url()).pathname.match(/\/accounts\/[^/]+\/activate$/)) throw new Error('ActivationRouteMismatch');
    await adminPage.getByText(studentName, { exact: true }).waitFor({ state: 'hidden', timeout: 10000 });
    if (await adminPage.locator('#school-account-new-password').count()) {
      if ((await adminPage.locator('#school-account-new-password').inputValue()) !== '') throw new Error('ActivationPasswordNotCleared');
    }
    stages.student_activate = 'PASS';

    const teacherRow = adminPage.locator('.directory-account-row').filter({ hasText: teacherName });
    await teacherRow.getByRole('button', { name: '设置登录密码', exact: true }).click();
    teacherPassword = createPassword();
    await adminPage.locator('#school-account-new-password').fill(teacherPassword);
    const teacherActivation = waitForWrite(adminPage, '/activate', [200]);
    await adminPage.locator('.directory-activation').getByRole('button', { name: '激活账号', exact: true }).click();
    const teacherActivationResponse = await teacherActivation;
    if (!new URL(teacherActivationResponse.url()).pathname.match(/\/accounts\/[^/]+\/activate$/)) throw new Error('ActivationRouteMismatch');
    await adminPage.getByText(teacherName, { exact: true }).waitFor({ state: 'hidden', timeout: 10000 });
    if (await adminPage.locator('#school-account-new-password').count()) {
      if ((await adminPage.locator('#school-account-new-password').inputValue()) !== '') throw new Error('ActivationPasswordNotCleared');
    }
    stages.teacher_activate = 'PASS';

    if (schoolNameChanged) {
      await restoreSchoolName(adminPage, schoolNameBefore);
      schoolNameChanged = false;
      stages.school_name_restore = 'PASS';
    }

    await uiLogout(adminPage);
    const studentContext = await browser.newContext({ serviceWorkers: 'block' });
    const studentPage = await studentContext.newPage();
    try {
      await enterWithCredentials(studentPage, studentLogin, studentPassword, ACCOUNT_ROLES.student, SCHOOL_REF);
      stages.student_login = 'PASS';
      await studentPage.locator(ACCOUNT_ROLES.student.landmark).waitFor({ state: 'visible', timeout: 15000 });
      await saveScreenshot(studentPage, payload.artifact_dir, SCREENSHOTS[1], [studentLogin, studentName]);
      screenshots.push(SCREENSHOTS[1]);
      stages.student_role_ui = 'PASS';
      await uiLogout(studentPage);
    } finally {
      await bestEffortLogout(studentPage);
      await studentContext.close();
      studentPassword = '';
    }

    const teacherContext = await browser.newContext({ serviceWorkers: 'block' });
    const teacherPage = await teacherContext.newPage();
    try {
      await enterWithCredentials(teacherPage, teacherLogin, teacherPassword, ACCOUNT_ROLES.teacher, SCHOOL_REF);
      stages.teacher_login = 'PASS';
      await teacherPage.getByRole('heading', { name: '班级任务进度', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
      await saveScreenshot(teacherPage, payload.artifact_dir, SCREENSHOTS[2], [teacherLogin, teacherName]);
      screenshots.push(SCREENSHOTS[2]);
      stages.teacher_role_ui = 'PASS';
      await uiLogout(teacherPage);
    } finally {
      await bestEffortLogout(teacherPage);
      await teacherContext.close();
      teacherPassword = '';
    }
    stages.session_cleanup = 'PASS';
  } catch {
    workflowError = true;
  } finally {
    if (schoolNameChanged && adminPage && !adminPage.isClosed()) {
      try {
        await restoreSchoolName(adminPage, schoolNameBefore);
        stages.school_name_restore = 'PASS';
      } catch {
        // The safe stage result remains FAIL; do not return the display name.
      }
    }
    if (adminPage) {
      try { await uiLogout(adminPage); } catch { await bestEffortLogout(adminPage); }
    }
    await context.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
    studentPassword = '';
    teacherPassword = '';
  }

  if (screenshots.length === SCREENSHOTS.length) stages.screenshots = 'PASS';
  const failed = STAGE_KEYS.some((stage) => stages[stage] === 'FAIL');
  const preservedConfiguredName = stages.school_name_configure === 'PASS'
    && stages.school_name_restore === 'SKIPPED_NULL_ORIGINAL';
  const passed = !workflowError && !failed && !preservedConfiguredName;
  return {
    workflow: 'school-directory',
    status: passed ? 'PASS' : !workflowError && !failed && preservedConfiguredName ? 'PARTIAL' : 'FAIL',
    stages,
    screenshots: screenshots.length === SCREENSHOTS.length ? SCREENSHOTS : [],
  };
}

async function restoreSchoolName(page, originalName) {
  const input = page.locator('#school-display-name');
  await input.waitFor({ state: 'visible', timeout: 10000 });
  const response = waitForWrite(page, '/api/v1/school/admin/school/name', [200]);
  await input.fill(originalName);
  await input.locator('xpath=following-sibling::button').click();
  await response;
  await page.getByText('名称已保存。', { exact: true }).waitFor({ state: 'visible' });
  if ((await input.inputValue()) !== originalName) throw new Error('SchoolNameRestoreNotVisible');
}

async function main() {
  const payload = await readInput();
  if (!validPayload(payload)) {
    process.stdout.write(`${JSON.stringify({ workflow: 'school-directory', status: 'FAIL', stages: failedStages(), screenshots: [] })}\n`);
    process.exitCode = 2;
    return;
  }
  const result = await runDirectory(payload);
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = 0;
}

main().catch(() => {
  process.stdout.write(`${JSON.stringify({ workflow: 'school-directory', status: 'FAIL', stages: failedStages(), screenshots: [] })}\n`);
  process.exitCode = 2;
});
