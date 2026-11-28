import {RealApiError, realApiProvider} from './real-api'

const root = '/api/v1/school/support'
export const supportPageSize = 20

export const supportCategories = {
  LEARNING_SUPPORT: '学习适应',
  ATTENDANCE_SUPPORT: '出勤与返校',
  PEER_RELATION: '同伴相处',
  FAMILY_CONTEXT: '家庭相关',
  OTHER: '其他',
} as const

export const supportCaseStates = {
  SUBMITTED: '待受理',
  TRIAGED: '已受理',
  PLANNED: '已制定计划',
  FOLLOWING: '跟进中',
  REVIEW: '待复核',
  CLOSED: '已结案',
} as const

export const supportActionStates = {
  PENDING: '待反馈',
  SUBMITTED: '已提交',
  ACCEPTED: '已确认',
  RETURNED: '待补充',
  CANCELLED: '已取消',
} as const

type Category = keyof typeof supportCategories
export type CaseStatus = keyof typeof supportCaseStates
export type TeacherReferral = { category_code: Category; observation: string }
type ActionStatus = keyof typeof supportActionStates
type Row = Record<string, unknown>

const invalid = () => new RealApiError('API_INVALID_RESPONSE', '学校支持服务返回了无法识别的数据。')
const casePattern = /^SSC_(?:[a-f0-9]{32}|DEMO_[0-9]{3})$/
const actionPattern = /^SSA_(?:[a-f0-9]{32}|DEMO_[0-9]{2}_[0-9]{2})$/
const feedbackPattern = /^FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/

export function supportError(error: unknown): string {
  const code = error instanceof RealApiError ? error.code.toLowerCase() : ''
  if (code === 'workflow_conflict' || code === 'idempotency_conflict' || code === 'conflict_idempotency') {
    return '记录已变化，请刷新后核对当前状态。'
  }
  if (code === 'forbidden' || code === 'resource_not_found') return '当前账号无法访问这条记录。'
  if (code === 'validation_failed' || code === 'api_invalid_request') return '请核对提交内容后再试。'
  return '操作未确认，请稍后重试。'
}

function record(value: unknown, fields: readonly string[]): Row {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid()
  const actual = Object.keys(value)
  if (actual.length !== fields.length || !fields.every((field) => Object.hasOwn(value, field))) throw invalid()
  return value as Row
}

function text(value: unknown, max = 128): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw invalid()
  return value
}

function optionalText(value: unknown, max: number) {
  return value === null ? null : text(value, max)
}

function version(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw invalid()
  return value
}

function date(value: unknown): string {
  const result = text(value, 64)
  if (!Number.isFinite(Date.parse(result))) throw invalid()
  return result
}

function reference(value: unknown, pattern: RegExp): string {
  const result = text(value)
  if (!pattern.test(result)) throw invalid()
  return result
}

function choice<const Choices extends object>(value: unknown, choices: Choices): Extract<keyof Choices, string> {
  if (typeof value !== 'string' || !Object.hasOwn(choices, value)) throw invalid()
  return value as Extract<keyof Choices, string>
}

function page<T>(value: unknown, map: (value: unknown) => T) {
  const data = record(value, ['items', 'total'])
  if (!Array.isArray(data.items) || typeof data.total !== 'number'
    || !Number.isSafeInteger(data.total) || data.total < data.items.length) throw invalid()
  return {items: data.items.map(map), total: data.total}
}

const caseFields = ['case_ref', 'source', 'category_code', 'status', 'state_version', 'created_at', 'updated_at']
const detailFields = [...caseFields, 'student_ref', 'class_ref', 'content', 'plan', 'actions', 'assigned_at', 'closed_at']

function summary(data: Row) {
  if (data.source !== 'TEACHER_REFERRAL' && data.source !== 'STUDENT_REQUEST') throw invalid()
  return {
    caseRef: reference(data.case_ref, casePattern),
    category: choice(data.category_code, supportCategories),
    status: choice(data.status, supportCaseStates),
    version: version(data.state_version),
    updatedAt: date(data.updated_at),
  }
}

function action(value: unknown) {
  const data = record(value, ['action_ref', 'case_ref', 'status', 'version', 'teacher_user_id', 'instructions', 'feedback', 'due_at', 'created_at', 'updated_at'])
  return {
    actionRef: reference(data.action_ref, actionPattern),
    caseRef: reference(data.case_ref, casePattern),
    status: choice(data.status, supportActionStates),
    version: version(data.version),
    instructions: optionalText(data.instructions, 4000),
    feedback: optionalText(data.feedback, 4000),
    dueAt: data.due_at === null ? null : date(data.due_at),
  }
}

function detail(value: unknown, expectedRef: string) {
  const data = record(value, detailFields)
  const current = summary(data)
  if (current.caseRef !== expectedRef || !Array.isArray(data.actions)) throw invalid()
  const actions = data.actions.map(action)
  if (actions.some((item) => item.caseRef !== current.caseRef)) throw invalid()
  return {...current, content: optionalText(data.content, 4000), plan: optionalText(data.plan, 4000), actions}
}

export type SupportAction = ReturnType<typeof action>
export type SupportCase = ReturnType<typeof detail>

async function read(path: string, query?: Record<string, string | number>) {
  return (await realApiProvider.requestSchoolSupport({method: 'GET', path: root + path, query})).data
}

async function write(path: string, body: Record<string, unknown>, key: string) {
  return (await realApiProvider.requestSchoolSupport({method: 'POST', path: root + path, body, idempotencyKey: key})).data
}

export function supportRequestKey() {
  return `school-support-${crypto.randomUUID()}`
}

export const schoolSupport = {
  async students() {
    return page(await read('/students'), (item) => {
      const row = record(item, ['student_ref', 'display_name', 'class_ref'])
      return {studentRef: text(row.student_ref), name: text(row.display_name, 120), classRef: text(row.class_ref)}
    }).items
  },
  async cases(offset: number, triagedOnly = false) {
    return page(await read('/cases', {
      offset, limit: supportPageSize, ...(triagedOnly ? {triaged_only: 'true'} : {}),
    }), (item) => summary(record(item, caseFields)))
  },
  async actions(offset: number) {
    return page(await read('/actions', {offset, limit: supportPageSize}), action)
  },
  async detail(caseRef: string) {
    return detail(await read(`/cases/${reference(caseRef, casePattern)}`), caseRef)
  },
  async planEvidence(caseRef: string) {
    const data = record(await read(`/cases/${reference(caseRef, casePattern)}/plan-evidence`), ['feedback'])
    if (data.feedback === null) return null
    const feedback = record(data.feedback, ['title', 'body', 'published_at', 'content_revision'])
    return {
      title: text(feedback.title, 120),
      body: text(feedback.body, 2000),
      publishedAt: date(feedback.published_at),
      revision: version(feedback.content_revision),
    }
  },
  async assignees(caseRef: string) {
    return page(await read(`/cases/${reference(caseRef, casePattern)}/assignees`), (item) => {
      const row = record(item, ['teacher_user_id', 'display_name'])
      return {userId: text(row.teacher_user_id), name: text(row.display_name, 120)}
    }).items
  },
  async create(category: Category, content: string, key: string, student?: {studentRef: string; classRef: string}) {
    const response = record(await write('/cases', {
      category_code: category, content,
      ...(student ? {student_ref: student.studentRef, class_ref: student.classRef} : {}),
    }, key), caseFields)
    const receipt = summary(response)
    if (receipt.category !== category || response.source !== (student ? 'TEACHER_REFERRAL' : 'STUDENT_REQUEST')) throw invalid()
    return receipt
  },
  async askAboutFeedback(feedbackRef: string, revision: number, question: string, key: string) {
    const row = record(await write(`/feedback-questions/${reference(feedbackRef, feedbackPattern)}`, {
      content_revision: version(revision), question,
    }, key), caseFields)
    const receipt = summary(row)
    if (row.source !== 'STUDENT_REQUEST' || receipt.category !== 'OTHER') throw invalid()
    return receipt
  },
  async transition(current: SupportCase, status: Extract<CaseStatus, 'TRIAGED' | 'PLANNED' | 'REVIEW' | 'CLOSED'>, key: string, plan?: string) {
    return detail(await write(`/cases/${current.caseRef}/transitions`, {
      expected_version: current.version, target_status: status, ...(plan ? {plan} : {}),
    }, key), current.caseRef)
  },
  async assign(current: SupportCase, input: {instructions: string; dueAt: string; teacher?: string}, key: string) {
    return detail(await write(`/cases/${current.caseRef}/actions`, {
      expected_version: current.version, instructions: input.instructions, due_at: input.dueAt,
      ...(input.teacher ? {target: 'TEACHER', teacher_user_id: input.teacher} : {target: 'STUDENT'}),
    }, key), current.caseRef)
  },
  async feedback(current: SupportAction, outcome: Exclude<ActionStatus, 'PENDING'>, key: string, feedback?: string) {
    const result = action(await write(`/actions/${current.actionRef}/feedback`, {
      expected_version: current.version, outcome, ...(feedback ? {feedback} : {}),
    }, key))
    if (result.actionRef !== current.actionRef || result.caseRef !== current.caseRef || result.version <= current.version) throw invalid()
    if (result.version === current.version + 1 && result.status !== outcome) throw invalid()
    return result
  },
}
