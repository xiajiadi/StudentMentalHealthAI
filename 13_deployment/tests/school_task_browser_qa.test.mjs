import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  REQUIRED_SCREENSHOTS,
  FAILURE_SCREENSHOT_NAME,
  CAT_FAILURE_SUBSTAGES,
  fallbackPageDiagnostics,
  CAT_CARD_COMPLETION_SELECTOR,
  CAT_QUESTION_COMPLETION_SELECTOR,
  CAT_COMPLETION_BUTTON_SELECTOR,
  TASK_STAGE_KEYS,
  cleanupRoleSession,
  summarizeTaskWorkflow,
  validTaskPayload,
} from '../school_task_browser_qa.mjs';

const payload = (artifactDir) => ({
  credentials: {
    'alpha.admin': { username: 'SYNTHETIC_ADMIN', password: 'p'.repeat(24) },
    'alpha.student': { username: 'SYNTHETIC_STUDENT', password: 'p'.repeat(24) },
    'alpha.teacher': { username: 'SYNTHETIC_TEACHER', password: 'p'.repeat(24) },
  },
  accounts: {
    'alpha.admin': { role: 'SCHOOL_ADMIN', api_role: 'ADMIN', path: '/admin/overview' },
    'alpha.student': { role: 'STUDENT', api_role: 'STUDENT', path: '/student/home' },
    'alpha.teacher': { role: 'TEACHER', api_role: 'TEACHER', path: '/teacher/overview' },
  },
  artifact_dir: artifactDir,
  frontend_url: 'http://127.0.0.1:4178',
  backend_url: 'http://127.0.0.1:8088',
});

test('task workflow payload accepts only synthetic accounts and fixed routes', () => {
  const artifactDir = path.join(
    os.tmpdir(), '.StudentMentalHealthAI-school-workspace-20261011', 'browser-qa',
    '20261012T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  );
  assert.equal(validTaskPayload(payload(artifactDir)), true);
  const realLike = payload(artifactDir);
  realLike.credentials['alpha.student'].username = 'student@example.test';
  assert.equal(validTaskPayload(realLike), false);
  const wrongRoute = payload(artifactDir);
  wrongRoute.accounts['alpha.admin'].path = '/student/home';
  assert.equal(validTaskPayload(wrongRoute), false);
  assert.equal(validTaskPayload({ ...payload(artifactDir), artifact_dir: path.join(os.tmpdir(), 'unrelated') }), false);
});

test('CAT completion selector covers question and no-question completion branches', () => {
  assert.equal(CAT_QUESTION_COMPLETION_SELECTOR, 'button[aria-label="完成测评"]');
  assert.equal(CAT_CARD_COMPLETION_SELECTOR, '.assessment-complete-card .question-card__footer button');
  assert.equal(
    CAT_COMPLETION_BUTTON_SELECTOR,
    'button[aria-label="完成测评"], .assessment-complete-card .question-card__footer button',
  );
});

test('PASS requires every workflow stage and all five actual screenshots', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'school-task-qa-'));
  const artifactDir = path.join(root, '.StudentMentalHealthAI-school-workspace-20261011', 'browser-qa');
  await mkdir(artifactDir, { recursive: true });
  try {
    for (const name of REQUIRED_SCREENSHOTS) await writeFile(path.join(artifactDir, name), 'synthetic screenshot marker');
    await writeFile(path.join(artifactDir, FAILURE_SCREENSHOT_NAME), 'masked admin diagnostic screenshot marker');
    const stages = Object.fromEntries(TASK_STAGE_KEYS.map((key) => [key, 'PASS']));
    assert.equal(summarizeTaskWorkflow(stages, REQUIRED_SCREENSHOTS, artifactDir).status, 'PASS');

    const missingStage = { ...stages };
    delete missingStage.admin_revoke;
    const partial = summarizeTaskWorkflow(missingStage, REQUIRED_SCREENSHOTS, artifactDir, 0, {
      stage: 'admin_revoke', error_class: 'TimeoutError', screenshot: FAILURE_SCREENSHOT_NAME,
      diagnostics: {
        route_mode: 'student_assessment_session',
        selectors: Object.fromEntries([
          'assessment_page', 'assessment_loading', 'question_title', 'question_card',
          'assessment_complete_card', 'assessment_error', 'assigned_task',
        ].map((key) => [key, key === 'assessment_loading'])),
        responses: [{ method: 'GET', status: 200, endpoint: '/api/v1/assessments/{assessment_id}/state', url: '/api/v1/assessments/ASSESS_private/state?token=sentinel' }],
        rawPath: '/student/assessment/ASSESS_private',
      },
    });
    assert.equal(partial.status, 'FAIL');
    assert.equal(partial.stages.class_created, 'PASS');
    assert.equal(partial.stages.admin_revoke, 'FAIL');
    assert.deepEqual(partial.failure, {
      stage: 'admin_revoke', error_class: 'TimeoutError', screenshot: FAILURE_SCREENSHOT_NAME,
      diagnostics: {
        route_mode: 'student_assessment_session',
        selectors: {
          assessment_page: false, assessment_loading: true, question_title: false,
          question_card: false, assessment_complete_card: false, assessment_error: false, assigned_task: false,
        },
        responses: [{ method: 'GET', status: 200, endpoint: '/api/v1/assessments/{assessment_id}/state' }],
      },
    });

    const catFailureStages = { ...stages, cat_started: 'FAIL' };
    const catFailure = summarizeTaskWorkflow(catFailureStages, [], artifactDir, 2, {
      stage: 'cat_started', error_class: 'TimeoutError',
      diagnostics: {
        route_mode: 'student_assessment_session',
        cat_substage: 'question_ready',
        selectors: Object.fromEntries([
          'assessment_page', 'assessment_loading', 'question_title', 'question_card',
          'assessment_complete_card', 'assessment_error', 'assigned_task',
        ].map((key) => [key, key === 'assessment_loading'])),
        responses: [{
          method: 'GET', status: 200,
          endpoint: '/api/v1/assessments/{assessment_id}/state',
          body: 'psychological sentinel', url: '/student/assessment/private-id?token=secret',
        }],
      },
    });
    assert.equal(catFailure.failure.diagnostics.cat_substage, 'question_ready');
    assert.equal(catFailure.failure.diagnostics.route_mode, 'student_assessment_session');
    assert.equal(catFailure.failure.diagnostics.responses[0].status, 200);
    assert.equal(JSON.stringify(catFailure).includes('sentinel'), false);
    assert.equal(JSON.stringify(catFailure).includes('private-id'), false);
    assert.equal(Object.hasOwn(catFailure.failure, 'responses'), false);
    const postAnswerFailure = summarizeTaskWorkflow(
      { ...stages, cat_completed: 'FAIL' }, [], artifactDir, 2,
      { stage: 'cat_completed', error_class: 'TimeoutError', diagnostics: { cat_substage: 'complete' } },
    );
    assert.equal(postAnswerFailure.failure.diagnostics.cat_substage, 'complete');
    const invalidSubstage = summarizeTaskWorkflow(catFailureStages, [], artifactDir, 2, {
      stage: 'cat_started', error_class: 'TimeoutError',
      diagnostics: { cat_substage: 'question_ready / private detail' },
    });
    assert.equal(Object.hasOwn(invalidSubstage.failure, 'cat_substage'), false);
    assert.deepEqual(CAT_FAILURE_SUBSTAGES, [
      'task_row', 'task_click', 'task_route', 'question_ready', 'progress', 'submit', 'complete',
    ]);
    assert.deepEqual(fallbackPageDiagnostics('complete'), { cat_substage: 'complete' });
    assert.equal(fallbackPageDiagnostics('untrusted details'), null);
    const fallbackWithResponses = fallbackPageDiagnostics('progress', [
      {
        method: 'POST',
        status: 200,
        endpoint: '/api/v1/assessments/{assessment_id}/responses',
        url: '/api/v1/assessments/ASSESS_private/responses?token=private',
        request: { body: 'answer private' },
        response: { json: { item: 'question private' } },
        extra: 'must not escape',
      },
      {
        method: 'POST',
        status: 200,
        endpoint: '/api/v1/assessments/ASSESS_private/responses',
      },
      {
        method: 'DELETE',
        status: 200,
        endpoint: '/api/v1/assessments/{assessment_id}/responses',
      },
    ]);
    assert.deepEqual(fallbackWithResponses, {
      cat_substage: 'progress',
      responses: [{
        method: 'POST',
        status: 200,
        endpoint: '/api/v1/assessments/{assessment_id}/responses',
      }],
    });
    assert.equal(JSON.stringify(fallbackWithResponses).includes('private'), false);
    assert.equal(Object.hasOwn(fallbackWithResponses, 'selectors'), false);
    assert.equal(Object.hasOwn(fallbackWithResponses, 'route_mode'), false);
    const unsafeFailure = summarizeTaskWorkflow(missingStage, REQUIRED_SCREENSHOTS, artifactDir, 0, {
      stage: 'admin_revoke', error_class: 'TimeoutError', screenshot: FAILURE_SCREENSHOT_NAME,
      message: 'private error sentinel', password: 'credential sentinel',
    });
    assert.equal(JSON.stringify(unsafeFailure).includes('sentinel'), false);
    assert.equal(summarizeTaskWorkflow(stages, REQUIRED_SCREENSHOTS.slice(1), artifactDir).status, 'FAIL');
    assert.equal(summarizeTaskWorkflow(stages, REQUIRED_SCREENSHOTS, artifactDir, 2).status, 'FAIL');
    const untrustedPath = [...REQUIRED_SCREENSHOTS];
    untrustedPath[0] = '../private.png';
    assert.equal(summarizeTaskWorkflow(stages, untrustedPath, artifactDir).status, 'FAIL');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('failed UI logout still attempts fallback and closes the browser context', async () => {
  let fallbackCalls = 0;
  let closeCalls = 0;
  const result = await cleanupRoleSession({}, { close: async () => { closeCalls += 1; } }, {
    loginSubmitted: true,
    logout: async () => { throw new Error('password sentinel never returned'); },
    fallbackLogout: async () => { fallbackCalls += 1; return false; },
  });

  assert.deepEqual(result, { logout: 'FAIL', context: 'PASS' });
  assert.equal(fallbackCalls, 1);
  assert.equal(closeCalls, 1);
});

test('successful UI logout closes context without API fallback', async () => {
  let fallbackCalls = 0;
  let closeCalls = 0;
  const result = await cleanupRoleSession({}, { close: async () => { closeCalls += 1; } }, {
    loginSubmitted: true,
    logout: async () => undefined,
    fallbackLogout: async () => { fallbackCalls += 1; return false; },
  });

  assert.deepEqual(result, { logout: 'PASS', context: 'PASS' });
  assert.equal(fallbackCalls, 0);
  assert.equal(closeCalls, 1);
});

test('failed context close keeps session-cleanup evidence failed', async () => {
  const result = await cleanupRoleSession({}, { close: async () => { throw new Error('not emitted'); } }, {
    loginSubmitted: false,
  });
  assert.deepEqual(result, { logout: 'PASS', context: 'FAIL' });
});
