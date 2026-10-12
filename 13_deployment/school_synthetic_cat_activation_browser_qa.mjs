import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const FRONTEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');

export const WORKSPACE_PREFIX = '.StudentMentalHealthAI-school-workspace-20261011';
export const FRONTEND_URL = 'http://127.0.0.1:4178';
export const BACKEND_URL = 'http://127.0.0.1:8088';
export const ACCOUNT_ROUTES = {
  'alpha.admin': { role: 'SCHOOL_ADMIN', api_role: 'ADMIN', path: '/admin/overview' },
  'alpha.student': { role: 'STUDENT', api_role: 'STUDENT', path: '/student/home' },
  'alpha.teacher': { role: 'TEACHER', api_role: 'TEACHER', path: '/teacher/overview' },
  'alpha.psychological_specialist': {
    role: 'PSYCHOLOGICAL_SPECIALIST', api_role: 'PSYCHOLOGICAL_SPECIALIST', path: '/specialist/overview',
  },
};
export const SCREENSHOTS = [
  'specialist-activation-desktop.png',
  'specialist-activation-mobile.png',
  'admin-saved-task-desktop.png',
  'student-saved-cat-history.png',
  'teacher-saved-task-desktop.png',
  'teacher-saved-task-mobile.png',
];
export const SCREENSHOT_STAGES = {
  'specialist-activation-desktop.png': 'specialist_desktop_screenshot',
  'specialist-activation-mobile.png': 'specialist_mobile_screenshot',
  'admin-saved-task-desktop.png': 'admin_desktop_screenshot',
  'student-saved-cat-history.png': 'student_desktop_screenshot',
  'teacher-saved-task-desktop.png': 'teacher_desktop_screenshot',
  'teacher-saved-task-mobile.png': 'teacher_mobile_screenshot',
};
export const UI_STAGE_KEYS = [
  'specialist_login',
  'assets_read_200',
  'asset_template_http_200',
  'asset_bank_list_http_200',
  'asset_plan_list_http_200',
  'asset_template_flags_valid',
  'asset_bank_list_flags_valid',
  'asset_plan_list_flags_valid',
  'asset_template_shape_valid',
  'asset_template_metadata_valid',
  'asset_template_status_valid',
  'student_identity_resolved',
  'teacher_identity_resolved',
  'bank_created_201',
  'plan_created_201',
  'history_version_selected',
  'activation_created_201',
  'activation_metadata_matched',
  'specialist_desktop_screenshot',
  'specialist_mobile_screenshot',
  'admin_login',
  'class_created',
  'student_assigned',
  'teacher_assigned',
  'activation_selected',
  'task_published_201',
  'task_activation_matched',
  'admin_metadata_redacted',
  'admin_desktop_screenshot',
  'student_login',
  'cat_started',
  'cat_version_provenance_matched',
  'three_responses_saved',
  'cat_completed',
  'student_completed_history',
  'student_desktop_screenshot',
  'teacher_login',
  'teacher_completion_aggregate',
  'teacher_metadata_redacted',
  'teacher_desktop_screenshot',
  'teacher_mobile_screenshot',
  'sessions_cleaned',
];
export const STAGE_KEYS = [...UI_STAGE_KEYS, 'screenshots'];
export const SAFE_FAILURE_CLASSES = [
  'Error', 'TimeoutError', 'TypeError', 'RangeError', 'ReferenceError', 'ProtocolError', 'TargetClosedError',
];
export const API_STATUS_KEYS = [
  'template_read', 'bank_list_specialist', 'plan_list_specialist', 'bank_create', 'plan_create',
  'cat_catalog_reload',
  'auth_me_student', 'auth_me_teacher',
  'plan_version_detail', 'bank_version_detail',
  'activation_list_specialist', 'activation_create', 'activation_list_admin', 'class_create',
  'student_assignment', 'teacher_assignment', 'task_publish', 'task_list', 'task_start', 'assessment_state',
  'response_1', 'response_2', 'response_3', 'assessment_complete', 'teacher_progress',
];
export const API_PREFIX = '/api/v1/school/cat-assets';
export const LIVE_CHECKPOINT_NAME = 'live-stage.json';
const LIVE_EXTRA_STEP_KEYS = [
  'browser_launch', 'auth_me', 'csrf_request', 'csrf_response_body_read', 'header_checked',
  'mutation_request', 'mutation_response_body_read', 'history_catalog_reload', 'open_asset_workspace',
  'select_plans_tab', 'wait_plan_list', 'select_saved_plan', 'select_plan_version',
  'plan_version_detail_read', 'bank_version_detail_read', 'row_clicked', 'row_selection_confirmed',
  'selected_text_confirmed', 'read_activation_history',
  'task_start_validator', 'teacher_progress_validator', 'teacher_ui_validator',
];
const TASK_START_VALIDATION_CODES = [
  'HTTP_STATUS', 'ENVELOPE_SHAPE', 'DTO_KEYS', 'TASK_REF', 'ASSESSMENT_ID', 'SUBJECT_ID',
  'STATUS', 'ANSWERED_COUNT', 'ADMINISTERED_COUNT', 'MAX_ITEMS', 'CAN_COMPLETE',
  'CURRENT_ITEM', 'SELECTED_ITEM_ID', 'OPTION_SHAPE',
];
const TEACHER_PROGRESS_VALIDATION_CODES = [
  'HTTP_STATUS', 'BODY_READ_FAILED', 'ENVELOPE_SHAPE', 'ROWS_SHAPE', 'MATCHING_ROW_COUNT', 'DTO_KEYS',
  'CLASS_REF', 'TASK_REF', 'TASK_STATUS', 'OPENS_AT', 'DUE_AT', 'PUBLISHED_COUNT',
  'ACTIVE_COUNT', 'REVOKED_COUNT', 'NOT_STARTED_COUNT', 'CREATED_COUNT',
  'IN_PROGRESS_COUNT', 'COMPLETED_COUNT', 'ABANDONED_COUNT', 'INVALID_COUNT', 'FORBIDDEN_FIELD',
];
const TEACHER_UI_VALIDATION_CODES = [
  'ROW_NOT_VISIBLE', 'ROW_COUNT', 'COMPLETED_CELL_COUNT', 'COMPLETED_VALUE',
];
const CHECKPOINT_ERROR_CODES = [
  'BrowserEvaluationTimeout', 'ResponseBodyTimeout', 'BrowserActionTimeout',
  'CsrfRequestTimeout', 'MutationRequestTimeout',
];
export const CAT_COMPLETE_SELECTOR = 'button[aria-label="完成测评"], .assessment-complete-card .question-card__footer button';

const REF = {
  bank: /^CBANK_[A-Za-z0-9-]{36}$/,
  bankVersion: /^CBVER_[A-Za-z0-9-]{36}$/,
  plan: /^CPLAN_[A-Za-z0-9-]{36}$/,
  planVersion: /^CPVER_[A-Za-z0-9-]{36}$/,
  activation: /^CACT_[A-Za-z0-9-]{36}$/,
  task: /^TASK_[A-Za-z0-9_.-]{1,123}$/,
  assessment: /^ASSESS_[A-Za-z0-9_.-]{1,120}$/,
};
const BANK_KEYS = [
  'item_bank_id', 'version', 'instrument_id', 'target_population', 'measurement_model',
  'dimensions', 'items', 'status', 'metadata',
];
const ITEM_KEYS = [
  'item_id', 'dimension', 'stem', 'response_type', 'response_options', 'scoring', 'model',
  'parameters', 'source', 'status',
];
const CONFIG_KEYS = [
  'config_version', 'model', 'estimator', 'selection_method', 'min_items', 'max_items', 'se_threshold',
  'initial_theta', 'prior_mean', 'prior_sd', 'optimization_interval', 'seed', 'exposure_control', 'content_balancing',
];
const SYNTHETIC_METADATA_KEYS = [
  'synthetic', 'intended_use', 'psychological_interpretation_allowed',
  'instrument_version', 'notice', 'psychometric_status',
];
const ACTIVATION_KEYS = [
  'activation_ref', 'plan_version_ref', 'bank_version_ref', 'plan_name', 'plan_version_number',
  'bank_name', 'bank_version_number', 'status', 'revision', 'created_at', 'revoked_at',
];
const TASK_KEYS = [
  'task_ref', 'class_ref', 'status', 'opens_at', 'due_at', 'published_at', 'published_enrollment_count',
  'active_enrollment_count', 'revoked_enrollment_count', 'instrument_id', 'instrument_version',
  'activation_ref', 'plan_name', 'plan_version_number',
];
const TASK_START_KEYS = [
  'task_ref', 'assessment_id', 'subject_id', 'status', 'selected_item_id', 'current_item',
  'answered_count', 'administered_count', 'can_complete', 'max_items',
];
const ASSESSMENT_STATE_KEYS = [
  'assessment_id', 'subject_id', 'status', 'selected_item_id', 'current_item', 'current_index',
  'answered_count', 'administered_count', 'can_complete', 'max_items', 'cat_provider_version',
  'cat_item_bank_version', 'cat_config_version',
];
const TEACHER_PROGRESS_KEYS = [
  'class_ref', 'task_ref', 'task_status', 'opens_at', 'due_at', 'published_enrollment_count',
  'active_enrollment_count', 'revoked_enrollment_count', 'not_started_count', 'created_count',
  'in_progress_count', 'completed_count', 'abandoned_count', 'invalid_count',
];
const FORBIDDEN_PUBLIC_KEYS = new Set([
  'bank_document', 'config_document', 'payload_ciphertext', 'current_item', 'subject_id',
  'assessment_id', 'response', 'responses', 'student_user_id', 'user_id',
]);

const isRecord = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (value, keys) => isRecord(value)
  && Object.keys(value).sort().join('|') === [...keys].sort().join('|');
const safeText = (value, max = 200) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const integer = (value, low = 0, high = Number.MAX_SAFE_INTEGER) =>
  Number.isSafeInteger(value) && value >= low && value <= high;
const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const safeDate = (value) => safeText(value, 64) && Number.isFinite(Date.parse(value));
const flagsValid = (value) => value?.engineering_only === true
  && value?.psychological_interpretation_allowed === false;
const envelopeData = (value) => isRecord(value) && Object.hasOwn(value, 'data') ? value.data : null;
const visibleText = async (page) => page.locator('body').innerText();

function artifactPathAllowed(candidate) {
  if (typeof candidate !== 'string' || !path.isAbsolute(candidate)) return false;
  const base = path.resolve('D:\\Projects', WORKSPACE_PREFIX);
  const relative = path.relative(base, path.resolve(candidate));
  const parts = relative.split(path.sep);
  return parts.length === 2 && parts[0] === 'browser-qa'
    && /^\d{8}T\d{6}Z-[a-f0-9]{32}$/.test(parts[1]) && !path.isAbsolute(relative);
}

export function validPayload(payload) {
  if (!exactKeys(payload, ['accounts', 'artifact_dir', 'backend_url', 'credentials', 'frontend_url'])
    || payload.frontend_url !== FRONTEND_URL || payload.backend_url !== BACKEND_URL
    || !artifactPathAllowed(payload.artifact_dir)
    || !exactKeys(payload.accounts, Object.keys(ACCOUNT_ROUTES))
    || !exactKeys(payload.credentials, Object.keys(ACCOUNT_ROUTES))) return false;
  return Object.entries(ACCOUNT_ROUTES).every(([slot, expected]) => {
    const account = payload.accounts[slot];
    const credential = payload.credentials[slot];
    return exactKeys(account, ['role', 'api_role', 'path'])
      && account.role === expected.role && account.api_role === expected.api_role && account.path === expected.path
      && exactKeys(credential, ['username', 'password'])
      && typeof credential.username === 'string' && /^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(credential.username)
      && typeof credential.password === 'string' && credential.password.length >= 16 && credential.password.length <= 512;
  });
}

export function validSyntheticMetadata(value) {
  return isRecord(value)
    && Object.keys(value).every((key) => SYNTHETIC_METADATA_KEYS.includes(key))
    && value.synthetic === true && value.intended_use === 'engineering_test_only'
    && value.psychological_interpretation_allowed === false
    && (!Object.hasOwn(value, 'instrument_version') || value.instrument_version === null
      || safeText(value.instrument_version, 160))
    && (!Object.hasOwn(value, 'notice') || value.notice === null
      || (typeof value.notice === 'string' && value.notice.length <= 500))
    && (!Object.hasOwn(value, 'psychometric_status') || value.psychometric_status === null
      || value.psychometric_status === 'PENDING_PSYCHOMETRIC_CONFIRMATION');
}

export function validBankDocument(value, expectedItemCount = 3) {
  if (!exactKeys(value, BANK_KEYS) || !safeText(value.item_bank_id, 160) || !safeText(value.version, 160)
    || !safeText(value.instrument_id, 160) || !safeText(value.target_population, 160)
    || value.measurement_model !== 'GRM' || !Array.isArray(value.dimensions) || value.dimensions.length !== 1
    || !safeText(value.dimensions[0], 160) || !Array.isArray(value.items) || value.items.length !== expectedItemCount
    || value.status !== 'published' || !validSyntheticMetadata(value.metadata)) return false;
  const dimension = value.dimensions[0];
  const seen = new Set();
  return value.items.every((item) => {
    if (!exactKeys(item, ITEM_KEYS) || !/^ITEM_[A-Za-z0-9_.-]{1,122}$/.test(item.item_id)
      || seen.has(item.item_id) || item.dimension !== dimension || !safeText(item.stem, 2000)
      || item.response_type !== 'likert' || item.model !== 'GRM' || !safeText(item.source, 160)
      || !['published', 'demo', 'synthetic'].includes(item.status)
      || !['published', 'demo', 'synthetic'].includes(item.status) || !Array.isArray(item.response_options)
      || item.response_options.length < 2 || item.response_options.length > 10
      || !item.response_options.every((option) => safeText(option, 160))
      || !exactKeys(item.parameters, ['a', 'thresholds']) || !finite(item.parameters.a)
      || item.parameters.a <= 0 || item.parameters.a > 10 || !Array.isArray(item.parameters.thresholds)
      || item.parameters.thresholds.length !== item.response_options.length - 1
      || !item.parameters.thresholds.every(finite)
      || item.parameters.thresholds.some((current, index) => index > 0 && current <= item.parameters.thresholds[index - 1])
      || !isRecord(item.scoring) || Object.keys(item.scoring).length !== item.response_options.length
      || item.response_options.some((option) => !Object.hasOwn(item.scoring, option))) return false;
    const scores = item.response_options.map((option) => item.scoring[option]);
    if (!scores.every((score) => integer(score, 0, item.response_options.length - 1))
      || new Set(scores).size !== scores.length
      || scores.slice().sort((left, right) => left - right).some((score, index) => score !== index)) return false;
    seen.add(item.item_id);
    return true;
  });
}

export function validConfigDocument(value) {
  return exactKeys(value, CONFIG_KEYS) && safeText(value.config_version, 120)
    && value.model === 'GRM' && ['EAP', 'BM'].includes(value.estimator) && value.selection_method === 'MFI'
    && value.min_items === 3 && value.max_items === 3 && value.se_threshold === 0.001
    && finite(value.initial_theta) && finite(value.prior_mean) && finite(value.prior_sd) && value.prior_sd > 0 && value.prior_sd <= 10
    && Array.isArray(value.optimization_interval) && value.optimization_interval.length === 2
    && value.optimization_interval.every(finite) && value.optimization_interval[0] < value.optimization_interval[1]
    && integer(value.seed, 0, 4294967295) && value.exposure_control === 'none' && value.content_balancing === 'none';
}

export function validActivationMetadata(value, expectedPlanVersionRef) {
  return exactKeys(value, ACTIVATION_KEYS)
    && typeof value.activation_ref === 'string' && REF.activation.test(value.activation_ref)
    && value.plan_version_ref === expectedPlanVersionRef && REF.planVersion.test(value.plan_version_ref)
    && typeof value.bank_version_ref === 'string' && REF.bankVersion.test(value.bank_version_ref)
    && safeText(value.plan_name, 120) && integer(value.plan_version_number, 1)
    && safeText(value.bank_name, 120) && integer(value.bank_version_number, 1)
    && value.status === 'ACTIVE' && value.revision === 1 && safeDate(value.created_at) && value.revoked_at === null;
}

export function extractActivationCreate(responseStatus, envelope, expectedPlanVersionRef) {
  const value = envelopeData(envelope);
  if (responseStatus !== 201 || !exactKeys(value, [
    'engineering_only', 'psychological_interpretation_allowed', 'activation',
  ]) || !flagsValid(value) || !validActivationMetadata(value.activation, expectedPlanVersionRef)) return null;
  return value.activation;
}

export function validTaskPublishRequest(value, expectedActivationRef) {
  return exactKeys(value, ['opens_at', 'due_at', 'activation_ref'])
    && safeDate(value.opens_at) && (value.due_at === null || (safeDate(value.due_at) && value.due_at >= value.opens_at))
    && value.activation_ref === expectedActivationRef && REF.activation.test(value.activation_ref);
}

export function extractTaskPublication(responseStatus, envelope, expectedActivationRef) {
  const value = envelopeData(envelope);
  if (responseStatus !== 201 || !exactKeys(value, TASK_KEYS)
    || !safeText(value.task_ref, 128) || !REF.task.test(value.task_ref)
    || !safeText(value.class_ref, 128) || value.status !== 'PUBLISHED'
    || !safeDate(value.opens_at) || (value.due_at !== null && !safeDate(value.due_at))
    || !safeDate(value.published_at) || !integer(value.published_enrollment_count, 1)
    || value.active_enrollment_count !== value.published_enrollment_count || value.revoked_enrollment_count !== 0
    || !safeText(value.instrument_id, 128) || !safeText(value.instrument_version, 64)
    || value.activation_ref !== expectedActivationRef || !safeText(value.plan_name, 120)
    || !integer(value.plan_version_number, 1)) return null;
  if (Object.keys(value).some((key) => FORBIDDEN_PUBLIC_KEYS.has(key))) return null;
  return value;
}

export function extractTaskStart(responseStatus, envelope, expectedTaskRef) {
  if (taskStartValidationCode(responseStatus, envelope, expectedTaskRef) !== null) return null;
  return envelopeData(envelope);
}

export function taskStartValidationCode(responseStatus, envelope, expectedTaskRef) {
  if (responseStatus !== 200) return 'HTTP_STATUS';
  const value = envelopeData(envelope);
  if (!isRecord(envelope) || !Object.hasOwn(envelope, 'data') || !isRecord(value)) return 'ENVELOPE_SHAPE';
  if (!exactKeys(value, TASK_START_KEYS)) return 'DTO_KEYS';
  if (value.task_ref !== expectedTaskRef || !REF.task.test(value.task_ref)) return 'TASK_REF';
  if (!REF.assessment.test(value.assessment_id)) return 'ASSESSMENT_ID';
  if (!safeText(value.subject_id, 128)) return 'SUBJECT_ID';
  if (value.status !== 'created') return 'STATUS';
  if (value.answered_count !== 0) return 'ANSWERED_COUNT';
  // CAT state counts recorded traces. The first selected item is presented before
  // any trace exists, so a real initial session reports administered_count=0.
  if (!integer(value.administered_count, 0, 3)) return 'ADMINISTERED_COUNT';
  if (value.max_items !== 3) return 'MAX_ITEMS';
  if (value.can_complete !== false) return 'CAN_COMPLETE';
  const item = value.current_item;
  if (!isRecord(item) || !exactKeys(item, ['item_id', 'prompt', 'response_type', 'options'])
    || !safeText(item.item_id, 160) || !safeText(item.prompt, 2000)
    || item.response_type !== 'likert' || !Array.isArray(item.options)) return 'CURRENT_ITEM';
  if (value.selected_item_id !== item.item_id) return 'SELECTED_ITEM_ID';
  if (item.options.length < 2 || !item.options.every((option) => isRecord(option) && exactKeys(option, ['value', 'label'])
    && safeText(option.value, 160) && safeText(option.label, 160))) return 'OPTION_SHAPE';
  return null;
}

export function extractAssessmentState(responseStatus, envelope, expected) {
  const value = envelopeData(envelope);
  if (responseStatus !== 200 || !exactKeys(value, ASSESSMENT_STATE_KEYS)
    || value.assessment_id !== expected.assessmentId || !REF.assessment.test(value.assessment_id)
    || !safeText(value.subject_id, 128) || !['created', 'in_progress', 'completed'].includes(value.status)
    || !integer(value.answered_count, 0, 3) || !integer(value.administered_count, 0, 3)
    || value.max_items !== 3 || typeof value.can_complete !== 'boolean'
    || value.cat_item_bank_version !== expected.bankVersion
    || value.cat_config_version !== expected.configVersion
    || !safeText(value.cat_provider_version, 120)) return null;
  return value;
}

export function validResponseWrite(requestBody, responseState, expected) {
  return exactKeys(requestBody, ['item_id', 'response'])
    && safeText(requestBody.item_id, 160) && safeText(requestBody.response, 160)
    && extractAssessmentState(200, { data: responseState }, expected) !== null;
}

export function extractCompletion(responseStatus, envelope, expectedAssessmentId) {
  const value = envelopeData(envelope);
  if (responseStatus !== 200 || !isRecord(value) || value.schema_version !== 'assessment.v1'
    || value.assessment_id !== expectedAssessmentId || value.status !== 'completed') return null;
  return { assessment_id: value.assessment_id, status: value.status };
}

export function extractTeacherAggregate(responseStatus, envelope, expectedClassRef, expectedTaskRef) {
  if (teacherProgressValidationCode(responseStatus, envelope, expectedClassRef, expectedTaskRef) !== null) return null;
  const rows = envelopeData(envelope).filter((row) => row.task_ref === expectedTaskRef);
  return { completed_count: rows[0].completed_count, active_enrollment_count: rows[0].active_enrollment_count };
}

export function teacherProgressValidationCode(responseStatus, envelope, expectedClassRef, expectedTaskRef) {
  if (responseStatus !== 200) return 'HTTP_STATUS';
  const value = envelopeData(envelope);
  if (!isRecord(envelope) || !Object.hasOwn(envelope, 'data')) return 'ENVELOPE_SHAPE';
  if (!Array.isArray(value)) return 'ROWS_SHAPE';
  const rows = value.filter((row) => isRecord(row) && row.task_ref === expectedTaskRef);
  if (rows.length !== 1) return 'MATCHING_ROW_COUNT';
  const row = rows[0];
  if (!exactKeys(row, TEACHER_PROGRESS_KEYS)) return 'DTO_KEYS';
  if (row.class_ref !== expectedClassRef) return 'CLASS_REF';
  if (row.task_ref !== expectedTaskRef) return 'TASK_REF';
  if (row.task_status !== 'PUBLISHED') return 'TASK_STATUS';
  if (!safeDate(row.opens_at)) return 'OPENS_AT';
  if (row.due_at !== null && !safeDate(row.due_at)) return 'DUE_AT';
  const expectedCounts = [
    ['published_enrollment_count', 1, 'PUBLISHED_COUNT'],
    ['active_enrollment_count', 1, 'ACTIVE_COUNT'],
    ['revoked_enrollment_count', 0, 'REVOKED_COUNT'],
    ['not_started_count', 0, 'NOT_STARTED_COUNT'],
    ['created_count', 0, 'CREATED_COUNT'],
    ['in_progress_count', 0, 'IN_PROGRESS_COUNT'],
    ['completed_count', 1, 'COMPLETED_COUNT'],
    ['abandoned_count', 0, 'ABANDONED_COUNT'],
    ['invalid_count', 0, 'INVALID_COUNT'],
  ];
  for (const [key, expected, code] of expectedCounts) {
    if (!integer(row[key], 0) || row[key] !== expected) return code;
  }
  if (Object.keys(row).some((key) => FORBIDDEN_PUBLIC_KEYS.has(key))) return 'FORBIDDEN_FIELD';
  return null;
}

export function roleCleanupComplete(openedSessions, cleanedSessions) {
  return integer(openedSessions, 0, 6) && integer(cleanedSessions, 0, 6)
    && openedSessions === cleanedSessions;
}

export function extractAuthenticatedMember(responseStatus, envelope, expectedRole) {
  const actor = envelopeData(envelope);
  if (responseStatus !== 200 || !exactKeys(actor, ['user_id', 'role']) || actor.role !== expectedRole
    || typeof actor.user_id !== 'string' || !/^USER_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/.test(actor.user_id)) return null;
  return actor.user_id;
}

export function validAssignmentRequest(role, body, expectedUserId) {
  const field = role === 'student' ? 'student_user_id' : role === 'teacher' ? 'teacher_user_id' : null;
  return field !== null && typeof expectedUserId === 'string'
    && /^USER_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/.test(expectedUserId)
    && exactKeys(body, [field]) && body[field] === expectedUserId;
}

export function summarizeWorkflow(stages, screenshotFiles, artifactDir, runnerExitCode = 0, failure = null, apiStatuses = {}) {
  const exactStages = isRecord(stages) && Object.keys(stages).length === STAGE_KEYS.length
    && STAGE_KEYS.every((key) => Object.hasOwn(stages, key) && ['PASS', 'FAIL'].includes(stages[key]));
  const screenshotsValid = Array.isArray(screenshotFiles) && screenshotFiles.length === SCREENSHOTS.length
    && new Set(screenshotFiles).size === SCREENSHOTS.length && SCREENSHOTS.every((name) => screenshotFiles.includes(name));
  const safeStages = Object.fromEntries(STAGE_KEYS.map((key) => [
    key, exactStages && stages[key] === 'PASS' ? 'PASS' : 'FAIL',
  ]));
  for (const [name, stage] of Object.entries(SCREENSHOT_STAGES)) {
    let exists = false;
    try { exists = screenshotsValid && fsStat(path.join(artifactDir, name)); } catch { /* fixed fail */ }
    if (!exists) safeStages[stage] = 'FAIL';
  }
  const statuses = Object.fromEntries(API_STATUS_KEYS.flatMap((key) =>
    Number.isInteger(apiStatuses[key]) && apiStatuses[key] >= 100 && apiStatuses[key] <= 599
      ? [[key, apiStatuses[key]]] : []));
  const passed = runnerExitCode === 0 && exactStages && screenshotsValid
    && STAGE_KEYS.every((key) => safeStages[key] === 'PASS');
  const result = {
    workflow: 'synthetic-cat-activation', status: passed ? 'PASS' : 'FAIL',
    stages: safeStages, screenshots: passed ? [...SCREENSHOTS] : [], api_statuses: statuses,
  };
  if (!passed && failure && UI_STAGE_KEYS.includes(failure.stage)) {
    result.failure = {
      stage: failure.stage,
      error_class: SAFE_FAILURE_CLASSES.includes(failure.error_class) ? failure.error_class : 'Error',
    };
  }
  return result;
}

const fsStat = (file) => {
  const fs = require('node:fs');
  return fs.statSync(file).isFile();
};

const pad = (value) => String(value).padStart(2, '0');
const localInputDate = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
const shortRef = (value) => value.slice(-6);
const taskLabel = (reference) => `任务 ${shortRef(reference)}`;
const emptyStages = () => Object.fromEntries(STAGE_KEYS.map((key) => [key, 'FAIL']));
const safeErrorClass = (error) => SAFE_FAILURE_CLASSES.includes(error?.name) ? error.name : 'Error';
const randomId = () => globalThis.crypto?.randomUUID?.();

export function validLiveCheckpoint(stage, step, status) {
  const validStatus = ['STARTED', 'PASS', 'FAIL'].includes(status)
    || /^HTTP_[1-5][0-9]{2}$/.test(status)
    || /^FAIL_AFTER_HTTP_[1-5][0-9]{2}$/.test(status)
    || TASK_START_VALIDATION_CODES.some((code) => status === `INVALID_${code}`)
    || TEACHER_PROGRESS_VALIDATION_CODES.some((code) => status === `INVALID_${code}`)
    || TEACHER_UI_VALIDATION_CODES.some((code) => status === `INVALID_${code}`)
    || CHECKPOINT_ERROR_CODES.some((code) => status === `ERROR_${code}`);
  return UI_STAGE_KEYS.includes(stage)
    && (UI_STAGE_KEYS.includes(step) || API_STATUS_KEYS.includes(step) || LIVE_EXTRA_STEP_KEYS.includes(step))
    && validStatus;
}

export function writeLiveCheckpoint(artifactDir, stage, step, status) {
  if (!validLiveCheckpoint(stage, step, status) || !artifactPathAllowed(artifactDir)) return false;
  const fs = require('node:fs');
  const target = path.join(artifactDir, LIVE_CHECKPOINT_NAME);
  const temporary = `${target}.tmp`;
  try {
    fs.writeFileSync(temporary, JSON.stringify({ stage, step, status }), { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporary, target);
    return true;
  } catch {
    try { fs.rmSync(temporary, { force: true }); } catch { /* fixed diagnostic only */ }
    return false;
  }
}

async function withDeadline(promise, timeoutMs, errorCode) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(errorCode)), timeoutMs);
  });
  try { return await Promise.race([promise, deadline]); }
  finally { clearTimeout(timer); }
}

async function evaluateWithDeadline(page, callback, argument, timeoutMs = 35000) {
  return withDeadline(page.evaluate(callback, argument), timeoutMs, 'BrowserEvaluationTimeout');
}

async function responseJson(response, timeoutMs = 10000) {
  return withDeadline(response.json(), timeoutMs, 'ResponseBodyTimeout');
}

async function clickAndWait(page, requestMatch, click, timeout = 30000, onResponse = null) {
  const requestPromise = page.waitForRequest(requestMatch, { timeout });
  const responsePromise = page.waitForResponse((response) => requestMatch(response.request()), { timeout })
    .then((response) => {
      if (onResponse) onResponse(response.status());
      return response;
    });
  const clickPromise = Promise.resolve().then(click);
  const [request, response] = await withDeadline(
    Promise.all([requestPromise, responsePromise, clickPromise]), timeout + 10000, 'BrowserActionTimeout',
  );
  return { request, response, envelope: await responseJson(response) };
}

export async function doRealApiMutation(
  requestContext, payload, pathname, body, idempotencyKey, expectedStatus, apiKey, apiStatuses, checkpoint,
) {
  checkpoint(apiKey, 'STARTED');
  checkpoint('csrf_request', 'STARTED');
  const csrfResponse = await withDeadline(requestContext.get(`${payload.backend_url}/api/v1/auth/csrf`, {
    headers: { Accept: 'application/json' }, timeout: 15000, failOnStatusCode: false, maxRetries: 0,
  }), 20000, 'CsrfRequestTimeout');
  checkpoint('csrf_request', `HTTP_${csrfResponse.status()}`);
  if (csrfResponse.status() !== 200) throw new Error('CsrfStatusMismatch');
  checkpoint('csrf_request', 'PASS');
  checkpoint('csrf_response_body_read', 'STARTED');
  const csrfEnvelope = await responseJson(csrfResponse);
  checkpoint('csrf_response_body_read', 'PASS');
  const token = csrfEnvelope?.data?.csrf_token;
  if (typeof token !== 'string' || !token) throw new Error('CsrfUnavailable');
  const requestHeaders = {
    Accept: 'application/json', 'Content-Type': 'application/json',
    'X-CSRF-Token': token, 'Idempotency-Key': idempotencyKey,
  };
  const serializedBody = JSON.stringify(body);
  checkpoint('header_checked', 'STARTED');
  if (requestHeaders.Accept !== 'application/json' || requestHeaders['Content-Type'] !== 'application/json'
    || requestHeaders['Idempotency-Key'] !== idempotencyKey || !requestHeaders['X-CSRF-Token']) {
    throw new Error('MutationHeadersInvalid');
  }
  checkpoint('header_checked', 'PASS');
  checkpoint('mutation_request', 'STARTED');
  const response = await withDeadline(requestContext.post(`${payload.backend_url}${pathname}`, {
    headers: requestHeaders, data: serializedBody, timeout: 30000, failOnStatusCode: false, maxRetries: 0,
  }), 35000, 'MutationRequestTimeout');
  apiStatuses[apiKey] = response.status();
  checkpoint(apiKey, `HTTP_${response.status()}`);
  if (response.status() !== expectedStatus || requestHeaders['Idempotency-Key'] !== idempotencyKey
    || !requestHeaders['X-CSRF-Token'] || JSON.stringify(JSON.parse(serializedBody)) !== serializedBody) {
    throw new Error('MutationStatusOrHeadersMismatch');
  }
  checkpoint('mutation_response_body_read', 'STARTED');
  const envelope = await responseJson(response);
  checkpoint('mutation_response_body_read', 'PASS');
  checkpoint(apiKey, 'PASS');
  return {
    requestBody: JSON.parse(serializedBody),
    requestHeaders: Object.fromEntries(Object.entries(requestHeaders).map(([key, value]) => [key.toLowerCase(), value])),
    response,
    envelope,
  };
}

async function waitForGet(page, pathname, apiKey, apiStatuses) {
  const match = (response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname === pathname;
  const response = await page.waitForResponse(match, { timeout: 30000 });
  apiStatuses[apiKey] = response.status();
  if (response.status() !== 200) throw new Error('ReadStatusMismatch');
  return responseJson(response);
}

export async function refreshTeacherProgress(page) {
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('button')]
      .find((candidate) => candidate.textContent?.trim() === '刷新');
    return Boolean(button && !button.disabled);
  }, null, { timeout: 20000 });
  const progressPath = '/api/v1/school/teacher/task-progress';
  const match = (response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname === progressPath;
  const responsePromise = page.waitForResponse(match, { timeout: 30000 }).then(
    (response) => response, () => null,
  );
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  const response = await responsePromise;
  if (!response) throw new Error('TeacherProgressUiRequestUnavailable');
  return response;
}

async function startRole(browser, payload, slot, onSessionOpen) {
  const context = await browser.newContext({ serviceWorkers: 'block' });
  let page;
  try { page = await context.newPage(); }
  catch (error) {
    try { await withDeadline(context.close(), 8000, 'ContextCloseTimeout'); } catch { /* bounded context cleanup */ }
    throw error;
  }
  const credential = payload.credentials[slot];
  const session = {
    context, page, loginSubmitted: false,
    credential: { username: credential.username, password: credential.password },
  };
  onSessionOpen(session);
  await page.goto(`${payload.frontend_url}/login`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('textbox', { name: 'Username' }).fill(session.credential.username);
  await page.getByLabel('Password').fill(session.credential.password);
  session.loginSubmitted = true;
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  const picker = page.locator('#school-context');
  if (await picker.isVisible({ timeout: 1200 }).catch(() => false)) {
    const options = await picker.locator('option:not([disabled])').evaluateAll((items) => items.map((item) => item.value));
    if (options.length !== 1 || !options[0]) throw new Error('SchoolContextUnavailable');
    await picker.selectOption(options[0]);
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
  }
  await page.waitForURL((url) => url.pathname === payload.accounts[slot].path, { timeout: 20000 });
  if (await page.getByLabel('Password').isVisible().catch(() => false)) throw new Error('PasswordFieldStillVisible');
  return session;
}

async function logoutSession(session, payload) {
  let logoutOk = !session.loginSubmitted;
  let closed = false;
  try {
    if (session.loginSubmitted) {
      try {
        await session.page.locator('.account-menu > summary').click({ timeout: 3000 });
        await session.page.getByRole('button', { name: '退出登录', exact: true }).click({ timeout: 3000 });
        await session.page.waitForURL((url) => url.pathname === '/login', { timeout: 10000 });
        logoutOk = true;
      } catch {
        logoutOk = await evaluateWithDeadline(session.page, async (backendUrl) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 5000);
          try {
            const csrf = await fetch(`${backendUrl}/api/v1/auth/csrf`, {
              credentials: 'include', signal: controller.signal,
            });
            if (!csrf.ok) return false;
            const token = (await csrf.json())?.data?.csrf_token;
            if (typeof token !== 'string' || !token) return false;
            const result = await fetch(`${backendUrl}/api/v1/auth/logout`, {
              method: 'POST', credentials: 'include', headers: { 'X-CSRF-Token': token },
              signal: controller.signal,
            });
            return result.ok;
          } finally { clearTimeout(timer); }
        }, payload.backend_url, 7000);
      }
    }
  } catch { logoutOk = false; }
  try { await withDeadline(session.context.close(), 8000, 'ContextCloseTimeout'); closed = true; } catch { closed = false; }
  if (session.credential) { session.credential.username = ''; session.credential.password = ''; }
  return logoutOk && closed;
}

async function screenshot(page, payload, name, viewport) {
  if (!SCREENSHOTS.includes(name)) throw new Error('UnexpectedScreenshot');
  await page.setViewportSize(viewport);
  await evaluateWithDeadline(page, () => {
    window.scrollTo(0, 0);
    return new Promise((resolve) => requestAnimationFrame(resolve));
  }, null, 5000);
  await page.screenshot({
    path: path.join(payload.artifact_dir, name), fullPage: true, animations: 'disabled',
    mask: ['.account-menu', 'input, textarea, select', '.question-card', '.assessment-result'].map((selector) => page.locator(selector)),
  });
}

async function readAssetsThroughSpecialistUi(page, payload, apiStatuses, stages, setFailureStage) {
  const catCatalog = page.waitForResponse((response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/api/v1/school/cat-management/catalog', { timeout: 30000 });
  await page.goto(`${payload.frontend_url}/specialist/cat`, { waitUntil: 'domcontentloaded' });
  if ((await catCatalog).status() !== 200) throw new Error('SpecialistCatalogUnavailable');
  const paths = ['/template', '/banks', '/plans'].map((suffix) => page.waitForResponse((response) =>
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === `${API_PREFIX}${suffix}`, { timeout: 30000 }));
  await page.getByRole('button', { name: '题库与方案', exact: true }).click();
  const responses = await Promise.all(paths);
  const values = [];
  const statusKeys = ['template_read', 'bank_list_specialist', 'plan_list_specialist'];
  const httpStages = ['asset_template_http_200', 'asset_bank_list_http_200', 'asset_plan_list_http_200'];
  const flagStages = ['asset_template_flags_valid', 'asset_bank_list_flags_valid', 'asset_plan_list_flags_valid'];
  for (let index = 0; index < responses.length; index += 1) {
    apiStatuses[statusKeys[index]] = responses[index].status();
    setFailureStage(httpStages[index]);
    if (responses[index].status() !== 200) throw new Error('AssetPanelUnavailable');
    stages[httpStages[index]] = 'PASS';
    const envelope = await responseJson(responses[index]);
    const value = envelopeData(envelope);
    setFailureStage(flagStages[index]);
    if (!flagsValid(value)) throw new Error('AssetPanelFlagsInvalid');
    stages[flagStages[index]] = 'PASS';
    values.push(value);
  }
  setFailureStage('asset_template_shape_valid');
  await page.getByRole('heading', { name: '题库', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  if (!exactKeys(values[0], [
    'engineering_only', 'psychological_interpretation_allowed', 'bank_document', 'config_document', 'item_count', 'dimension_count',
  ]) || !integer(values[0].item_count, 3, 100) || values[0].item_count !== values[0].bank_document?.items?.length
    || !isRecord(values[0].config_document) || !Array.isArray(values[1]?.items)
    || typeof values[1]?.has_more !== 'boolean' || !Array.isArray(values[2]?.items)
    || typeof values[2]?.has_more !== 'boolean') throw new Error('AssetTemplateIncompatible');
  stages.asset_template_shape_valid = 'PASS';
  setFailureStage('asset_template_metadata_valid');
  if (!validSyntheticMetadata(values[0].bank_document?.metadata)
    || values[0].bank_document.metadata.instrument_version !== 'synthetic_item_bank.v1 / demo.v1') {
    throw new Error('AssetTemplateMetadataIncompatible');
  }
  stages.asset_template_metadata_valid = 'PASS';
  setFailureStage('asset_template_status_valid');
  if (!validBankDocument(values[0].bank_document, values[0].item_count)) {
    throw new Error('AssetTemplateStatusIncompatible');
  }
  stages.asset_template_status_valid = 'PASS';
  return { template: values[0], banks: values[1], plans: values[2] };
}

export function makeBank(templateBank, runId) {
  const document = structuredClone(templateBank);
  document.item_bank_id = `ITEMBANK_synthetic_cat_qa_${runId.slice(0, 8)}`;
  document.version = `synthetic.cat.qa.bank.${runId.slice(0, 8)}`;
  document.status = 'published';
  document.metadata = {
    ...structuredClone(templateBank.metadata),
    instrument_version: 'synthetic_item_bank.v1 / demo.v1',
    synthetic: true,
    intended_use: 'engineering_test_only',
    psychological_interpretation_allowed: false,
  };
  document.items = document.items.slice(0, 3).map((item, index) => ({
    ...item,
    item_id: `ITEM_synthetic_cat_qa_${runId.slice(0, 8)}_${index + 1}`,
    stem: `合成浏览器工程题 ${index + 1}`,
    status: 'published',
  }));
  return document;
}

function makeConfig(templateConfig, runId) {
  return {
    ...structuredClone(templateConfig),
    config_version: `synthetic.cat.qa.${runId.slice(0, 8)}`,
    min_items: 3,
    max_items: 3,
    se_threshold: 0.001,
  };
}

async function captureRequest(page, method, pathname, action) {
  const matches = (request) => request.method() === method && new URL(request.url()).pathname === pathname;
  const requestPromise = page.waitForRequest(matches, { timeout: 30000 });
  const responsePromise = page.waitForResponse((response) => matches(response.request()), { timeout: 30000 });
  const actionPromise = Promise.resolve().then(action);
  const [request, response] = await withDeadline(
    Promise.all([requestPromise, responsePromise, actionPromise]), 40000, 'BrowserActionTimeout',
  );
  return { request, response, envelope: await responseJson(response) };
}

async function readAuthenticatedMemberId(session, payload, expectedRole, apiKey, apiStatuses) {
  const result = await evaluateWithDeadline(session.page, async (backendUrl) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(`${backendUrl}/api/v1/auth/me`, {
        credentials: 'include', headers: { Accept: 'application/json' }, signal: controller.signal,
      });
      const envelope = await response.json();
      const actor = envelope?.data;
      return {
        status: response.status,
        actor: actor && typeof actor === 'object' && !Array.isArray(actor)
          ? { user_id: actor.user_id, role: actor.role } : null,
      };
    } finally { clearTimeout(timer); }
  }, payload.backend_url);
  apiStatuses[apiKey] = result.status;
  const userId = extractAuthenticatedMember(result.status, { data: result.actor }, expectedRole);
  if (!userId) throw new Error('AuthenticatedMemberIdentityMismatch');
  return userId;
}

export async function prepareSavedPlanHistory(page, planName, apiStatuses, checkpoint) {
  checkpoint('history_catalog_reload', 'STARTED');
  const reloadCatalog = page.waitForResponse((response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/api/v1/school/cat-management/catalog', { timeout: 30000 }).then(
    (response) => response, () => null,
  );
  await page.reload({ waitUntil: 'domcontentloaded' });
  const catalogResponse = await reloadCatalog;
  if (!catalogResponse) throw new Error('CatalogReloadUnavailable');
  apiStatuses.cat_catalog_reload = catalogResponse.status();
  checkpoint('history_catalog_reload', `HTTP_${catalogResponse.status()}`);
  if (catalogResponse.status() !== 200) throw new Error('CatalogReloadStatusMismatch');
  checkpoint('history_catalog_reload', 'PASS');

  checkpoint('open_asset_workspace', 'STARTED');
  await page.getByRole('button', { name: '题库与方案', exact: true }).click();
  await page.locator('.asset-workspace').waitFor({ state: 'visible', timeout: 15000 });
  checkpoint('open_asset_workspace', 'PASS');

  checkpoint('select_plans_tab', 'STARTED');
  const plansTab = page.locator('.asset-tabs').getByRole('button', { name: 'CAT 方案', exact: true });
  await plansTab.waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForFunction(() => {
    const buttons = Array.from(document.querySelectorAll('.asset-tabs button'));
    const tab = buttons.find((button) => button.textContent?.trim() === 'CAT 方案');
    return Boolean(tab && !tab.disabled);
  }, null, { timeout: 20000 });
  await plansTab.click();
  await page.waitForFunction(() => {
    const buttons = Array.from(document.querySelectorAll('.asset-tabs button'));
    const tab = buttons.find((button) => button.textContent?.trim() === 'CAT 方案');
    return Boolean(tab && tab.getAttribute('aria-pressed') === 'true' && !tab.disabled);
  }, null, { timeout: 15000 });
  checkpoint('select_plans_tab', 'PASS');

  checkpoint('wait_plan_list', 'STARTED');
  await page.locator('.asset-state[aria-busy="true"]').waitFor({ state: 'detached', timeout: 15000 });
  await page.getByRole('heading', { name: 'CAT 方案', exact: true }).waitFor({ state: 'visible', timeout: 15000 });
  const planRow = page.locator('.asset-list__items .asset-row').filter({ hasText: planName });
  await planRow.waitFor({ state: 'visible', timeout: 20000 });
  checkpoint('wait_plan_list', 'PASS');

  checkpoint('select_saved_plan', 'STARTED');
  await planRow.click();
  const history = page.locator('.asset-history__row');
  await history.first().waitFor({ state: 'visible', timeout: 20000 });
  checkpoint('select_saved_plan', 'PASS');
  return { catalogResponse, history };
}

export async function selectPlanHistoryVersion(
  page, history, planName, versionNumber, planVersionRef, bankVersionRef, apiStatuses, checkpoint,
) {
  checkpoint('select_plan_version', 'STARTED');
  const versionLabel = `版本 ${versionNumber} ·`;
  const versionRow = history.filter({ hasText: versionLabel });
  await versionRow.waitFor({ state: 'visible', timeout: 15000 });

  const planVersionPath = `${API_PREFIX}/plan-versions/${encodeURIComponent(planVersionRef)}`;
  const planVersionResponse = page.waitForResponse((response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname === planVersionPath, { timeout: 30000 }).then(
    (response) => response, () => null,
  );
  const bankVersionPath = `${API_PREFIX}/bank-versions/${encodeURIComponent(bankVersionRef)}`;
  const bankVersionResponse = page.waitForResponse((response) => response.request().method() === 'GET'
    && new URL(response.url()).pathname === bankVersionPath, { timeout: 30000 }).then(
    (response) => response, () => null,
  );

  checkpoint('plan_version_detail_read', 'STARTED');
  checkpoint('bank_version_detail_read', 'STARTED');
  checkpoint('row_clicked', 'STARTED');
  await versionRow.click();
  checkpoint('row_clicked', 'PASS');

  const planResponse = await planVersionResponse;
  if (!planResponse) throw new Error('PlanVersionDetailUnavailable');
  apiStatuses.plan_version_detail = planResponse.status();
  checkpoint('plan_version_detail_read', `HTTP_${planResponse.status()}`);
  if (planResponse.status() !== 200) throw new Error('PlanVersionDetailStatusMismatch');
  checkpoint('plan_version_detail_read', 'PASS');

  const bankResponse = await bankVersionResponse;
  if (!bankResponse) throw new Error('BankVersionDetailUnavailable');
  apiStatuses.bank_version_detail = bankResponse.status();
  checkpoint('bank_version_detail_read', `HTTP_${bankResponse.status()}`);
  if (bankResponse.status() !== 200) throw new Error('BankVersionDetailStatusMismatch');
  checkpoint('bank_version_detail_read', 'PASS');

  checkpoint('row_selection_confirmed', 'STARTED');
  await page.waitForFunction((label) => {
    const rows = Array.from(document.querySelectorAll('.asset-editor .asset-history__row'));
    const row = rows.find((candidate) => candidate.textContent?.includes(label));
    return row?.getAttribute('aria-pressed') === 'true';
  }, versionLabel, { timeout: 15000 });
  checkpoint('row_selection_confirmed', 'PASS');

  checkpoint('selected_text_confirmed', 'STARTED');
  const selectedVersion = page.locator('.asset-editor .asset-history__selected');
  await selectedVersion.waitFor({ state: 'visible', timeout: 15000 });
  const selectedText = await selectedVersion.innerText();
  if (!selectedText.startsWith(`已选择 ${planName} v${versionNumber}：绑定 `)) {
    throw new Error('PlanVersionSelectionMismatch');
  }
  checkpoint('selected_text_confirmed', 'PASS');
  checkpoint('select_plan_version', 'PASS');
  return selectedText;
}

export async function runWorkflow(payload, { chromium: browserLauncher = chromium } = {}) {
  if (!validPayload(payload)) return summarizeWorkflow(emptyStages(), [], payload?.artifact_dir, 2);
  const stages = emptyStages();
  const screenshotFiles = [];
  const apiStatuses = {};
  let browser;
  let session;
  let failure = null;
  let failureStage = 'specialist_login';
  let cleanedSessions = 0;
  let classRef = '';
  let taskRef = '';
  let assessmentId = '';
  let activation = null;
  let planVersionRef = '';
  let bankDocument;
  let configDocument;
  let taskShortRef = '';
  let openedSessions = 0;
  let liveStage = 'specialist_login';
  let liveStep = 'browser_launch';
  let liveStatus = 'STARTED';
  const checkpoint = (step, status, stage = liveStage) => {
    liveStage = stage;
    liveStep = step;
    liveStatus = status;
    writeLiveCheckpoint(payload.artifact_dir, stage, step, status);
  };
  const setFailureStage = (stage) => {
    failureStage = stage;
    checkpoint(stage, 'STARTED', stage);
  };
  let studentUserId = '';
  let teacherUserId = '';
  try {
    checkpoint('browser_launch', 'STARTED', 'specialist_login');
    browser = await browserLauncher.launch({ headless: true });
    checkpoint('browser_launch', 'PASS', 'specialist_login');

    session = await startRole(browser, payload, 'alpha.psychological_specialist', (opened) => {
      session = opened;
      openedSessions += 1;
    });
    stages.specialist_login = 'PASS';
    setFailureStage('assets_read_200');
    const { template } = await readAssetsThroughSpecialistUi(
      session.page, payload, apiStatuses, stages, setFailureStage,
    );
    stages.assets_read_200 = 'PASS';

    setFailureStage('bank_created_201');
    const runId = randomId();
    if (typeof runId !== 'string') throw new Error('SecureRandomUnavailable');
    const bankName = `合成浏览器题库 ${runId.slice(0, 8)}`;
    const planName = `合成浏览器方案 ${runId.slice(0, 8)}`;
    bankDocument = makeBank(template.bank_document, runId);
    configDocument = makeConfig(template.config_document, runId);
    if (!validBankDocument(bankDocument) || !validConfigDocument(configDocument)) throw new Error('PreparedAssetsInvalid');

    const bankKey = `synthetic-cat-activation-qa-${runId}-bank`;
    const bankMutation = await doRealApiMutation(
      session.page.request, payload, `${API_PREFIX}/banks`, { display_name: bankName, bank_document: bankDocument },
      bankKey, 201, 'bank_create', apiStatuses, (step, status) => checkpoint(step, status),
    );
    const bankValue = envelopeData(bankMutation.envelope);
    const bankRef = bankValue?.bank?.bank_ref;
    const bankVersionRef = bankValue?.version_ref;
    if (!flagsValid(bankValue) || !REF.bank.test(String(bankRef)) || !REF.bankVersion.test(String(bankVersionRef))
      || bankValue.bank?.display_name !== bankName || bankValue.bank?.versions?.length !== 1
      || bankValue.bank.versions[0]?.version_ref !== bankVersionRef
      || bankValue.bank.versions[0]?.item_count !== 3) throw new Error('BankResponseMismatch');
    const bankRequest = bankMutation.requestBody;
    if (!exactKeys(bankRequest, ['display_name', 'bank_document']) || bankRequest.display_name !== bankName
      || !validBankDocument(bankRequest.bank_document) || bankMutation.requestHeaders['idempotency-key'] !== bankKey
      || !bankMutation.requestHeaders['x-csrf-token']) {
      throw new Error('BankRequestMismatch');
    }
    stages.bank_created_201 = 'PASS';

    setFailureStage('plan_created_201');
    const planKey = `synthetic-cat-activation-qa-${runId}-plan`;
    const planBody = { display_name: planName, bank_version_ref: bankVersionRef, config_document: configDocument };
    const planMutation = await doRealApiMutation(
      session.page.request, payload, `${API_PREFIX}/plans`, planBody, planKey, 201, 'plan_create', apiStatuses,
      (step, status) => checkpoint(step, status),
    );
    const planValue = envelopeData(planMutation.envelope);
    planVersionRef = planValue?.version_ref ?? '';
    if (!flagsValid(planValue) || !REF.plan.test(String(planValue?.plan?.plan_ref))
      || !REF.planVersion.test(planVersionRef) || planValue.plan?.display_name !== planName
      || planValue.plan?.versions?.length !== 1 || planValue.plan.versions[0]?.version_ref !== planVersionRef
      || planValue.plan.versions[0]?.version_number !== 1) throw new Error('PlanResponseMismatch');
    const actualPlanRequest = planMutation.requestBody;
    if (!exactKeys(actualPlanRequest, ['display_name', 'bank_version_ref', 'config_document'])
      || actualPlanRequest.display_name !== planName || actualPlanRequest.bank_version_ref !== bankVersionRef
      || !validConfigDocument(actualPlanRequest.config_document)
      || planMutation.requestHeaders['idempotency-key'] !== planKey
      || !planMutation.requestHeaders['x-csrf-token']) throw new Error('PlanRequestMismatch');
    stages.plan_created_201 = 'PASS';

    setFailureStage('history_version_selected');
    const { catalogResponse, history } = await prepareSavedPlanHistory(
      session.page, planName, apiStatuses, (step, status) => checkpoint(step, status),
    );
    const activationHistoryPromise = session.page.waitForResponse((response) => {
      const url = new URL(response.url());
      return response.request().method() === 'GET' && url.pathname === `${API_PREFIX}/activations`
        && url.searchParams.get('plan_version_ref') === planVersionRef;
    }, { timeout: 30000 }).then((response) => response, () => null);
    checkpoint('read_activation_history', 'STARTED');
    await selectPlanHistoryVersion(
      session.page, history, planName, 1, planVersionRef, bankVersionRef, apiStatuses,
      (step, status) => checkpoint(step, status),
    );
    const activationHistoryResponse = await activationHistoryPromise;
    if (!activationHistoryResponse) throw new Error('ActivationHistoryUnavailable');
    apiStatuses.activation_list_specialist = activationHistoryResponse.status();
    checkpoint('read_activation_history', `HTTP_${activationHistoryResponse.status()}`);
    if (activationHistoryResponse.status() !== 200) throw new Error('ActivationHistoryStatusMismatch');
    const specialistActivationPage = envelopeData(await responseJson(activationHistoryResponse));
    if (activationHistoryResponse.status() !== 200 || !flagsValid(specialistActivationPage)
      || !exactKeys(specialistActivationPage, [
        'engineering_only', 'psychological_interpretation_allowed', 'items', 'has_more',
      ]) || !Array.isArray(specialistActivationPage.items) || specialistActivationPage.items.length !== 0
      || specialistActivationPage.has_more !== false) throw new Error('SpecialistActivationHistoryInvalid');
    checkpoint('read_activation_history', 'PASS');
    checkpoint('select_plan_version', 'PASS');
    stages.history_version_selected = 'PASS';

    setFailureStage('activation_created_201');
    const activationPath = `${API_PREFIX}/plan-versions/${planVersionRef}/activations`;
    const activationResult = await captureRequest(
      session.page, 'POST', activationPath,
      () => session.page.getByRole('button', { name: '启用此版本', exact: true }).click(),
    );
    apiStatuses.activation_create = activationResult.response.status();
    const activationValue = extractActivationCreate(activationResult.response.status(), activationResult.envelope, planVersionRef);
    const activationRequest = activationResult.request.postDataJSON();
    if (!activationValue || activationValue.bank_version_ref !== bankVersionRef
      || !exactKeys(activationRequest, []) || !activationResult.request.headers()['idempotency-key']
      || !activationResult.request.headers()['x-csrf-token']) throw new Error('ActivationResponseMismatch');
    activation = activationValue;
    stages.activation_created_201 = 'PASS';
    stages.activation_metadata_matched = 'PASS';
    const specialistText = await visibleText(session.page);
    if (specialistText.includes(activation.activation_ref) || specialistText.includes(planVersionRef)) {
      throw new Error('SpecialistReferenceRendered');
    }
    await screenshot(session.page, payload, SCREENSHOTS[0], { width: 1365, height: 900 });
    screenshotFiles.push(SCREENSHOTS[0]);
    stages.specialist_desktop_screenshot = 'PASS';
    await screenshot(session.page, payload, SCREENSHOTS[1], { width: 390, height: 844 });
    screenshotFiles.push(SCREENSHOTS[1]);
    stages.specialist_mobile_screenshot = 'PASS';
    if (!await logoutSession(session, payload)) throw new Error('SpecialistLogoutFailed');
    cleanedSessions += 1;
    session = null;

    setFailureStage('student_identity_resolved');
    session = await startRole(browser, payload, 'alpha.student', (opened) => {
      session = opened;
      openedSessions += 1;
    });
    studentUserId = await readAuthenticatedMemberId(session, payload, 'STUDENT', 'auth_me_student', apiStatuses);
    stages.student_identity_resolved = 'PASS';
    if (!await logoutSession(session, payload)) throw new Error('StudentIdentityLogoutFailed');
    cleanedSessions += 1;
    session = null;

    setFailureStage('teacher_identity_resolved');
    session = await startRole(browser, payload, 'alpha.teacher', (opened) => {
      session = opened;
      openedSessions += 1;
    });
    teacherUserId = await readAuthenticatedMemberId(session, payload, 'TEACHER', 'auth_me_teacher', apiStatuses);
    stages.teacher_identity_resolved = 'PASS';
    if (!await logoutSession(session, payload)) throw new Error('TeacherIdentityLogoutFailed');
    cleanedSessions += 1;
    session = null;

    setFailureStage('admin_login');
    session = await startRole(browser, payload, 'alpha.admin', (opened) => {
      session = opened;
      openedSessions += 1;
    });
    stages.admin_login = 'PASS';
    setFailureStage('class_created');
    classRef = await createClass(session.page, payload, apiStatuses);
    stages.class_created = 'PASS';
    setFailureStage('student_assigned');
    await assignMember(session.page, classRef, 'student', studentUserId, apiStatuses);
    stages.student_assigned = 'PASS';
    setFailureStage('teacher_assigned');
    await assignMember(session.page, classRef, 'teacher', teacherUserId, apiStatuses);
    stages.teacher_assigned = 'PASS';
    studentUserId = '';
    teacherUserId = '';

    setFailureStage('activation_selected');
    const activationListPromise = session.page.waitForResponse((response) => response.request().method() === 'GET'
      && new URL(response.url()).pathname === `${API_PREFIX}/activations`, { timeout: 30000 });
    await session.page.locator('#school-task-mode-saved').check();
    const activationListResponse = await activationListPromise;
    apiStatuses.activation_list_admin = activationListResponse.status();
    if (activationListResponse.status() !== 200) throw new Error('ActivationListStatusMismatch');
    const activationList = await responseJson(activationListResponse);
    const listData = envelopeData(activationList);
    if (!flagsValid(listData) || !exactKeys(listData, [
      'engineering_only', 'psychological_interpretation_allowed', 'items', 'has_more',
    ]) || !Array.isArray(listData.items) || typeof listData.has_more !== 'boolean') throw new Error('ActivationListInvalid');
    const listedActivation = listData.items.find((item) => validActivationMetadata(item, planVersionRef)
      && item.activation_ref === activation.activation_ref);
    if (!listedActivation) throw new Error('ActivationNotEligibleForAdmin');
    const selector = session.page.locator('#school-task-activation');
    await selector.waitFor({ state: 'visible', timeout: 15000 });
    const option = await selector.locator('option').evaluateAll((items, reference) => {
      const item = items.find((candidate) => candidate.value === reference);
      return item ? { value: item.value, text: item.textContent?.trim() ?? '' } : null;
    }, activation.activation_ref);
    if (!option || !option.text.includes(`${activation.plan_name} v${activation.plan_version_number}`)
      || !option.text.includes(`${activation.bank_name} v${activation.bank_version_number}`)) throw new Error('ActivationOptionMismatch');
    await selector.selectOption(activation.activation_ref);
    const adminText = await visibleText(session.page);
    if (adminText.includes(activation.activation_ref) || adminText.includes(bankDocument.items[0].stem)
      || adminText.includes(JSON.stringify(configDocument))) throw new Error('AdminAssetContentExposed');
    stages.activation_selected = 'PASS';

    setFailureStage('task_published_201');
    const classSelect = session.page.locator('#school-class-select');
    if (await classSelect.inputValue() !== classRef) throw new Error('ClassSelectionChanged');
    const opens = new Date(Date.now() - 5 * 60 * 1000);
    const opensValue = localInputDate(opens);
    await session.page.locator('#school-task-opens').fill(opensValue);
    const taskPath = `/api/v1/school/classes/${encodeURIComponent(classRef)}/tasks`;
    const taskListPromise = session.page.waitForResponse((response) => response.request().method() === 'GET'
      && new URL(response.url()).pathname === taskPath, { timeout: 30000 }).then(
      (response) => response, () => null,
    );
    const publication = await clickAndWait(
      session.page,
      (request) => request.method() === 'POST' && new URL(request.url()).pathname === taskPath,
      () => session.page.getByRole('button', { name: '发布任务', exact: true }).click(),
    );
    apiStatuses.task_publish = publication.response.status();
    const taskBody = publication.request.postDataJSON();
    if (!validTaskPublishRequest(taskBody, activation.activation_ref)) throw new Error('TaskRequestBindingMismatch');
    if (!publication.request.headers()['idempotency-key'] || !publication.request.headers()['x-csrf-token']) {
      throw new Error('TaskWriteHeadersMissing');
    }
    const publishedTask = extractTaskPublication(publication.response.status(), publication.envelope, activation.activation_ref);
    if (!publishedTask || publishedTask.class_ref !== classRef || publishedTask.plan_name !== activation.plan_name
      || publishedTask.plan_version_number !== activation.plan_version_number
      || publishedTask.instrument_id !== bankDocument.instrument_id
      || publishedTask.instrument_version !== bankDocument.metadata.instrument_version) throw new Error('TaskResponseBindingMismatch');
    taskRef = publishedTask.task_ref;
    taskShortRef = shortRef(taskRef);
    const listResponse = await taskListPromise;
    apiStatuses.task_list = listResponse.status();
    if (listResponse.status() !== 200) throw new Error('TaskListReloadFailed');
    const listDataTask = envelopeData(await responseJson(listResponse));
    if (!Array.isArray(listDataTask) || !listDataTask.some((item) => item.task_ref === taskRef
      && item.activation_ref === activation.activation_ref && item.plan_name === activation.plan_name
      && item.plan_version_number === activation.plan_version_number)) throw new Error('TaskListBindingMismatch');
    stages.task_published_201 = 'PASS';
    stages.task_activation_matched = 'PASS';
    if (await visibleText(session.page).then((text) => text.includes(activation.activation_ref)
      || text.includes(bankDocument.items[0].stem) || text.includes(JSON.stringify(configDocument)))) {
      throw new Error('AdminTaskContentExposed');
    }
    stages.admin_metadata_redacted = 'PASS';
    await screenshot(session.page, payload, SCREENSHOTS[2], { width: 1365, height: 900 });
    screenshotFiles.push(SCREENSHOTS[2]);
    stages.admin_desktop_screenshot = 'PASS';
    if (!await logoutSession(session, payload)) throw new Error('AdminLogoutFailed');
    cleanedSessions += 1;
    session = null;

    setFailureStage('student_login');
    session = await startRole(browser, payload, 'alpha.student', (opened) => {
      session = opened;
      openedSessions += 1;
    });
    stages.student_login = 'PASS';
    setFailureStage('cat_started');
    const startPath = (reference) => `/api/v1/school/tasks/${encodeURIComponent(reference)}/start`;
    const startRequestPromise = session.page.waitForRequest((request) => request.method() === 'POST'
      && new URL(request.url()).pathname === startPath(taskRef), { timeout: 30000 }).then(
      (request) => request, () => null,
    );
    const startResponsePromise = session.page.waitForResponse((response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname === startPath(taskRef), { timeout: 30000 }).then(
      (response) => response, () => null,
    );
    const stateResponsePromise = session.page.waitForResponse((response) => response.request().method() === 'GET'
      && new RegExp('^/api/v1/assessments/[^/]+/state$').test(new URL(response.url()).pathname), { timeout: 30000 }).then(
      (response) => response, () => null,
    );
    await session.page.goto(`${payload.frontend_url}/student/assessments`, { waitUntil: 'domcontentloaded' });
    const taskRow = session.page.locator('.assigned-task').filter({
      has: session.page.getByRole('heading', { name: taskLabel(taskRef), exact: true }),
    });
    await taskRow.waitFor({ state: 'visible', timeout: 20000 });
    await taskRow.getByRole('button', { name: '开始任务', exact: true }).click();
    const [startRequest, startResponse, stateResponse] = await Promise.all([
      startRequestPromise, startResponsePromise, stateResponsePromise,
    ]);
    if (!startRequest || !startResponse || !stateResponse
      || JSON.stringify(startRequest.postDataJSON()) !== '{}'
      || !startRequest.headers()['idempotency-key'] || !startRequest.headers()['x-csrf-token']) {
      throw new Error('TaskStartRequestMismatch');
    }
    apiStatuses.task_start = startResponse.status();
    const startEnvelope = await responseJson(startResponse);
    const startFailureCode = taskStartValidationCode(startResponse.status(), startEnvelope, taskRef);
    if (startFailureCode !== null) {
      checkpoint('task_start_validator', `INVALID_${startFailureCode}`, 'cat_started');
      throw new Error('SavedTaskStartMismatch');
    }
    const startData = extractTaskStart(startResponse.status(), startEnvelope, taskRef);
    if (!startData) throw new Error('SavedTaskStartMismatch');
    assessmentId = startData.assessment_id;
    const stateData = extractAssessmentState(stateResponse.status(), await responseJson(stateResponse), {
      assessmentId, bankVersion: bankDocument.version, configVersion: configDocument.config_version,
    });
    apiStatuses.assessment_state = stateResponse.status();
    if (!stateData || stateData.max_items !== 3 || stateData.answered_count !== 0) throw new Error('SavedCatProvenanceMismatch');
    await session.page.waitForURL((url) => url.pathname === `/student/assessment/${encodeURIComponent(assessmentId)}`, { timeout: 20000 });
    await session.page.locator('#question-title').waitFor({ state: 'visible', timeout: 20000 });
    stages.cat_started = 'PASS';
    stages.cat_version_provenance_matched = 'PASS';

    let currentItem = stateData.current_item;
    for (let responseIndex = 1; responseIndex <= 3; responseIndex += 1) {
      await session.page.locator('.question-card').waitFor({ state: 'visible', timeout: 15000 });
      await session.page.locator('.answer-option').first().click();
      const responsePath = `/api/v1/assessments/${encodeURIComponent(assessmentId)}/responses`;
      const saved = await clickAndWait(
        session.page,
        (request) => request.method() === 'POST' && new URL(request.url()).pathname === responsePath,
        () => session.page.getByRole('button', { name: '下一题', exact: true }).click(),
      );
      apiStatuses[`response_${responseIndex}`] = saved.response.status();
      const requestBody = saved.request.postDataJSON();
      const responseState = extractAssessmentState(saved.response.status(), saved.envelope, {
        assessmentId, bankVersion: bankDocument.version, configVersion: configDocument.config_version,
      });
      if (!responseState || responseState.answered_count !== responseIndex
        || !exactKeys(requestBody, ['item_id', 'response']) || !safeText(requestBody.item_id, 160)
        || !safeText(requestBody.response, 160) || !saved.request.headers()['idempotency-key']
        || !saved.request.headers()['x-csrf-token']) throw new Error('SavedCatResponseMismatch');
      if (currentItem && requestBody.item_id !== currentItem.item_id) throw new Error('SavedCatItemSequenceMismatch');
      if (responseIndex < 3) {
        await session.page.locator('#question-title').waitFor({ state: 'visible', timeout: 15000 });
        currentItem = responseState.current_item;
      } else if (!responseState.can_complete || responseState.current_item !== null) {
        throw new Error('SavedCatStoppingGateMismatch');
      }
    }
    stages.three_responses_saved = 'PASS';

    setFailureStage('cat_completed');
    const completePath = `/api/v1/assessments/${encodeURIComponent(assessmentId)}/complete`;
    const completed = await clickAndWait(
      session.page,
      (request) => request.method() === 'POST' && new URL(request.url()).pathname === completePath,
      () => session.page.locator(CAT_COMPLETE_SELECTOR).first().click(),
    );
    apiStatuses.assessment_complete = completed.response.status();
    if (!extractCompletion(completed.response.status(), completed.envelope, assessmentId)
      || !completed.request.headers()['idempotency-key'] || !completed.request.headers()['x-csrf-token']) {
      throw new Error('AssessmentCompletionMismatch');
    }
    await session.page.waitForURL((url) => /^\/student\/assessment\/[^/]+\/result$/.test(url.pathname), { timeout: 20000 });
    await session.page.goto(`${payload.frontend_url}/student/assessments`, { waitUntil: 'domcontentloaded' });
    const completedEntry = session.page.locator('.task-history__entry').filter({
      has: session.page.getByRole('heading', { name: taskLabel(taskRef), exact: true }),
    });
    await completedEntry.waitFor({ state: 'visible', timeout: 20000 });
    if (await completedEntry.count() !== 1 || !(await completedEntry.innerText()).includes('已完成')) {
      throw new Error('CompletedTaskHistoryMismatch');
    }
    stages.cat_completed = 'PASS';
    stages.student_completed_history = 'PASS';
    const studentText = await visibleText(session.page);
    if (studentText.includes(bankDocument.items[0].stem) || studentText.includes(planVersionRef)
      || studentText.includes(activation.activation_ref)) throw new Error('StudentAssetMetadataExposed');
    await screenshot(session.page, payload, SCREENSHOTS[3], { width: 1365, height: 900 });
    screenshotFiles.push(SCREENSHOTS[3]);
    stages.student_desktop_screenshot = 'PASS';
    if (!await logoutSession(session, payload)) throw new Error('StudentLogoutFailed');
    cleanedSessions += 1;
    session = null;

    setFailureStage('teacher_login');
    session = await startRole(browser, payload, 'alpha.teacher', (opened) => {
      session = opened;
      openedSessions += 1;
    });
    stages.teacher_login = 'PASS';
    setFailureStage('teacher_completion_aggregate');
    const progressResponse = await refreshTeacherProgress(session.page);
    apiStatuses.teacher_progress = progressResponse.status();
    let progressEnvelope;
    try {
      progressEnvelope = await responseJson(progressResponse);
    } catch {
      checkpoint('teacher_progress_validator', 'INVALID_BODY_READ_FAILED', 'teacher_completion_aggregate');
      throw new Error('TeacherAggregateMismatch');
    }
    const progressFailureCode = teacherProgressValidationCode(progressResponse.status(), progressEnvelope, classRef, taskRef);
    if (progressFailureCode !== null) {
      checkpoint('teacher_progress_validator', `INVALID_${progressFailureCode}`, 'teacher_completion_aggregate');
      throw new Error('TeacherAggregateMismatch');
    }
    const aggregate = extractTeacherAggregate(progressResponse.status(), progressEnvelope, classRef, taskRef);
    if (!aggregate) throw new Error('TeacherAggregateMismatch');
    const teacherRow = session.page.locator('.task-progress-row')
      .filter({ has: session.page.getByText(`班级 ${shortRef(classRef)}`, { exact: true }) })
      .filter({ has: session.page.getByRole('heading', { name: taskLabel(taskRef), exact: true }) });
    try {
      await teacherRow.waitFor({ state: 'visible', timeout: 20000 });
    } catch {
      checkpoint('teacher_ui_validator', 'INVALID_ROW_NOT_VISIBLE', 'teacher_completion_aggregate');
      throw new Error('TeacherUiAggregateMismatch');
    }
    if (await teacherRow.count() !== 1) {
      checkpoint('teacher_ui_validator', 'INVALID_ROW_COUNT', 'teacher_completion_aggregate');
      throw new Error('TeacherUiAggregateMismatch');
    }
    const completedCells = teacherRow.locator('dl > div')
      .filter({ has: session.page.getByText('已完成', { exact: true }) });
    if (await completedCells.count() !== 1) {
      checkpoint('teacher_ui_validator', 'INVALID_COMPLETED_CELL_COUNT', 'teacher_completion_aggregate');
      throw new Error('TeacherUiAggregateMismatch');
    }
    const completedValues = completedCells.locator('dd');
    const completedValueCount = await completedValues.count();
    let completedCountText = '';
    if (completedValueCount === 1) {
      try { completedCountText = (await completedValues.innerText()).trim(); } catch { /* fixed validation below */ }
    }
    if (completedValueCount !== 1 || completedCountText !== '1') {
      checkpoint('teacher_ui_validator', 'INVALID_COMPLETED_VALUE', 'teacher_completion_aggregate');
      throw new Error('TeacherUiAggregateMismatch');
    }
    setFailureStage('teacher_metadata_redacted');
    const teacherText = await visibleText(session.page);
    if (teacherText.includes(bankDocument.items[0].stem) || teacherText.includes(planVersionRef)
      || teacherText.includes(activation.activation_ref) || teacherText.includes(assessmentId)) {
      throw new Error('TeacherAssetOrIndividualDataExposed');
    }
    stages.teacher_completion_aggregate = 'PASS';
    stages.teacher_metadata_redacted = 'PASS';
    setFailureStage('teacher_desktop_screenshot');
    await screenshot(session.page, payload, SCREENSHOTS[4], { width: 1365, height: 900 });
    screenshotFiles.push(SCREENSHOTS[4]);
    stages.teacher_desktop_screenshot = 'PASS';
    setFailureStage('teacher_mobile_screenshot');
    await screenshot(session.page, payload, SCREENSHOTS[5], { width: 390, height: 844 });
    screenshotFiles.push(SCREENSHOTS[5]);
    stages.teacher_mobile_screenshot = 'PASS';
    setFailureStage('sessions_cleaned');
    if (!await logoutSession(session, payload)) throw new Error('TeacherLogoutFailed');
    cleanedSessions += 1;
    session = null;
    if (!roleCleanupComplete(openedSessions, cleanedSessions)) throw new Error('RoleSessionCleanupMismatch');
    stages.sessions_cleaned = 'PASS';
  } catch (error) {
    failure = { stage: failureStage, error_class: safeErrorClass(error) };
    const errorCode = CHECKPOINT_ERROR_CODES.includes(error?.message) ? `ERROR_${error.message}` : null;
    const cleanupStatus = errorCode ?? (liveStatus.startsWith('INVALID_') ? liveStatus
      : liveStatus.startsWith('HTTP_') ? `FAIL_AFTER_${liveStatus}` : 'FAIL');
    checkpoint(liveStep, cleanupStatus, failureStage);
  } finally {
    for (const account of Object.values(payload.credentials)) {
      account.username = '';
      account.password = '';
    }
    if (session) {
      try {
        if (await logoutSession(session, payload)) cleanedSessions += 1;
      } catch { /* fixed cleanup failure */ }
    }
    try { if (browser) await withDeadline(browser.close(), 10000, 'BrowserCloseTimeout'); } catch { /* fixed cleanup failure */ }
    taskRef = ''; classRef = ''; assessmentId = ''; planVersionRef = ''; activation = null;
    bankDocument = null; configDocument = null; taskShortRef = '';
    studentUserId = ''; teacherUserId = '';
  }
  if (roleCleanupComplete(openedSessions, cleanedSessions)) stages.sessions_cleaned = 'PASS';
  stages.screenshots = screenshotFiles.length === SCREENSHOTS.length ? 'PASS' : 'FAIL';
  const result = summarizeWorkflow(stages, screenshotFiles, payload.artifact_dir, 0, failure, apiStatuses);
  if (result.status !== 'PASS' && !result.failure) {
    result.failure = { stage: UI_STAGE_KEYS.find((key) => stages[key] !== 'PASS') ?? 'sessions_cleaned', error_class: 'Error' };
  }
  if (result.status === 'PASS') checkpoint('sessions_cleaned', 'PASS', 'sessions_cleaned');
  else if (!failure) {
    const failedStage = result.failure?.stage ?? 'sessions_cleaned';
    checkpoint(failedStage, 'FAIL', failedStage);
  }
  return result;
}

async function createClass(page, payload, apiStatuses) {
  const classSelect = page.locator('#school-class-select');
  await classSelect.waitFor({ state: 'visible', timeout: 15000 });
  const previous = await classSelect.inputValue();
  const responsePromise = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/school/classes', { timeout: 30000 });
  await page.getByRole('button', { name: '创建班级', exact: true }).click();
  const response = await responsePromise;
  apiStatuses.class_create = response.status();
  if (response.status() !== 201) throw new Error('ClassCreateStatusMismatch');
  const classValue = envelopeData(await responseJson(response));
  if (!isRecord(classValue) || !/^CLASS_[A-Za-z0-9_.-]{1,120}$/.test(classValue.class_ref)) throw new Error('ClassCreateResponseInvalid');
  await page.waitForFunction((prior) => {
    const select = document.querySelector('#school-class-select');
    return Boolean(select && select.value !== prior && /^CLASS_/.test(select.value));
  }, previous, { timeout: 15000 });
  const classRef = await classSelect.inputValue();
  if (classRef !== classValue.class_ref || classRef === previous) throw new Error('ClassCreateUiMismatch');
  return classRef;
}

async function assignMember(page, classRef, role, expectedUserId, apiStatuses) {
  const selectId = role === 'student' ? '#school-student-select' : '#school-teacher-select';
  const select = page.locator(selectId);
  await select.waitFor({ state: 'visible', timeout: 15000 });
  const optionExists = await select.locator('option').evaluateAll((options, userId) =>
    options.some((option) => option.value === userId), expectedUserId);
  if (!optionExists) throw new Error('AuthenticatedMemberNotEligible');
  await select.selectOption(expectedUserId);
  if (await select.inputValue() !== expectedUserId) throw new Error('AuthenticatedMemberSelectionMismatch');
  const pathName = `/api/v1/school/classes/${encodeURIComponent(classRef)}/${role === 'student' ? 'students' : 'teachers'}`;
  const result = await clickAndWait(
    page,
    (request) => request.method() === 'POST' && new URL(request.url()).pathname === pathName,
    () => select.locator('xpath=..').getByRole('button', { name: '分配', exact: true }).click(),
  );
  apiStatuses[role === 'student' ? 'student_assignment' : 'teacher_assignment'] = result.response.status();
  const body = result.request.postDataJSON();
  if (!result.response.ok() || !isRecord(envelopeData(result.envelope))
    || !validAssignmentRequest(role, body, expectedUserId)
    || !result.request.headers()['idempotency-key'] || !result.request.headers()['x-csrf-token']) {
    throw new Error('MemberAssignmentFailed');
  }
  await page.getByText(role === 'student' ? '学生已加入班级。' : '教师已分配到班级。', { exact: true })
    .waitFor({ state: 'visible', timeout: 15000 });
}

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  let payload;
  try { payload = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { payload = null; }
  if (!validPayload(payload)) {
    console.log(JSON.stringify({ workflow: 'synthetic-cat-activation', status: 'FAIL', stages: emptyStages(), screenshots: [], failure: { stage: 'specialist_login', error_class: 'Error' } }));
    return 2;
  }
  try {
    const result = await runWorkflow(payload);
    console.log(JSON.stringify(result));
    return result.status === 'PASS' ? 0 : 2;
  } catch {
    for (const account of Object.values(payload.credentials)) { account.username = ''; account.password = ''; }
    console.log(JSON.stringify({ workflow: 'synthetic-cat-activation', status: 'FAIL', stages: emptyStages(), screenshots: [], failure: { stage: 'specialist_login', error_class: 'Error' } }));
    return 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main();
