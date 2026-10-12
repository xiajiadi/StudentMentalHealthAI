import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BACKEND_URL,
  AGGREGATE_SUBSTAGES,
  FRONTEND_URL,
  SAFE_FAILURE_CLASSES,
  SCHOOL_REF,
  SETUP_EXPECTED_HTTP_STATUS,
  SETUP_SUBSTAGES,
  SELECTION_SUBSTAGES,
  SCREENSHOTS,
  SCREENSHOT_MASK_SELECTORS,
  SCREENSHOT_STAGES,
  UI_STAGE_KEYS,
  WORKSPACE,
  savedCatApiRequestPayload,
  validSavedCatSimulationPayload,
  aggregateUiMismatch,
  extractAggregateUiResult,
  validSavedPlanVersion,
  validSavedSimulation,
  preservePendingWaitFailure,
  summarizeSavedSimulationWorkflow,
} from '../school_saved_cat_simulation_browser_qa.mjs';

const artifactDir = path.join(WORKSPACE, 'browser-qa', '20261013T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
const planVersion = (number, maxItems) => ({
  engineering_only: true,
  psychological_interpretation_allowed: false,
  version: { version_ref: `CPVER_${String(number).padStart(8, 'a')}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`, version_number: number, created_at: '2026-10-13T00:00:00Z' },
  bank_version_ref: 'CBVER_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  config_document: { config_version: 'synthetic.cat.v1', min_items: 3, max_items: maxItems, seed: 20261013 },
});
const expected = {
  planVersionRef: planVersion(1, 3).version.version_ref,
  bankVersionRef: 'CBVER_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  itemBankId: 'ITEMBANK_synthetic_demo',
  itemBankVersion: 'synthetic.demo.v1',
  configVersion: 'synthetic.cat.v1',
  seed: 20261013,
  maxItems: 3,
};
const simulation = {
  engineering_only: true,
  psychological_interpretation_allowed: false,
  plan_version_ref: expected.planVersionRef,
  bank_version_ref: expected.bankVersionRef,
  item_bank_id: expected.itemBankId,
  item_bank_version: expected.itemBankVersion,
  config_version: expected.configVersion,
  n_examinees: 100,
  seed: expected.seed,
  metrics: { bias: -0.02, rmse: 0.21, mae: 0.17, mean_test_length: 3, median_test_length: 3, mean_se: 0.43 },
  stopping_reason_distribution: { SE_THRESHOLD_REACHED: 20, MAX_ITEMS_REACHED: 80 },
};
const payload = () => ({
  credentials: { 'alpha.psychological_specialist': { username: 'SYNTHETIC_ALPHA_SPECIALIST', password: 's'.repeat(24) } },
  artifact_dir: artifactDir,
  frontend_url: FRONTEND_URL,
  backend_url: BACKEND_URL,
});

test('payload accepts only the sealed synthetic specialist and fixed local origins', () => {
  assert.equal(validSavedCatSimulationPayload(payload()), true);
  assert.equal(SCHOOL_REF, 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1');
  assert.equal(SCREENSHOTS.length, 2);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.account-menu'), true);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('input, textarea, select'), true);

  const extraRole = payload();
  extraRole.credentials['alpha.admin'] = { username: 'SYNTHETIC_ADMIN', password: 'a'.repeat(24) };
  assert.equal(validSavedCatSimulationPayload(extraRole), false);
  const externalPath = payload();
  externalPath.artifact_dir = path.join(os.tmpdir(), 'unrelated');
  assert.equal(validSavedCatSimulationPayload(externalPath), false);
  const wrongOrigin = payload();
  wrongOrigin.backend_url = 'http://127.0.0.1:9999';
  assert.equal(validSavedCatSimulationPayload(wrongOrigin), false);
  const invalidCredential = payload();
  invalidCredential.credentials['alpha.psychological_specialist'].username = 'person@example.test';
  assert.equal(validSavedCatSimulationPayload(invalidCredential), false);
});

test('saved plan version validator keeps the immutable plan and bank binding exact', () => {
  assert.equal(validSavedPlanVersion(planVersion(1, 3)), true);
  assert.equal(validSavedPlanVersion({ ...planVersion(1, 3), bank_version_ref: 'CBVER_wrong' }), false);
  assert.equal(validSavedPlanVersion({ ...planVersion(1, 3), config_document: { ...planVersion(1, 3).config_document, max_items: 0 } }), false);
  assert.equal(validSavedPlanVersion({ ...planVersion(1, 3), hidden: 'response-body-sentinel' }), false);
});

test('simulation response permits only exact finite aggregate data and complete counts', () => {
  assert.equal(validSavedSimulation(simulation, expected), true);
  assert.equal(validSavedSimulation({ ...simulation, psychological_interpretation_allowed: true }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, metrics: { ...simulation.metrics, mae: Infinity } }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, results: [{ subject_id: 'private-sentinel' }] }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, n_examinees: 1000 }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, plan_version_ref: 'CPVER_other' }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, stopping_reason_distribution: { MAX_ITEMS_REACHED: 99 } }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, stopping_reason_distribution: { PRIVATE_REASON: 100 } }, expected), false);
  assert.equal(validSavedSimulation({ ...simulation, metrics: { ...simulation.metrics, mean_test_length: 10 } }, expected), false);
});

test('aggregate UI extraction matches metric rows, separator-prefixed stop spans, and sibling version binding', async () => {
  const prepared = {
    planName: '浏览器合成方案-qa', bankName: '浏览器合成题库-qa', bankVersionNumber: 1,
    bankVersionRef: 'CBVER_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    planVersionRef1: 'CPVER_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    planVersionRef2: 'CPVER_bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  };
  const metricRows = [
      { label: '偏差', value: '-0.020' }, { label: '均方根误差', value: '0.210' },
      { label: '平均绝对误差', value: '0.170' }, { label: '平均题数', value: '3.00' },
      { label: '中位题数', value: '3.00' }, { label: '平均标准误', value: '0.430' },
    ];
  const stopSpans = ['达到停止阈值 20', ' · 达到最多题数 80'];
  const resultText = '本次汇总 · 100 个合成样本';
  const extracted = extractAggregateUiResult({
    querySelectorAll: (selector) => selector === 'dl > div'
      ? metricRows.map(({ label, value }) => ({
        querySelector: (childSelector) => ({ textContent: childSelector === 'dt' ? label : value }),
      }))
      : selector === 'p:first-of-type span' ? stopSpans.map((textContent) => ({ textContent })) : [],
    textContent: resultText,
  });
  assert.deepEqual(Object.keys(extracted).sort(), ['metrics', 'resultText', 'stops']);
  assert.equal(extracted.resultText, resultText);
  const snapshot = {
    ...extracted,
    bindingText: '浏览器合成方案-qa v1 题库：浏览器合成题库-qa v1（v1）配置：synthetic.cat.v1',
  };
  assert.equal(aggregateUiMismatch(snapshot, simulation, prepared, 1), null);
  assert.equal(aggregateUiMismatch({ ...snapshot, bindingText: '浏览器合成题库-qa v1' }, simulation, prepared, 1), 'binding_labels');
  assert.equal(aggregateUiMismatch({ ...snapshot, stops: ['达到停止阈值 20', ' · 达到最多题数 79'] }, simulation, prepared, 1), 'stop_distribution');
  assert.equal(aggregateUiMismatch({ ...snapshot, metrics: snapshot.metrics.slice(1) }, simulation, prepared, 1), 'metric_shape');
  assert.equal(aggregateUiMismatch({ ...snapshot, metrics: snapshot.metrics.map((row) => row.label === '偏差' ? { ...row, value: '-0.021' } : row) }, simulation, prepared, 1), 'metric_values');

  const source = await import('node:fs/promises').then(({ readFile }) => readFile(new URL('../../10_frontend/src/components/school/SpecialistCatAssets.vue', import.meta.url), 'utf8'));
  assert.ok(source.indexOf('class="asset-simulation__binding"') < source.indexOf('class="asset-simulation__result"'));
  assert.deepEqual(AGGREGATE_SUBSTAGES, [
    'result_visible', 'metric_snapshot', 'metric_shape', 'metric_values',
    'stop_distribution', 'binding_labels', 'opaque_reference_check',
  ]);
  const diagnostic = summarizeSavedSimulationWorkflow(
    Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], os.tmpdir(), 2,
    { stage: 'ui_aggregates_matched_api', aggregate_diagnostic: { substage: 'binding_labels' } },
  );
  assert.deepEqual(diagnostic.diagnostics, { stage: 'ui_aggregates_matched_api', substage: 'binding_labels' });
  const unsafe = summarizeSavedSimulationWorkflow(
    Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], os.tmpdir(), 2,
    { stage: 'ui_aggregates_matched_api', aggregate_diagnostic: { substage: 'binding_labels', visible_text: 'private' } },
  );
  assert.equal(Object.hasOwn(unsafe, 'diagnostics'), false);
});

test('workflow result requires all stages and both screenshots to exist', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'saved-cat-simulation-qa-'));
  const filesDir = path.join(root, 'browser-qa', 'run');
  await mkdir(filesDir, { recursive: true });
  try {
    for (const name of SCREENSHOTS) await writeFile(path.join(filesDir, name), 'masked screenshot marker');
    const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'PASS']));
    assert.equal(summarizeSavedSimulationWorkflow(stages, SCREENSHOTS, filesDir, 0).status, 'PASS');
    assert.equal(summarizeSavedSimulationWorkflow({ ...stages, unsaved_config_ignored: 'FAIL' }, SCREENSHOTS, filesDir, 0).status, 'FAIL');
    assert.equal(summarizeSavedSimulationWorkflow(stages, ['../private.png'], filesDir, 0).status, 'FAIL');

    const mobile = SCREENSHOTS.find((name) => SCREENSHOT_STAGES[name] === 'mobile_screenshot');
    await rm(path.join(filesDir, mobile));
    const missing = summarizeSavedSimulationWorkflow(stages, SCREENSHOTS, filesDir, 0);
    assert.equal(missing.stages.mobile_screenshot, 'FAIL');
    assert.equal(missing.stages.desktop_screenshot, 'PASS');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('asset preparation uses each route status and emits only fixed substage/status diagnostics', async () => {
  assert.deepEqual(SETUP_EXPECTED_HTTP_STATUS, {
    template_read: 200,
    bank_create: 201,
    plan_create: 201,
    plan_version_create: 200,
    bank_version_read: 200,
    plan_version1_read: 200,
    plan_version2_read: 200,
  });
  assert.equal(SETUP_SUBSTAGES.includes('plan_version_create_shape'), true);
  const failure = {
    stage: 'synthetic_assets_prepared',
    error_class: 'Error',
    setup_diagnostic: { substage: 'plan_version_create', http_status: 200 },
  };
  const safe = summarizeSavedSimulationWorkflow(
    Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], os.tmpdir(), 2, failure,
  );
  assert.deepEqual(safe.diagnostics, {
    stage: 'synthetic_assets_prepared', substage: 'plan_version_create', http_status: 200,
  });
  const malformed = summarizeSavedSimulationWorkflow(
    Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], os.tmpdir(), 2,
    { ...failure, setup_diagnostic: { substage: 'plan_version_create', http_status: 200, body: 'body-sentinel' } },
  );
  assert.equal(Object.hasOwn(malformed, 'diagnostics'), false);
  assert.equal(JSON.stringify(malformed).includes('body-sentinel'), false);
});

test('saved-version selection failures expose only fixed substage and HTTP status', () => {
  assert.deepEqual(SELECTION_SUBSTAGES, [
    'route_heading', 'assets_panel_open', 'template_response', 'plan_tab_open',
    'plan_row_visible', 'plan_detail_response', 'history_versions_verified',
    'history_row_visible', 'version_responses', 'binding_label',
  ]);
  const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));
  const result = summarizeSavedSimulationWorkflow(stages, [], os.tmpdir(), 2, {
    stage: 'saved_version_selected',
    error_class: 'TimeoutError',
    selection_diagnostic: { substage: 'plan_row_visible', http_status: 200 },
  });
  assert.deepEqual(result.diagnostics, {
    stage: 'saved_version_selected', substage: 'plan_row_visible', http_status: 200,
  });
  const malformed = summarizeSavedSimulationWorkflow(stages, [], os.tmpdir(), 2, {
    stage: 'saved_version_selected',
    selection_diagnostic: { substage: 'plan_row_visible', http_status: 200, selector: 'private sentinel' },
  });
  assert.equal(Object.hasOwn(malformed, 'diagnostics'), false);
  assert.equal(JSON.stringify(malformed).includes('private sentinel'), false);
});

test('bank, plan, and plan-version evaluate payloads preserve distinct idempotency keys', async () => {
  const cases = [
    ['bank_create', 'saved-cat-browser-bank-key-1'],
    ['plan_create', 'saved-cat-browser-plan-key-2'],
    ['plan_version_create', 'saved-cat-browser-version-key-3'],
  ];
  const payloads = cases.map(([endpoint, idempotencyKey]) => savedCatApiRequestPayload({
    base: BACKEND_URL,
    method: 'POST',
    endpoint,
    body: { synthetic: true },
    idempotencyKey,
  }));
  assert.deepEqual(payloads.map((value) => value.idempotencyKey), cases.map(([, key]) => key));
  assert.equal(payloads.some((value) => value.idempotencyKey === undefined), false);
  assert.equal(payloads.every((value) => !Object.hasOwn(value, 'key')), true);

  const source = await import('node:fs/promises').then(({ readFile }) => readFile(new URL('../school_saved_cat_simulation_browser_qa.mjs', import.meta.url), 'utf8'));
  assert.match(source, /body: input, idempotencyKey\s*\}\)\s*=>/);
  assert.match(source, /headers\['Idempotency-Key'\]\s*=\s*idempotencyKey/);
  assert.match(source, /savedCatApiRequestPayload\(\{ base: backendUrl, method, endpoint, body, idempotencyKey \}\)/);
});

test('a failed pending response wait remains observable without an unhandled rejection', async () => {
  const sentinel = new Error('safe wait failure');
  const pending = preservePendingWaitFailure(Promise.reject(sentinel));
  await assert.rejects(pending, (error) => error === sentinel);
});

test('workflow explicitly opens the plan tab before looking up the prepared saved plan', async () => {
  const source = await import('node:fs/promises').then(({ readFile }) => readFile(new URL('../school_saved_cat_simulation_browser_qa.mjs', import.meta.url), 'utf8'));
  const tabNavigation = source.indexOf("getByRole('button', { name: 'CAT 方案', exact: true }).click()");
  const savedPlanLookup = source.indexOf("locator('.asset-list__items .asset-row').filter({ hasText: prepared.planName })");
  const savedPlanClick = source.indexOf('await planRow.click()', savedPlanLookup);
  assert.notEqual(tabNavigation, -1);
  assert.notEqual(savedPlanLookup, -1);
  assert.notEqual(savedPlanClick, -1);
  assert.ok(tabNavigation < savedPlanLookup && savedPlanLookup < savedPlanClick);
});

test('failure summaries expose only a fixed stage and safe error class', () => {
  const sentinel = 'response-body-password-reference-sentinel';
  const result = summarizeSavedSimulationWorkflow(
    Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], os.tmpdir(), 2,
    { stage: 'simulation100_verified', error_class: `TimeoutError ${sentinel}`, message: sentinel, response_body: sentinel },
  );
  assert.equal(result.failure.stage, 'simulation100_verified');
  assert.equal(result.failure.error_class, 'Error');
  assert.equal(JSON.stringify(result).includes(sentinel), false);
  assert.equal(SAFE_FAILURE_CLASSES.includes('TimeoutError'), true);
});

test('browser source captures real responses without route interception and masks fields', async () => {
  const source = await import('node:fs/promises').then(({ readFile }) => readFile(new URL('../school_saved_cat_simulation_browser_qa.mjs', import.meta.url), 'utf8'));
  assert.equal(source.includes('page.route('), false);
  assert.equal(source.includes('.route.fulfill('), false);
  assert.equal(source.includes('response_body'), false);
  assert.equal(source.includes('responseMatches(response, \'POST\''), true);
  assert.equal(source.includes('X-CSRF-Token'), true);
  assert.equal(source.includes('input, textarea, select'), true);
});
