import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  API_STATUS_KEYS,
  BACKEND_URL,
  SCREENSHOTS,
  STAGE_KEYS,
  UI_STAGE_KEYS,
  extractActivationCreate,
  extractAuthenticatedMember,
  extractAssessmentState,
  extractCompletion,
  extractTaskPublication,
  extractTaskStart,
  taskStartValidationCode,
  extractTeacherAggregate,
  teacherProgressValidationCode,
  refreshTeacherProgress,
  doRealApiMutation,
  prepareSavedPlanHistory,
  selectPlanHistoryVersion,
  makeBank,
  roleCleanupComplete,
  summarizeWorkflow,
  validBankDocument,
  validConfigDocument,
  validAssignmentRequest,
  validLiveCheckpoint,
  validSyntheticMetadata,
  writeLiveCheckpoint,
  validResponseWrite,
  validTaskPublishRequest,
} from '../school_synthetic_cat_activation_browser_qa.mjs';

const bankVersionRef = 'CBVER_12345678-1234-1234-1234-123456789012';
const planVersionRef = 'CPVER_12345678-1234-1234-1234-123456789012';
const activationRef = 'CACT_12345678-1234-1234-1234-123456789012';
const classRef = 'CLASS_synthetic_qa';
const taskRef = 'TASK_synthetic_qa';
const assessmentId = 'ASSESS_synthetic_qa';
const flags = { engineering_only: true, psychological_interpretation_allowed: false };

function bankDocument() {
  const options = ['从不', '有时', '经常'];
  return {
    item_bank_id: 'ITEMBANK_synthetic_cat_qa', version: 'synthetic.cat.qa.v1',
    instrument_id: 'CURRENT_SYNTHETIC_GRM', target_population: 'SYNTHETIC_STUDENT_DEMO',
    measurement_model: 'GRM', dimensions: ['demo_trait'], status: 'published',
    metadata: { synthetic: true, intended_use: 'engineering_test_only', psychological_interpretation_allowed: false },
    items: [1, 2, 3].map((index) => ({
      item_id: `ITEM_synthetic_cat_qa_${index}`, dimension: 'demo_trait', stem: `合成工程题 ${index}`,
      response_type: 'likert', response_options: options,
      scoring: { 从不: 0, 有时: 1, 经常: 2 }, model: 'GRM', parameters: { a: 1, thresholds: [-1, 1] },
      source: 'synthetic_fixture', status: 'published',
    })),
  };
}

function configDocument() {
  return {
    config_version: 'synthetic.cat.qa.v1', model: 'GRM', estimator: 'EAP', selection_method: 'MFI',
    min_items: 3, max_items: 3, se_threshold: 0.001, initial_theta: 0, prior_mean: 0, prior_sd: 1,
    optimization_interval: [-4, 4], seed: 20261013, exposure_control: 'none', content_balancing: 'none',
  };
}

test('fresh asset documents retain the bounded synthetic engineering markers', () => {
  assert.equal(validBankDocument(bankDocument()), true);
  assert.equal(validConfigDocument(configDocument()), true);
  assert.equal(validBankDocument({ ...bankDocument(), items: bankDocument().items.slice(0, 2) }), false);
  assert.equal(validConfigDocument({ ...configDocument(), max_items: 4 }), false);
});

test('real fixture metadata survives bank authoring with distinct instrument and asset versions', async () => {
  const fixturePath = new URL('../../01_cat-engine/fixtures/synthetic_item_bank.v1.json', import.meta.url);
  const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
  assert.equal(validSyntheticMetadata(fixture.metadata), true);
  assert.equal(fixture.metadata.instrument_version, 'synthetic_item_bank.v1 / demo.v1');
  const authored = makeBank(fixture, 'synthetic-run-123456');
  assert.equal(validBankDocument(authored), true);
  assert.equal(authored.metadata.instrument_version, fixture.metadata.instrument_version);
  assert.equal(authored.metadata.notice, fixture.metadata.notice);
  assert.equal(authored.metadata.psychometric_status, fixture.metadata.psychometric_status);
  assert.notEqual(authored.version, authored.metadata.instrument_version);
  assert.equal(validSyntheticMetadata({ ...fixture.metadata, unrecognized: 'must fail' }), false);
  assert.equal(validSyntheticMetadata({ ...fixture.metadata, synthetic: 1 }), false);
});

test('activation API evidence is extracted from an actual HTTP response envelope', async () => {
  const metadata = {
    activation_ref: activationRef, plan_version_ref: planVersionRef, bank_version_ref: bankVersionRef,
    plan_name: '合成浏览器方案', plan_version_number: 1,
    bank_name: '合成浏览器题库', bank_version_number: 1,
    status: 'ACTIVE', revision: 1, created_at: '2026-10-13T00:00:00Z', revoked_at: null,
  };
  const request = new Request(`http://127.0.0.1:8088/api/v1/school/cat-assets/plan-versions/${planVersionRef}/activations`, {
    method: 'POST', headers: { 'content-type': 'application/json', 'idempotency-key': 'synthetic-key', 'x-csrf-token': 'synthetic-csrf' },
    body: JSON.stringify({}),
  });
  assert.deepEqual(await request.json(), {});
  const response = new Response(JSON.stringify({ data: { ...flags, activation: metadata } }), { status: 201 });
  const activation = extractActivationCreate(response.status, await response.json(), planVersionRef);
  assert.deepEqual(activation, metadata);
  assert.equal(extractActivationCreate(200, { data: { ...flags, activation: metadata } }, planVersionRef), null);
  assert.equal(extractActivationCreate(201, { data: { ...flags, engineering_only: 1, activation: metadata } }, planVersionRef), null);
});

test('published task request and response prove the same selected immutable activation', async () => {
  const request = new Request(`http://127.0.0.1:8088/api/v1/school/classes/${classRef}/tasks`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ opens_at: '2026-10-13T00:00:00Z', due_at: null, activation_ref: activationRef }),
  });
  const requestBody = await request.json();
  assert.equal(validTaskPublishRequest(requestBody, activationRef), true);
  assert.equal(validTaskPublishRequest({ ...requestBody, activation_ref: 'CACT_other' }, activationRef), false);
  const data = {
    task_ref: taskRef, class_ref: classRef, status: 'PUBLISHED', opens_at: requestBody.opens_at,
    due_at: null, published_at: '2026-10-13T00:01:00Z', published_enrollment_count: 1,
    active_enrollment_count: 1, revoked_enrollment_count: 0, instrument_id: 'CURRENT_SYNTHETIC_GRM',
    instrument_version: 'demo.v1', activation_ref: activationRef, plan_name: '合成浏览器方案', plan_version_number: 1,
  };
  const response = new Response(JSON.stringify({ data }), { status: 201 });
  assert.equal(extractTaskPublication(response.status, await response.json(), activationRef)?.task_ref, taskRef);
  assert.equal(extractTaskPublication(200, { data }, activationRef), null);
  assert.equal(extractTaskPublication(201, { data: { ...data, bank_document: bankDocument() } }, activationRef), null);
});

test('member assignment binds the exact authenticated student and teacher actors', async () => {
  const studentResponse = new Response(JSON.stringify({ data: { user_id: 'USER_synthetic_student', role: 'STUDENT' } }), { status: 200 });
  const studentId = extractAuthenticatedMember(studentResponse.status, await studentResponse.json(), 'STUDENT');
  const teacherResponse = new Response(JSON.stringify({ data: { user_id: 'USER_synthetic_teacher', role: 'TEACHER' } }), { status: 200 });
  const teacherId = extractAuthenticatedMember(teacherResponse.status, await teacherResponse.json(), 'TEACHER');
  assert.equal(studentId, 'USER_synthetic_student');
  assert.equal(teacherId, 'USER_synthetic_teacher');
  assert.equal(extractAuthenticatedMember(200, { data: { user_id: studentId, role: 'TEACHER' } }, 'STUDENT'), null);
  assert.equal(extractAuthenticatedMember(200, { data: { user_id: studentId, role: 'STUDENT', username: 'private' } }, 'STUDENT'), null);

  const studentAssignment = new Request('http://127.0.0.1:8088/api/v1/school/classes/CLASS_x/students', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ student_user_id: studentId }),
  });
  const teacherAssignment = new Request('http://127.0.0.1:8088/api/v1/school/classes/CLASS_x/teachers', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ teacher_user_id: teacherId }),
  });
  assert.equal(validAssignmentRequest('student', await studentAssignment.json(), studentId), true);
  assert.equal(validAssignmentRequest('teacher', await teacherAssignment.json(), teacherId), true);
  assert.equal(validAssignmentRequest('student', { student_user_id: teacherId }, studentId), false);
  assert.equal(validAssignmentRequest('student', { student_user_id: studentId, extra: true }, studentId), false);
});

test('live checkpoint data is restricted to safe workflow stages, steps and status values', () => {
  assert.equal(validLiveCheckpoint('bank_created_201', 'bank_create', 'STARTED'), true);
  assert.equal(validLiveCheckpoint('bank_created_201', 'bank_create', 'HTTP_201'), true);
  assert.equal(validLiveCheckpoint('bank_created_201', 'bank_create', 'FAIL_AFTER_HTTP_201'), true);
  assert.equal(validLiveCheckpoint('bank_created_201', 'mutation_response_body_read', 'ERROR_ResponseBodyTimeout'), true);
  assert.equal(validLiveCheckpoint('bank_created_201', 'bank_create', 'SYNTHETIC_USER_ID'), false);
  assert.equal(validLiveCheckpoint('bank_created_201', 'mutation_response_body_read', 'ERROR_PrivateMessage'), false);
  assert.equal(validLiveCheckpoint('cat_started', 'task_start_validator', 'INVALID_ADMINISTERED_COUNT'), true);
  assert.equal(validLiveCheckpoint('cat_started', 'task_start_validator', 'INVALID_private_value'), false);
  assert.equal(validLiveCheckpoint('teacher_completion_aggregate', 'teacher_progress_validator', 'INVALID_COMPLETED_COUNT'), true);
  assert.equal(validLiveCheckpoint('teacher_completion_aggregate', 'teacher_progress_validator', 'INVALID_BODY_READ_FAILED'), true);
  assert.equal(validLiveCheckpoint('teacher_completion_aggregate', 'teacher_ui_validator', 'INVALID_ROW_NOT_VISIBLE'), true);
  assert.equal(validLiveCheckpoint('teacher_completion_aggregate', 'teacher_ui_validator', 'INVALID_private_value'), false);
  assert.equal(validLiveCheckpoint('private-ref', 'bank_create', 'PASS'), false);
  assert.equal(writeLiveCheckpoint(os.tmpdir(), 'bank_created_201', 'bank_create', 'PASS'), false);
  assert.equal(roleCleanupComplete(6, 6), true);
  assert.equal(roleCleanupComplete(6, 1), false);
});

test('student task start is attributed to cat_started after login and before the start request', async () => {
  const source = await readFile(new URL('../school_synthetic_cat_activation_browser_qa.mjs', import.meta.url), 'utf8');
  const loginPassed = source.indexOf("stages.student_login = 'PASS';");
  const startStage = source.indexOf("setFailureStage('cat_started');", loginPassed);
  const startListener = source.indexOf('const startRequestPromise =', startStage);
  const startClick = source.indexOf("getByRole('button', { name: '开始任务'", startListener);
  assert.ok(loginPassed >= 0 && startStage > loginPassed && startListener > startStage && startClick > startListener);
});

test('teacher progress validation begins after teacher authentication', async () => {
  const source = await readFile(new URL('../school_synthetic_cat_activation_browser_qa.mjs', import.meta.url), 'utf8');
  const loginPassed = source.indexOf("stages.teacher_login = 'PASS';");
  const aggregateStage = source.indexOf("setFailureStage('teacher_completion_aggregate');", loginPassed);
  const progressRefresh = source.indexOf('refreshTeacherProgress(session.page)', aggregateStage);
  const redactionStage = source.indexOf("setFailureStage('teacher_metadata_redacted');", progressRefresh);
  assert.ok(loginPassed >= 0 && aggregateStage > loginPassed && progressRefresh > aggregateStage && redactionStage > progressRefresh);
  assert.doesNotMatch(source.slice(aggregateStage, redactionStage), /session\.page\.goto/);
});

test('teacher progress refresh installs the real GET listener before clicking without navigating', async () => {
  const events = [];
  const response = {
    request: () => ({ method: () => 'GET' }),
    url: () => 'http://127.0.0.1:8088/api/v1/school/teacher/task-progress',
    status: () => 200,
  };
  const page = {
    waitForFunction: async (predicate, argument, options) => {
      assert.equal(typeof predicate, 'function');
      assert.equal(argument, null);
      assert.equal(options.timeout, 20000);
      events.push('ready');
    },
    waitForResponse: (predicate, options) => {
      assert.equal(options.timeout, 30000);
      assert.equal(predicate(response), true);
      events.push('listener');
      return Promise.resolve(response);
    },
    getByRole: (role, options) => {
      assert.equal(role, 'button');
      assert.deepEqual(options, { name: '刷新', exact: true });
      return { click: async () => { events.push('click'); } };
    },
  };
  assert.equal(await refreshTeacherProgress(page), response);
  assert.deepEqual(events, ['ready', 'listener', 'click']);
});

test('saved plan history navigation switches to CAT plans before locating the created plan', async () => {
  const events = [];
  let plansSelected = false;
  let tabWaitCount = 0;
  const catalogResponse = {
    status: () => 200,
    request: () => ({ method: () => 'GET' }),
    url: () => 'http://127.0.0.1:8088/api/v1/school/cat-management/catalog',
  };
  const planRow = {
    waitFor: async ({ state }) => {
      assert.equal(state, 'visible');
      assert.equal(plansSelected, true);
      events.push('plan-row-visible');
    },
    click: async () => { events.push('plan-row-clicked'); },
  };
  const historyRow = {
    waitFor: async ({ state }) => {
      assert.equal(state, 'visible');
      assert.equal(events.includes('plan-row-clicked'), true);
      events.push('history-visible');
    },
  };
  const history = { first: () => historyRow };
  const page = {
    waitForResponse: (matches, options) => {
      assert.equal(options.timeout, 30000);
      assert.equal(matches(catalogResponse), true);
      return Promise.resolve(catalogResponse);
    },
    reload: async (options) => {
      assert.deepEqual(options, { waitUntil: 'domcontentloaded' });
      events.push('page-reloaded');
    },
    getByRole: (role, options) => {
      if (role === 'button' && options.name === '题库与方案') {
        return { click: async () => { events.push('workspace-opened'); } };
      }
      if (role === 'button' && options.name === 'CAT 方案') {
        return {
          waitFor: async ({ state }) => { assert.equal(state, 'visible'); },
          click: async () => { plansSelected = true; events.push('plans-tab-clicked'); },
        };
      }
      if (role === 'heading' && options.name === 'CAT 方案') {
        return { waitFor: async ({ state }) => { assert.equal(state, 'visible'); events.push('plans-heading-visible'); } };
      }
      throw new Error('UnexpectedLocator');
    },
    locator: (selector) => {
      if (selector === '.asset-workspace') return { waitFor: async () => { events.push('workspace-visible'); } };
      if (selector === '.asset-tabs') return { getByRole: (role, options) => page.getByRole(role, options) };
      if (selector === '.asset-state[aria-busy="true"]') {
        return { waitFor: async ({ state }) => { assert.equal(state, 'detached'); events.push('loading-finished'); } };
      }
      if (selector === '.asset-list__items .asset-row') return {
        filter: ({ hasText }) => {
          assert.equal(plansSelected, true);
          assert.equal(hasText, '合成计划名称');
          return planRow;
        },
      };
      if (selector === '.asset-history__row') return history;
      throw new Error('UnexpectedSelector');
    },
    waitForFunction: async (callback, _argument, options) => {
      assert.equal(typeof callback, 'function');
      if (tabWaitCount === 0) {
        assert.equal(options.timeout, 20000);
        assert.equal(plansSelected, false);
        events.push('plans-tab-unlocked');
      } else {
        assert.equal(options.timeout, 15000);
        assert.equal(plansSelected, true);
        events.push('plans-tab-active');
      }
      tabWaitCount += 1;
    },
  };
  const checkpoints = [];
  const apiStatuses = {};
  const result = await prepareSavedPlanHistory(page, '合成计划名称', apiStatuses, (step, status) => {
    checkpoints.push({ step, status });
  });
  assert.equal(result.catalogResponse, catalogResponse);
  assert.equal(apiStatuses.cat_catalog_reload, 200);
  assert.equal(result.history, history);
  assert.ok(events.indexOf('plans-tab-unlocked') < events.indexOf('plans-tab-clicked'));
  assert.ok(events.indexOf('plans-tab-clicked') < events.indexOf('plan-row-visible'));
  assert.deepEqual(checkpoints, [
    { step: 'history_catalog_reload', status: 'STARTED' },
    { step: 'history_catalog_reload', status: 'HTTP_200' },
    { step: 'history_catalog_reload', status: 'PASS' },
    { step: 'open_asset_workspace', status: 'STARTED' },
    { step: 'open_asset_workspace', status: 'PASS' },
    { step: 'select_plans_tab', status: 'STARTED' },
    { step: 'select_plans_tab', status: 'PASS' },
    { step: 'wait_plan_list', status: 'STARTED' },
    { step: 'wait_plan_list', status: 'PASS' },
    { step: 'select_saved_plan', status: 'STARTED' },
    { step: 'select_saved_plan', status: 'PASS' },
  ]);
});

test('plan version selection waits for the scoped selected-history indicator and pressed row', async () => {
  let pressed = false;
  let selectionReady = true;
  let clickConfirms = true;
  const events = [];
  const selectedText = '已选择 合成计划名称 v1：绑定 合成题库 v1。';
  const planResponse = {
    status: () => 200,
    request: () => ({ method: () => 'GET' }),
    url: () => `http://127.0.0.1:8088/api/v1/school/cat-assets/plan-versions/${planVersionRef}`,
  };
  const bankResponse = {
    status: () => 200,
    request: () => ({ method: () => 'GET' }),
    url: () => `http://127.0.0.1:8088/api/v1/school/cat-assets/bank-versions/${bankVersionRef}`,
  };
  const versionRow = {
    waitFor: async ({ state }) => { assert.equal(state, 'visible'); events.push('row-visible'); },
    click: async () => { pressed = clickConfirms; events.push('row-clicked'); },
    getAttribute: async (name) => { assert.equal(name, 'aria-pressed'); return pressed ? 'true' : 'false'; },
  };
  const page = {
    waitForResponse: (matches, options) => {
      assert.equal(options.timeout, 30000);
      if (matches(planResponse)) { events.push('plan-detail-200'); return Promise.resolve(planResponse); }
      if (matches(bankResponse)) { events.push('bank-detail-200'); return Promise.resolve(bankResponse); }
      throw new Error('UnexpectedDetailRequest');
    },
    waitForFunction: async (callback, label, options) => {
      assert.equal(typeof callback, 'function');
      assert.equal(label, '版本 1 ·');
      assert.equal(options.timeout, 15000);
      if (!selectionReady || !pressed) throw new Error('SelectionNotConfirmed');
      events.push('pressed-confirmed');
    },
    locator: (selector) => {
      assert.equal(selector, '.asset-editor .asset-history__selected');
      return {
        waitFor: async ({ state }) => { assert.equal(state, 'visible'); events.push('selected-visible'); },
        innerText: async () => selectedText,
      };
    },
  };
  const history = {
    filter: ({ hasText }) => {
      assert.equal(hasText, '版本 1 ·');
      return versionRow;
    },
  };
  const checkpoints = [];
  const apiStatuses = {};
  const actual = await selectPlanHistoryVersion(
    page, history, '合成计划名称', 1, planVersionRef, bankVersionRef, apiStatuses, (step, status) => {
    checkpoints.push({ step, status });
  });
  assert.equal(actual, selectedText);
  assert.equal(apiStatuses.plan_version_detail, 200);
  assert.equal(apiStatuses.bank_version_detail, 200);
  assert.ok(events.indexOf('row-clicked') < events.indexOf('selected-visible'));
  assert.ok(events.indexOf('plan-detail-200') < events.indexOf('pressed-confirmed'));
  assert.ok(events.indexOf('bank-detail-200') < events.indexOf('pressed-confirmed'));
  assert.deepEqual(checkpoints, [
    { step: 'select_plan_version', status: 'STARTED' },
    { step: 'plan_version_detail_read', status: 'STARTED' },
    { step: 'bank_version_detail_read', status: 'STARTED' },
    { step: 'row_clicked', status: 'STARTED' },
    { step: 'row_clicked', status: 'PASS' },
    { step: 'plan_version_detail_read', status: 'HTTP_200' },
    { step: 'plan_version_detail_read', status: 'PASS' },
    { step: 'bank_version_detail_read', status: 'HTTP_200' },
    { step: 'bank_version_detail_read', status: 'PASS' },
    { step: 'row_selection_confirmed', status: 'STARTED' },
    { step: 'row_selection_confirmed', status: 'PASS' },
    { step: 'selected_text_confirmed', status: 'STARTED' },
    { step: 'selected_text_confirmed', status: 'PASS' },
    { step: 'select_plan_version', status: 'PASS' },
  ]);

  pressed = false;
  clickConfirms = false;
  selectionReady = false;
  await assert.rejects(selectPlanHistoryVersion(
    page, history, '合成计划名称', 1, planVersionRef, bankVersionRef, {}, () => {},
  ), /SelectionNotConfirmed/);
});

test('real mutation helper sends through the page request context and preserves status, headers and payload', async () => {
  const endpoint = '/api/v1/school/cat-assets/banks';
  const requestBody = { display_name: '合成浏览器题库', bank_document: bankDocument() };
  const idempotencyKey = 'synthetic-cat-qa-fixed-key';
  const requestCalls = [];
  const csrfResponse = { status: () => 200, json: async () => ({ data: { csrf_token: 'synthetic-csrf-token' } }) };
  let mutationStatus = 201;
  const mutationResponse = { status: () => mutationStatus, json: async () => ({ data: { created: true } }) };
  const page = { request: {
    get: async (url, options) => {
      requestCalls.push({ method: 'GET', url, options });
      return csrfResponse;
    },
    post: async (url, options) => {
      requestCalls.push({ method: 'POST', url, options });
      return mutationResponse;
    },
  } };
  const checkpoints = [];
  const apiStatuses = {};
  const mutation = await doRealApiMutation(
    page.request, { backend_url: BACKEND_URL }, endpoint, requestBody, idempotencyKey, 201, 'bank_create', apiStatuses,
    (step, status) => checkpoints.push({ step, status }),
  );
  assert.equal(mutation.response.status(), 201);
  assert.deepEqual(mutation.envelope, { data: { created: true } });
  assert.equal(requestCalls.length, 2);
  assert.equal(requestCalls[0].url, `${BACKEND_URL}/api/v1/auth/csrf`);
  assert.equal(requestCalls[0].options.timeout, 15000);
  assert.equal(requestCalls[0].options.failOnStatusCode, false);
  assert.equal(requestCalls[1].method, 'POST');
  assert.equal(requestCalls[1].url, `${BACKEND_URL}${endpoint}`);
  assert.equal(requestCalls[1].options.timeout, 30000);
  assert.equal(requestCalls[1].options.failOnStatusCode, false);
  assert.equal(requestCalls[1].options.maxRetries, 0);
  assert.equal(requestCalls[1].options.headers['X-CSRF-Token'], 'synthetic-csrf-token');
  assert.equal(requestCalls[1].options.headers['Idempotency-Key'], idempotencyKey);
  assert.equal(requestCalls[1].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(requestCalls[1].options.data), requestBody);
  assert.deepEqual(mutation.requestBody, requestBody);
  assert.equal(mutation.requestHeaders['idempotency-key'], idempotencyKey);
  assert.equal(mutation.requestHeaders['x-csrf-token'], 'synthetic-csrf-token');
  assert.deepEqual(checkpoints, [
    { step: 'bank_create', status: 'STARTED' },
    { step: 'csrf_request', status: 'STARTED' },
    { step: 'csrf_request', status: 'HTTP_200' },
    { step: 'csrf_request', status: 'PASS' },
    { step: 'csrf_response_body_read', status: 'STARTED' },
    { step: 'csrf_response_body_read', status: 'PASS' },
    { step: 'header_checked', status: 'STARTED' },
    { step: 'header_checked', status: 'PASS' },
    { step: 'mutation_request', status: 'STARTED' },
    { step: 'bank_create', status: 'HTTP_201' },
    { step: 'mutation_response_body_read', status: 'STARTED' },
    { step: 'mutation_response_body_read', status: 'PASS' },
    { step: 'bank_create', status: 'PASS' },
  ]);
  assert.equal(apiStatuses.bank_create, 201);

  mutationStatus = 200;
  checkpoints.length = 0;
  await assert.rejects(doRealApiMutation(
    page.request, { backend_url: BACKEND_URL }, endpoint, requestBody, idempotencyKey, 201, 'bank_create', apiStatuses,
    (step, status) => checkpoints.push({ step, status }),
  ), /MutationStatusOrHeadersMismatch/);
  assert.equal(apiStatuses.bank_create, 200);
  assert.deepEqual(checkpoints, [
    { step: 'bank_create', status: 'STARTED' },
    { step: 'csrf_request', status: 'STARTED' },
    { step: 'csrf_request', status: 'HTTP_200' },
    { step: 'csrf_request', status: 'PASS' },
    { step: 'csrf_response_body_read', status: 'STARTED' },
    { step: 'csrf_response_body_read', status: 'PASS' },
    { step: 'header_checked', status: 'STARTED' },
    { step: 'header_checked', status: 'PASS' },
    { step: 'mutation_request', status: 'STARTED' },
    { step: 'bank_create', status: 'HTTP_200' },
  ]);
});

test('start DTO extraction follows the backend schema and CAT fixture state shape', async () => {
  const schemaPath = new URL('../../09_backend/src/smhai_backend/domains/school_tasks/schemas.py', import.meta.url);
  const backendSchema = await readFile(schemaPath, 'utf8');
  const dtoBlock = backendSchema.match(/class TaskStartDto\(SchoolOutputDto\):([\s\S]*?)(?=\n\nclass )/);
  assert.ok(dtoBlock);
  const backendFields = [...dtoBlock[1].matchAll(/^\s{4}([a-z_]+):/gm)].map((match) => match[1]).sort();
  assert.deepEqual(backendFields, [
    'task_ref', 'assessment_id', 'subject_id', 'status', 'selected_item_id', 'current_item',
    'answered_count', 'administered_count', 'can_complete', 'max_items',
  ].sort());
  const assessmentServicePath = new URL('../../09_backend/src/smhai_backend/domains/assessment/service.py', import.meta.url);
  const assessmentService = await readFile(assessmentServicePath, 'utf8');
  assert.match(assessmentService, /"status":\s*"created"/);
  assert.match(assessmentService, /record\.assessment\["status"\]\s*=\s*"in_progress"/);
  const stateForActorBlock = assessmentService.match(/async def state_for_actor\([\s\S]*?(?=\n    async def _fresh_authorized_record)/);
  assert.ok(stateForActorBlock);
  assert.doesNotMatch(stateForActorBlock[0], /assessment\["status"\]\s*=/);
  const catSourcePath = new URL('../../01_cat-engine/src/cat_engine/api/app.py', import.meta.url);
  const catSource = await readFile(catSourcePath, 'utf8');
  assert.match(catSource, /"options":\s*\[\s*\{\s*"value": option, "label": option\s*\}/);
  assert.match(catSource, /administered = len\(session\.traces\)/);
  const fixturePath = new URL('../../01_cat-engine/fixtures/synthetic_item_bank.v1.json', import.meta.url);
  const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
  const fixtureItem = fixture.items[0];
  const currentItem = {
    item_id: fixtureItem.item_id, prompt: fixtureItem.stem, response_type: fixtureItem.response_type,
    options: fixtureItem.response_options.map((option) => ({ value: option, label: option })),
  };
  const started = {
    task_ref: taskRef, assessment_id: assessmentId, subject_id: 'SUBJ_synthetic', status: 'created',
    selected_item_id: currentItem.item_id, current_item: currentItem, answered_count: 0, administered_count: 0,
    can_complete: false, max_items: 3,
  };
  const startResponse = new Response(JSON.stringify({ data: started }), { status: 200 });
  assert.equal(extractTaskStart(startResponse.status, await startResponse.json(), taskRef)?.max_items, 3);
  assert.equal(taskStartValidationCode(200, { data: { ...started, status: 'in_progress' } }, taskRef), 'STATUS');
  assert.equal(taskStartValidationCode(200, { data: { ...started, administered_count: 1 } }, taskRef), null);
  assert.equal(taskStartValidationCode(200, { data: { ...started, administered_count: -1 } }, taskRef), 'ADMINISTERED_COUNT');
  assert.equal(taskStartValidationCode(200, { data: { ...started, selected_item_id: 'ITEM_wrong' } }, taskRef), 'SELECTED_ITEM_ID');
  assert.equal(taskStartValidationCode(200, { data: { ...started, current_item: { ...currentItem, options: ['private-shape'] } } }, taskRef), 'OPTION_SHAPE');
  assert.equal(taskStartValidationCode(201, { data: started }, taskRef), 'HTTP_STATUS');
});

test('saved state, response and completion enforce three-item version provenance', async () => {
  const currentItem = { item_id: 'ITEM_synthetic_cat_qa_1', prompt: 'Synthetic prompt', options: [
    { value: 'never', label: 'never' }, { value: 'sometimes', label: 'sometimes' },
  ] };
  const state = {
    assessment_id: assessmentId, subject_id: 'SUBJECT_synthetic', status: 'in_progress',
    selected_item_id: currentItem.item_id, current_item: currentItem, current_index: 0,
    answered_count: 0, administered_count: 1, can_complete: false, max_items: 3,
    cat_provider_version: 'synthetic-provider.v1', cat_item_bank_version: 'synthetic.cat.qa.v1',
    cat_config_version: 'synthetic.cat.qa.v1',
  };
  const expected = { assessmentId, bankVersion: 'synthetic.cat.qa.v1', configVersion: 'synthetic.cat.qa.v1' };
  const stateResponse = new Response(JSON.stringify({ data: state }), { status: 200 });
  const parsedState = extractAssessmentState(stateResponse.status, await stateResponse.json(), expected);
  assert.equal(parsedState.max_items, 3);
  assert.equal(validResponseWrite({ item_id: currentItem.item_id, response: '有时' }, parsedState, expected), true);
  assert.equal(validResponseWrite({ item_id: currentItem.item_id, response: '有时', answer_text: 'private' }, parsedState, expected), false);
  assert.equal(extractAssessmentState(200, { data: { ...state, cat_item_bank_version: 'latest' } }, expected), null);
  assert.deepEqual(extractCompletion(200, { data: { schema_version: 'assessment.v1', assessment_id: assessmentId, status: 'completed' } }, assessmentId), {
    assessment_id: assessmentId, status: 'completed',
  });
});

test('teacher result is an aggregate only and exact success requires every stage and masked screenshot file', async () => {
  const schemaPath = new URL('../../09_backend/src/smhai_backend/domains/school_tasks/schemas.py', import.meta.url);
  const schema = await readFile(schemaPath, 'utf8');
  const dtoBlock = schema.match(/class TeacherTaskProgressDto\(SchoolOutputDto\):([\s\S]*?)(?=\n\nclass )/);
  assert.ok(dtoBlock);
  const dtoFields = [...dtoBlock[1].matchAll(/^\s{4}([a-z_]+):/gm)].map((match) => match[1]).sort();
  const repositoryPath = new URL('../../11_database/database_layer/repositories.py', import.meta.url);
  const repository = await readFile(repositoryPath, 'utf8');
  const countStart = repository.indexOf('class TaskProgressCounts:');
  const countEnd = repository.indexOf('class SchoolOperationsRepository:', countStart);
  assert.ok(countStart >= 0 && countEnd > countStart);
  const countBlock = repository.slice(countStart, countEnd);
  const countFields = [...countBlock.matchAll(/^\s{4}([a-z_]+):/gm)].map((match) => match[1]);
  assert.deepEqual(dtoFields, [
    'class_ref', 'task_ref', 'task_status', 'opens_at', 'due_at', ...countFields,
  ].sort());
  const row = {
    class_ref: classRef, task_ref: taskRef, task_status: 'PUBLISHED', opens_at: '2026-10-13T00:00:00Z', due_at: null,
    published_enrollment_count: 1, active_enrollment_count: 1, revoked_enrollment_count: 0,
    not_started_count: 0, created_count: 0, in_progress_count: 0, completed_count: 1,
    abandoned_count: 0, invalid_count: 0,
  };
  const response = new Response(JSON.stringify({ data: [row] }), { status: 200 });
  assert.deepEqual(extractTeacherAggregate(response.status, await response.json(), classRef, taskRef), {
    completed_count: 1, active_enrollment_count: 1,
  });
  assert.equal(teacherProgressValidationCode(200, { data: [{ ...row, completed_count: 0 }] }, classRef, taskRef), 'COMPLETED_COUNT');
  assert.equal(teacherProgressValidationCode(200, { data: [{ ...row, private_answer: 'must not echo' }] }, classRef, taskRef), 'DTO_KEYS');
  assert.equal(teacherProgressValidationCode(200, { data: [row, row] }, classRef, taskRef), 'MATCHING_ROW_COUNT');
  assert.equal(teacherProgressValidationCode(503, { data: [row] }, classRef, taskRef), 'HTTP_STATUS');
  assert.equal(extractTeacherAggregate(200, { data: [{ ...row, assessment_id: assessmentId }] }, classRef, taskRef), null);
  assert.ok(API_STATUS_KEYS.includes('task_publish'));
  assert.equal(roleCleanupComplete(1, 1), true);
  assert.equal(roleCleanupComplete(4, 1), false);
  assert.equal(roleCleanupComplete(1, 0), false);

  const directory = await mkdtemp(path.join(os.tmpdir(), 'synthetic-cat-activation-qa-'));
  try {
    for (const name of SCREENSHOTS) await writeFile(path.join(directory, name), 'synthetic masked screenshot evidence');
    const stages = Object.fromEntries(STAGE_KEYS.map((key) => [key, 'PASS']));
    const success = summarizeWorkflow(stages, SCREENSHOTS, directory, 0, null, { task_publish: 201, task_start: 200 });
    assert.equal(success.status, 'PASS');
    assert.equal(UI_STAGE_KEYS.every((key) => success.stages[key] === 'PASS'), true);
    assert.equal(success.api_statuses.task_publish, 201);
    assert.equal(summarizeWorkflow({ ...stages, task_activation_matched: 'FAIL' }, SCREENSHOTS, directory).status, 'FAIL');
    const sentinel = 'synthetic-private-stem-response-password-sentinel';
    const failed = summarizeWorkflow(stages, SCREENSHOTS, directory, 2, {
      stage: 'student_login', error_class: `Error ${sentinel}`, message: sentinel, responseBody: sentinel,
    }, { task_publish: sentinel });
    assert.equal(JSON.stringify(failed).includes(sentinel), false);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
