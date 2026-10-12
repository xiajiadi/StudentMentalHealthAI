import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BACKEND_URL,
  FRONTEND_URL,
  SCREENSHOTS,
  SCREENSHOT_MASK_SELECTORS,
  SCREENSHOT_STAGES,
  UI_STAGE_KEYS,
  WORKSPACE,
  validCatAssetsPayload,
  validCatAssetFlags,
  validCatAssetsTemplate,
  validCatBankDocument,
  validCatConfig,
  validCatBankList,
  validCatBankWrite,
  validCatBankVersion,
  validCatPlanList,
  validCatPlanWrite,
  validCatPlanVersion,
  summarizeCatAssetsWorkflow,
} from '../school_cat_assets_browser_qa.mjs';

const bankRef = 'CBANK_12345678-1234-1234-1234-123456789012';
const bankVersionRef = 'CBVER_12345678-1234-1234-1234-123456789012';
const planRef = 'CPLAN_12345678-1234-1234-1234-123456789012';
const planVersionRef = 'CPVER_12345678-1234-1234-1234-123456789012';
const item = (id = 'ITEM_synthetic_001') => ({
  item_id: id, dimension: 'demo_trait', stem: 'Synthetic item text', response_type: 'likert',
  response_options: ['never', 'sometimes', 'often'], scoring: { never: 0, sometimes: 1, often: 2 },
  model: 'GRM', parameters: { a: 1.2, thresholds: [-1, 1] }, source: 'synthetic_fixture', status: 'published',
});
const bankDocument = () => ({
  item_bank_id: 'CURRENT_SYNTHETIC_GRM', version: 'demo.v1', instrument_id: 'CURRENT_SYNTHETIC_GRM',
  target_population: 'SYNTHETIC_STUDENT_DEMO', measurement_model: 'GRM', dimensions: ['demo_trait'],
  items: Array.from({ length: 9 }, (_, index) => item(`ITEM_synthetic_${String(index + 1).padStart(3, '0')}`)),
  status: 'published', metadata: { synthetic: true, intended_use: 'engineering_test_only', psychological_interpretation_allowed: false },
});
const config = (overrides = {}) => ({
  config_version: 'synthetic.cat.v1', model: 'GRM', estimator: 'EAP', selection_method: 'MFI', min_items: 3,
  max_items: 8, se_threshold: 0.5, initial_theta: 0, prior_mean: 0, prior_sd: 1,
  optimization_interval: [-4, 4], seed: 20261012, exposure_control: 'none', content_balancing: 'none', ...overrides,
});
const flags = { engineering_only: true, psychological_interpretation_allowed: false };
const bankMeta = {
  bank_ref: bankRef, display_name: 'Synthetic bank', status: 'ACTIVE', revision: 2,
  created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:01:00Z',
};
const bankVersion = { version_ref: bankVersionRef, version_number: 2, created_at: '2026-10-12T00:01:00Z', item_count: 9, dimension_count: 1 };
const bankDetail = { ...flags, bank: { ...bankMeta, versions: [bankVersion] } };
const planMeta = {
  plan_ref: planRef, display_name: 'Synthetic plan', status: 'ACTIVE', revision: 2,
  created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:02:00Z',
};
const planVersion = { version_ref: planVersionRef, version_number: 2, created_at: '2026-10-12T00:02:00Z' };
const planDetail = { ...flags, plan: { ...planMeta, versions: [planVersion] } };

function payload() {
  return {
    credentials: { 'alpha.psychological_specialist': { username: 'SYNTHETIC_ALPHA_SPECIALIST', password: 's'.repeat(24) } },
    artifact_dir: path.join(WORKSPACE, 'browser-qa', '20261012T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'),
    frontend_url: FRONTEND_URL,
    backend_url: BACKEND_URL,
  };
}

test('payload confines execution to fixed local origins and one sealed synthetic specialist', () => {
  assert.equal(validCatAssetsPayload(payload()), true);
  assert.deepEqual(SCREENSHOTS, ['specialist-cat-assets-desktop.png', 'specialist-cat-assets-mobile.png']);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.account-menu'), true);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('input, textarea, select'), true);
  const extraActor = payload(); extraActor.credentials['alpha.admin'] = { username: 'SYNTHETIC_ADMIN', password: 'a'.repeat(24) };
  assert.equal(validCatAssetsPayload(extraActor), false);
  const unsafeArtifact = payload(); unsafeArtifact.artifact_dir = path.join(os.tmpdir(), 'unrelated-qa-artifacts');
  assert.equal(validCatAssetsPayload(unsafeArtifact), false);
  const remote = payload(); remote.backend_url = 'https://example.invalid';
  assert.equal(validCatAssetsPayload(remote), false);
});

test('actual template and bounded GRM content must keep synthetic-only flags and structures', () => {
  const document = bankDocument();
  assert.equal(validCatBankDocument(document), true);
  assert.equal(validCatConfig(config(), document.items.length), true);
  assert.equal(validCatAssetsTemplate({ ...flags, bank_document: document, config_document: config(), item_count: 9, dimension_count: 1 }), true);
  assert.equal(validCatAssetsTemplate({ engineering_only: false, psychological_interpretation_allowed: false, bank_document: document, config_document: config(), item_count: 9, dimension_count: 1 }), false);
  assert.equal(validCatBankDocument({ ...document, items: [...document.items, item(document.items[0].item_id)] }), false);
  assert.equal(validCatConfig(config({ max_items: 10 }), 9), false);
  assert.equal(validCatAssetFlags({ ...flags, psychological_interpretation_allowed: true }), false);
});

test('bank and plan API validators match the nested Backend DTOs and exact references', () => {
  assert.equal(validCatBankList({ ...flags, items: [bankMeta], has_more: false }), true);
  assert.equal(validCatBankWrite({ ...bankDetail, version_ref: bankVersionRef }, bankMeta.display_name), true);
  assert.equal(validCatBankVersion({ ...flags, version: bankVersion, bank_document: bankDocument() }, bankVersionRef), true);
  assert.equal(validCatPlanList({ ...flags, items: [planMeta], has_more: false }), true);
  assert.equal(validCatPlanWrite({ ...planDetail, version_ref: planVersionRef }, planMeta.display_name), true);
  assert.equal(validCatPlanVersion({
    ...flags, version: planVersion, bank_version_ref: bankVersionRef, config_document: config({ max_items: 6 }),
  }, planVersionRef, bankVersionRef), true);
  assert.equal(validCatPlanVersion({
    ...flags, version: planVersion, bank_version_ref: 'CBVER_wrong', config_document: config({ max_items: 6 }),
  }), false);
  assert.equal(validCatBankWrite({ ...bankDetail, version_ref: 'private-ref' }), false);
});

test('workflow PASS requires exact stage names and two actual screenshot files', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'school-cat-assets-qa-'));
  try {
    for (const name of SCREENSHOTS) await writeFile(path.join(root, name), 'synthetic masked screenshot marker');
    const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'PASS']));
    assert.equal(summarizeCatAssetsWorkflow(stages, SCREENSHOTS, root, 0).status, 'PASS');
    assert.equal(summarizeCatAssetsWorkflow({ ...stages, plan_version_saved: 'FAIL' }, SCREENSHOTS, root, 0).status, 'FAIL');
    assert.equal(summarizeCatAssetsWorkflow(stages, ['../private.png'], root, 0).status, 'FAIL');
    const mobile = SCREENSHOTS.find((name) => SCREENSHOT_STAGES[name] === 'mobile_screenshot');
    await rm(path.join(root, mobile));
    assert.equal(summarizeCatAssetsWorkflow(stages, SCREENSHOTS, root, 0).stages.mobile_screenshot, 'FAIL');
    const sentinel = 'synthetic-private-response-and-password-marker';
    const failed = summarizeCatAssetsWorkflow(Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL'])), [], root, 2,
      { stage: 'bank_created', error_class: `Error:${sentinel}`, message: sentinel, responseBody: sentinel });
    assert.equal(JSON.stringify(failed).includes(sentinel), false);
    const source = await readFile(new URL('../school_cat_assets_browser_qa.mjs', import.meta.url), 'utf8');
    assert.equal(source.includes('page.route('), false);
    assert.equal(source.includes('.route.fulfill('), false);
  } finally { await rm(root, { recursive: true, force: true }); }
});
