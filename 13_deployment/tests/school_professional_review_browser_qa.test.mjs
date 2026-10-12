import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BACKEND_URL,
  ADMIN_SCREENSHOT_MASK_SELECTORS,
  FRONTEND_URL,
  REVIEW_NOTE,
  SCHOOL_REF,
  SCREENSHOTS,
  SCREENSHOT_STAGES,
  SCREENSHOT_MASK_SELECTORS,
  UI_STAGE_KEYS,
  WORKSPACE,
  professionalReviewCaseIndex,
  professionalReviewEnrollmentIndex,
  professionalReviewTaskIndex,
  loginRole,
  summarizeProfessionalReviewWorkflow,
  validProfessionalReviewPayload,
} from '../school_professional_review_browser_qa.mjs';

const artifactDir = path.join(WORKSPACE, 'browser-qa', '20261012T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
const makePayload = () => ({
  credentials: {
    'alpha.admin': { username: 'SYNTHETIC_ALPHA_ADMIN', password: 'a'.repeat(24) },
    'alpha.psychological_specialist': { username: 'SYNTHETIC_ALPHA_SPECIALIST', password: 's'.repeat(24) },
  },
  setup: {
    class_ref: `CLASS_${'a'.repeat(32)}`,
    task_ref: `TASK_${'b'.repeat(32)}`,
    enrollment_ref: `ENROLL_${'c'.repeat(32)}`,
  },
  artifact_dir: artifactDir,
  frontend_url: FRONTEND_URL,
  backend_url: BACKEND_URL,
});

test('runner accepts only exact synthetic admin and specialist credentials and safe setup refs', () => {
  assert.equal(validProfessionalReviewPayload(makePayload()), true);
  assert.deepEqual(SCREENSHOTS, [
    'admin-professional-assignment.png',
    'specialist-professional-review-desktop.png',
    'specialist-professional-review-mobile.png',
  ]);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.account-menu'), true);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.terminal-summary'), true);
  assert.equal(ADMIN_SCREENSHOT_MASK_SELECTORS.includes('.account-menu'), true);
  assert.equal(ADMIN_SCREENSHOT_MASK_SELECTORS.includes('#school-student-select'), true);
  assert.equal(REVIEW_NOTE.includes('合成演示'), true);

  const wrongArtifact = makePayload();
  wrongArtifact.artifact_dir = path.join(os.tmpdir(), 'unrelated', 'browser-qa', 'run');
  assert.equal(validProfessionalReviewPayload(wrongArtifact), false);
  const badTaskRef = makePayload();
  badTaskRef.setup.task_ref = '../private';
  assert.equal(validProfessionalReviewPayload(badTaskRef), false);
  const realLike = makePayload();
  realLike.credentials['alpha.psychological_specialist'].username = 'specialist@example.test';
  assert.equal(validProfessionalReviewPayload(realLike), false);
  const extraCredential = makePayload();
  extraCredential.credentials['alpha.admin'].csrf = 'credential sentinel';
  assert.equal(validProfessionalReviewPayload(extraCredential), false);
  const extraSetup = makePayload();
  extraSetup.setup.response_text = 'must not be supplied';
  assert.equal(validProfessionalReviewPayload(extraSetup), false);
});

test('visible task and record selection is derived from exact API list ordering', () => {
  const taskRef = makePayload().setup.task_ref;
  const enrollmentRef = makePayload().setup.enrollment_ref;
  const taskRows = [{ task_ref: 'TASK_else' }, { task_ref: taskRef }];
  const enrollmentRows = [{ enrollment_ref: 'ENROLL_else' }, { enrollment_ref: enrollmentRef }];
  const caseRows = [{ case_ref: 'PCR_else' }, { case_ref: 'PCR_0123456789abcdef' }];

  assert.equal(professionalReviewTaskIndex(taskRows, taskRef), 1);
  assert.equal(professionalReviewEnrollmentIndex(enrollmentRows, enrollmentRef), 1);
  assert.equal(professionalReviewCaseIndex(caseRows, 'PCR_0123456789abcdef'), 1);
  assert.equal(professionalReviewTaskIndex([...taskRows, { task_ref: taskRef }], taskRef), -1);
  assert.equal(professionalReviewEnrollmentIndex(enrollmentRows, '../private'), -1);
  assert.equal(professionalReviewCaseIndex(caseRows, '../private'), -1);
});

test('login helper uses the session credential slot and verifies the server actor role', async () => {
  const payload = makePayload();
  const values = { username: '', password: '' };
  const field = (name) => ({
    waitFor: async () => {},
    inputValue: async () => values[name],
    fill: async (value) => { values[name] = value; },
    isVisible: async () => false,
  });
  const page = {
    goto: async () => {},
    getByRole: (role, options) => role === 'textbox'
      ? field('username')
      : { click: async () => {} },
    locator: (selector) => selector === '#password'
      ? field('password')
      : { isVisible: async () => false },
    waitForURL: async (predicate) => {
      assert.equal(predicate(new URL(`${FRONTEND_URL}/specialist/overview`)), true);
    },
    evaluate: async () => ({
      status: 200,
      actor: {
        user_id: 'USER_SYNTHETIC_SPECIALIST',
        active_context: { role: 'PSYCHOLOGICAL_SPECIALIST', school_ref: SCHOOL_REF },
      },
    }),
  };
  const session = { page, slot: 'alpha.psychological_specialist', loginSubmitted: false };

  await loginRole(session, payload, 'PSYCHOLOGICAL_SPECIALIST', '/specialist/overview');

  assert.equal(values.username, payload.credentials['alpha.psychological_specialist'].username);
  assert.equal(values.password, payload.credentials['alpha.psychological_specialist'].password);
  assert.equal(session.loginSubmitted, true);
  assert.equal(session.actorUserId, 'USER_SYNTHETIC_SPECIALIST');
});

test('workflow PASS requires every stage and both actual screenshot files', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'school-professional-review-qa-'));
  const filesDir = path.join(root, 'browser-qa', 'run');
  await mkdir(filesDir, { recursive: true });
  try {
    for (const name of SCREENSHOTS) await writeFile(path.join(filesDir, name), 'synthetic masked screenshot marker');
    const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'PASS']));
    assert.equal(summarizeProfessionalReviewWorkflow(stages, SCREENSHOTS, filesDir, 0).status, 'PASS');

    const missingDecision = { ...stages, decision_saved: 'FAIL' };
    assert.equal(summarizeProfessionalReviewWorkflow(missingDecision, SCREENSHOTS, filesDir, 0).status, 'FAIL');
    assert.equal(summarizeProfessionalReviewWorkflow(stages, SCREENSHOTS, filesDir, 2).status, 'FAIL');
    assert.equal(summarizeProfessionalReviewWorkflow(stages, ['../private.png'], filesDir, 0).status, 'FAIL');

    const desktopName = Object.entries(SCREENSHOT_STAGES).find(([, stage]) => stage === 'desktop_screenshot')?.[0];
    await rm(path.join(filesDir, desktopName));
    const missingDesktop = summarizeProfessionalReviewWorkflow(stages, SCREENSHOTS, filesDir, 0);
    assert.equal(missingDesktop.stages.desktop_screenshot, 'FAIL');
    assert.equal(missingDesktop.stages.mobile_screenshot, 'PASS');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('failure summaries expose only the fixed stage and error class', () => {
  const sentinel = 'review-note-password-reference-sentinel';
  const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));
  const result = summarizeProfessionalReviewWorkflow(stages, [], os.tmpdir(), 2, {
    stage: 'decision_saved', error_class: `TimeoutError: ${sentinel}`, message: sentinel, response_body: sentinel,
  });
  assert.deepEqual(result.failure, { stage: 'decision_saved', error_class: 'Error' });
  assert.equal(JSON.stringify(result).includes(sentinel), false);
  assert.equal(SCHOOL_REF, 'SYNTHETIC_SCHOOL_SEED_ALPHA_V1');
});
