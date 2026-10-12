import type { ApiEnvelope } from '@/types/contracts'
import { RealApiError, requestIndependentConversation, type IndependentConversationRequest } from '@/services/real-api'

const basePath = '/api/v1/student/conversations'

export type ConversationStatus = 'open' | 'active' | 'closed' | 'archived'
export type ConversationTurnStatus = 'requested' | 'completed' | 'blocked' | 'failed'

export interface IndependentConversation {
  conversationId: string
  status: ConversationStatus
  createdAt: string
  updatedAt: string
}

export interface IndependentCitation {
  citationId: string
  title: string | null
  organization: string | null
  locator: string | null
  rank: number
}

export interface IndependentSuggestion {
  text: string
}

export interface IndependentAnswer {
  kind: 'answer'
  summary: string
  observations: string[]
  suggestions: IndependentSuggestion[]
  disclaimer: string
}

export interface ApprovedSafetyResponse {
  kind: 'approved_safety_response'
  text: string
}

export type IndependentMessageContent = IndependentAnswer | ApprovedSafetyResponse

export interface IndependentConversationTurn {
  turnId: string
  status: ConversationTurnStatus
  action: string | null
  createdAt: string
  completedAt: string | null
  citations: IndependentCitation[]
}

export interface IndependentConversationMessage {
  messageId: string
  sequence: number
  createdAt: string
  turnId: string
  role: 'student' | 'assistant'
  text: string | null
  content: IndependentMessageContent | null
  turn: IndependentConversationTurn
}

export interface IndependentConversationPage {
  items: IndependentConversation[]
  total: number
  hasMore: boolean
}

export interface IndependentConversationDetail {
  conversation: IndependentConversation
  messages: IndependentConversationMessage[]
  offset: number
  limit: number
  totalTurns: number
  hasMore: boolean
}

export interface IndependentTurnReceipt {
  turnId: string
  status: ConversationTurnStatus
  replayed: boolean
  action: string | null
  completedAt: string | null
  content: IndependentMessageContent | null
  citations: IndependentCitation[]
}

export interface IndependentConversationTransport {
  requestIndependentConversation<T>(request: IndependentConversationRequest): Promise<ApiEnvelope<T>>
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const invalidResponse = (message: string): never => {
  throw new RealApiError('API_INVALID_RESPONSE', message)
}

const expectKeys = (value: Record<string, unknown>, required: string[], allowed = required) => {
  if (required.some((key) => !Object.hasOwn(value, key)) || Object.keys(value).some((key) => !allowed.includes(key))) {
    invalidResponse('教育支持记录格式无法识别。')
  }
}

const expectString = (value: unknown, message: string): string => {
  if (typeof value !== 'string' || !value.trim()) return invalidResponse(message)
  return value
}

const expectNullableString = (value: unknown, message: string): string | null => {
  if (value === null) return null
  return expectString(value, message)
}

const expectSafeId = (value: unknown, prefix: 'CONV' | 'TURN'): string => {
  const id = expectString(value, '教育支持记录格式无法识别。')
  if (!new RegExp(`^${prefix}_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$`).test(id)) {
    return invalidResponse('教育支持记录格式无法识别。')
  }
  return id
}

const mapConversation = (value: unknown): IndependentConversation => {
  if (!isRecord(value)) return invalidResponse('会话记录格式无法识别。')
  expectKeys(value, ['conversation_id', 'status', 'created_at', 'updated_at'])
  const conversationId = expectSafeId(value.conversation_id, 'CONV')
  const status = value.status
  if (status !== 'open' && status !== 'active' && status !== 'closed' && status !== 'archived') {
    return invalidResponse('会话状态无法识别。')
  }
  return {
    conversationId,
    status,
    createdAt: expectString(value.created_at, '会话时间格式无法识别。'),
    updatedAt: expectString(value.updated_at, '会话时间格式无法识别。'),
  }
}

const mapCitation = (value: unknown): IndependentCitation => {
  if (!isRecord(value)) return invalidResponse('来源信息格式无法识别。')
  const keys = [
    'citation_id', 'source_id', 'chunk_id', 'document_id', 'title', 'organization',
    'locator', 'source_version', 'source_hash', 'rank',
  ]
  expectKeys(value, keys)
  const optionalTextKeys = [
    'chunk_id', 'document_id', 'title', 'organization', 'locator', 'source_version', 'source_hash',
  ]
  for (const key of optionalTextKeys) {
    if (value[key] !== null && typeof value[key] !== 'string') return invalidResponse('来源信息格式无法识别。')
  }
  expectString(value.citation_id, '来源信息格式无法识别。')
  expectString(value.source_id, '来源信息格式无法识别。')
  if (typeof value.rank !== 'number' || !Number.isInteger(value.rank) || value.rank < 1) {
    return invalidResponse('来源信息格式无法识别。')
  }
  return {
    citationId: value.citation_id as string,
    title: value.title as string | null,
    organization: value.organization as string | null,
    locator: value.locator as string | null,
    rank: value.rank,
  }
}

const mapContent = (value: unknown): IndependentMessageContent => {
  if (!isRecord(value)) return invalidResponse('已审核回复格式无法识别。')
  if (value.kind === 'approved_safety_response') {
    expectKeys(value, ['kind', 'text'])
    return { kind: 'approved_safety_response', text: expectString(value.text, '安全提示格式无法识别。') }
  }
  expectKeys(value, ['summary', 'observations', 'suggestions', 'disclaimer'])
  if (!Array.isArray(value.observations) || !value.observations.every((item) => typeof item === 'string')) {
    return invalidResponse('已审核回复格式无法识别。')
  }
  if (!Array.isArray(value.suggestions)) return invalidResponse('已审核回复格式无法识别。')
  const suggestions = value.suggestions.map((item): IndependentSuggestion => {
    if (!isRecord(item)) return invalidResponse('已审核回复格式无法识别。')
    expectKeys(item, ['text', 'source_chunk_ids'])
    if (!Array.isArray(item.source_chunk_ids) || item.source_chunk_ids.length === 0
      || !item.source_chunk_ids.every((chunkId) => typeof chunkId === 'string' && chunkId.length > 0)) {
      return invalidResponse('已审核回复格式无法识别。')
    }
    return { text: expectString(item.text, '已审核回复格式无法识别。') }
  })
  return {
    kind: 'answer',
    summary: expectString(value.summary, '已审核回复格式无法识别。'),
    observations: value.observations,
    suggestions,
    disclaimer: expectString(value.disclaimer, '已审核回复格式无法识别。'),
  }
}

const mapTurn = (value: unknown): IndependentConversationTurn => {
  if (!isRecord(value)) return invalidResponse('对话状态格式无法识别。')
  expectKeys(value, ['turn_id', 'status', 'action', 'created_at', 'completed_at', 'safe_metadata', 'citations'])
  const turnId = expectSafeId(value.turn_id, 'TURN')
  const status = value.status
  if (status !== 'requested' && status !== 'completed' && status !== 'blocked' && status !== 'failed') {
    return invalidResponse('对话状态无法识别。')
  }
  if (!isRecord(value.safe_metadata) || !Array.isArray(value.citations)) {
    return invalidResponse('对话状态格式无法识别。')
  }
  return {
    turnId,
    status,
    action: expectNullableString(value.action, '对话状态格式无法识别。'),
    createdAt: expectString(value.created_at, '对话时间格式无法识别。'),
    completedAt: expectNullableString(value.completed_at, '对话时间格式无法识别。'),
    citations: value.citations.map(mapCitation),
  }
}

const mapMessage = (value: unknown, turns: Map<string, IndependentConversationTurn>): IndependentConversationMessage => {
  if (!isRecord(value)) return invalidResponse('历史消息格式无法识别。')
  expectKeys(value, ['message_id', 'sequence', 'kind', 'created_at', 'payload'])
  if (typeof value.sequence !== 'number' || !Number.isInteger(value.sequence) || value.sequence < 1 || !isRecord(value.payload)) {
    return invalidResponse('历史消息格式无法识别。')
  }
  const payload = value.payload
  const turnId = expectSafeId(payload.turn_id, 'TURN')
  const turn = turns.get(turnId)
  if (!turn) return invalidResponse('历史消息与对话状态不匹配。')
  if (value.kind === 'user_input') {
    expectKeys(payload, ['turn_id', 'text'])
    return {
      messageId: expectString(value.message_id, '历史消息格式无法识别。'),
      sequence: value.sequence,
      createdAt: expectString(value.created_at, '历史消息时间格式无法识别。'),
      turnId,
      role: 'student',
      text: expectString(payload.text, '历史消息格式无法识别。'),
      content: null,
      turn,
    }
  }
  if (value.kind === 'approved_output') {
    expectKeys(payload, ['turn_id', 'content'])
    return {
      messageId: expectString(value.message_id, '历史消息格式无法识别。'),
      sequence: value.sequence,
      createdAt: expectString(value.created_at, '历史消息时间格式无法识别。'),
      turnId,
      role: 'assistant',
      text: null,
      content: mapContent(payload.content),
      turn,
    }
  }
  return invalidResponse('历史消息类型无法识别。')
}

const mapTurnReceipt = (value: unknown): IndependentTurnReceipt => {
  if (!isRecord(value)) return invalidResponse('发送结果格式无法识别。')
  const allowed = [
    'turn_id', 'status', 'replayed', 'action', 'completed_at', 'user_message_sequence',
    'assistant_message_sequence', 'citations', 'safe_metadata', 'content',
  ]
  expectKeys(value, allowed.filter((key) => key !== 'content'), allowed)
  const status = value.status
  if (status !== 'requested' && status !== 'completed' && status !== 'blocked' && status !== 'failed') {
    return invalidResponse('发送状态无法识别。')
  }
  if (typeof value.replayed !== 'boolean' || !Array.isArray(value.citations) || !isRecord(value.safe_metadata)) {
    return invalidResponse('发送结果格式无法识别。')
  }
  for (const key of ['user_message_sequence', 'assistant_message_sequence']) {
    if (value[key] !== null && (!Number.isInteger(value[key]) || (value[key] as number) < 1)) {
      return invalidResponse('发送结果格式无法识别。')
    }
  }
  if (value.content !== undefined && value.content !== null) {
    if (!isRecord(value.content)) return invalidResponse('发送结果格式无法识别。')
  }
  if (value.action !== null && typeof value.action !== 'string') {
    return invalidResponse('发送结果格式无法识别。')
  }
  return {
    turnId: expectSafeId(value.turn_id, 'TURN'),
    status,
    replayed: value.replayed,
    action: expectNullableString(value.action, '发送结果格式无法识别。'),
    completedAt: expectNullableString(value.completed_at, '发送结果时间格式无法识别。'),
    content: value.content == null ? null : mapContent(value.content),
    citations: value.citations.map(mapCitation),
  }
}

const defaultTransport: IndependentConversationTransport = {
  requestIndependentConversation<T>(request: IndependentConversationRequest): Promise<ApiEnvelope<T>> {
    return requestIndependentConversation<T>(request)
  },
}

export class IndependentConversationsService {
  constructor(private readonly transport: IndependentConversationTransport = defaultTransport) {}

  async list(offset = 0, limit = 20): Promise<IndependentConversationPage> {
    if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 50) {
      throw new RealApiError('VALIDATION_FAILED', '会话分页参数无效。')
    }
    const response = await this.transport.requestIndependentConversation<unknown>({
      method: 'GET',
      path: basePath,
      query: { offset, limit },
    })
    const data = response.data
    if (!isRecord(data)) return invalidResponse('会话列表格式无法识别。')
    expectKeys(data, ['items', 'total', 'has_more'])
    if (!Array.isArray(data.items) || typeof data.total !== 'number' || !Number.isInteger(data.total)
      || data.total < 0 || typeof data.has_more !== 'boolean') return invalidResponse('会话列表格式无法识别。')
    return { items: data.items.map(mapConversation), total: data.total, hasMore: data.has_more }
  }

  async create(idempotencyKey: string): Promise<IndependentConversation> {
    const response = await this.transport.requestIndependentConversation<unknown>({
      method: 'POST', path: basePath, body: {}, idempotencyKey,
    })
    return mapConversation(response.data)
  }

  async detail(conversationId: string, offset = 0, limit = 20): Promise<IndependentConversationDetail> {
    const id = expectSafeId(conversationId, 'CONV')
    if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 50) {
      throw new RealApiError('VALIDATION_FAILED', '会话分页参数无效。')
    }
    const response = await this.transport.requestIndependentConversation<unknown>({
      method: 'GET',
      path: `${basePath}/${encodeURIComponent(id)}`,
      query: { offset, limit },
    })
    const data = response.data
    if (!isRecord(data)) return invalidResponse('会话详情格式无法识别。')
    expectKeys(data, ['conversation', 'messages', 'turns', 'offset', 'limit', 'total_turns', 'has_more'])
    if (!Array.isArray(data.messages) || !Array.isArray(data.turns)
      || typeof data.offset !== 'number' || !Number.isInteger(data.offset) || data.offset < 0
      || typeof data.limit !== 'number' || !Number.isInteger(data.limit) || data.limit < 1 || data.limit > 50
      || typeof data.total_turns !== 'number' || !Number.isInteger(data.total_turns) || data.total_turns < 0
      || typeof data.has_more !== 'boolean') {
      return invalidResponse('会话详情格式无法识别。')
    }
    const conversation = mapConversation(data.conversation)
    if (conversation.conversationId !== id) return invalidResponse('会话详情标识不匹配。')
    const turns = data.turns.map(mapTurn)
    const turnMap = new Map(turns.map((turn) => [turn.turnId, turn]))
    const messages = data.messages.map((message) => mapMessage(message, turnMap))
    if (messages.some((message, index) => index > 0 && messages[index - 1]!.sequence >= message.sequence)) {
      return invalidResponse('历史消息顺序无法识别。')
    }
    return {
      conversation,
      messages,
      offset: data.offset,
      limit: data.limit,
      totalTurns: data.total_turns,
      hasMore: data.has_more,
    }
  }

  async send(conversationId: string, text: string, idempotencyKey: string): Promise<IndependentTurnReceipt> {
    const id = expectSafeId(conversationId, 'CONV')
    const message = text.trim()
    if (!message || message.length > 20_000) throw new RealApiError('VALIDATION_FAILED', '请输入不超过 20000 个字符的消息。')
    if (!idempotencyKey.trim() || idempotencyKey.length > 200) throw new RealApiError('VALIDATION_FAILED', '消息请求标识无效。')
    const response = await this.transport.requestIndependentConversation<unknown>({
      method: 'POST',
      path: `${basePath}/${encodeURIComponent(id)}/messages`,
      body: { text: message },
      idempotencyKey,
    })
    return mapTurnReceipt(response.data)
  }
}

export const independentConversations = new IndependentConversationsService()

export const newConversationIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  }
  return `independent-conversation-${crypto.randomUUID()}`
}
