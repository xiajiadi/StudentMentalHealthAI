import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');

export const WORKSPACE = 'D:\\Projects\\.StudentMentalHealthAI-school-workspace-20261011';
export const FRONTEND_URL = 'http://127.0.0.1:4178';
export const BACKEND_URL = 'http://127.0.0.1:8088';
export const SCHOOL_REF = 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1';
export const SCREENSHOTS = [
  'specialist-cat-management-desktop.png',
  'specialist-cat-management-mobile.png',
];
export const SCREENSHOT_STAGES = {
  'specialist-cat-management-desktop.png': 'desktop_screenshot',
  'specialist-cat-management-mobile.png': 'mobile_screenshot',
};
export const UI_STAGE_KEYS = [
  'specialist_login',
  'catalog_read_verified',
  'simulation100_verified',
  'ui_aggregates_matched_api',
  'repeat_simulation_verified',
  'desktop_screenshot',
  'mobile_screenshot',
  'session_cleanup',
];
export const SCREENSHOT_MASK_SELECTORS = [
  '.account-menu',
  'input, textarea, select',
  '.cat-config-block__heading span:last-child',
  '.cat-results__heading > div > p:last-child',
];
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError',
  'ProtocolError', 'TargetClosedError', 'CatManagementResponseError',
];

const WORKFLOW = 'school-cat-management';
const SPECIALIST_SLOT = 'alpha.psychological_specialist';
const METRIC_KEYS = ['bias', 'rmse', 'mae', 'mean_test_length', 'median_test_length', 'mean_se'];
const STOP_LABELS = {
  SE_THRESHOLD_REACHED: '达到标准误停止条件',
  MAX_ITEMS_REACHED: '达到题数上限',
  ITEM_BANK_EXHAUSTED: '可用题目已用完',
  MANUAL_TERMINATION: '手动停止',
  ERROR: '运行错误',
  NOT_STOPPED: '未触发停止条件',
};
const METRIC_LABELS = {
  bias: '偏差 Bias',
  rmse: '均方根误差 RMSE',
  mae: '平均绝对误差 MAE',
  mean_test_length: '平均题数',
  median_test_length: '中位题数',
  mean_se: '平均标准误',
};
const failedStages = () => Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));
const hasExactKeys = (value, keys) => isRecord(value)
  && Object.keys(value).sort().join('|') === [...keys].sort().join('|');

function isWithinArtifactRun(candidate) {
  const base = path.resolve(WORKSPACE);
  const target = path.resolve(candidate);
  const relative = path.relative(base, target);
  const parts = relative.split(path.sep);
  return parts.length === 2
    && parts[0] === 'browser-qa'
    && /^\d{8}T\d{6}Z-[a-f0-9]{32}$/.test(parts[1])
    && !path.isAbsolute(relative);
}

export function validCatManagementPayload(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  if (Object.keys(payload).sort().join('|') !== 'artifact_dir|backend_url|credentials|frontend_url') return false;
  if (payload.frontend_url !== FRONTEND_URL || payload.backend_url !== BACKEND_URL
    || typeof payload.artifact_dir !== 'string' || !isWithinArtifactRun(payload.artifact_dir)) return false;
  const credentials = payload.credentials;
  if (!credentials || typeof credentials !== 'object' || Array.isArray(credentials)
    || Object.keys(credentials).join('|') !== SPECIALIST_SLOT) return false;
  const account = credentials[SPECIALIST_SLOT];
  return Boolean(account && typeof account === 'object' && !Array.isArray(account)
    && Object.keys(account).sort().join('|') === 'password|username'
    && typeof account.username === 'string' && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(account.username)
    && typeof account.password === 'string' && account.password.length >= 16 && account.password.length <= 512);
}

const isRecord = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const isText = (value) => typeof value === 'string' && value.trim().length > 0;
const isInteger = (value, minimum = 0) => Number.isSafeInteger(value) && value >= minimum;

export function validCatCatalog(value) {
  if (!hasExactKeys(value, ['schema_version', 'engineering_only', 'psychological_interpretation_allowed', 'item_bank', 'config', 'simulation'])
    || value.schema_version !== 'synthetic_cat_management.v1'
    || value.engineering_only !== true || value.psychological_interpretation_allowed !== false
    || !hasExactKeys(value.item_bank, ['item_bank_id', 'version', 'instrument_id', 'item_count', 'dimension_count', 'status', 'validation'])
    || !hasExactKeys(value.config, ['config_version', 'model', 'estimator', 'selection_method', 'min_items', 'max_items', 'se_threshold', 'seed'])
    || !hasExactKeys(value.simulation, ['available', 'sample_sizes', 'fixed_seed'])) return false;
  const bank = value.item_bank;
  const config = value.config;
  const simulation = value.simulation;
  return isText(bank.item_bank_id) && isText(bank.version) && isText(bank.instrument_id)
    && isInteger(bank.item_count, 1) && isInteger(bank.dimension_count, 1)
    && ['draft', 'calibrating', 'validated', 'published', 'deprecated'].includes(bank.status)
    && bank.validation === 'STRUCTURE_VALID'
    && isText(config.config_version) && isText(config.model) && isText(config.estimator)
    && isText(config.selection_method) && isInteger(config.min_items, 1)
    && isInteger(config.max_items, config.min_items) && config.max_items <= bank.item_count
    && typeof config.se_threshold === 'number' && Number.isFinite(config.se_threshold)
    && isInteger(config.seed)
    && simulation.available === true
    && Array.isArray(simulation.sample_sizes)
    && simulation.sample_sizes.length === 2
    && simulation.sample_sizes[0] === 100 && simulation.sample_sizes[1] === 1000
    && simulation.fixed_seed === config.seed;
}

export function validCatSimulation(value, catalog, sampleSize) {
  if (!validCatCatalog(catalog)
    || !hasExactKeys(value, [
      'schema_version', 'engineering_only', 'psychological_interpretation_allowed',
      'item_bank_id', 'item_bank_version', 'config_version', 'n_examinees', 'seed',
      'metrics', 'stopping_reason_distribution',
    ])
    || value.schema_version !== 'synthetic_cat_management.v1'
    || value.engineering_only !== true || value.psychological_interpretation_allowed !== false
    || value.n_examinees !== sampleSize || ![100, 1000].includes(sampleSize)
    || value.item_bank_id !== catalog.item_bank.item_bank_id
    || value.item_bank_version !== catalog.item_bank.version
    || value.config_version !== catalog.config.config_version
    || value.seed !== catalog.config.seed
    || !hasExactKeys(value.metrics, METRIC_KEYS)
    || !isRecord(value.stopping_reason_distribution)) return false;
  const metricKeys = Object.keys(value.metrics).sort();
  if (metricKeys.join('|') !== [...METRIC_KEYS].sort().join('|')) return false;
  for (const key of METRIC_KEYS) {
    const metric = value.metrics[key];
    if (typeof metric !== 'number' || !Number.isFinite(metric)
      || (key !== 'bias' && metric < 0)
      || ((key === 'mean_test_length' || key === 'median_test_length') && metric === 0)) return false;
  }
  const stops = Object.entries(value.stopping_reason_distribution);
  return stops.length > 0
    && stops.every(([reason, count]) => Object.hasOwn(STOP_LABELS, reason) && isInteger(count))
    && stops.reduce((sum, [, count]) => sum + count, 0) === sampleSize;
}

export function summarizeCatManagementWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null) {
  const exactStages = isRecord(stages)
    && Object.keys(stages).length === UI_STAGE_KEYS.length
    && UI_STAGE_KEYS.every((key) => Object.hasOwn(stages, key) && ['PASS', 'FAIL'].includes(stages[key]));
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

const responseMatches = (response, method, pathname, backendUrl) => {
  const url = new URL(response.url());
  return url.origin === backendUrl && url.pathname === pathname && response.request().method() === method;
};

const responseData = (envelope) => envelope?.data?.data ?? envelope?.data;

async function apiActor(page, backendUrl) {
  return page.evaluate(async (base) => {
    const response = await fetch(`${base}/api/v1/auth/me`, {
      credentials: 'include', headers: { Accept: 'application/json' },
    });
    if (!response.ok) return { status: response.status, actor: null };
    const envelope = await response.json();
    return { status: response.status, actor: envelope?.data?.actor ?? envelope?.data };
  }, backendUrl);
}

async function loginSpecialist(session, payload) {
  const page = session.page;
  await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
  const username = page.getByRole('textbox', { name: 'Username' });
  const password = page.locator('#password');
  await username.waitFor({ state: 'visible', timeout: 10000 });
  if ((await username.inputValue()) !== '' || (await password.inputValue()) !== '') throw new Error('LoginFormNotBlank');
  const account = payload.credentials[SPECIALIST_SLOT];
  try {
    await username.fill(account.username);
    await password.fill(account.password);
    session.loginSubmitted = true;
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    const picker = page.locator('#school-context');
    if (await picker.isVisible({ timeout: 1200 }).catch(() => false)) {
      const choices = await picker.locator('option:not([disabled])').evaluateAll((options) => options.map((item) => item.value));
      if (choices.length !== 1 || !choices[0]) throw new Error('SchoolContextMismatch');
      await picker.selectOption(choices[0]);
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
    }
    await page.waitForURL((url) => url.pathname === '/specialist/overview', { timeout: 20000 });
    if (await password.isVisible().catch(() => false) && (await password.inputValue()) !== '') throw new Error('LoginPasswordNotCleared');
    const authenticated = await apiActor(page, payload.backend_url);
    if (authenticated.status !== 200
      || authenticated.actor?.active_context?.role !== 'PSYCHOLOGICAL_SPECIALIST'
      || authenticated.actor?.active_context?.school_ref !== SCHOOL_REF) throw new Error('AuthenticatedRoleMismatch');
  } finally {
    account.username = '';
    account.password = '';
  }
}

async function logoutSession(session, backendUrl) {
  let logoutOk = !session.loginSubmitted;
  let contextClosed = false;
  if (session.loginSubmitted) {
    try {
      await session.page.locator('.account-menu > summary').click({ timeout: 3000 });
      await session.page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 3000 });
      await session.page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
      logoutOk = true;
    } catch {
      try {
        logoutOk = await session.page.evaluate(async (base) => {
          const csrf = await fetch(`${base}/api/v1/auth/csrf`, {
            credentials: 'include', headers: { Accept: 'application/json' },
          });
          if (!csrf.ok) return false;
          const envelope = await csrf.json();
          const token = envelope?.data?.csrf_token;
          if (typeof token !== 'string' || !token) return false;
          const response = await fetch(`${base}/api/v1/auth/logout`, {
            method: 'POST', credentials: 'include',
            headers: { Accept: 'application/json', 'X-CSRF-Token': token },
          });
          return response.ok;
        }, backendUrl);
      } catch { logoutOk = false; }
    }
  }
  try { await session.context.close(); contextClosed = true; } catch { contextClosed = false; }
  return logoutOk && contextClosed;
}

function clearPayloadCredentials(payload) {
  const account = payload?.credentials?.[SPECIALIST_SLOT];
  if (account && typeof account === 'object') {
    account.username = '';
    account.password = '';
  }
  if (payload && typeof payload === 'object') payload.credentials = undefined;
}

function formatMetric(key, value) {
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: key === 'mean_test_length' || key === 'median_test_length' ? 2 : 3,
    minimumFractionDigits: 0,
  }).format(value);
}

async function readJsonResponse(response, label) {
  if (response.status() !== 200) throw new Error(label);
  try { return responseData(await response.json()); } catch { throw new Error(label); }
}

async function assertCatalogVisible(page, catalog) {
  const visible = await page.locator('.cat-workbench').evaluate((root) => ({
    factCount: root.querySelectorAll('.cat-facts > div').length,
    version: root.querySelector('.cat-facts > div:first-child dd')?.textContent?.trim() ?? '',
    count: root.querySelector('.cat-facts > div:nth-child(3) dd')?.textContent?.trim() ?? '',
    dimensions: root.querySelector('.cat-facts > div:nth-child(4) dd')?.textContent?.trim() ?? '',
    configVersion: root.querySelector('.cat-config-block__heading span:last-child')?.textContent?.trim() ?? '',
    text: root.textContent ?? '',
  }));
  return visible.factCount === 5
    && visible.version === catalog.item_bank.version
    && visible.count === `${catalog.item_bank.item_count} 道`
    && visible.dimensions === `${catalog.item_bank.dimension_count} 个`
    && visible.configVersion === catalog.config.config_version
    && !visible.text.includes(catalog.item_bank.item_bank_id)
    && !visible.text.includes(catalog.item_bank.instrument_id);
}

const sortedEntries = (value) => Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
const sameAggregate = (first, second) => JSON.stringify(sortedEntries(first.metrics)) === JSON.stringify(sortedEntries(second.metrics))
  && JSON.stringify(sortedEntries(first.stopping_reason_distribution))
    === JSON.stringify(sortedEntries(second.stopping_reason_distribution));

async function assertAggregatesVisible(page, simulation) {
  const visible = await page.locator('.cat-results').evaluate((root) => ({
    metrics: [...root.querySelectorAll('.cat-metrics > div')].map((row) => ({
      label: row.querySelector('dt')?.textContent?.trim() ?? '',
      value: row.querySelector('dd')?.textContent?.trim() ?? '',
    })),
    reasons: [...root.querySelectorAll('.cat-stopping li')].map((row) => ({
      label: row.children[0]?.textContent?.trim() ?? '',
      count: row.children[2]?.textContent?.trim() ?? '',
    })),
    summary: root.querySelector('.cat-results__heading > div > p:last-child')?.textContent?.trim() ?? '',
  }));
  const metricsByLabel = Object.fromEntries(visible.metrics.map(({ label, value }) => [label, value]));
  if (visible.metrics.length !== METRIC_KEYS.length) throw new Error('CatMetricUiShapeMismatch');
  for (const key of METRIC_KEYS) {
    if (metricsByLabel[METRIC_LABELS[key]] !== formatMetric(key, simulation.metrics[key])) {
      throw new Error('CatMetricUiApiMismatch');
    }
  }
  const reasonsByLabel = Object.fromEntries(visible.reasons.map(({ label, count }) => [label, Number(count)]));
  const expectedReasons = Object.entries(simulation.stopping_reason_distribution)
    .map(([reason, count]) => [STOP_LABELS[reason], count]);
  if (visible.reasons.length !== expectedReasons.length
    || expectedReasons.some(([label, count]) => reasonsByLabel[label] !== count)) {
    throw new Error('CatStoppingUiApiMismatch');
  }
  if (!visible.summary.includes(simulation.item_bank_version)
    || !visible.summary.includes(simulation.config_version)
    || !visible.summary.includes(simulation.n_examinees.toLocaleString('zh-CN'))) {
    throw new Error('CatResultMetadataUiMismatch');
  }
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

export async function runCatManagementWorkflow(payload, { chromium: browserLauncher = chromium } = {}) {
  const stages = failedStages();
  const screenshotFiles = [];
  let browser = null;
  let session = null;
  let failure = null;
  let failureStage = 'specialist_login';
  try {
    browser = await browserLauncher.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    session = { context, page: await context.newPage(), loginSubmitted: false };
    await loginSpecialist(session, payload);
    stages.specialist_login = 'PASS';

    failureStage = 'catalog_read_verified';
    const catalogResponsePromise = session.page.waitForResponse(
      (response) => responseMatches(response, 'GET', '/api/v1/school/cat-management/catalog', payload.backend_url),
      { timeout: 30000 },
    );
    await session.page.goto(`${payload.frontend_url}/specialist/cat`, { waitUntil: 'domcontentloaded' });
    const catalogResponse = await catalogResponsePromise;
    const catalog = await readJsonResponse(catalogResponse, 'CatCatalogReadFailed');
    if (!validCatCatalog(catalog)) throw new Error('CatCatalogShapeMismatch');
    await session.page.getByRole('heading', { name: '测评方案与模拟', exact: true }).waitFor({ state: 'visible', timeout: 20000 });
    await session.page.getByRole('heading', { name: '工程模拟不代表心理学结论', exact: true })
      .waitFor({ state: 'visible', timeout: 10000 });
    await session.page.getByText(/心理学解释已关闭/).waitFor({ state: 'visible', timeout: 10000 });
    if (!(await assertCatalogVisible(session.page, catalog))) throw new Error('CatCatalogUiMismatch');
    stages.catalog_read_verified = 'PASS';

    failureStage = 'simulation100_verified';
    const sampleInput = session.page.locator('input[name="cat-sample-size"][value="100"]');
    await sampleInput.waitFor({ state: 'visible', timeout: 10000 });
    if (!(await sampleInput.isChecked())) await sampleInput.click();
    const firstSimulationPromise = session.page.waitForResponse(
      (response) => responseMatches(response, 'POST', '/api/v1/school/cat-management/simulations', payload.backend_url),
      { timeout: 600000 },
    );
    await session.page.getByRole('button', { name: '运行工程模拟', exact: true }).click();
    await session.page.getByText(/运行中，较大批次可能需要数分钟。/).waitFor({ state: 'visible', timeout: 5000 });
    if (!(await sampleInput.isDisabled()) || !(await session.page.locator('.cat-button--primary').isDisabled())) {
      throw new Error('CatSimulationPendingControlsUnlocked');
    }
    const firstResponse = await firstSimulationPromise;
    const firstSimulation = await readJsonResponse(firstResponse, 'CatSimulationFailed');
    if (!validCatSimulation(firstSimulation, catalog, 100)) throw new Error('CatSimulationShapeMismatch');
    stages.simulation100_verified = 'PASS';

    failureStage = 'ui_aggregates_matched_api';
    await session.page.getByRole('heading', { name: '模拟结果', exact: true }).waitFor({ state: 'visible', timeout: 30000 });
    await session.page.getByText('仅供工程验证', { exact: true }).waitFor({ state: 'visible', timeout: 10000 });
    await assertAggregatesVisible(session.page, firstSimulation);
    stages.ui_aggregates_matched_api = 'PASS';

    failureStage = 'repeat_simulation_verified';
    const secondSimulationPromise = session.page.waitForResponse(
      (response) => responseMatches(response, 'POST', '/api/v1/school/cat-management/simulations', payload.backend_url),
      { timeout: 600000 },
    );
    await session.page.getByRole('button', { name: '再次运行并对照', exact: true }).click();
    const secondResponse = await secondSimulationPromise;
    const secondSimulation = await readJsonResponse(secondResponse, 'CatRepeatSimulationFailed');
    if (!validCatSimulation(secondSimulation, catalog, 100)) throw new Error('CatRepeatSimulationShapeMismatch');
    const repeatMatches = sameAggregate(firstSimulation, secondSimulation);
    if (!repeatMatches) throw new Error('CatRepeatAggregateMismatch');
    await assertAggregatesVisible(session.page, secondSimulation);
    await session.page.getByText('本次与上一轮同样本量运行的聚合结果一致。', { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 });
    stages.repeat_simulation_verified = 'PASS';
    firstSimulation.metrics = null;
    firstSimulation.stopping_reason_distribution = null;
    secondSimulation.metrics = null;
    secondSimulation.stopping_reason_distribution = null;

    failureStage = 'desktop_screenshot';
    await captureScreenshot(session.page, payload, SCREENSHOTS[0], 1365, 900);
    screenshotFiles.push(SCREENSHOTS[0]);
    stages.desktop_screenshot = 'PASS';
    failureStage = 'mobile_screenshot';
    await captureScreenshot(session.page, payload, SCREENSHOTS[1], 390, 844);
    screenshotFiles.push(SCREENSHOTS[1]);
    stages.mobile_screenshot = 'PASS';
  } catch (error) {
    failure = { stage: failureStage, error_class: safeExceptionClass(error) };
  } finally {
    failureStage = 'session_cleanup';
    try {
      stages.session_cleanup = !session || await logoutSession(session, payload.backend_url) ? 'PASS' : 'FAIL';
    } catch { stages.session_cleanup = 'FAIL'; }
    try { if (browser) await browser.close(); } catch { stages.session_cleanup = 'FAIL'; }
    clearPayloadCredentials(payload);
  }

  if (stages.session_cleanup !== 'PASS' && !failure) {
    failure = { stage: 'session_cleanup', error_class: 'Error' };
  }
  const result = summarizeCatManagementWorkflow(stages, screenshotFiles, payload.artifact_dir, 0, failure);
  if (result.status !== 'PASS' && !result.failure) {
    const failed = UI_STAGE_KEYS.find((key) => stages[key] !== 'PASS') ?? 'session_cleanup';
    result.failure = { stage: failed, error_class: 'Error' };
  }
  return result;
}

async function main() {
  const payload = await readInput();
  if (!validCatManagementPayload(payload)) {
    console.log(JSON.stringify({
      workflow: WORKFLOW,
      status: 'FAIL',
      stages: failedStages(),
      screenshots: [],
      failure: { stage: 'specialist_login', error_class: 'Error' },
    }));
    return 2;
  }
  try {
    const result = await runCatManagementWorkflow(payload);
    console.log(JSON.stringify(result));
    return result.status === 'PASS' ? 0 : 2;
  } catch {
    clearPayloadCredentials(payload);
    console.log(JSON.stringify({
      workflow: WORKFLOW,
      status: 'FAIL',
      stages: failedStages(),
      screenshots: [],
      failure: { stage: 'specialist_login', error_class: 'Error' },
    }));
    return 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
