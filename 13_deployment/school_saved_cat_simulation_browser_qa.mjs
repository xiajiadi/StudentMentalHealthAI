import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { randomBytes, randomUUID } from 'node:crypto';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');

export const WORKSPACE = 'D:\\Projects\\.StudentMentalHealthAI-school-workspace-20261011';
export const FRONTEND_URL = 'http://127.0.0.1:4178';
export const BACKEND_URL = 'http://127.0.0.1:8088';
export const SCHOOL_REF = 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1';
export const SCREENSHOTS = [
  'specialist-saved-cat-simulation-desktop.png',
  'specialist-saved-cat-simulation-mobile.png',
];
export const SCREENSHOT_STAGES = {
  'specialist-saved-cat-simulation-desktop.png': 'desktop_screenshot',
  'specialist-saved-cat-simulation-mobile.png': 'mobile_screenshot',
};
export const UI_STAGE_KEYS = [
  'specialist_login',
  'synthetic_assets_prepared',
  'saved_version_selected',
  'simulation100_verified',
  'ui_aggregates_matched_api',
  'repeat_simulation_verified',
  'unsaved_config_ignored',
  'history_switch_clears_result',
  'desktop_screenshot',
  'mobile_screenshot',
  'session_cleanup',
];
export const SETUP_SUBSTAGES = [
  'template_read', 'template_shape',
  'bank_create', 'bank_create_shape',
  'plan_create', 'plan_create_shape',
  'plan_version_create', 'plan_version_create_shape',
  'bank_version_read', 'bank_version_shape',
  'plan_version1_read', 'plan_version1_shape',
  'plan_version2_read', 'plan_version2_shape',
];
export const SELECTION_SUBSTAGES = [
  'route_heading', 'assets_panel_open', 'template_response', 'plan_tab_open',
  'plan_row_visible', 'plan_detail_response', 'history_versions_verified',
  'history_row_visible', 'version_responses', 'binding_label',
];
export const AGGREGATE_SUBSTAGES = [
  'result_visible', 'metric_snapshot', 'metric_shape', 'metric_values',
  'stop_distribution', 'binding_labels', 'opaque_reference_check',
];
export const SETUP_EXPECTED_HTTP_STATUS = {
  template_read: 200,
  bank_create: 201,
  plan_create: 201,
  plan_version_create: 200,
  bank_version_read: 200,
  plan_version1_read: 200,
  plan_version2_read: 200,
};
export const SCREENSHOT_MASK_SELECTORS = [
  '.account-menu',
  'input, textarea, select',
];
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError',
  'ProtocolError', 'TargetClosedError', 'SavedCatResponseError',
];

const WORKFLOW = 'school-saved-cat-simulation';
const SPECIALIST_SLOT = 'alpha.psychological_specialist';
const METRIC_KEYS = ['bias', 'rmse', 'mae', 'mean_test_length', 'median_test_length', 'mean_se'];
const STOP_LABELS = {
  SE_THRESHOLD_REACHED: '达到停止阈值',
  MAX_ITEMS_REACHED: '达到最多题数',
  ITEM_BANK_EXHAUSTED: '题库题目已用尽',
  MANUAL_TERMINATION: '手动结束',
  ERROR: '运行错误',
  NOT_STOPPED: '未停止',
};
const METRIC_LABELS = {
  bias: '偏差',
  rmse: '均方根误差',
  mae: '平均绝对误差',
  mean_test_length: '平均题数',
  median_test_length: '中位题数',
  mean_se: '平均标准误',
};
const failedStages = () => Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));
const isRecord = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (value, keys) => isRecord(value)
  && Object.keys(value).sort().join('|') === [...keys].sort().join('|');
const isText = (value) => typeof value === 'string' && value.trim().length > 0;
const isFiniteNumber = (value, minimum = -Infinity) => typeof value === 'number' && Number.isFinite(value) && value >= minimum;
const responseData = (envelope) => envelope?.data?.data ?? envelope?.data;

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

export function validSavedCatSimulationPayload(payload) {
  if (!exactKeys(payload, ['artifact_dir', 'backend_url', 'credentials', 'frontend_url'])
    || payload.frontend_url !== FRONTEND_URL || payload.backend_url !== BACKEND_URL
    || typeof payload.artifact_dir !== 'string' || !isWithinArtifactRun(payload.artifact_dir)) return false;
  const credentials = payload.credentials;
  if (!exactKeys(credentials, [SPECIALIST_SLOT])) return false;
  const account = credentials[SPECIALIST_SLOT];
  return exactKeys(account, ['password', 'username'])
    && typeof account.username === 'string'
    && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(account.username)
    && typeof account.password === 'string'
    && account.password.length >= 16 && account.password.length <= 512;
}

export function savedCatApiRequestPayload({ base, method, endpoint, body, idempotencyKey }) {
  return { base, method, endpoint, body, idempotencyKey };
}

export function validSavedPlanVersion(value) {
  return exactKeys(value, [
    'engineering_only', 'psychological_interpretation_allowed', 'version', 'bank_version_ref', 'config_document',
  ])
    && value.engineering_only === true
    && value.psychological_interpretation_allowed === false
    && exactKeys(value.version, ['version_ref', 'version_number', 'created_at'])
    && /^CPVER_[A-Za-z0-9-]{36}$/.test(value.version.version_ref)
    && Number.isSafeInteger(value.version.version_number) && value.version.version_number > 0
    && isText(value.bank_version_ref) && /^CBVER_[A-Za-z0-9-]{36}$/.test(value.bank_version_ref)
    && isRecord(value.config_document)
    && Number.isSafeInteger(value.config_document.seed)
    && Number.isSafeInteger(value.config_document.min_items) && value.config_document.min_items >= 1
    && Number.isSafeInteger(value.config_document.max_items)
    && value.config_document.max_items >= value.config_document.min_items
    && value.config_document.max_items <= 100;
}

export function validSavedSimulation(value, expected) {
  if (!exactKeys(value, [
    'engineering_only', 'psychological_interpretation_allowed', 'plan_version_ref', 'bank_version_ref',
    'item_bank_id', 'item_bank_version', 'config_version', 'n_examinees', 'seed', 'metrics',
    'stopping_reason_distribution',
  ]) || value.engineering_only !== true || value.psychological_interpretation_allowed !== false
    || value.plan_version_ref !== expected.planVersionRef
    || value.bank_version_ref !== expected.bankVersionRef
    || value.item_bank_id !== expected.itemBankId
    || value.item_bank_version !== expected.itemBankVersion
    || value.config_version !== expected.configVersion
    || value.n_examinees !== 100 || value.seed !== expected.seed
    || !exactKeys(value.metrics, METRIC_KEYS)
    || !isRecord(value.stopping_reason_distribution)) return false;
  if (!METRIC_KEYS.every((key) => isFiniteNumber(value.metrics[key], key === 'bias' ? -Infinity : 0))) return false;
  if (value.metrics.mean_test_length <= 0 || value.metrics.median_test_length <= 0
    || value.metrics.mean_test_length > expected.maxItems
    || value.metrics.median_test_length > expected.maxItems) return false;
  const stops = Object.entries(value.stopping_reason_distribution);
  return stops.length > 0
    && stops.every(([reason, count]) => Object.hasOwn(STOP_LABELS, reason) && Number.isSafeInteger(count) && count >= 0)
    && stops.reduce((sum, [, count]) => sum + count, 0) === 100;
}

export function summarizeSavedSimulationWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null) {
  const stagesValid = isRecord(stages)
    && Object.keys(stages).length === UI_STAGE_KEYS.length
    && UI_STAGE_KEYS.every((key) => Object.hasOwn(stages, key) && ['PASS', 'FAIL'].includes(stages[key]));
  const safeStages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [
    key, stagesValid && stages[key] === 'PASS' ? 'PASS' : 'FAIL',
  ]));
  const namesValid = Array.isArray(screenshotFiles)
    && screenshotFiles.length === SCREENSHOTS.length
    && new Set(screenshotFiles).size === SCREENSHOTS.length
    && SCREENSHOTS.every((name) => screenshotFiles.includes(name));
  for (const [name, stage] of Object.entries(SCREENSHOT_STAGES)) {
    let present = false;
    try { present = namesValid && require('node:fs').statSync(path.join(artifactDir, name)).isFile(); } catch { /* fixed failure */ }
    if (!present) safeStages[stage] = 'FAIL';
  }
  const passed = runnerExitCode === 0 && stagesValid && namesValid
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
  const diagnostic = failure?.stage === 'synthetic_assets_prepared' ? failure.setup_diagnostic : null;
  if (exactSetupDiagnostic(diagnostic)) {
    result.diagnostics = {
      stage: 'synthetic_assets_prepared',
      substage: diagnostic.substage,
      http_status: diagnostic.http_status,
    };
  }
  const selectionDiagnostic = failure?.stage === 'saved_version_selected' ? failure.selection_diagnostic : null;
  if (exactSelectionDiagnostic(selectionDiagnostic)) {
    result.diagnostics = {
      stage: 'saved_version_selected',
      substage: selectionDiagnostic.substage,
      http_status: selectionDiagnostic.http_status,
    };
  }
  const aggregateDiagnostic = failure && [
    'ui_aggregates_matched_api', 'repeat_simulation_verified', 'unsaved_config_ignored',
  ].includes(failure.stage) ? failure.aggregate_diagnostic : null;
  if (exactAggregateDiagnostic(aggregateDiagnostic)) {
    result.diagnostics = {
      stage: failure.stage,
      substage: aggregateDiagnostic.substage,
    };
  }
  return result;
}

function exactSetupDiagnostic(value) {
  return exactKeys(value, ['substage', 'http_status'])
    && SETUP_SUBSTAGES.includes(value.substage)
    && Number.isInteger(value.http_status) && value.http_status >= 0 && value.http_status <= 599;
}

function exactSelectionDiagnostic(value) {
  return exactKeys(value, ['substage', 'http_status'])
    && SELECTION_SUBSTAGES.includes(value.substage)
    && Number.isInteger(value.http_status) && value.http_status >= 0 && value.http_status <= 599;
}

function exactAggregateDiagnostic(value) {
  return exactKeys(value, ['substage']) && AGGREGATE_SUBSTAGES.includes(value.substage);
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
  try {
    const url = new URL(response.url());
    return url.origin === backendUrl && url.pathname === pathname && response.request().method() === method;
  } catch { return false; }
};

export function preservePendingWaitFailure(promise) {
  void promise.catch(() => undefined);
  return promise;
}

export function waitForResponseHandled(page, predicate, options) {
  return preservePendingWaitFailure(page.waitForResponse(predicate, options));
}

async function apiActor(page, backendUrl) {
  return page.evaluate(async (base) => {
    const response = await fetch(`${base}/api/v1/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' } });
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
      const choices = await picker.locator('option:not([disabled])').evaluateAll((items) => items.map((item) => item.value));
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

function setSetupDiagnostic(diagnostic, substage, httpStatus = 0) {
  if (!diagnostic || !SETUP_SUBSTAGES.includes(substage)) return;
  diagnostic.substage = substage;
  diagnostic.http_status = Number.isInteger(httpStatus) && httpStatus >= 0 && httpStatus <= 599 ? httpStatus : 0;
}

async function apiRequest(
  page, backendUrl, method, endpoint, body = undefined, idempotencyKey = undefined,
  expectedStatus = method === 'GET' ? 200 : 201, setupDiagnostic = null, setupSubstage = null,
) {
  if (setupSubstage) setSetupDiagnostic(setupDiagnostic, setupSubstage);
  const result = await page.evaluate(async ({ base, method: verb, endpoint: pathName, body: input, idempotencyKey }) => {
    try {
      const headers = { Accept: 'application/json' };
      if (verb !== 'GET') {
        const csrfResponse = await fetch(`${base}/api/v1/auth/csrf`, { credentials: 'include', headers: { Accept: 'application/json' } });
        if (!csrfResponse.ok) return { status: csrfResponse.status, envelope: null };
        const csrfEnvelope = await csrfResponse.json();
        const token = csrfEnvelope?.data?.csrf_token;
        if (typeof token !== 'string' || !token) return { status: 0, envelope: null };
        headers['Content-Type'] = 'application/json';
        headers['X-CSRF-Token'] = token;
        headers['Idempotency-Key'] = idempotencyKey;
      }
      const response = await fetch(`${base}${pathName}`, {
        method: verb,
        credentials: 'include',
        headers,
        ...(input === undefined ? {} : { body: JSON.stringify(input) }),
      });
      let envelope = null;
      try { envelope = await response.json(); } catch { /* fixed error below */ }
      return { status: response.status, envelope };
    } catch {
      return { status: 0, envelope: null };
    }
  }, savedCatApiRequestPayload({ base: backendUrl, method, endpoint, body, idempotencyKey }));
  if (setupSubstage) setSetupDiagnostic(setupDiagnostic, setupSubstage, result?.status ?? 0);
  if (!result || result.status !== expectedStatus || !isRecord(result.envelope)) {
    result.envelope = null;
    throw new Error('SavedCatApiRequestFailed');
  }
  const data = responseData(result.envelope);
  result.envelope = null;
  if (!isRecord(data)) throw new Error('SavedCatApiShapeMismatch');
  return data;
}

function validEngineeringTemplate(value) {
  return exactKeys(value, ['engineering_only', 'psychological_interpretation_allowed', 'bank_document', 'config_document', 'item_count', 'dimension_count'])
    && value.engineering_only === true && value.psychological_interpretation_allowed === false
    && isRecord(value.bank_document) && value.bank_document.metadata?.synthetic === true
    && value.bank_document.metadata?.psychological_interpretation_allowed === false
    && Array.isArray(value.bank_document.items) && value.bank_document.items.length >= 4
    && value.item_count === value.bank_document.items.length
    && Number.isSafeInteger(value.dimension_count) && value.dimension_count === 1
    && isRecord(value.config_document)
    && Number.isSafeInteger(value.config_document.seed) && value.config_document.seed >= 0
    && Number.isSafeInteger(value.config_document.min_items) && value.config_document.min_items >= 1
    && Number.isSafeInteger(value.config_document.max_items)
    && value.config_document.max_items <= value.bank_document.items.length;
}

function savedAssetName(label) {
  return `浏览器合成${label}-${randomBytes(4).toString('hex')}`;
}

async function prepareSyntheticSavedVersions(page, backendUrl, diagnostic) {
  const template = await apiRequest(
    page, backendUrl, 'GET', '/api/v1/school/cat-assets/template',
    undefined, undefined, SETUP_EXPECTED_HTTP_STATUS.template_read, diagnostic, 'template_read',
  );
  setSetupDiagnostic(diagnostic, 'template_shape', SETUP_EXPECTED_HTTP_STATUS.template_read);
  if (!validEngineeringTemplate(template)) throw new Error('SavedCatTemplateMismatch');
  const suffix = randomBytes(4).toString('hex');
  const bankName = `浏览器合成题库-${suffix}`;
  const bankWrite = await apiRequest(
    page, backendUrl, 'POST', '/api/v1/school/cat-assets/banks',
    { display_name: bankName, bank_document: template.bank_document }, `saved-cat-browser-bank-${randomUUID()}`,
    SETUP_EXPECTED_HTTP_STATUS.bank_create, diagnostic, 'bank_create',
  );
  setSetupDiagnostic(diagnostic, 'bank_create_shape', SETUP_EXPECTED_HTTP_STATUS.bank_create);
  const bankRef = bankWrite?.bank?.bank_ref;
  const bankVersionRef = bankWrite?.version_ref;
  if (bankWrite.engineering_only !== true || bankWrite.psychological_interpretation_allowed !== false
    || typeof bankRef !== 'string' || !/^CBANK_[A-Za-z0-9-]{36}$/.test(bankRef)
    || typeof bankVersionRef !== 'string' || !/^CBVER_[A-Za-z0-9-]{36}$/.test(bankVersionRef)
    || bankWrite.bank?.display_name !== bankName) {
    throw new Error('SavedCatBankCreateMismatch');
  }
  const planName = `浏览器合成方案-${suffix}`;
  const configV1 = { ...template.config_document, min_items: 3, max_items: 3, se_threshold: 0.001 };
  const planWrite = await apiRequest(
    page, backendUrl, 'POST', '/api/v1/school/cat-assets/plans',
    { display_name: planName, bank_version_ref: bankVersionRef, config_document: configV1 }, `saved-cat-browser-plan-${randomUUID()}`,
    SETUP_EXPECTED_HTTP_STATUS.plan_create, diagnostic, 'plan_create',
  );
  setSetupDiagnostic(diagnostic, 'plan_create_shape', SETUP_EXPECTED_HTTP_STATUS.plan_create);
  const planRef = planWrite?.plan?.plan_ref;
  const planVersionRef1 = planWrite?.version_ref;
  if (planWrite.engineering_only !== true || planWrite.psychological_interpretation_allowed !== false
    || typeof planRef !== 'string' || !/^CPLAN_[A-Za-z0-9-]{36}$/.test(planRef)
    || typeof planVersionRef1 !== 'string' || !/^CPVER_[A-Za-z0-9-]{36}$/.test(planVersionRef1)
    || planWrite.plan?.display_name !== planName) {
    throw new Error('SavedCatPlanCreateMismatch');
  }
  const configV2 = { ...configV1, max_items: 4 };
  const planVersionWrite = await apiRequest(
    page, backendUrl, 'POST', `/api/v1/school/cat-assets/plans/${planRef}/versions`,
    { expected_revision: 1, bank_version_ref: bankVersionRef, config_document: configV2 }, `saved-cat-browser-version-${randomUUID()}`,
    SETUP_EXPECTED_HTTP_STATUS.plan_version_create, diagnostic, 'plan_version_create',
  );
  setSetupDiagnostic(diagnostic, 'plan_version_create_shape', SETUP_EXPECTED_HTTP_STATUS.plan_version_create);
  const planVersionRef2 = planVersionWrite?.version_ref;
  if (planVersionWrite.engineering_only !== true || planVersionWrite.psychological_interpretation_allowed !== false
    || typeof planVersionRef2 !== 'string' || !/^CPVER_[A-Za-z0-9-]{36}$/.test(planVersionRef2)
    || planVersionRef2 === planVersionRef1) throw new Error('SavedCatPlanVersionCreateMismatch');

  const bankVersion = await apiRequest(
    page, backendUrl, 'GET', `/api/v1/school/cat-assets/bank-versions/${bankVersionRef}`,
    undefined, undefined, SETUP_EXPECTED_HTTP_STATUS.bank_version_read, diagnostic, 'bank_version_read',
  );
  setSetupDiagnostic(diagnostic, 'bank_version_shape', SETUP_EXPECTED_HTTP_STATUS.bank_version_read);
  const bankVersionNumber = bankVersion?.version?.version_number;
  const itemBankId = bankVersion?.bank_document?.item_bank_id;
  const itemBankVersion = bankVersion?.bank_document?.version;
  if (bankVersion.engineering_only !== true || bankVersion.psychological_interpretation_allowed !== false
    || bankVersion?.version?.version_ref !== bankVersionRef || bankVersionNumber !== 1
    || typeof itemBankId !== 'string' || typeof itemBankVersion !== 'string'
    || bankVersion.bank_document?.metadata?.synthetic !== true
    || !Array.isArray(bankVersion.bank_document.items)
    || bankVersion.bank_document.items.length !== template.item_count) throw new Error('SavedCatBankVersionReadMismatch');
  const planV1 = await apiRequest(
    page, backendUrl, 'GET', `/api/v1/school/cat-assets/plan-versions/${planVersionRef1}`,
    undefined, undefined, SETUP_EXPECTED_HTTP_STATUS.plan_version1_read, diagnostic, 'plan_version1_read',
  );
  setSetupDiagnostic(diagnostic, 'plan_version1_shape', SETUP_EXPECTED_HTTP_STATUS.plan_version1_read);
  const planV2 = await apiRequest(
    page, backendUrl, 'GET', `/api/v1/school/cat-assets/plan-versions/${planVersionRef2}`,
    undefined, undefined, SETUP_EXPECTED_HTTP_STATUS.plan_version2_read, diagnostic, 'plan_version2_read',
  );
  setSetupDiagnostic(diagnostic, 'plan_version2_shape', SETUP_EXPECTED_HTTP_STATUS.plan_version2_read);
  if (!validSavedPlanVersion(planV1) || !validSavedPlanVersion(planV2)
    || planV1.version.version_ref !== planVersionRef1 || planV2.version.version_ref !== planVersionRef2
    || planV1.bank_version_ref !== bankVersionRef || planV2.bank_version_ref !== bankVersionRef
    || planV1.config_document.min_items !== 3 || planV1.config_document.max_items !== 3
    || planV1.config_document.se_threshold !== 0.001 || planV2.config_document.max_items !== 4) {
    throw new Error('SavedCatPlanVersionReadMismatch');
  }
  const prepared = {
    bankName,
    bankRef,
    bankVersionRef,
    bankVersionNumber,
    itemBankId,
    itemBankVersion,
    planName,
    planRef,
    planVersionRef1,
    planVersionRef2,
    configV1,
    configV2,
    configVersion1: planV1.config_document.config_version,
    configVersion2: planV2.config_document.config_version,
    maxItems1: planV1.config_document.max_items,
    maxItems2: planV2.config_document.max_items,
    seed: planV1.config_document.seed,
  };
  template.bank_document = null;
  template.config_document = null;
  bankVersion.bank_document = null;
  planV1.config_document = null;
  planV2.config_document = null;
  return prepared;
}

async function selectSavedPlanVersion(page, payload, prepared, planVersionRef, number, diagnostic) {
  diagnostic.substage = 'history_row_visible';
  const detailPromise = waitForResponseHandled(page,
    (response) => responseMatches(response, 'GET', `/api/v1/school/cat-assets/plan-versions/${planVersionRef}`, payload.backend_url),
    { timeout: 20000 },
  );
  const bankPromise = waitForResponseHandled(page,
    (response) => responseMatches(response, 'GET', `/api/v1/school/cat-assets/bank-versions/${prepared.bankVersionRef}`, payload.backend_url),
    { timeout: 20000 },
  );
  const row = page.locator('.asset-history__row').filter({ hasText: new RegExp(`版本\\s*${number}(?:\\s|·)`) });
  await row.waitFor({ state: 'visible', timeout: 12000 });
  await row.click();
  diagnostic.substage = 'version_responses';
  const [planResponse, bankResponse] = await Promise.all([detailPromise, bankPromise]);
  diagnostic.http_status = planResponse.status();
  if (planResponse.status() !== 200) throw new Error('SavedCatHistoryReadFailed');
  diagnostic.http_status = bankResponse.status();
  if (planResponse.status() !== 200 || bankResponse.status() !== 200) throw new Error('SavedCatHistoryReadFailed');
  const planData = responseData(await planResponse.json());
  const bankData = responseData(await bankResponse.json());
  if (!validSavedPlanVersion(planData) || planData.version.version_ref !== planVersionRef
    || planData.bank_version_ref !== prepared.bankVersionRef
    || !exactKeys(bankData, ['engineering_only', 'psychological_interpretation_allowed', 'version', 'bank_document'])
    || bankData.version?.version_ref !== prepared.bankVersionRef
    || bankData.bank_document?.item_bank_id !== prepared.itemBankId
    || bankData.bank_document?.version !== prepared.itemBankVersion) throw new Error('SavedCatHistoryBindingMismatch');
  planData.config_document = null;
  bankData.bank_document = null;
  diagnostic.substage = 'binding_label';
  await page.getByText(`已选择 ${prepared.planName} v${number}`, { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
  const binding = await page.locator('.asset-simulation__binding').textContent();
  if (!binding?.includes(`${prepared.planName} v${number}`)
    || !binding.includes(`${prepared.bankName} v${prepared.bankVersionNumber}`)
    || binding.includes(planVersionRef) || binding.includes(prepared.bankVersionRef)) throw new Error('SavedCatVersionLabelMismatch');
}

function validSimulationResponse(value, prepared, planVersionRef, configVersion) {
  return validSavedSimulation(value, {
    planVersionRef,
    bankVersionRef: prepared.bankVersionRef,
    itemBankId: prepared.itemBankId,
    itemBankVersion: prepared.itemBankVersion,
    configVersion,
    seed: prepared.seed,
    maxItems: planVersionRef === prepared.planVersionRef1 ? prepared.maxItems1 : prepared.maxItems2,
  });
}

async function readSimulationResponse(response, prepared, planVersionRef, configVersion) {
  if (response.status() !== 200) throw new Error('SavedCatSimulationHttpFailure');
  let value = responseData(await response.json());
  if (!validSimulationResponse(value, prepared, planVersionRef, configVersion)) {
    value = null;
    throw new Error('SavedCatSimulationShapeMismatch');
  }
  const request = response.request();
  const requestPath = new URL(request.url()).pathname;
  let requestBody = null;
  try { requestBody = request.postDataJSON(); } catch { /* fixed validation failure below */ }
  if (request.method() !== 'POST' || requestPath !== `/api/v1/school/cat-assets/plan-versions/${planVersionRef}/simulations`
    || !exactKeys(requestBody, ['n_examinees']) || requestBody.n_examinees !== 100) {
    value = null;
    requestBody = null;
    throw new Error('SavedCatSimulationRequestMismatch');
  }
  requestBody = null;
  return value;
}

const sortedEntries = (value) => Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
const sameAggregates = (left, right) => JSON.stringify(sortedEntries(left.metrics)) === JSON.stringify(sortedEntries(right.metrics))
  && JSON.stringify(sortedEntries(left.stopping_reason_distribution)) === JSON.stringify(sortedEntries(right.stopping_reason_distribution));

export function aggregateUiMismatch(snapshot, simulation, prepared, planVersionNumber) {
  if (!exactKeys(snapshot, ['metrics', 'stops', 'bindingText', 'resultText'])
    || !Array.isArray(snapshot.metrics) || !Array.isArray(snapshot.stops)
    || typeof snapshot.bindingText !== 'string' || typeof snapshot.resultText !== 'string') return 'metric_snapshot';
  const byLabel = Object.create(null);
  for (const row of snapshot.metrics) {
    if (!exactKeys(row, ['label', 'value']) || typeof row.label !== 'string' || typeof row.value !== 'string'
      || Object.hasOwn(byLabel, row.label)) return 'metric_shape';
    byLabel[row.label] = row.value;
  }
  if (snapshot.metrics.length !== METRIC_KEYS.length
    || Object.keys(byLabel).length !== METRIC_KEYS.length
    || METRIC_KEYS.some((key) => !Object.hasOwn(byLabel, METRIC_LABELS[key]))) return 'metric_shape';
  for (const key of METRIC_KEYS) {
    const digits = key === 'mean_test_length' || key === 'median_test_length' ? 2 : 3;
    if (Number(byLabel[METRIC_LABELS[key]]) !== Number(simulation.metrics[key].toFixed(digits))) return 'metric_values';
  }
  const actualStops = snapshot.stops.map((value) => typeof value === 'string'
    ? value.trimStart().replace(/^(?:·\s*)+/, '').trim()
    : '');
  const expectedStops = Object.entries(simulation.stopping_reason_distribution)
    .map(([key, count]) => `${STOP_LABELS[key]} ${count}`).sort();
  if (actualStops.length !== expectedStops.length
    || actualStops.some((value) => !value)
    || JSON.stringify(actualStops.sort()) !== JSON.stringify(expectedStops)) return 'stop_distribution';
  if (!snapshot.bindingText.includes(`${prepared.planName} v${planVersionNumber}`)
    || !snapshot.bindingText.includes(`${prepared.bankName} v${prepared.bankVersionNumber}`)
    || snapshot.bindingText.includes(prepared.planVersionRef1) || snapshot.bindingText.includes(prepared.planVersionRef2)
    || snapshot.bindingText.includes(prepared.bankVersionRef)) return 'binding_labels';
  return null;
}

export function extractAggregateUiResult(element) {
  return {
    metrics: [...element.querySelectorAll('dl > div')].map((row) => ({
      label: row.querySelector('dt')?.textContent?.trim() ?? '',
      value: row.querySelector('dd')?.textContent?.trim() ?? '',
    })),
    stops: [...element.querySelectorAll('p:first-of-type span')].map((span) => span.textContent?.trim() ?? ''),
    resultText: element.textContent ?? '',
  };
}

async function assertAggregateUi(page, simulation, prepared, planVersionNumber, diagnostic) {
  diagnostic.substage = 'result_visible';
  const root = page.locator('.asset-simulation__result');
  await root.waitFor({ state: 'visible', timeout: 30000 });
  diagnostic.substage = 'metric_snapshot';
  const visible = await root.evaluate(extractAggregateUiResult);
  const bindingText = await page.locator('.asset-simulation__binding').textContent() ?? '';
  const mismatch = aggregateUiMismatch({ ...visible, bindingText }, simulation, prepared, planVersionNumber);
  if (mismatch) {
    diagnostic.substage = mismatch;
    throw new Error('SavedCatAggregateUiMismatch');
  }
  diagnostic.substage = 'opaque_reference_check';
  const pageText = await page.locator('body').innerText();
  if (/\b(?:CPVER|CBVER|CPLAN|CBANK)_[A-Za-z0-9-]{20,}\b/.test(pageText)) throw new Error('OpaqueAssetReferenceVisible');
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

async function logoutSession(session, backendUrl) {
  let logoutOk = !session.loginSubmitted;
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
  try { await session.context.close(); } catch { logoutOk = false; }
  return logoutOk;
}

function clearPayloadCredentials(payload) {
  const account = payload?.credentials?.[SPECIALIST_SLOT];
  if (account && typeof account === 'object') {
    account.username = '';
    account.password = '';
  }
  if (payload && typeof payload === 'object') payload.credentials = undefined;
}

async function runSavedSimulationWorkflow(payload, { chromium: browserLauncher = chromium } = {}) {
  const stages = failedStages();
  const screenshotFiles = [];
  let simulationResponseCount = 0;
  let browser = null;
  let session = null;
  let failure = null;
  let failureStage = 'specialist_login';
  let prepared = null;
  let first = null;
  let second = null;
  let unsavedCheck = null;
  const setupDiagnostic = { substage: 'template_read', http_status: 0 };
  const selectionDiagnostic = { substage: 'route_heading', http_status: 0 };
  const aggregateDiagnostic = { substage: 'result_visible' };
  try {
    browser = await browserLauncher.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    session = { context, page: await context.newPage(), loginSubmitted: false };
    await loginSpecialist(session, payload);
    stages.specialist_login = 'PASS';

    failureStage = 'synthetic_assets_prepared';
    prepared = await prepareSyntheticSavedVersions(session.page, payload.backend_url, setupDiagnostic);
    stages.synthetic_assets_prepared = 'PASS';

    failureStage = 'saved_version_selected';
    await session.page.goto(`${payload.frontend_url}/specialist/cat`, { waitUntil: 'domcontentloaded' });
    await session.page.getByRole('heading', { name: '测评方案与模拟', exact: true }).waitFor({ state: 'visible', timeout: 20000 });
    selectionDiagnostic.substage = 'assets_panel_open';
    const templateResponse = waitForResponseHandled(session.page,
      (response) => responseMatches(response, 'GET', '/api/v1/school/cat-assets/template', payload.backend_url),
      { timeout: 20000 },
    );
    await session.page.getByRole('button', { name: '题库与方案', exact: true }).click();
    selectionDiagnostic.substage = 'template_response';
    const assetsTemplate = await templateResponse;
    selectionDiagnostic.http_status = assetsTemplate.status();
    if (assetsTemplate.status() !== 200) throw new Error('SavedCatAssetsPanelFailed');
    selectionDiagnostic.substage = 'plan_tab_open';
    await session.page.getByRole('button', { name: 'CAT 方案', exact: true }).click();
    session.page.on('response', (response) => {
      if (responseMatches(
        response,
        'POST',
        `/api/v1/school/cat-assets/plan-versions/${prepared.planVersionRef1}/simulations`,
        payload.backend_url,
      )) simulationResponseCount += 1;
    });
    const planDetailPromise = waitForResponseHandled(session.page,
      (response) => responseMatches(response, 'GET', `/api/v1/school/cat-assets/plans/${prepared.planRef}`, payload.backend_url),
      { timeout: 20000 },
    );
    selectionDiagnostic.substage = 'plan_row_visible';
    const planRow = session.page.locator('.asset-list__items .asset-row').filter({ hasText: prepared.planName });
    await planRow.waitFor({ state: 'visible', timeout: 12000 });
    await planRow.click();
    selectionDiagnostic.substage = 'plan_detail_response';
    const planDetailResponse = await planDetailPromise;
    selectionDiagnostic.http_status = planDetailResponse.status();
    if (planDetailResponse.status() !== 200) throw new Error('SavedCatPlanDetailFailed');
    const planDetail = responseData(await planDetailResponse.json());
    const historyRefs = planDetail?.plan?.versions?.map((item) => item.version_ref) ?? [];
    if (!historyRefs.includes(prepared.planVersionRef1) || !historyRefs.includes(prepared.planVersionRef2)) {
      throw new Error('SavedCatHistoryMissingPreparedVersions');
    }
    selectionDiagnostic.substage = 'history_versions_verified';
    planDetail.plan.versions = null;
    await selectSavedPlanVersion(session.page, payload, prepared, prepared.planVersionRef1, 1, selectionDiagnostic);
    stages.saved_version_selected = 'PASS';

    failureStage = 'simulation100_verified';
    const simulationPath1 = `/api/v1/school/cat-assets/plan-versions/${prepared.planVersionRef1}/simulations`;
    const firstPromise = waitForResponseHandled(session.page,
      (response) => responseMatches(response, 'POST', simulationPath1, payload.backend_url),
      { timeout: 600000 },
    );
    await session.page.locator('.asset-simulation__batch select').selectOption('100');
    await session.page.getByRole('button', { name: '运行已保存版本', exact: true }).click();
    await session.page.getByText('运行中，较大批次可能需要几分钟。', { exact: true }).waitFor({ state: 'visible', timeout: 10000 });
    if (!(await session.page.locator('.asset-simulation__batch select').isDisabled())
      || !(await session.page.locator('.asset-simulation .asset-button--primary').isDisabled())) {
      throw new Error('SavedCatPendingControlsUnlocked');
    }
    const firstResponse = await firstPromise;
    first = await readSimulationResponse(firstResponse, prepared, prepared.planVersionRef1, prepared.configVersion1);
    stages.simulation100_verified = 'PASS';

    failureStage = 'ui_aggregates_matched_api';
    await assertAggregateUi(session.page, first, prepared, 1, aggregateDiagnostic);
    stages.ui_aggregates_matched_api = 'PASS';

    failureStage = 'repeat_simulation_verified';
    const secondPromise = waitForResponseHandled(session.page,
      (response) => responseMatches(response, 'POST', simulationPath1, payload.backend_url),
      { timeout: 600000 },
    );
    await session.page.getByRole('button', { name: '再次运行并比较', exact: true }).click();
    const secondResponse = await secondPromise;
    second = await readSimulationResponse(secondResponse, prepared, prepared.planVersionRef1, prepared.configVersion1);
    if (!sameAggregates(first, second)) throw new Error('SavedCatRepeatAggregateMismatch');
    await assertAggregateUi(session.page, second, prepared, 1, aggregateDiagnostic);
    await session.page.getByText('本次与上次运行的汇总结果相同。仅在方案版本、题库版本、样本量和种子一致时比较。', { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 });
    stages.repeat_simulation_verified = 'PASS';

    failureStage = 'desktop_screenshot';
    await captureScreenshot(session.page, payload, SCREENSHOTS[0], 1365, 900);
    screenshotFiles.push(SCREENSHOTS[0]);
    stages.desktop_screenshot = 'PASS';
    failureStage = 'mobile_screenshot';
    await captureScreenshot(session.page, payload, SCREENSHOTS[1], 390, 844);
    screenshotFiles.push(SCREENSHOTS[1]);
    stages.mobile_screenshot = 'PASS';

    failureStage = 'unsaved_config_ignored';
    const maxItemsInput = session.page.locator('.asset-config-grid label').filter({ hasText: '最多题数' }).locator('input');
    await maxItemsInput.fill('2');
    if ((await maxItemsInput.inputValue()) !== '2' || await session.page.locator('.asset-simulation__result').count() !== 0) {
      throw new Error('SavedCatDraftEditDidNotClearResult');
    }
    const thirdPromise = waitForResponseHandled(session.page,
      (response) => responseMatches(response, 'POST', simulationPath1, payload.backend_url),
      { timeout: 600000 },
    );
    await session.page.getByRole('button', { name: '运行已保存版本', exact: true }).click();
    const thirdResponse = await thirdPromise;
    unsavedCheck = await readSimulationResponse(thirdResponse, prepared, prepared.planVersionRef1, prepared.configVersion1);
    if (!sameAggregates(first, unsavedCheck)
      || !validSimulationResponse(unsavedCheck, prepared, prepared.planVersionRef1, prepared.configVersion1)) {
      throw new Error('SavedCatUnsavedDraftAffectedSimulation');
    }
    if (simulationResponseCount !== 3) throw new Error('SavedCatUnexpectedRetryCount');
    await assertAggregateUi(session.page, unsavedCheck, prepared, 1, aggregateDiagnostic);
    stages.unsaved_config_ignored = 'PASS';

    failureStage = 'history_switch_clears_result';
    const switchVersionPromise = waitForResponseHandled(session.page,
      (response) => responseMatches(response, 'GET', `/api/v1/school/cat-assets/plan-versions/${prepared.planVersionRef2}`, payload.backend_url),
      { timeout: 20000 },
    );
    const secondHistoryRow = session.page.locator('.asset-history__row').filter({ hasText: /版本\s*2(?:\s|·)/ });
    await secondHistoryRow.click();
    if (await session.page.locator('.asset-simulation__result').count() !== 0) throw new Error('SavedCatHistorySwitchKeptOldResult');
    const switchedResponse = await switchVersionPromise;
    if (switchedResponse.status() !== 200) throw new Error('SavedCatHistorySwitchReadFailed');
    let switched = responseData(await switchedResponse.json());
    if (!validSavedPlanVersion(switched) || switched.version.version_ref !== prepared.planVersionRef2
      || switched.bank_version_ref !== prepared.bankVersionRef || switched.config_document.max_items !== 4) {
      throw new Error('SavedCatHistorySwitchBindingMismatch');
    }
    switched.config_document = null;
    await session.page.getByText(`已选择 ${prepared.planName} v2`, { exact: false }).waitFor({ state: 'visible', timeout: 10000 });
    const switchedBinding = await session.page.locator('.asset-simulation__binding').textContent();
    if (!switchedBinding?.includes(`${prepared.planName} v2`)
      || !switchedBinding.includes(`${prepared.bankName} v${prepared.bankVersionNumber}`)
      || switchedBinding.includes(prepared.planVersionRef2) || switchedBinding.includes(prepared.bankVersionRef)) {
      throw new Error('SavedCatHistorySwitchLabelMismatch');
    }
    stages.history_switch_clears_result = 'PASS';
  } catch (error) {
    failure = { stage: failureStage, error_class: safeExceptionClass(error) };
    if (failureStage === 'synthetic_assets_prepared') {
      failure.setup_diagnostic = { ...setupDiagnostic };
    } else if (failureStage === 'saved_version_selected') {
      failure.selection_diagnostic = { ...selectionDiagnostic };
    } else if (['ui_aggregates_matched_api', 'repeat_simulation_verified', 'unsaved_config_ignored'].includes(failureStage)) {
      failure.aggregate_diagnostic = { ...aggregateDiagnostic };
    }
  } finally {
    failureStage = 'session_cleanup';
    try { stages.session_cleanup = !session || await logoutSession(session, payload.backend_url) ? 'PASS' : 'FAIL'; }
    catch { stages.session_cleanup = 'FAIL'; }
    try { if (browser) await browser.close(); } catch { stages.session_cleanup = 'FAIL'; }
    if (prepared) {
      prepared.configV1 = null; prepared.configV2 = null;
      prepared.bankRef = null; prepared.bankVersionRef = null;
      prepared.planRef = null; prepared.planVersionRef1 = null; prepared.planVersionRef2 = null;
      prepared.itemBankId = null; prepared.itemBankVersion = null;
      prepared = null;
    }
    for (const result of [first, second, unsavedCheck]) {
      if (result) { result.metrics = null; result.stopping_reason_distribution = null; }
    }
    first = null; second = null; unsavedCheck = null;
    clearPayloadCredentials(payload);
  }
  if (stages.session_cleanup !== 'PASS' && !failure) failure = { stage: 'session_cleanup', error_class: 'Error' };
  const result = summarizeSavedSimulationWorkflow(stages, screenshotFiles, payload.artifact_dir, 0, failure);
  if (result.status !== 'PASS' && !result.failure) {
    const failed = UI_STAGE_KEYS.find((key) => stages[key] !== 'PASS') ?? 'session_cleanup';
    result.failure = { stage: failed, error_class: 'Error' };
  }
  return result;
}

async function main() {
  const payload = await readInput();
  if (!validSavedCatSimulationPayload(payload)) {
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
    const result = await runSavedSimulationWorkflow(payload);
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
