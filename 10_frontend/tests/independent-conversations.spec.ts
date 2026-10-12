import { describe, expect, it, vi } from 'vitest'
import type { ApiEnvelope } from '@/types/contracts'
import { RealApiError } from '@/services/real-api'
import {
  IndependentConversationsService,
  newConversationIdempotencyKey,
  type IndependentConversationRequest,
} from '@/services/independent-conversations'

const conversation = {
  conversation_id: 'CONV_SYNTHETIC_001',
  status: 'open',
  created_at: '2026-10-07T00:00:00Z',
  updated_at: '2026-10-07T00:01:00Z',
}

const userTurn = {
  turn_id: 'TURN_SYNTHETIC_001',
  status: 'completed',
  action: 'ALLOW',
  created_at: '2026-10-07T00:01:00Z',
  completed_at: '2026-10-07T00:01:02Z',
  safe_metadata: {},
  citations: [{
    citation_id: 'CIT_SYNTHETIC_001', source_id: 'SRC_SYNTHETIC_001', chunk_id: null,
    document_id: null, title: '学习计划资料', organization: '合成示例', locator: '第 1 节',
    source_version: null, source_hash: null, rank: 1,
  }],
}

const detailDto = {
  conversation,
  messages: [
    { message_id: 'MSG_SYNTHETIC_001', sequence: 1, kind: 'user_input', created_at: userTurn.created_at, payload: { turn_id: userTurn.turn_id, text: '如何安排复习？' } },
    {
      message_id: 'MSG_SYNTHETIC_002', sequence: 2, kind: 'approved_output', created_at: userTurn.completed_at,
      payload: { turn_id: userTurn.turn_id, content: {
        summary: '可以先列出本周要完成的任务。',
        observations: ['把任务拆成较小步骤。'],
        suggestions: [{ text: '为每项任务安排一个时间段。', source_chunk_ids: ['CHUNK_PRIVATE_001'] }],
        disclaimer: '这是一般教育信息。',
      } },
    },
  ],
  turns: [userTurn], offset: 0, limit: 20, total_turns: 1, has_more: false,
}

const envelope = <T>(data: T): ApiEnvelope<T> => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })

const makeService = (response: unknown) => {
  const calls: IndependentConversationRequest[] = []
  const requestIndependentConversation = vi.fn(async <T>(request: IndependentConversationRequest): Promise<ApiEnvelope<T>> => {
    calls.push(request)
    if (response instanceof Error) throw response
    return envelope(response as T)
  })
  return { service: new IndependentConversationsService({ requestIndependentConversation }), calls, requestIndependentConversation }
}

describe('独立教育支持 API', () => {
  it('只请求分页元数据，不要求列表摘要', async () => {
    const { service, calls } = makeService({ items: [conversation], total: 1, has_more: true })

    const page = await service.list(20, 10)

    expect(page).toEqual({
      items: [{ conversationId: conversation.conversation_id, status: 'open', createdAt: conversation.created_at, updatedAt: conversation.updated_at }],
      total: 1,
      hasMore: true,
    })
    expect(calls).toEqual([{ method: 'GET', path: '/api/v1/student/conversations', query: { offset: 20, limit: 10 } }])
  })

  it('校验解密后的历史 DTO，并只向页面暴露已批准内容与可读引用', async () => {
    const { service } = makeService(detailDto)

    const detail = await service.detail(conversation.conversation_id)

    expect(detail.messages.map((message) => message.role)).toEqual(['student', 'assistant'])
    expect(detail.messages[0]?.text).toBe('如何安排复习？')
    expect(detail.messages[1]?.content).toMatchObject({ kind: 'answer', summary: '可以先列出本周要完成的任务。' })
    expect(detail.messages[1]?.turn.citations).toEqual([{
      citationId: 'CIT_SYNTHETIC_001', title: '学习计划资料', organization: '合成示例', locator: '第 1 节', rank: 1,
    }])
    expect(JSON.stringify(detail)).not.toContain('CHUNK_PRIVATE_001')
    expect(JSON.stringify(detail)).not.toContain('safe_metadata')
  })

  it('拒绝关联到另一会话的响应或含内部字段的历史内容', async () => {
    const mismatched = makeService({ ...detailDto, conversation: { ...conversation, conversation_id: 'CONV_SYNTHETIC_002' } })
    await expect(mismatched.service.detail(conversation.conversation_id)).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })

    const internal = makeService({ ...detailDto, system_prompt: 'internal' })
    await expect(internal.service.detail(conversation.conversation_id)).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('保留已批准的安全提示与阻断状态，不把它转换成普通回答', async () => {
    const safetyTurn = { ...userTurn, status: 'blocked', action: 'CRISIS_ROUTE', citations: [] }
    const safetyDetail = {
      ...detailDto,
      messages: [
        detailDto.messages[0],
        {
          message_id: 'MSG_SYNTHETIC_003', sequence: 2, kind: 'approved_output', created_at: safetyTurn.completed_at,
          payload: { turn_id: safetyTurn.turn_id, content: { kind: 'approved_safety_response', text: '合成安全提示内容。' } },
        },
      ],
      turns: [safetyTurn],
    }
    const { service } = makeService(safetyDetail)

    const detail = await service.detail(conversation.conversation_id)

    expect(detail.messages[0]?.turn.status).toBe('blocked')
    expect(detail.messages[1]?.content).toEqual({ kind: 'approved_safety_response', text: '合成安全提示内容。' })
  })

  it('提交只含文本与稳定幂等键，响应失败时不触发服务端外的回退', async () => {
    const { service, calls } = makeService({
      turn_id: 'TURN_SYNTHETIC_002', status: 'requested', replayed: false, action: null,
      completed_at: null, user_message_sequence: 3, assistant_message_sequence: null,
      citations: [], safe_metadata: {}, content: null,
    })
    const receipt = await service.send(conversation.conversation_id, '  合成消息  ', 'stable-key')
    expect(receipt.status).toBe('requested')
    expect(calls).toEqual([{
      method: 'POST', path: '/api/v1/student/conversations/CONV_SYNTHETIC_001/messages',
      body: { text: '合成消息' }, idempotencyKey: 'stable-key',
    }])

    const rejected = makeService(new RealApiError('NETWORK_ERROR', 'request failed'))
    await expect(rejected.service.send(conversation.conversation_id, '合成消息', 'stable-key')).rejects.toThrow('request failed')
    expect(rejected.requestIndependentConversation).toHaveBeenCalledTimes(1)
  })

  it('不发送格式错误的会话标识或分页参数', async () => {
    const { service, requestIndependentConversation } = makeService(detailDto)

    await expect(service.detail('/api/v1/student/conversations/CONV_SYNTHETIC_001')).rejects.toBeInstanceOf(RealApiError)
    await expect(service.list(-1, 20)).rejects.toBeInstanceOf(RealApiError)
    expect(requestIndependentConversation).not.toHaveBeenCalled()
  })

  it('接受 Backend 合约允许的点号会话与轮次标识', async () => {
    const dottedConversation = { ...conversation, conversation_id: 'CONV_SYNTHETIC.001' }
    const dottedTurnId = 'TURN_SYNTHETIC.001'
    const dottedDetail = {
      ...detailDto,
      conversation: dottedConversation,
      turns: [{ ...userTurn, turn_id: dottedTurnId }],
      messages: detailDto.messages.map((message) => ({
        ...message,
        payload: { ...message.payload, turn_id: dottedTurnId },
      })),
    }
    const { service, calls } = makeService(dottedDetail)

    const detail = await service.detail(dottedConversation.conversation_id)

    expect(detail.conversation.conversationId).toBe('CONV_SYNTHETIC.001')
    expect(detail.messages[0]?.turnId).toBe(dottedTurnId)
    expect(calls[0]?.path).toBe('/api/v1/student/conversations/CONV_SYNTHETIC.001')
  })

  it('生成加密安全的幂等标识', () => {
    expect(newConversationIdempotencyKey()).toMatch(/^independent-conversation-[0-9a-f-]{36}$/i)
  })
})
