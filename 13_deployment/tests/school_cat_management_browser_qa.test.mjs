import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BACKEND_URL,
  FRONTEND_URL,
  SAFE_FAILURE_CLASSES,
  SCHOOL_REF,
  SCREENSHOTS,
  SCREENSHOT_MASK_SELECTORS,
  SCREENSHOT_STAGES,
  UI_STAGE_KEYS,
  WORKSPACE,
  validCatCatalog,
  validCatManagementPayload,
  validCatSimulation,
  summarizeCatManagementWorkflow,
} from '../school_cat_management_browser_qa.mjs';

const artifactDir = path.join(WORKSPACE, 'browser-qa', '20261012T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
const catalog = {
  schema_version: 'synthetic_cat_management.v1',
  engineering_only: true,
  psychological_interpretation_allowed: false,
  item_bank: {
    item_bank_id: 'ITEMBANK_demo_cat', version: 'demo.v1', instrument_id: 'CURRENT_SYNTHETIC_GRM',
    item_count: 9, dimension_count: 1, status: 'published', validation: 'STRUCTURE_VALID',
  },
  config: {
    config_version: 'demo.cat.v1', model: 'GRM', estimator: 'EAP', selection_method: 'MFI',
    min_items: 3, max_items: 8, se_threshold: 0.55, seed: 20260904,
  },
  simulation: { available: true, sample_sizes: [100, 1000], fixed_seed: 20260904 },
};
const simulation = {
  schema_version: 'synthetic_cat_management.v1',
  engineering_only: true,
  psychological_interpretation_allowed: false,
  item_bank_id: catalog.item_bank.item_bank_id,
  item_bank_version: catalog.item_bank.version,
  config_version: catalog.config.config_version,
  n_examinees: 100,
  seed: catalog.config.seed,
  metrics: { bias: -0.02, rmse: 0.21, mae: 0.17, mean_test_length: 7.2, median_test_length: 8, mean_se: 0.43 },
  stopping_reason_distribution: { SE_THRESHOLD_REACHED: 76, MAX_ITEMS_REACHED: 24 },
};
const payload = () => ({
  credentials: {
    'alpha.psychological_specialist': { username: 'SYNTHETIC_ALPHA_SPECIALIST', password: 's'.repeat(24) },
  },
  artifact_dir: artifactDir,
  frontend_url: FRONTEND_URL,
  backend_url: BACKEND_URL,
});

test('payload accepts only the sealed synthetic specialist account and fixed local origins', () => {
  assert.equal(validCatManagementPayload(payload()), true);
  assert.equal(SCHOOL_REF, 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1');
  assert.equal(SCREENSHOTS.length, 2);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.account-menu'), true);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('input, textarea, select'), true);

  const extraRole = payload();
  extraRole.credentials['alpha.admin'] = { username: 'SYNTHETIC_ADMIN', password: 'a'.repeat(24) };
  assert.equal(validCatManagementPayload(extraRole), false);
  const unsafeReference = payload();
  unsafeReference.artifact_dir = path.join(os.tmpdir(), '..', 'unrelated');
  assert.equal(validCatManagementPayload(unsafeReference), false);
  const unsafeUser = payload();
  unsafeUser.credentials['alpha.psychological_specialist'].username = 'student@example.test';
  assert.equal(validCatManagementPayload(unsafeUser), false);
  const extraContext = payload();
  extraContext.school_ref = SCHOOL_REF;
  assert.equal(validCatManagementPayload(extraContext), false);
});

test('catalog validator requires the engineering-only current synthetic metadata shape', () => {
  assert.equal(validCatCatalog(catalog), true);
  assert.equal(validCatCatalog({ ...catalog, psychological_interpretation_allowed: true }), false);
  assert.equal(validCatCatalog({ ...catalog, engineering_only: false }), false);
  assert.equal(validCatCatalog({ ...catalog, private_path: 'must-not-be-projected' }), false);
  assert.equal(validCatCatalog({ ...catalog, simulation: { ...catalog.simulation, sample_sizes: [1000, 100] } }), false);
});

test('simulation validator accepts aggregates only and requires finite metrics and complete counts', () => {
  assert.equal(validCatSimulation(simulation, catalog, 100), true);
  assert.equal(validCatSimulation({ ...simulation, results: [{ subject_id: 'must-not-be-returned' }] }, catalog, 100), false);
  assert.equal(validCatSimulation({ ...simulation, metrics: { ...simulation.metrics, mae: Infinity } }, catalog, 100), false);
  assert.equal(validCatSimulation({ ...simulation, metrics: { ...simulation.metrics, private_metric: 1 } }, catalog, 100), false);
  assert.equal(validCatSimulation({ ...simulation, stopping_reason_distribution: { SE_THRESHOLD_REACHED: 99 } }, catalog, 100), false);
  assert.equal(validCatSimulation({ ...simulation, seed: 7 }, catalog, 100), false);
  assert.equal(validCatSimulation({ ...simulation, n_examinees: 1000 }, catalog, 100), false);
});

test('workflow requires every UI stage and both actual screenshot files', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'school-cat-management-qa-'));
  const filesDir = path.join(root, 'browser-qa', 'run');
  await mkdir(filesDir, { recursive: true });
  try {
    for (const name of SCREENSHOTS) await writeFile(path.join(filesDir, name), 'synthetic masked screenshot marker');
    const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'PASS']));
    assert.equal(summarizeCatManagementWorkflow(stages, SCREENSHOTS, filesDir, 0).status, 'PASS');

    assert.equal(summarizeCatManagementWorkflow({ ...stages, ui_aggregates_matched_api: 'FAIL' }, SCREENSHOTS, filesDir, 0).status, 'FAIL');
    assert.equal(summarizeCatManagementWorkflow(stages, SCREENSHOTS, filesDir, 2).status, 'FAIL');
    assert.equal(summarizeCatManagementWorkflow(stages, ['../private.png'], filesDir, 0).status, 'FAIL');

    const mobile = SCREENSHOTS.find((name) => SCREENSHOT_STAGES[name] === 'mobile_screenshot');
    await rm(path.join(filesDir, mobile));
    const missing = summarizeCatManagementWorkflow(stages, SCREENSHOTS, filesDir, 0);
    assert.equal(missing.stages.mobile_screenshot, 'FAIL');
    assert.equal(missing.stages.desktop_screenshot, 'PASS');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('failure summary contains only a fixed stage and safe error class', () => {
  const sentinel = 'response-body-password-reference-sentinel';
  const result = summarizeCatManagementWorkflow(
    Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], os.tmpdir(), 2,
    { stage: 'simulation100_verified', error_class: `TimeoutError: ${sentinel}`, message: sentinel, body: sentinel },
  );
  assert.equal(result.failure.stage, 'simulation100_verified');
  assert.equal(result.failure.error_class, 'Error');
  assert.equal(JSON.stringify(result).includes(sentinel), false);
  assert.equal(SAFE_FAILURE_CLASSES.includes('TimeoutError'), true);
});
