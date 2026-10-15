import test from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyCurrentPath,
  isLoopbackBrowserOrigin,
  safeForbiddenRouteDiagnostic,
  safeRestoreDiagnostic,
  studentHistoryMetadataFailureCode,
  studentHistoryRenderedMismatch,
} from '../school_browser_qa.mjs';

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
  assert.equal(safeRestoreDiagnostic('student_history', 'metadata_render', 'PRIVATE_TEXT', '/student/history'), null);
});

test('history row comparison preserves API order and rejects wrong counts or dates', () => {
  const metadata = [
    { status: 'completed', items_answered: 3, started_at: '2026-10-12T10:00:00Z', completed_at: '2026-10-12T10:05:00Z' },
    { status: 'created', items_answered: 0, started_at: null, completed_at: null },
  ];
  const formatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
  const expectedTimes = [formatter.format(new Date(metadata[0].completed_at)), '尚未开始'];
  const statusLabels = ['已完成的合成测评', '尚未开始的合成测评'];
  const summaries = [`3 项已记录 · ${expectedTimes[0]}`, '0 项已记录 · 尚未开始'];
  assert.equal(studentHistoryRenderedMismatch(metadata, statusLabels, summaries, expectedTimes), null);
  assert.equal(studentHistoryRenderedMismatch(metadata, [...statusLabels].reverse(), summaries, expectedTimes), 'STATUS_LABEL_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, statusLabels, ['0 项已记录 · 尚未开始', summaries[0]], expectedTimes), 'ITEM_COUNT_LABEL_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, statusLabels, ['3 项已记录 · wrong-date', summaries[1]], expectedTimes), 'DATE_LABEL_MISMATCH');
  assert.equal(studentHistoryRenderedMismatch(metadata, statusLabels, [summaries[0], '0 项已记录 · 时间未提供'], expectedTimes), 'NULL_TIME_LABEL_MISMATCH');
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
