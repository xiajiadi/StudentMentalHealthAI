import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BACKEND_URL,
  FRONTEND_URL,
  SCHOOL_REF,
  SCREENSHOTS,
  SCREENSHOT_STAGES,
  SCREENSHOT_MASK_SELECTORS,
  UI_STAGE_KEYS,
  WORKSPACE,
  summarizeConversationWorkflow,
  safeConversationId,
  conversationItemSelector,
  validConversationPayload,
} from '../school_conversation_browser_qa.mjs';

const artifactDir = path.join(WORKSPACE, 'browser-qa', '20261012T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
const makePayload = () => ({
  student: { username: 'SYNTHETIC_ALPHA_STUDENT', password: 'p'.repeat(24) },
  artifact_dir: artifactDir,
  frontend_url: FRONTEND_URL,
  backend_url: BACKEND_URL,
  school_ref: SCHOOL_REF,
});

test('runner accepts only the fixed synthetic student payload and artifact root', () => {
  assert.equal(validConversationPayload(makePayload()), true);
  assert.deepEqual(SCREENSHOTS, [
    'student-independent-conversation-desktop.png',
    'student-independent-conversation-mobile.png',
  ]);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.account-menu'), true);
  assert.equal(SCREENSHOT_MASK_SELECTORS.includes('.conversation-message--student'), true);

  const wrongWorkspace = makePayload();
  wrongWorkspace.artifact_dir = path.join(os.tmpdir(), 'unrelated', 'browser-qa', 'run');
  assert.equal(validConversationPayload(wrongWorkspace), false);

  const invalidRunDirectory = makePayload();
  invalidRunDirectory.artifact_dir = path.join(WORKSPACE, 'browser-qa', 'arbitrary');
  assert.equal(validConversationPayload(invalidRunDirectory), false);

  const wrongRoute = makePayload();
  wrongRoute.backend_url = 'http://127.0.0.1:9000';
  assert.equal(validConversationPayload(wrongRoute), false);

  const nonSynthetic = makePayload();
  nonSynthetic.student.username = 'student@example.test';
  assert.equal(validConversationPayload(nonSynthetic), false);

  const extraCredential = makePayload();
  extraCredential.student.csrf = 'credential sentinel';
  assert.equal(validConversationPayload(extraCredential), false);
});

test('create response yields only a valid opaque conversation id', () => {
  assert.equal(safeConversationId({ data: { conversation_id: 'CONV_0123456789abcdef' } }), 'CONV_0123456789abcdef');
  assert.equal(safeConversationId({ data: { conversation_id: 'CONV_0123456789abcdef', owner: 'private' } }), 'CONV_0123456789abcdef');
  assert.equal(safeConversationId({ data: { conversation_id: '../private' } }), null);
  assert.equal(safeConversationId({ data: { id: 'CONV_0123456789abcdef' } }), null);
  assert.equal(
    conversationItemSelector('CONV_0123456789abcdef'),
    '.conversation-list__item[data-conversation-id="CONV_0123456789abcdef"]',
  );
  assert.equal(conversationItemSelector('CONV_0123456789abcdef"] .secret'), null);
});

test('workflow PASS requires exact stages, zero-citation checks, and the screenshot file', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'school-independent-conversation-qa-'));
  const filesDir = path.join(root, 'browser-qa', 'run');
  await mkdir(filesDir, { recursive: true });
  try {
    for (const name of SCREENSHOTS) await writeFile(path.join(filesDir, name), 'synthetic masked screenshot marker');
    const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'PASS']));
    assert.equal(summarizeConversationWorkflow(stages, SCREENSHOTS, filesDir, 0).status, 'PASS');

    const missingCitationCheck = { ...stages };
    delete missingCitationCheck.citations_absent;
    assert.equal(summarizeConversationWorkflow(missingCitationCheck, SCREENSHOTS, filesDir, 0).status, 'FAIL');

    assert.equal(summarizeConversationWorkflow(stages, SCREENSHOTS, filesDir, 7).status, 'FAIL');
    assert.equal(summarizeConversationWorkflow(stages, [], filesDir, 0).status, 'FAIL');
    assert.equal(summarizeConversationWorkflow(stages, ['../private.png'], filesDir, 0).status, 'FAIL');

    await rm(path.join(filesDir, SCREENSHOTS[0]));
    const missingDesktop = summarizeConversationWorkflow(stages, SCREENSHOTS, filesDir, 0);
    assert.equal(missingDesktop.stages[SCREENSHOT_STAGES[SCREENSHOTS[0]]], 'FAIL');
    assert.equal(missingDesktop.stages[SCREENSHOT_STAGES[SCREENSHOTS[1]]], 'PASS');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('failure summary keeps only allowlisted stage and class, never raw message/body', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'school-independent-conversation-failure-'));
  try {
    const secret = 'credential-and-query-sentinel';
    const stages = Object.fromEntries(UI_STAGE_KEYS.map((key) => [key, 'FAIL']));
    const result = summarizeConversationWorkflow(stages, [], root, 2, {
      stage: 'abstention_body_verified',
      error_class: `TimeoutError: ${secret}`,
      message: secret,
      response_body: secret,
    });
    assert.equal(result.failure.error_class, 'Error');
    assert.equal(result.failure.stage, 'abstention_body_verified');
    assert.equal(JSON.stringify(result).includes(secret), false);

    const invalidStage = summarizeConversationWorkflow(stages, [], root, 2, {
      stage: `private ${secret}`,
      error_class: 'TimeoutError',
    });
    assert.equal(Object.hasOwn(invalidStage, 'failure'), false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
