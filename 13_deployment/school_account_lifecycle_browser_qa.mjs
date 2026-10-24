import { randomBytes, webcrypto } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];
const STAGE_KEYS = [
  'admin_login', 'admin_route', 'roster_file', 'roster_preview', 'roster_import',
  'roster_persisted', 'credential_selection', 'credential_issue', 'encrypted_download',
  'first_login', 'credential_replay_rejected', 'student_login', 'role_denied',
  'viewport_1440', 'viewport_1024', 'viewport_768', 'viewport_390', 'logout',
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
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  if (!path.isAbsolute(value.artifact_dir) || !Array.isArray(value.class_refs)
    || value.class_refs.length !== 8 || new Set(value.class_refs).size !== 8) return false;
  const admin = value.admin;
  return typeof value.frontend_url === 'string' && value.frontend_url === 'http://127.0.0.1:4178'
    && typeof value.backend_url === 'string' && value.backend_url === 'http://127.0.0.1:8088'
    && typeof value.school_ref === 'string' && value.school_ref === 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1'
    && admin && typeof admin.username === 'string' && admin.username.startsWith('SYNTHETIC_')
    && typeof admin.password === 'string' && admin.password.length >= 16
    && value.class_refs.every((item) => typeof item === 'string' && /^LCQA-2026-C\d{2}$/.test(item));
}

function fail(output, stage, code, httpStatus) {
  output.status = 'FAIL';
  output.failure = { stage, code, ...(Number.isInteger(httpStatus) ? { http_status: httpStatus } : {}) };
  throw new Error('QA_STOP');
}

async function safeResponseJson(response) {
  try { return await response.json(); } catch { return null; }
}

async function captureViewport(page, output, payload, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  await page.waitForTimeout(150);
  const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const key = String(viewport.width);
  output.viewport_widths[key] = documentWidth;
  const stage = `viewport_${key}`;
  output.stages[stage] = documentWidth <= viewport.width ? 'PASS' : 'FAIL';
  const filename = `account-lifecycle-${key}.png`;
  const screenshotPath = path.join(payload.artifact_dir, filename);
  const accountMenu = page.locator('.account-menu');
  await page.screenshot({
    path: screenshotPath,
    fullPage: true,
    animations: 'disabled',
    mask: (await accountMenu.count()) ? [accountMenu] : [],
  });
  output.screenshots[key] = screenshotPath;
  if (documentWidth > viewport.width) fail(output, stage, 'HORIZONTAL_OVERFLOW');
}

async function decryptCredentialExport(download, passphrase) {
  const filePath = await download.path();
  if (!filePath) throw new Error('DOWNLOAD_PATH_UNAVAILABLE');
  const bytes = await fs.readFile(filePath);
  const encrypted = JSON.parse(bytes.toString('utf8'));
  if (encrypted.format !== 'psynova-credentials-encrypted-v1'
    || encrypted.algorithm !== 'AES-256-GCM'
    || encrypted.kdf !== 'PBKDF2-SHA-256'
    || encrypted.iterations !== 310000) throw new Error('ENCRYPTED_FORMAT_INVALID');
  const material = await webcrypto.subtle.importKey(
    'raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveKey'],
  );
  const key = await webcrypto.subtle.deriveKey({
    name: 'PBKDF2',
    salt: new Uint8Array(Buffer.from(encrypted.salt, 'base64')),
    iterations: encrypted.iterations,
    hash: 'SHA-256',
  }, material, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  const cleartext = await webcrypto.subtle.decrypt({
    name: 'AES-GCM',
    iv: new Uint8Array(Buffer.from(encrypted.iv, 'base64')),
  }, key, new Uint8Array(Buffer.from(encrypted.ciphertext, 'base64')));
  return { credentials: JSON.parse(new TextDecoder().decode(cleartext)).credentials, bytes: bytes.length };
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
    stages: Object.fromEntries(STAGE_KEYS.map((key) => [key, 'FAIL'])),
    counts: { classes: payload.class_refs.length },
    viewport_widths: {},
    screenshots: {},
  };
  let browser;
  let page;
  let checkpoint = 'browser_launch';
  let adminPassword = payload.admin.password;
  let studentPassword = '';
  let firstCredential = null;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: true });
    page = await context.newPage({ viewport: { width: 1440, height: 900 } });
    checkpoint = 'login_page';
    await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    checkpoint = 'login_form';
    await page.locator('#account').waitFor({ state: 'visible', timeout: 20000 });
    await page.locator('#account').fill(payload.admin.username);
    await page.locator('#password').fill(adminPassword);
    checkpoint = 'login_submit';
    await page.getByRole('button', { name: '登录', exact: true }).click();
    checkpoint = 'context_choice';
    const contextPicker = page.locator('#school-context');
    if (await contextPicker.isVisible({ timeout: 2500 }).catch(() => false)) {
      const matchingOption = await contextPicker.locator('option:not([disabled])').evaluateAll(
        (options, targetSchoolRef) => {
          const matches = options.filter((option) => option.textContent?.includes(targetSchoolRef)
            && option.textContent?.includes('学校管理员'));
          return matches.length === 1 ? matches[0].value : null;
        },
        payload.school_ref,
      );
      if (!matchingOption) fail(output, 'admin_login', 'ADMIN_CONTEXT_AMBIGUOUS');
      await contextPicker.selectOption(matchingOption);
      await page.getByRole('button', { name: '继续', exact: true }).click();
    }
    checkpoint = 'admin_route';
    await page.waitForURL((url) => url.pathname === '/admin/overview', { timeout: 20000 });
    output.stages.admin_login = 'PASS';

    await page.getByRole('link', { name: '账号管理', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/admin/users', { timeout: 15000 });
    await page.locator('#lifecycle-title').waitFor({ state: 'visible', timeout: 15000 });
    if (!(await page.getByRole('tab', { name: '学生花名册', exact: true }).count())) {
      fail(output, 'admin_route', 'LIFECYCLE_WORKSPACE_NOT_RENDERED');
    }
    output.stages.admin_route = 'PASS';

    await page.getByRole('tab', { name: '学生花名册', exact: true }).click();
    const csvLines = [
      '# psynova_student_roster_template_v1',
      'student_number,display_name,class_ref,grade_level',
    ];
    let rowNo = 0;
    const expectedPerClass = new Map(payload.class_refs.map((classRef) => [classRef, 0]));
    for (let classIndex = 0; classIndex < payload.class_refs.length; classIndex += 1) {
      const classRef = payload.class_refs[classIndex];
      for (let studentIndex = 1; studentIndex <= 25; studentIndex += 1) {
        rowNo += 1;
        const suffix = String(studentIndex).padStart(3, '0');
        const studentNumber = `LCQA26-C${String(classIndex + 1).padStart(2, '0')}-${suffix}`;
        const displayName = `LifecycleQA-LCQA26-C${String(classIndex + 1).padStart(2, '0')}-${suffix}`;
        csvLines.push(`${studentNumber},${displayName},${classRef},`);
        expectedPerClass.set(classRef, (expectedPerClass.get(classRef) ?? 0) + 1);
      }
    }
    const rosterCsv = `${csvLines.join('\r\n')}\r\n`;
    await page.locator('input[type="file"]').setInputFiles({
      name: 'psynova-student-roster-v1.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(`\uFEFF${rosterCsv}`, 'utf8'),
    });
    await page.getByText('200 条记录，8 个班级', { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
    output.stages.roster_file = rowNo === 200 ? 'PASS' : 'FAIL';
    if (rowNo !== 200) fail(output, 'roster_file', 'ROW_COUNT_MISMATCH');

    const previewResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/school/admin/roster/preview',
    { timeout: 30000 });
    await page.getByRole('button', { name: '服务端预览', exact: true }).click();
    const preview = await previewResponse;
    if (preview.status() !== 200) fail(output, 'roster_preview', 'PREVIEW_HTTP_STATUS', preview.status());
    const previewBody = await safeResponseJson(preview);
    const previewData = previewBody?.data;
    const previewGroups = previewData?.class_groups;
    if (!previewData?.valid || previewData.row_count !== 200
      || previewData.errors?.length !== 0 || !Array.isArray(previewGroups)
      || previewGroups.length !== 8
      || previewGroups.some((item) => item.row_count !== 25)) {
      fail(output, 'roster_preview', 'PREVIEW_RESULT_MISMATCH');
    }
    await page.getByText('服务端预览：200 条', { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
    output.stages.roster_preview = 'PASS';
    output.counts.students = previewData.row_count;
    output.counts.per_class = previewGroups.every((item) => expectedPerClass.get(item.class_ref) === item.row_count)
      ? 25 : 0;
    if (output.counts.per_class !== 25) fail(output, 'roster_preview', 'CLASS_GROUP_MISMATCH');

    const importResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/school/admin/roster/import',
    { timeout: 60000 });
    await page.getByRole('button', { name: '确认导入', exact: true }).click();
    const imported = await importResponse;
    if (imported.status() !== 201) fail(output, 'roster_import', 'IMPORT_HTTP_STATUS', imported.status());
    const importedBody = await safeResponseJson(imported);
    const importData = importedBody?.data;
    if (importData?.row_count !== 200 || importData.created_count !== 200
      || importData.accounts?.length !== 200 || importData.class_groups?.length !== 8
      || importData.class_groups.some((item) => item.row_count !== 25)) {
      fail(output, 'roster_import', 'IMPORT_RESULT_MISMATCH');
    }
    output.run_ref = importData.run_ref;
    output.stages.roster_import = 'PASS';
    await page.getByText(/新增 200 个账号/).waitFor({ state: 'visible', timeout: 20000 });
    output.stages.roster_persisted = 'PASS';

    await page.getByRole('tab', { name: '账号状态', exact: true }).click();
    await page.locator('.lifecycle input[type="search"]').fill('LCQA26');
    await page.locator('.lifecycle__table-wrap tbody tr').first().waitFor({ state: 'visible', timeout: 15000 });
    const statusRows = page.locator('.lifecycle__table-wrap tbody tr');
    if (await statusRows.count() !== 25 || !(await page.getByText('200 个账号', { exact: false }).count())) {
      fail(output, 'credential_selection', 'ACCOUNT_SEARCH_OR_PAGINATION_MISMATCH');
    }
    output.stages.credential_selection = 'PASS';

    for (const classRef of payload.class_refs) {
      await page.getByRole('tab', { name: '一次性凭据', exact: true }).click();
      await page.locator('.lifecycle__credential-tools select').selectOption(classRef);
      await page.getByRole('button', { name: '选择当前页', exact: true }).click();
    }
    const selectedText = await page.locator('.lifecycle__selection-tools').first().innerText();
    if (!selectedText.includes('已选择 200 人')) fail(output, 'credential_selection', 'BULK_SELECTION_MISMATCH');

    const issueResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/school/admin/accounts/credentials/issue',
    { timeout: 60000 });
    await page.locator('input[autocomplete="current-password"]').fill(adminPassword);
    await page.getByRole('button', { name: '发行凭据', exact: true }).click();
    const issueResponse = await issueResponsePromise;
    if (issueResponse.status() !== 201) fail(output, 'credential_issue', 'ISSUE_HTTP_STATUS', issueResponse.status());
    const issueBody = await safeResponseJson(issueResponse);
    const credentials = issueBody?.data?.credentials;
    if (!Array.isArray(credentials) || credentials.length !== 200
      || new Set(credentials.map((item) => item.user_id)).size !== 200
      || issueResponse.headers()['cache-control']?.toLowerCase() !== 'no-store') {
      fail(output, 'credential_issue', 'ISSUE_RESULT_MISMATCH');
    }
    firstCredential = credentials[0];
    output.counts.credentials_issued = credentials.length;
    output.stages.credential_issue = 'PASS';
    const passphrase = `${randomBytes(32).toString('base64url')}Aa1!`;
    await page.locator('input[autocomplete="new-password"]').fill(passphrase);
    const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
    await page.getByRole('button', { name: '加密下载', exact: true }).click();
    const download = await downloadPromise;
    const exported = await decryptCredentialExport(download, passphrase);
    if (exported.credentials.length !== 200
      || exported.credentials[0]?.credential !== firstCredential.credential) {
      fail(output, 'encrypted_download', 'CREDENTIAL_EXPORT_MISMATCH');
    }
    output.counts.credential_file_bytes = exported.bytes;
    output.stages.encrypted_download = 'PASS';
    if ((await page.locator('body').innerText()).includes(firstCredential.credential)) {
      fail(output, 'encrypted_download', 'CREDENTIAL_RENDERED_IN_UI');
    }

    studentPassword = `${randomBytes(24).toString('base64url')}Aa1!`;
    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    await page.getByRole('button', { name: '首次登录', exact: true }).click();
    await page.getByLabel('学校编号').fill(payload.school_ref);
    await page.getByLabel('账号', { exact: true }).fill(firstCredential.login_name);
    await page.getByLabel('一次性凭据').fill(firstCredential.credential);
    await page.getByLabel('新密码').fill(studentPassword);
    await page.getByLabel('确认新密码').fill(studentPassword);
    await page.getByRole('button', { name: '提交', exact: true }).click();
    await page.getByText('密码已更新，请返回登录。', { exact: true }).waitFor({ state: 'visible', timeout: 20000 });
    output.stages.first_login = 'PASS';

    await page.getByRole('button', { name: '返回登录', exact: true }).click();
    await page.locator('#account').fill(firstCredential.login_name);
    await page.locator('#password').fill(studentPassword);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/student/home', { timeout: 20000 });
    const actorResult = await page.evaluate(async (backendUrl) => {
      const response = await fetch(`${backendUrl}/api/v1/auth/me`, { credentials: 'include' });
      let body = null;
      try { body = await response.json(); } catch { /* fixed result below */ }
      return { status: response.status, actor: body?.data };
    }, payload.backend_url);
    if (actorResult.status !== 200 || actorResult.actor?.role !== 'STUDENT'
      || actorResult.actor?.active_context?.school_ref !== payload.school_ref) {
      fail(output, 'student_login', 'IMPORTED_STUDENT_SESSION_MISMATCH');
    }
    output.stages.student_login = 'PASS';

    const deniedStatus = await page.evaluate(async (backendUrl) => {
      const response = await fetch(`${backendUrl}/api/v1/school/admin/accounts/summary`, {
        credentials: 'include', headers: { Accept: 'application/json' },
      });
      return response.status;
    }, payload.backend_url);
    if (deniedStatus !== 403) fail(output, 'role_denied', 'STUDENT_ADMIN_API_NOT_FORBIDDEN', deniedStatus);
    await page.goto(`${payload.frontend_url}/admin/overview`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL((url) => url.pathname === '/student/home', { timeout: 10000 });
    output.stages.role_denied = 'PASS';

    const replayResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/first-login',
    { timeout: 30000 });
    await page.locator('.account-menu > summary').click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
    await page.getByRole('button', { name: '首次登录', exact: true }).click();
    await page.getByLabel('学校编号').fill(payload.school_ref);
    await page.getByLabel('账号', { exact: true }).fill(firstCredential.login_name);
    await page.getByLabel('一次性凭据').fill(firstCredential.credential);
    const replayPassword = `${randomBytes(24).toString('base64url')}Bb2!`;
    await page.getByLabel('新密码').fill(replayPassword);
    await page.getByLabel('确认新密码').fill(replayPassword);
    await page.getByRole('button', { name: '提交', exact: true }).click();
    const replayResponse = await replayResponsePromise;
    if (![401, 409].includes(replayResponse.status())) {
      fail(output, 'credential_replay_rejected', 'USED_CREDENTIAL_REPLAY_ACCEPTED', replayResponse.status());
    }
    output.stages.credential_replay_rejected = 'PASS';
    await page.getByRole('alert').waitFor({ state: 'visible', timeout: 10000 });

    output.stages.logout = 'PASS';
    output.status = STAGE_KEYS.every((key) => output.stages[key] === 'PASS') ? 'PASS' : 'FAIL';
  } catch (error) {
    if (!output.failure) {
      const message = error instanceof Error ? error.message : '';
      const stage = STAGE_KEYS.find((key) => output.stages[key] !== 'PASS') ?? 'browser_runner';
      const code = message === 'QA_STOP'
        ? (output.failure?.code ?? 'CONTROLLED_ASSERTION')
        : error instanceof Error && error.name === 'TimeoutError' ? 'ACTION_TIMEOUT' : 'BROWSER_ACTION_FAILED';
      output.failure = { ...(output.failure ?? {}), stage, code, checkpoint };
    }
  } finally {
    if (page) {
      try {
        const loginButton = page.getByRole('button', { name: '登录', exact: true });
        if (await loginButton.count()) {
          // Current page is already signed out or on the public auth screen.
        } else if (await page.locator('.account-menu > summary').count()) {
          await page.locator('.account-menu > summary').click();
          const logoutButton = page.getByRole('button', { name: '退出登录', exact: true });
          if (await logoutButton.count()) await logoutButton.click();
        }
      } catch { /* best-effort session cleanup */ }
    }
    adminPassword = '';
    studentPassword = '';
    firstCredential = null;
    if (browser) await browser.close().catch(() => undefined);
  }
  process.stdout.write(`${JSON.stringify(output)}\n`);
  process.exitCode = output.status === 'PASS' ? 0 : 2;
}

main().catch(() => {
  process.stdout.write(`${JSON.stringify({ status: 'FAIL', failure: { stage: 'browser_runner', code: 'UNHANDLED_FAILURE' } })}\n`);
  process.exitCode = 2;
});
