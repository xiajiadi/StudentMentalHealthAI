import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');
const fs = require('node:fs');

export const WORKSPACE = 'D:\\Projects\\.StudentMentalHealthAI-school-workspace-20261011';
export const FRONTEND_URL = 'http://127.0.0.1:4178';
export const BACKEND_URL = 'http://127.0.0.1:8088';
export const SCHOOL_REF = 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1';
export const SCREENSHOTS = ['specialist-cat-assets-desktop.png', 'specialist-cat-assets-mobile.png'];
export const SCREENSHOT_STAGES = {
  'specialist-cat-assets-desktop.png': 'desktop_screenshot',
  'specialist-cat-assets-mobile.png': 'mobile_screenshot',
};
export const SCREENSHOT_MASK_SELECTORS = [
  '.account-menu',
  'input, textarea, select',
  '.asset-history__row time',
];
export const UI_STAGE_KEYS = [
  'specialist_login',
  'cat_page_open',
  'assets_panel_tab_clicked',
  'asset_template_seen',
  'asset_template_http200',
  'asset_banks_seen',
  'asset_banks_http200',
  'asset_plans_seen',
  'asset_plans_http200',
  'asset_payload_validated',
  'asset_heading_visible',
  'asset_list_visible',
  'assets_panel_loaded',
  'bank_created',
  'bank_version_saved',
  'plan_created',
  'plan_version_saved',
  'history_reload_verified',
  'desktop_screenshot',
  'mobile_screenshot',
  'session_cleanup',
];
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError', 'ProtocolError', 'TargetClosedError',
];

const WORKFLOW = 'school-cat-assets';
const SPECIALIST_SLOT = 'alpha.psychological_specialist';
const API_PREFIX = '/api/v1/school/cat-assets';
const BANK_REF = /^CBANK_[A-Za-z0-9-]{36}$/;
const BANK_VERSION_REF = /^CBVER_[A-Za-z0-9-]{36}$/;
const PLAN_REF = /^CPLAN_[A-Za-z0-9-]{36}$/;
const PLAN_VERSION_REF = /^CPVER_[A-Za-z0-9-]{36}$/;
const ITEM_ID = /^ITEM_[A-Za-z0-9_.-]{1,122}$/;
const BANK_KEYS = [
  'item_bank_id', 'version', 'instrument_id', 'target_population', 'measurement_model',
  'dimensions', 'items', 'status', 'metadata',
];
const CONFIG_KEYS = [
  'config_version', 'model', 'estimator', 'selection_method', 'min_items', 'max_items', 'se_threshold',
  'initial_theta', 'prior_mean', 'prior_sd', 'optimization_interval', 'seed', 'exposure_control', 'content_balancing',
];
const ITEM_KEYS = [
  'item_id', 'dimension', 'stem', 'response_type', 'response_options', 'scoring', 'model', 'parameters', 'source', 'status',
];
const ASSET_META_KEYS = ['bank_ref', 'display_name', 'status', 'revision', 'created_at', 'updated_at'];
const PLAN_META_KEYS = ['plan_ref', 'display_name', 'status', 'revision', 'created_at', 'updated_at'];
const BANK_VERSION_KEYS = ['version_ref', 'version_number', 'created_at', 'item_count', 'dimension_count'];
const PLAN_VERSION_KEYS = ['version_ref', 'version_number', 'created_at'];

const failedStages = () => Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));
const isRecord = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (value, keys) => isRecord(value)
  && Object.keys(value).sort().join('|') === [...keys].sort().join('|');
const safeText = (value, max = 5000) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const safeDate = (value) => safeText(value, 64) && !Number.isNaN(Date.parse(value));
const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const integer = (value, low = 0, high = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= low && value <= high;
const flagsValid = (value) => value.engineering_only === true && value.psychological_interpretation_allowed === false;
const responseData = (envelope) => envelope?.data?.data ?? envelope?.data;
const greatestVersion = (versions) => Array.isArray(versions)
  ? versions.reduce((latest, version) => !latest || version.version_number > latest.version_number ? version : latest, null)
  : null;

function artifactPathAllowed(candidate) {
  if (typeof candidate !== 'string') return false;
  const base = path.resolve(WORKSPACE);
  const target = path.resolve(candidate);
  const relative = path.relative(base, target);
  const parts = relative.split(path.sep);
  return parts.length === 2 && parts[0] === 'browser-qa'
    && /^\d{8}T\d{6}Z-[a-f0-9]{32}$/.test(parts[1]) && !path.isAbsolute(relative);
}

export function validCatAssetsPayload(payload) {
  if (!exactKeys(payload, ['artifact_dir', 'backend_url', 'credentials', 'frontend_url'])
    || payload.frontend_url !== FRONTEND_URL || payload.backend_url !== BACKEND_URL
    || !artifactPathAllowed(payload.artifact_dir)
    || !isRecord(payload.credentials) || Object.keys(payload.credentials).join('|') !== SPECIALIST_SLOT) return false;
  const account = payload.credentials[SPECIALIST_SLOT];
  return exactKeys(account, ['username', 'password'])
    && typeof account.username === 'string' && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(account.username)
    && typeof account.password === 'string' && account.password.length >= 16 && account.password.length <= 512;
}

export function validCatBankDocument(value) {
  if (!exactKeys(value, BANK_KEYS) || !safeText(value.item_bank_id, 160) || !safeText(value.version, 160)
    || !safeText(value.instrument_id, 160) || !safeText(value.target_population, 160)
    || value.measurement_model !== 'GRM' || !Array.isArray(value.dimensions) || value.dimensions.length !== 1
    || !safeText(value.dimensions[0], 160) || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 100
    || !['draft', 'published'].includes(value.status) || !isRecord(value.metadata)
    || value.metadata.synthetic !== true || value.metadata.intended_use !== 'engineering_test_only'
    || value.metadata.psychological_interpretation_allowed !== false) return false;
  const dimension = value.dimensions[0];
  const seen = new Set();
  return value.items.every((item) => {
    if (!exactKeys(item, ITEM_KEYS) || !ITEM_ID.test(String(item.item_id)) || seen.has(item.item_id)
      || item.dimension !== dimension || !safeText(item.stem, 2000) || item.response_type !== 'likert'
      || item.model !== 'GRM' || !['published', 'demo', 'synthetic'].includes(item.status)
      || !safeText(item.source, 160) || !Array.isArray(item.response_options)
      || item.response_options.length < 2 || item.response_options.length > 10
      || !item.response_options.every((option) => safeText(option, 160))
      || new Set(item.response_options).size !== item.response_options.length
      || !exactKeys(item.parameters, ['a', 'thresholds']) || !finite(item.parameters.a)
      || item.parameters.a <= 0 || item.parameters.a > 10 || !Array.isArray(item.parameters.thresholds)
      || item.parameters.thresholds.length !== item.response_options.length - 1
      || !item.parameters.thresholds.every(finite)
      || item.parameters.thresholds.some((current, index) => index > 0 && current <= item.parameters.thresholds[index - 1])
      || !isRecord(item.scoring) || Object.keys(item.scoring).length !== item.response_options.length
      || item.response_options.some((option) => !Object.hasOwn(item.scoring, option))) return false;
    const values = item.response_options.map((option) => item.scoring[option]);
    if (!values.every((score) => integer(score, 0, item.response_options.length - 1))
      || new Set(values).size !== values.length
      || values.slice().sort((a, b) => a - b).some((score, index) => score !== index)) return false;
    seen.add(item.item_id);
    return true;
  });
}

export function validCatConfig(value, itemCount = 100) {
  return exactKeys(value, CONFIG_KEYS) && safeText(value.config_version, 160)
    && value.model === 'GRM' && ['EAP', 'BM'].includes(value.estimator) && value.selection_method === 'MFI'
    && integer(value.min_items, 1, 100) && integer(value.max_items, value.min_items, Math.min(itemCount, 100))
    && (value.se_threshold === null || (finite(value.se_threshold) && value.se_threshold > 0 && value.se_threshold <= 10))
    && finite(value.initial_theta) && finite(value.prior_mean) && finite(value.prior_sd) && value.prior_sd > 0 && value.prior_sd <= 10
    && Array.isArray(value.optimization_interval) && value.optimization_interval.length === 2
    && value.optimization_interval.every(finite) && value.optimization_interval[0] < value.optimization_interval[1]
    && integer(value.seed, 0, 4294967295) && value.exposure_control === 'none' && value.content_balancing === 'none';
}

export function validCatAssetFlags(value) { return isRecord(value) && flagsValid(value); }

function validBankMeta(value) {
  return exactKeys(value, ASSET_META_KEYS) && typeof value.bank_ref === 'string' && BANK_REF.test(value.bank_ref)
    && safeText(value.display_name, 120) && ['ACTIVE', 'ARCHIVED'].includes(value.status)
    && integer(value.revision, 1) && safeDate(value.created_at) && safeDate(value.updated_at);
}

function validPlanMeta(value) {
  return exactKeys(value, PLAN_META_KEYS) && typeof value.plan_ref === 'string' && PLAN_REF.test(value.plan_ref)
    && safeText(value.display_name, 120) && ['ACTIVE', 'ARCHIVED'].includes(value.status)
    && integer(value.revision, 1) && safeDate(value.created_at) && safeDate(value.updated_at);
}

function validBankVersionMeta(value, expectedCount) {
  return exactKeys(value, BANK_VERSION_KEYS) && typeof value.version_ref === 'string' && BANK_VERSION_REF.test(value.version_ref)
    && integer(value.version_number, 1) && safeDate(value.created_at) && integer(value.item_count, 1, 100)
    && integer(value.dimension_count, 1, 1) && (expectedCount === undefined || value.item_count === expectedCount);
}

function validPlanVersionMeta(value) {
  return exactKeys(value, PLAN_VERSION_KEYS) && typeof value.version_ref === 'string' && PLAN_VERSION_REF.test(value.version_ref)
    && integer(value.version_number, 1) && safeDate(value.created_at);
}

function validBankDetail(value) {
  const metadata = isRecord(value?.bank) ? Object.fromEntries(ASSET_META_KEYS.map((key) => [key, value.bank[key]])) : null;
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'bank']) && flagsValid(value)
    && exactKeys(value.bank, [...ASSET_META_KEYS, 'versions']) && validBankMeta(metadata)
    && Array.isArray(value.bank.versions) && value.bank.versions.every((version) => validBankVersionMeta(version));
}

function validPlanDetail(value) {
  const metadata = isRecord(value?.plan) ? Object.fromEntries(PLAN_META_KEYS.map((key) => [key, value.plan[key]])) : null;
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'plan']) && flagsValid(value)
    && exactKeys(value.plan, [...PLAN_META_KEYS, 'versions']) && validPlanMeta(metadata)
    && Array.isArray(value.plan.versions) && value.plan.versions.every((version) => validPlanVersionMeta(version));
}

export function validCatAssetsTemplate(value) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'bank_document', 'config_document', 'item_count', 'dimension_count'])
    && flagsValid(value) && validCatBankDocument(value.bank_document)
    && validCatConfig(value.config_document, value.bank_document.items.length)
    && integer(value.item_count, 1, 100) && value.item_count === value.bank_document.items.length
    && integer(value.dimension_count, 1, 1) && value.dimension_count === value.bank_document.dimensions.length;
}

export function validCatBankList(value) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'items', 'has_more'])
    && flagsValid(value) && Array.isArray(value.items) && typeof value.has_more === 'boolean'
    && value.items.every(validBankMeta);
}

export function validCatBankWrite(value, expectedName = undefined) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'bank', 'version_ref'])
    && validBankDetail({ engineering_only: value.engineering_only, psychological_interpretation_allowed: value.psychological_interpretation_allowed, bank: value.bank })
    && typeof value.version_ref === 'string' && BANK_VERSION_REF.test(value.version_ref)
    && value.bank.versions.some((version) => version.version_ref === value.version_ref)
    && greatestVersion(value.bank.versions)?.version_ref === value.version_ref
    && (expectedName === undefined || value.bank.display_name === expectedName);
}

export function validCatBankVersion(value, expectedRef = undefined) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'version', 'bank_document'])
    && flagsValid(value) && validBankVersionMeta(value.version, value.bank_document?.items?.length)
    && (expectedRef === undefined || value.version.version_ref === expectedRef)
    && validCatBankDocument(value.bank_document)
    && value.version.dimension_count === value.bank_document.dimensions.length;
}

export function validCatPlanList(value) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'items', 'has_more'])
    && flagsValid(value) && Array.isArray(value.items) && typeof value.has_more === 'boolean'
    && value.items.every(validPlanMeta);
}

export function validCatPlanWrite(value, expectedName = undefined) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'plan', 'version_ref'])
    && validPlanDetail({ engineering_only: value.engineering_only, psychological_interpretation_allowed: value.psychological_interpretation_allowed, plan: value.plan })
    && typeof value.version_ref === 'string' && PLAN_VERSION_REF.test(value.version_ref)
    && value.plan.versions.some((version) => version.version_ref === value.version_ref)
    && greatestVersion(value.plan.versions)?.version_ref === value.version_ref
    && (expectedName === undefined || value.plan.display_name === expectedName);
}

export function validCatPlanVersion(value, expectedVersionRef = undefined, expectedBankVersionRef = undefined) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'version', 'bank_version_ref', 'config_document'])
    && flagsValid(value) && validPlanVersionMeta(value.version)
    && (expectedVersionRef === undefined || value.version.version_ref === expectedVersionRef)
    && typeof value.bank_version_ref === 'string' && BANK_VERSION_REF.test(value.bank_version_ref)
    && (expectedBankVersionRef === undefined || value.bank_version_ref === expectedBankVersionRef)
    && validCatConfig(value.config_document);
}

export function summarizeCatAssetsWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null) {
  const stageListValid = isRecord(stages) && Object.keys(stages).length === UI_STAGE_KEYS.length
    && UI_STAGE_KEYS.every((key) => Object.hasOwn(stages, key) && ['PASS', 'FAIL'].includes(stages[key]));
  const safeStages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, stageListValid && stages[key] === 'PASS' ? 'PASS' : 'FAIL']));
  const screenshotNamesValid = Array.isArray(screenshotFiles) && screenshotFiles.length === SCREENSHOTS.length
    && new Set(screenshotFiles).size === SCREENSHOTS.length && SCREENSHOTS.every((name) => screenshotFiles.includes(name));
  for (const [name, stage] of Object.entries(SCREENSHOT_STAGES)) {
    let fileExists = false;
    try { fileExists = screenshotNamesValid && fs.statSync(path.join(artifactDir, name)).isFile(); } catch { /* fixed failure */ }
    if (!fileExists) safeStages[stage] = 'FAIL';
  }
  const passed = runnerExitCode === 0 && stageListValid && screenshotNamesValid
    && UI_STAGE_KEYS.every((key) => safeStages[key] === 'PASS');
  const result = { workflow: WORKFLOW, status: passed ? 'PASS' : 'FAIL', stages: safeStages, screenshots: passed ? [...SCREENSHOTS] : [] };
  if (!passed && failure && UI_STAGE_KEYS.includes(failure.stage)) {
    result.failure = { stage: failure.stage, error_class: SAFE_FAILURE_CLASSES.includes(failure.error_class) ? failure.error_class : 'Error' };
  }
  return result;
}

const safeErrorClass = (error) => SAFE_FAILURE_CLASSES.includes(error?.name) ? error.name : 'Error';
const clearPayloadCredentials = (payload) => {
  const account = payload?.credentials?.[SPECIALIST_SLOT];
  if (account && typeof account === 'object') { account.username = ''; account.password = ''; }
  if (payload && typeof payload === 'object') payload.credentials = undefined;
};

async function readInput() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  const raw = Buffer.concat(chunks);
  try { return JSON.parse(raw.toString('utf8')); } catch { return null; }
  finally { raw.fill(0); for (const chunk of chunks) chunk.fill(0); }
}

const matchesResponse = (response, method, pathname, backendUrl) => {
  const url = new URL(response.url());
  return url.origin === backendUrl && url.pathname === pathname && response.request().method() === method;
};

async function verifiedResponse(response, expectedStatus, label) {
  if (response.status() !== expectedStatus) throw new Error(label);
  try { return responseData(await response.json()); } catch { throw new Error(label); }
}

async function loginSpecialist(session, payload) {
  const page = session.page;
  await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
  const username = page.getByRole('textbox', { name: 'Username' });
  const password = page.locator('#password');
  await username.waitFor({ state: 'visible', timeout: 10000 });
  if (await username.inputValue() !== '' || await password.inputValue() !== '') throw new Error('LoginFormNotBlank');
  const account = payload.credentials[SPECIALIST_SLOT];
  try {
    await username.fill(account.username);
    await password.fill(account.password);
    session.loginSubmitted = true;
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    const picker = page.locator('#school-context');
    if (await picker.isVisible({ timeout: 1200 }).catch(() => false)) {
      const choices = await picker.locator('option:not([disabled])').evaluateAll((options) => options.map((option) => option.value));
      if (choices.length !== 1 || !choices[0]) throw new Error('SchoolContextMismatch');
      await picker.selectOption(choices[0]);
      await page.getByRole('button', { name: 'Continue', exact: true }).click();
    }
    await page.waitForURL((url) => url.pathname === '/specialist/overview', { timeout: 20000 });
    if (await password.isVisible().catch(() => false) && await password.inputValue() !== '') throw new Error('LoginPasswordNotCleared');
    const actor = await page.evaluate(async (base) => {
      const response = await fetch(`${base}/api/v1/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' } });
      if (!response.ok) return { status: response.status, actor: null };
      const envelope = await response.json();
      return { status: response.status, actor: envelope?.data?.actor ?? envelope?.data };
    }, payload.backend_url);
    if (actor.status !== 200 || actor.actor?.active_context?.role !== 'PSYCHOLOGICAL_SPECIALIST'
      || actor.actor?.active_context?.school_ref !== SCHOOL_REF) throw new Error('AuthenticatedRoleMismatch');
  } finally { account.username = ''; account.password = ''; }
}

async function logoutSession(session, backendUrl) {
  let logoutOk = !session.loginSubmitted;
  let closed = false;
  if (session.loginSubmitted) {
    try {
      await session.page.locator('.account-menu > summary').click({ timeout: 3000 });
      await session.page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 3000 });
      await session.page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
      logoutOk = true;
    } catch {
      try {
        logoutOk = await session.page.evaluate(async (base) => {
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
      } catch { logoutOk = false; }
    }
  }
  try { await session.context.close(); closed = true; } catch { closed = false; }
  return logoutOk && closed;
}

async function captureScreenshot(page, payload, name, width, height) {
  if (!SCREENSHOTS.includes(name)) throw new Error('UnexpectedScreenshotName');
  await page.setViewportSize({ width, height });
  await page.evaluate(() => { window.scrollTo(0, 0); return new Promise((resolve) => requestAnimationFrame(resolve)); });
  await page.screenshot({
    path: path.join(payload.artifact_dir, name), fullPage: true, animations: 'disabled',
    mask: SCREENSHOT_MASK_SELECTORS.map((selector) => page.locator(selector)),
  });
}

async function waitResponse(page, method, pathname, backendUrl, status, label, click) {
  const responsePromise = page.waitForResponse(
    (response) => matchesResponse(response, method, pathname, backendUrl), { timeout: 30000 },
  );
  await click();
  const response = await responsePromise;
  return { response, data: await verifiedResponse(response, status, label) };
}

async function loadAssetPanel(page, payload, markStage, markFailureStage) {
  const definitions = [
    { key: 'asset_template', suffix: '/template' },
    { key: 'asset_banks', suffix: '/banks' },
    { key: 'asset_plans', suffix: '/plans' },
  ];
  const paths = definitions.map(({ suffix }) => page.waitForResponse(
    (response) => matchesResponse(response, 'GET', `${API_PREFIX}${suffix}`, payload.backend_url), { timeout: 30000 },
  ));
  markFailureStage('assets_panel_tab_clicked');
  await page.getByRole('button', { name: '题库与方案', exact: true }).click();
  markStage('assets_panel_tab_clicked');
  const responses = await Promise.allSettled(paths);
  const responseDataByKey = {};
  for (let index = 0; index < definitions.length; index += 1) {
    const { key } = definitions[index];
    const outcome = responses[index];
    if (outcome.status !== 'fulfilled') {
      markFailureStage(`${key}_seen`);
      throw new Error('CatAssetPanelRequestNotObserved');
    }
    markStage(`${key}_seen`);
    markFailureStage(`${key}_http200`);
    if (outcome.value.status() !== 200) throw new Error('CatAssetPanelRequestFailed');
    markStage(`${key}_http200`);
    const label = key === 'asset_template' ? 'CatAssetTemplateReadFailed'
      : key === 'asset_banks' ? 'CatAssetBankListFailed' : 'CatAssetPlanListFailed';
    responseDataByKey[key] = await verifiedResponse(outcome.value, 200, label);
  }
  markFailureStage('asset_payload_validated');
  const template = responseDataByKey.asset_template;
  const banks = responseDataByKey.asset_banks;
  const plans = responseDataByKey.asset_plans;
  if (!validCatAssetsTemplate(template) || !validCatBankList(banks) || !validCatPlanList(plans)) throw new Error('CatAssetInitialDataInvalid');
  markStage('asset_payload_validated');
  markFailureStage('asset_heading_visible');
  await page.getByRole('heading', { name: '题库', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  markStage('asset_heading_visible');
  markFailureStage('asset_list_visible');
  await page.locator('.asset-list').waitFor({ state: 'visible', timeout: 10000 });
  markStage('asset_list_visible');
  markStage('assets_panel_loaded');
  return { template, banks, plans };
}

function noOpaqueReferenceVisible(page, references) {
  return page.locator('body').innerText().then((text) => references.every((reference) => !text.includes(reference)));
}

export async function runCatAssetsWorkflow(payload, { chromium: browserLauncher = chromium } = {}) {
  const stages = failedStages();
  const screenshotFiles = [];
  let browser = null;
  let session = null;
  let failure = null;
  let failureStage = 'specialist_login';
  let bankRef = '';
  let bankVersionRef = '';
  let planRef = '';
  let planVersionRef = '';
  let editedStem = '';
  let createdBankName = '';
  let createdPlanName = '';
  let chosenMaxItems = 0;
  try {
    browser = await browserLauncher.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    session = { context, page: await context.newPage(), loginSubmitted: false };
    const page = session.page;
    await loginSpecialist(session, payload);
    stages.specialist_login = 'PASS';

    failureStage = 'cat_page_open';
    const catPageResponsePromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', '/api/v1/school/cat-management/catalog', payload.backend_url),
      { timeout: 30000 },
    );
    await page.goto(`${payload.frontend_url}/specialist/cat`, { waitUntil: 'domcontentloaded' });
    const catPageResponse = await catPageResponsePromise;
    if (catPageResponse.status() !== 200) throw new Error('CatManagementCatalogUnavailable');
    await page.getByRole('heading', { name: '测评方案与模拟', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
    stages.cat_page_open = 'PASS';

    failureStage = 'assets_panel_loaded';
    const { template } = await loadAssetPanel(page, payload,
      (key) => { stages[key] = 'PASS'; }, (key) => { failureStage = key; });
    stages.assets_panel_loaded = 'PASS';

    failureStage = 'bank_created';
    createdBankName = `合成浏览器题库${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}`;
    await page.getByRole('button', { name: '新建', exact: true }).click();
    await page.getByLabel('题库名称').fill(createdBankName);
    if (!(await page.locator('.asset-item textarea').count())) throw new Error('SyntheticBankEditorMissing');
    const { data: createBankData } = await waitResponse(
      page, 'POST', `${API_PREFIX}/banks`, payload.backend_url, 201, 'CatAssetBankCreateFailed',
      () => page.getByRole('button', { name: '创建题库', exact: true }).click(),
    );
    if (!validCatBankWrite(createBankData, createdBankName)) throw new Error('CatAssetBankCreateShapeMismatch');
    bankRef = createBankData.bank.bank_ref;
    bankVersionRef = createBankData.version_ref;
    const initialDocument = template.bank_document;
    if (createBankData.bank.versions[0]?.item_count !== initialDocument.items.length
      || !await noOpaqueReferenceVisible(page, [bankRef, bankVersionRef])) throw new Error('CatAssetBankCreateUiMismatch');
    await page.getByText(`版本 ${greatestVersion(createBankData.bank.versions).version_number} · ${initialDocument.items.length} 道题`, { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 });
    stages.bank_created = 'PASS';

    failureStage = 'bank_version_saved';
    editedStem = `${initialDocument.items[0].stem}（合成浏览器版本编辑）`;
    await page.locator('.asset-item textarea').first().fill(editedStem);
    const expectedBankVersion = greatestVersion(createBankData.bank.versions).version_number + 1;
    const { data: versionData } = await waitResponse(
      page, 'POST', `${API_PREFIX}/banks/${bankRef}/versions`, payload.backend_url, 200, 'CatAssetBankVersionFailed',
      () => page.getByRole('button', { name: '保存新版本', exact: true }).click(),
    );
    if (!validCatBankWrite(versionData) || versionData.bank.bank_ref !== bankRef
      || versionData.bank.revision !== createBankData.bank.revision + 1
      || greatestVersion(versionData.bank.versions)?.version_number !== expectedBankVersion
      || !versionData.bank.versions.some((version) => version.version_ref === versionData.version_ref)) throw new Error('CatAssetBankVersionShapeMismatch');
    bankVersionRef = versionData.version_ref;
    if (!await noOpaqueReferenceVisible(page, [bankRef, bankVersionRef])) throw new Error('CatAssetReferenceRendered');
    await page.getByText(`版本 ${expectedBankVersion} · ${initialDocument.items.length} 道题`, { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 });
    stages.bank_version_saved = 'PASS';

    failureStage = 'plan_created';
    await page.getByRole('button', { name: 'CAT 方案', exact: true }).click();
    await page.getByRole('button', { name: '新建', exact: true }).click();
    createdPlanName = `合成浏览器方案${new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)}`;
    await page.getByLabel('方案名称').fill(createdPlanName);
    const bankVersionSelect = page.getByLabel('绑定的题库');
    await page.waitForFunction((ref) => [...document.querySelectorAll('.asset-editor select option')].some((option) => option.value === ref), bankVersionRef, { timeout: 30000 });
    await bankVersionSelect.selectOption(bankVersionRef);
    await page.getByText(new RegExp(`固定绑定：${expectedBankVersion} · ${initialDocument.items.length} 道合成题`)).waitFor({ state: 'visible', timeout: 10000 });
    const initialMaxItems = template.config_document.max_items;
    if (initialMaxItems < template.config_document.min_items || initialMaxItems > initialDocument.items.length) throw new Error('SyntheticTemplateConfigIncompatible');
    const { data: createPlanData, response: createPlanResponse } = await waitResponse(
      page, 'POST', `${API_PREFIX}/plans`, payload.backend_url, 201, 'CatAssetPlanCreateFailed',
      () => page.getByRole('button', { name: '创建方案', exact: true }).click(),
    );
    if (!validCatPlanWrite(createPlanData, createdPlanName) || createPlanData.plan.versions.length !== 1) throw new Error('CatAssetPlanCreateShapeMismatch');
    planRef = createPlanData.plan.plan_ref;
    planVersionRef = createPlanData.version_ref;
    let createPlanRequest;
    try { createPlanRequest = createPlanResponse.request().postDataJSON(); } catch { throw new Error('CatAssetPlanRequestUnreadable'); }
    if (createPlanRequest?.bank_version_ref !== bankVersionRef) throw new Error('CatAssetPlanBankBindingMismatch');
    if (!await noOpaqueReferenceVisible(page, [bankRef, bankVersionRef, planRef, planVersionRef])) throw new Error('CatAssetReferenceRendered');
    stages.plan_created = 'PASS';

    failureStage = 'plan_version_saved';
    chosenMaxItems = Math.min(6, initialDocument.items.length);
    if (chosenMaxItems < template.config_document.min_items || chosenMaxItems >= initialMaxItems) {
      chosenMaxItems = initialMaxItems - 1;
    }
    if (chosenMaxItems < template.config_document.min_items || chosenMaxItems >= initialMaxItems) throw new Error('NoValidMaxItemsEdit');
    await page.getByLabel('最多题数').fill(String(chosenMaxItems));
    const expectedPlanVersion = greatestVersion(createPlanData.plan.versions).version_number + 1;
    const { data: planVersionData, response: planVersionResponse } = await waitResponse(
      page, 'POST', `${API_PREFIX}/plans/${planRef}/versions`, payload.backend_url, 200, 'CatAssetPlanVersionFailed',
      () => page.getByRole('button', { name: '保存方案新版本', exact: true }).click(),
    );
    if (!validCatPlanWrite(planVersionData) || planVersionData.plan.plan_ref !== planRef
      || greatestVersion(planVersionData.plan.versions)?.version_number !== expectedPlanVersion
      || !planVersionData.plan.versions.some((version) => version.version_ref === planVersionData.version_ref)) throw new Error('CatAssetPlanVersionShapeMismatch');
    let planVersionRequest;
    try { planVersionRequest = planVersionResponse.request().postDataJSON(); } catch { throw new Error('CatAssetPlanVersionRequestUnreadable'); }
    if (planVersionRequest?.bank_version_ref !== bankVersionRef
      || planVersionRequest?.config_document?.max_items !== chosenMaxItems) throw new Error('CatAssetPlanVersionRequestMismatch');
    planVersionRef = planVersionData.version_ref;
    stages.plan_version_saved = 'PASS';

    failureStage = 'history_reload_verified';
    const catalogReloadPromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', '/api/v1/school/cat-management/catalog', payload.backend_url), { timeout: 30000 },
    );
    await page.reload({ waitUntil: 'domcontentloaded' });
    const catalogReload = await catalogReloadPromise;
    if (catalogReload.status() !== 200) throw new Error('CatManagementReloadFailed');
    const { banks, plans } = await loadAssetPanel(page, payload,
      (key) => { stages[key] = 'PASS'; }, (key) => { failureStage = key; });
    if (!banks.items.some((bank) => bank.bank_ref === bankRef) || !plans.items.some((plan) => plan.plan_ref === planRef)) {
      throw new Error('CatAssetListReloadMismatch');
    }

    const bankDetailPromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', `${API_PREFIX}/banks/${bankRef}`, payload.backend_url), { timeout: 30000 },
    );
    const bankVersionReadPromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', `${API_PREFIX}/bank-versions/${bankVersionRef}`, payload.backend_url), { timeout: 30000 },
    );
    const bankRow = page.locator('.asset-list__items .asset-row').filter({ hasText: createdBankName });
    await bankRow.click();
    const bankDetailData = await verifiedResponse(await bankDetailPromise, 200, 'CatAssetBankReloadReadFailed');
    if (!validBankDetail(bankDetailData)
      || bankDetailData.bank.bank_ref !== bankRef
      || greatestVersion(bankDetailData.bank.versions)?.version_ref !== bankVersionRef) throw new Error('CatAssetBankHistoryReloadMismatch');
    const bankVersionReadData = await verifiedResponse(await bankVersionReadPromise, 200, 'CatAssetBankVersionReadFailed');
    if (!validCatBankVersion(bankVersionReadData, bankVersionRef)
      || bankVersionReadData.bank_document.items[0]?.stem !== editedStem) throw new Error('CatAssetBankDocumentReloadMismatch');
    if (await page.locator('.asset-item textarea').first().inputValue() !== editedStem) throw new Error('CatAssetBankEditorReloadMismatch');

    await page.getByRole('button', { name: 'CAT 方案', exact: true }).click();
    const planDetailPromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', `${API_PREFIX}/plans/${planRef}`, payload.backend_url), { timeout: 30000 },
    );
    const planVersionReadPromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', `${API_PREFIX}/plan-versions/${planVersionRef}`, payload.backend_url), { timeout: 30000 },
    );
    const linkedBankVersionReadPromise = page.waitForResponse(
      (response) => matchesResponse(response, 'GET', `${API_PREFIX}/bank-versions/${bankVersionRef}`, payload.backend_url), { timeout: 30000 },
    );
    const planRow = page.locator('.asset-list__items .asset-row').filter({ hasText: createdPlanName });
    await planRow.click();
    const planDetailData = await verifiedResponse(await planDetailPromise, 200, 'CatAssetPlanReloadReadFailed');
    if (!validPlanDetail(planDetailData)
      || planDetailData.plan.plan_ref !== planRef || greatestVersion(planDetailData.plan.versions)?.version_ref !== planVersionRef) {
      throw new Error('CatAssetPlanHistoryReloadMismatch');
    }
    const planVersionReadData = await verifiedResponse(await planVersionReadPromise, 200, 'CatAssetPlanVersionReadFailed');
    const linkedBankVersionReadData = await verifiedResponse(await linkedBankVersionReadPromise, 200, 'CatAssetLinkedBankVersionReadFailed');
    if (!validCatPlanVersion(planVersionReadData, planVersionRef, bankVersionRef)
      || planVersionReadData.config_document.max_items !== chosenMaxItems
      || !validCatBankVersion(linkedBankVersionReadData, bankVersionRef)) throw new Error('CatAssetPlanVersionReloadMismatch');
    const expectedBankLabel = `绑定题库为 ${createdBankName} v${expectedBankVersion}`;
    await page.getByText(expectedBankLabel, { exact: false }).waitFor({ state: 'visible', timeout: 15000 });
    await page.getByText(`版本 ${expectedPlanVersion} · ${createdBankName} v${expectedBankVersion}`, { exact: true })
      .waitFor({ state: 'visible', timeout: 10000 });
    if (await page.getByLabel('最多题数').inputValue() !== String(chosenMaxItems)) throw new Error('CatAssetPlanConfigUiMismatch');
    if (!await noOpaqueReferenceVisible(page, [bankRef, bankVersionRef, planRef, planVersionRef])) throw new Error('CatAssetReferenceRenderedAfterReload');
    stages.history_reload_verified = 'PASS';

    failureStage = 'desktop_screenshot';
    await captureScreenshot(page, payload, SCREENSHOTS[0], 1365, 900);
    screenshotFiles.push(SCREENSHOTS[0]);
    stages.desktop_screenshot = 'PASS';
    failureStage = 'mobile_screenshot';
    await captureScreenshot(page, payload, SCREENSHOTS[1], 390, 844);
    screenshotFiles.push(SCREENSHOTS[1]);
    stages.mobile_screenshot = 'PASS';
  } catch (error) {
    failure = { stage: failureStage, error_class: safeErrorClass(error) };
  } finally {
    failureStage = 'session_cleanup';
    try { stages.session_cleanup = !session || await logoutSession(session, payload.backend_url) ? 'PASS' : 'FAIL'; }
    catch { stages.session_cleanup = 'FAIL'; }
    try { if (browser) await browser.close(); } catch { stages.session_cleanup = 'FAIL'; }
    clearPayloadCredentials(payload);
    bankRef = ''; bankVersionRef = ''; planRef = ''; planVersionRef = ''; editedStem = '';
  }
  if (stages.session_cleanup !== 'PASS' && !failure) failure = { stage: 'session_cleanup', error_class: 'Error' };
  const result = summarizeCatAssetsWorkflow(stages, screenshotFiles, payload.artifact_dir, 0, failure);
  if (result.status !== 'PASS' && !result.failure) {
    const failed = UI_STAGE_KEYS.find((key) => stages[key] !== 'PASS') ?? 'session_cleanup';
    result.failure = { stage: failed, error_class: 'Error' };
  }
  return result;
}

async function main() {
  const payload = await readInput();
  if (!validCatAssetsPayload(payload)) {
    console.log(JSON.stringify({ workflow: WORKFLOW, status: 'FAIL', stages: failedStages(), screenshots: [], failure: { stage: 'specialist_login', error_class: 'Error' } }));
    return 2;
  }
  try {
    const result = await runCatAssetsWorkflow(payload);
    console.log(JSON.stringify(result));
    return result.status === 'PASS' ? 0 : 2;
  } catch {
    clearPayloadCredentials(payload);
    console.log(JSON.stringify({ workflow: WORKFLOW, status: 'FAIL', stages: failedStages(), screenshots: [], failure: { stage: 'specialist_login', error_class: 'Error' } }));
    return 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
