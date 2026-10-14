import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  SchoolConversationSafetyService,
} from '@/services/school-conversation-safety'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

const unassigned = {
  case_ref: 'SCONV_SYNTHETIC_01', status: 'UNASSIGNED_PENDING', state_version: 2,
  class_ref: 'CLASS_SYNTHETIC_01', created_at: '2026-10-15T01:00:00Z',
  updated_at: '2026-10-15T01:01:00Z',
}

const assignedCase = (changes: Record<string, unknown> = {}) => ({
  case_ref: 'SCONV_SYNTHETIC_01', class_ref: 'CLASS_SYNTHETIC_01', action: 'REVIEW_REQUIRED',
  reason_codes: ['SAFE_REVIEW_REQUIRED'], status: 'IN_REVIEW', state_version: 3,
  decision_code: null, created_at: '2026-10-15T01:00:00Z', updated_at: '2026-10-15T01:03:00Z',
  assigned_at: '2026-10-15T01:02:00Z', reviewed_at: null, closed_at: null,
  review_note: 'synthetic note', ...changes,
})

describe('school conversation safety transport', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('accepts only opaque admin queue metadata and rejects any extra identity or case content', async () => {
    const service = new SchoolConversationSafetyService()
    fetchMock.mockResolvedValueOnce(response(envelope({ items: [unassigned], total: 1 })))
    const page = await service.listUnassigned()
    expect(page.items).toEqual([unassigned])
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/school/conversation-safety/unassigned?offset=0&limit=20'),
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    )

    fetchMock.mockResolvedValueOnce(response(envelope({ items: [], total: 21 })))
    await service.listUnassigned(20, 20)
    expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/school/conversation-safety/unassigned?offset=20&limit=20'),
      expect.objectContaining({ method: 'GET' }),
    )

    fetchMock.mockResolvedValueOnce(response(envelope({
      items: [{ ...unassigned, subject_id: 'must-not-cross-admin-boundary' }], total: 1,
    })))
    await expect(service.listUnassigned()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('uses CSRF, idempotency and CAS versions for note and unresolved workflow transitions', async () => {
    const service = new SchoolConversationSafetyService()
    const assignedSummary = Object.fromEntries(
      Object.entries(assignedCase({ status: 'ASSIGNED', state_version: 2 })).filter(([field]) => field !== 'review_note'),
    )
    fetchMock.mockResolvedValueOnce(response(envelope({ items: [assignedSummary], total: 21 })))
    const page = await service.listAssigned(20, 20)
    expect(page.items[0]?.case_ref).toBe('SCONV_SYNTHETIC_01')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/school/conversation-safety/assigned?offset=20&limit=20'),
      expect.objectContaining({ method: 'GET' }),
    )
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(assignedCase())))
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(assignedCase({
        status: 'ESCALATION_NEEDED', state_version: 4, decision_code: 'UNRESOLVED_NEEDS_CONTEXT',
        updated_at: '2026-10-15T01:04:00Z',
      }))))

    const note = await service.saveNote('SCONV_SYNTHETIC_01', 2, 'synthetic note', 'safety-note-idem')
    expect(note.state_version).toBe(3)
    const noteCall = fetchMock.mock.calls[2] as [string, RequestInit]
    expect(noteCall[0]).toContain('/SCONV_SYNTHETIC_01/note')
    expect(noteCall[1].method).toBe('PUT')
    expect(noteCall[1].headers).toMatchObject({ 'X-CSRF-Token': 'csrf-synthetic', 'Idempotency-Key': 'safety-note-idem' })
    expect(JSON.parse(String(noteCall[1].body))).toEqual({ expected_version: 2, note: 'synthetic note' })

    const updated = await service.transition('SCONV_SYNTHETIC_01', 3, 'ESCALATION_NEEDED', 'safety-transition-idem')
    expect(updated.status).toBe('ESCALATION_NEEDED')
    const transitionCall = fetchMock.mock.calls[4] as [string, RequestInit]
    expect(transitionCall[0]).toContain('/SCONV_SYNTHETIC_01/transition')
    expect(JSON.parse(String(transitionCall[1].body))).toEqual({
      expected_version: 3, status: 'ESCALATION_NEEDED', decision_code: 'UNRESOLVED_NEEDS_CONTEXT',
    })
    expect(transitionCall[1].headers).toMatchObject({ 'Idempotency-Key': 'safety-transition-idem' })
  })
})
