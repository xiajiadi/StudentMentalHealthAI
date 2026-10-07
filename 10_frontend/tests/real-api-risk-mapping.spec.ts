import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
type TestRequest = InstanceType<typeof globalThis.Request>

function assessment(risk: unknown) {
  return {
    assessment_id: 'ASSESS_risk_mapping_test',
    subject_id: 'SUBJ_synthetic_risk_mapping_test',
    status: 'completed',
    dimensions: {},
    ...(risk === undefined ? {} : { risk }),
  }
}

async function getMappedAssessment(data: unknown) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8080')
  vi.stubGlobal('fetch', vi.fn(async (_request: TestRequest) => new ResponseConstructor(JSON.stringify({
    request_id: 'REQ_risk_mapping_test',
    trace_id: 'TRACE_risk_mapping_test',
    data,
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })))
  const { RealApiProvider } = await import('@/services/real-api')
  return new RealApiProvider().getAssessmentResult('ASSESS_risk_mapping_test')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('RealApiProvider assessment risk mapping', () => {
  it('rejects an absent risk object as an invalid API response', async () => {
    await expect(getMappedAssessment(assessment(undefined)))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it.each([
    ['missing level', { need_human_review: false }],
    ['unknown level', { level: 'unknown', need_human_review: false }],
  ])('rejects a %s instead of mapping it to normal', async (_label, risk) => {
    await expect(getMappedAssessment(assessment(risk)))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it.each([
    ['missing', { level: 'normal' }],
    ['non-boolean', { level: 'normal', need_human_review: 'false' }],
  ])('rejects a %s human-review flag instead of suppressing it', async (_label, risk) => {
    await expect(getMappedAssessment(assessment(risk)))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it.each([
    ['normal', false],
    ['high', true],
    ['crisis', true],
  ] as const)('preserves valid %s risk and human-review values', async (level, needHumanReview) => {
    const result = await getMappedAssessment(assessment({ level, need_human_review: needHumanReview }))

    expect(result.data.risk).toMatchObject({ level, need_human_review: needHumanReview })
  })
})
