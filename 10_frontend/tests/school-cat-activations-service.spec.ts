import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ requestSchoolCatAssets: vi.fn() }))
vi.mock('@/services/real-api', () => ({
  RealApiError: class RealApiError extends Error {
    constructor(public readonly code: string, message: string) { super(message) }
  },
  requestSchoolCatAssets: transport.requestSchoolCatAssets,
}))

import {
  SchoolCatActivationsService,
  catActivationReferencePatterns,
} from '@/services/school-cat-activations'

const flags = { engineering_only: true, psychological_interpretation_allowed: false }
const activation = (overrides: Record<string, unknown> = {}) => ({
  activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
  plan_version_ref: 'CPVER_12345678-1234-1234-1234-123456789012',
  bank_version_ref: 'CBVER_12345678-1234-1234-1234-123456789012',
  plan_name: '合成方案', plan_version_number: 2,
  bank_name: '合成题库', bank_version_number: 3,
  status: 'ACTIVE', revision: 1,
  created_at: '2026-10-13T00:00:00Z', revoked_at: null,
  ...overrides,
})
const envelope = (data: unknown) => ({ request_id: 'REQ_activation', trace_id: 'TRACE_activation', data })

beforeEach(() => { vi.clearAllMocks() })

describe('school CAT activation metadata service', () => {
  it('pages specialist activation history with an exact immutable plan-version filter', async () => {
    transport.requestSchoolCatAssets.mockResolvedValueOnce(envelope({
      ...flags, items: [activation(), activation({ status: 'REVOKED', revision: 2 })], has_more: true,
    }))
    const page = await new SchoolCatActivationsService().list({
      skip: 30, limit: 30, planVersionRef: activation().plan_version_ref,
    })
    expect(page).toMatchObject({ items: [{ status: 'ACTIVE' }, { status: 'REVOKED' }], has_more: true })
    expect(transport.requestSchoolCatAssets).toHaveBeenCalledWith({
      method: 'GET', path: '/api/v1/school/cat-assets/activations',
      query: { limit: 30, skip: 30, plan_version_ref: activation().plan_version_ref },
    })
  })

  it('creates and revokes activation rows with exact payloads and caller stable keys', async () => {
    transport.requestSchoolCatAssets
      .mockResolvedValueOnce(envelope({ ...flags, activation: activation() }))
      .mockResolvedValueOnce(envelope({ ...flags, activation: activation({ status: 'REVOKED', revision: 2, revoked_at: '2026-10-13T01:00:00Z' }) }))
    const service = new SchoolCatActivationsService()
    await expect(service.create(activation().plan_version_ref, 'stable-create-key')).resolves.toMatchObject({ status: 'ACTIVE' })
    await expect(service.revoke(activation().activation_ref, 1, 'stable-revoke-key')).resolves.toMatchObject({ status: 'REVOKED', revision: 2 })
    expect(transport.requestSchoolCatAssets.mock.calls.map(([input]) => input)).toEqual([
      {
        method: 'POST', path: `/api/v1/school/cat-assets/plan-versions/${activation().plan_version_ref}/activations`,
        body: {}, idempotencyKey: 'stable-create-key',
      },
      {
        method: 'PATCH', path: `/api/v1/school/cat-assets/activations/${activation().activation_ref}`,
        body: { expected_revision: 1, status: 'REVOKED' }, idempotencyKey: 'stable-revoke-key',
      },
    ])
  })

  it.each([
    ['numeric engineering flag', { ...flags, engineering_only: 1, items: [], has_more: false }],
    ['numeric interpretation flag', { ...flags, psychological_interpretation_allowed: 0, items: [], has_more: false }],
    ['extra private payload', { ...flags, items: [activation({ bank_document: { secret: true } })], has_more: false }],
  ])('rejects %s in activation metadata', async (_name, response) => {
    transport.requestSchoolCatAssets.mockResolvedValueOnce(envelope(response))
    await expect(new SchoolCatActivationsService().list()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('rejects invalid refs, revisions, and list limits before transport', async () => {
    const service = new SchoolCatActivationsService()
    await expect(service.list({ planVersionRef: 'CPVER_bad' })).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    await expect(service.list({ limit: 101 })).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    await expect(service.create('CPVER_bad', 'stable-key')).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    await expect(service.revoke('CACT_bad', 1, 'stable-key')).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    await expect(service.revoke(activation().activation_ref, 1.5, 'stable-key')).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    expect(transport.requestSchoolCatAssets).not.toHaveBeenCalled()
    expect(catActivationReferencePatterns.activation.test(activation().activation_ref)).toBe(true)
  })

  it('rejects mismatched saved-version reads and mutation resource identities', async () => {
    const otherPlan = 'CPVER_12345678-1234-1234-1234-123456789013'
    const otherActivation = 'CACT_12345678-1234-1234-1234-123456789013'
    const service = new SchoolCatActivationsService()
    transport.requestSchoolCatAssets.mockResolvedValueOnce(envelope({
      ...flags, items: [activation({ plan_version_ref: otherPlan })], has_more: false,
    }))
    await expect(service.list({ planVersionRef: activation().plan_version_ref }))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    transport.requestSchoolCatAssets.mockResolvedValueOnce(envelope({
      ...flags, activation: activation({ plan_version_ref: otherPlan }),
    }))
    await expect(service.create(activation().plan_version_ref, 'stable-key'))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    for (const change of [
      { activation_ref: otherActivation, status: 'REVOKED', revision: 2 },
      { status: 'ACTIVE', revision: 2 },
      { status: 'REVOKED', revision: 1 },
    ]) {
      transport.requestSchoolCatAssets.mockResolvedValueOnce(envelope({ ...flags, activation: activation(change) }))
      await expect(service.revoke(activation().activation_ref, 1, 'stable-revoke-key'))
        .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    }
  })
})
