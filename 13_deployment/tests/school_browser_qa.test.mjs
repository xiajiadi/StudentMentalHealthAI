import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  browserBinaryPrerequisite,
  classifyCurrentPath,
  isLoopbackBrowserOrigin,
  safeForbiddenRouteDiagnostic,
  safeRestoreDiagnostic,
  studentHistoryMetadataFailureCode,
  studentHistoryRenderedMismatch,
} from '../school_browser_qa.mjs';

test('headless browser preflight checks both exact Chromium and headless-shell revision paths', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'psynova-browser-prereq-'));
  try {
    const chromium = path.join(root, 'chromium-1243', 'chrome-win64', 'chrome.exe');
    const shell = path.join(
      root, 'chromium_headless_shell-1243', 'chrome-headless-shell-win64',
      'chrome-headless-shell.exe',
    );
    fs.mkdirSync(path.dirname(chromium), { recursive: true });
    fs.writeFileSync(chromium, 'synthetic executable marker');

    assert.deepEqual(browserBinaryPrerequisite(chromium, 'win32'), {
      status: 'FAIL', code: 'HEADLESS_SHELL_EXECUTABLE_MISSING',
    });
    fs.mkdirSync(path.dirname(shell), { recursive: true });
    fs.writeFileSync(shell, 'synthetic executable marker');
    assert.deepEqual(browserBinaryPrerequisite(chromium, 'win32'), {
      status: 'PASS', code: 'READY',
    });
    assert.deepEqual(browserBinaryPrerequisite(path.join(root, 'missing.exe'), 'win32'), {
      status: 'FAIL', code: 'CHROMIUM_EXECUTABLE_MISSING',
    });
    assert.equal(JSON.stringify(browserBinaryPrerequisite(chromium, 'win32')).includes(root), false);
  } finally {
    const tempRoot = path.resolve(os.tmpdir());
    const resolvedRoot = path.resolve(root);
    if (resolvedRoot === tempRoot || !resolvedRoot.startsWith(`${tempRoot}${path.sep}`)) {
      throw new Error('Refusing to remove test path outside the OS temp directory');
    }
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('forbidden-route diagnostics expose only fixed stage, code, and path classes', () => {
  const pathWithPrivateId = '/student/assessment/ASSESS_private-sentinel';
  const diagnostic = safeForbiddenRouteDiagnostic(
    'role_redirect', 'ROLE_REDIRECT_NOT_COMPLETED', pathWithPrivateId,
  );
  assert.deepEqual(diagnostic, {
    stage: 'forbidden_route',
    substage: 'role_redirect',
    code: 'ROLE_REDIRECT_NOT_COMPLETED',
    current_path: 'other',
  });
  assert.equal(JSON.stringify(diagnostic).includes('ASSESS_private-sentinel'), false);
  assert.equal(safeForbiddenRouteDiagnostic('role_redirect', 'RAW_ERROR', '/admin/overview'), null);
  assert.equal(classifyCurrentPath('/student/home'), 'student_home');
  assert.equal(classifyCurrentPath('/student/history'), 'student_history');
  assert.equal(classifyCurrentPath(null), 'unknown');
});

test('student history diagnostics follow the metadata DTO and bind null-time display to returned rows', async () => {
  const schema = (await import('node:fs/promises').then(({ readFile }) => readFile(
    new URL('../../09_backend/src/smhai_backend/domains/school_tasks/schemas.py', import.meta.url), 'utf8',
  ))).replace(/\r\n/g, '\n');
  const dtoBlock = schema.match(/class StudentAssessmentMetadataDto\(SchoolOutputDto\):([\s\S]*?)(?=\n\nclass )/);
  assert.ok(dtoBlock);
  const fields = [...dtoBlock[1].matchAll(/^\s{4}([a-z_]+):/gm)].map((match) => match[1]).sort();
  assert.deepEqual(fields, ['assessment_id', 'status', 'items_answered', 'started_at', 'completed_at'].sort());

  const envelope = { data: [
    { assessment_id: 'ASSESS_synthetic_completed', status: 'completed', items_answered: 3,
      started_at: '2026-10-12T10:00:00Z', completed_at: '2026-10-12T10:05:00Z' },
    { assessment_id: 'ASSESS_synthetic_created', status: 'created', items_answered: 0,
      started_at: null, completed_at: null },
  ] };
  assert.equal(studentHistoryMetadataFailureCode(200, envelope), null);
  assert.equal(studentHistoryMetadataFailureCode(200, { data: [] }), null);
  assert.equal(studentHistoryMetadataFailureCode(200, { data: [{ ...envelope.data[0], private_payload: 'sentinel' }] }), 'DTO_INVALID');
  assert.equal(studentHistoryMetadataFailureCode(200, { data: [{ ...envelope.data[1], started_at: 'not-a-date' }] }), 'DTO_INVALID');
  assert.equal(studentHistoryMetadataFailureCode(503, envelope), 'HTTP_STATUS');

  const diagnostic = safeRestoreDiagnostic(
    'student_history', 'metadata_render', 'NULL_TIME_LABEL_MISMATCH', '/student/history',
  );
  assert.deepEqual(diagnostic, {
    stage: 'student_history', substage: 'metadata_render',
    code: 'NULL_TIME_LABEL_MISMATCH', current_path: 'student_history',
  });
  assert.equal(safeRestoreDiagnostic('student_history', 'metadata_response', 'REQUEST_NOT_STARTED', '/student/home')?.code, 'REQUEST_NOT_STARTED');
  assert.equal(safeRestoreDiagnostic('student_history', 'metadata_response', 'REQUEST_FAILED', '/student/history')?.code, 'REQUEST_FAILED');
  assert.equal(safeRestoreDiagnostic('student_history', 'route', 'ROUTE_NOT_REACHED', '/student/home')?.code, 'ROUTE_NOT_REACHED');
  assert.equal(safeRestoreDiagnostic('student_history', 'route', 'LINK_NOT_VISIBLE', '/student/home')?.code, 'LINK_NOT_VISIBLE');
  assert.equal(safeRestoreDiagnostic('student_history', 'route', 'LINK_CLICK_FAILED', '/student/home')?.code, 'LINK_CLICK_FAILED');
  assert.equal(safeRestoreDiagnostic('student_history', 'metadata_render', 'PRIVATE_TEXT', '/student/history'), null);
});

test('student assessment metadata matches the current assessment cards and empty state', () => {
  const metadata = [
    { status: 'completed', items_answered: 3, started_at: '2026-10-12T10:00:00Z', completed_at: '2026-10-12T10:05:00Z' },
    { status: 'created', items_answered: 0, started_at: null, completed_at: null },
  ];
  const formatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
  const cards = [
    `已完成 3 项已记录 ${formatter.format(new Date(metadata[0].completed_at))}`,
    '待开始 0 项已记录 时间未提供',
  ];
  assert.equal(studentHistoryRenderedMismatch(metadata, cards, false), null);
  assert.equal(studentHistoryRenderedMismatch(metadata, [], false), 'EMPTY_STATE_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, [cards[0]], false), 'CARD_COUNT_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, ['进行中 3 项已记录 ${formatter.format(new Date(metadata[0].completed_at))}', cards[1]], false), 'STATUS_LABEL_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, ['已完成 4 项已记录 ${formatter.format(new Date(metadata[0].completed_at))}', cards[1]], false), 'ITEM_COUNT_LABEL_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, ['已完成 3 项已记录 wrong-date', cards[1]], false), 'DATE_LABEL_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch([], [], true), null);
});

test('rejects non-loopback, missing, malformed, or decorated origins', () => {
  for (const value of [
    'https://127.0.0.1:8104',
    'http://localhost:8104',
    'http://192.168.1.10:8104',
    'http://user@127.0.0.1:8104',
    'http://127.0.0.1:8104/path',
    'http://127.0.0.1:80',
    'http://127.0.0.1',
    null,
  ]) {
    assert.equal(isLoopbackBrowserOrigin(value), false, String(value));
  }
});
