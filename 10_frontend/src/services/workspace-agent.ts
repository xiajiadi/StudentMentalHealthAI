/* global AbortSignal, Blob, TextDecoder */

import { realApiProvider } from './real-api'
import type { SchoolOperationsAuditCategory, SchoolOperationsAuditEvent } from '@/api/client'
import type { RosterKind } from './school-roster-file'
import type { WorkspaceTableSummary } from './workspace-table'
import type { CaseStatus, TeacherReferral } from './school-support'

export type EducationTopic = 'weekly_plan' | 'small_steps' | 'study_stress'

export const educationTopics: Record<EducationTopic, string> = {
  weekly_plan: '帮我制定复习计划',
  small_steps: '怎样把学习目标拆成小步骤？',
  study_stress: '学习压力大时该怎么办？',
}

export interface WorkspaceAgentRow {
  ref: string
  label: string | null
  status: string | null
  due_at: string | null
  completed: number | null
  total: number | null
}

export interface WorkspaceAgentResult {
  schema_version: 'workspace_agent.v1'
  kind: 'student_tasks' | 'class_progress' | 'review_tasks' | 'school_tasks'
    | 'preview_class' | 'class_created' | 'education_topic' | 'unknown'
  rows: WorkspaceAgentRow[]
  total: number
  class_ref: string | null
  token: string | null
  topic: EducationTopic | null
}

export async function runWorkspaceAgent(
  request: { operation: 'snapshot' } | { operation: 'run'; text: string } | { operation: 'confirm'; token: string },
  signal?: AbortSignal,
) {
  return (await realApiProvider.requestWorkspaceAgent<WorkspaceAgentResult>(request, signal)).data
}

export type WorkflowPanel = 'review' | 'cat' | 'resources' | 'library' | 'support' | 'knowledge' | 'feedback' | 'publish' | 'system'
export type WorkspaceAttachment = RosterKind | 'cat_bank'
export type TaskPublicationPreview = {
  kind: 'preview_task'
  class_ref: string
  class_label: string
  opens_at: string
  due_at: string
  enrolled: number
  token: string
  plan_label?: string | null
}
export type CatDraft = {
  kind: 'cat_draft'
  draft_ref: string
  state: 'PREVIEW' | 'SAVED' | 'APPROVED' | 'PUBLISHED'
  plan_name: string
  class_designation: string
  opens_at: string
  due_at: string
  configuration: 'attachment' | 'school_template'
  item_count: number
  min_items: number
  max_items: number
}
export type WorkspaceAgentView =
  | { kind: 'student_tasks' | 'class_progress' | 'review_tasks' | 'school_tasks' | 'school_student_counts'; rows: WorkspaceAgentRow[]; total: number; class_count?: number; active?: number; artifact?: { filename: string; markdown: string } }
  | { kind: 'assessment_picker'; task_ref: string; due_at: string | null }
  | { kind: 'feedback_index'; total: number }
  | { kind: 'feedback_picker'; feedback_ref: string }
  | { kind: 'education_articles'; topics: string[] }
  | { kind: 'school_library_inventory'; total: number; chunks: number }
  | ({ kind: 'table_statistics' } & WorkspaceTableSummary)
  | { kind: 'preview_class'; class_ref: string; token: string }
  | TaskPublicationPreview
  | CatDraft
  | { kind: 'cat_inspection'; item_count: number; dimension_count: number; attachment_has_config: boolean }
  | { kind: 'cat_drafts' | 'cat_handoffs'; drafts: CatDraft[] }
  | ({ kind: 'teacher_referral' } & TeacherReferral)
  | { kind: 'teacher_support_status' | 'specialist_support_status' | 'specialist_support_plan'; total: number; shown: number; counts: Partial<Record<CaseStatus, number>> }
  | { kind: 'professional_review_queue'; task_count: number; open_count: number; in_review_count: number; tasks: { task_ref: string; class_label: string; open_count: number; in_review_count: number }[] }
  | { kind: 'roster_import' }
  | { kind: 'staff_roster_import' }
  | { kind: 'staff_invitation_status'; issued: number; accepted: number; expired: number; revoked: number }
  | { kind: 'school_audit'; items: Omit<SchoolOperationsAuditEvent, 'event_ref'>[]; query: { offset: number; limit: number; category: SchoolOperationsAuditCategory | null }; visible_count: number; has_more: boolean }
  | { kind: 'system_health'; statuses: Record<string, string>; checked_at: string }
  | { kind: 'workflow'; workflow: WorkflowPanel }
  | { kind: 'markdown'; filename: string; markdown: string }

export type WorkspaceEvent = { run_id: string } & (
  | { type: 'start'; trace_id: string }
  | { type: 'status'; status: 'screening' | 'model' | 'checking_response' }
  | { type: 'user' | 'answer'; text: string }
  | { type: 'tool_started'; label: string; call_id: string }
  | { type: 'tool_result'; label: string; call_id: string; view: WorkspaceAgentView }
  | { type: 'tool_failed'; label: string; call_id: string; code: string }
  | { type: 'safety'; text?: string; support: boolean }
  | { type: 'end'; status: 'completed' | 'blocked' | 'failed' | 'interrupted' | 'step_limit'; code?: string }
)

export async function loadWorkspaceConversation(signal?: AbortSignal) {
  const response = await realApiProvider.requestWorkspaceConversation('history', undefined, signal)
  return (await response.json()).data as { events: WorkspaceEvent[]; active: boolean }
}

export async function resetWorkspaceConversation() {
  await realApiProvider.requestWorkspaceConversation('reset')
}

export async function confirmWorkspacePublication(token: string) {
  const response = await realApiProvider.requestWorkspaceConversation('confirm-publication', { token })
  return (await response.json()).data as { task_ref: string; status: string }
}

export async function uploadWorkspaceCat(file: Blob, signal: AbortSignal) {
  const response = await realApiProvider.requestWorkspaceConversation('cat-attachment', file, signal)
  return (await response.json()).data as { ref: string }
}

export async function previewWorkspaceDocument(file: Blob, kind: 'pdf' | 'docx', signal: AbortSignal) {
  const response = await realApiProvider.requestWorkspaceConversation(`document-preview/${kind}`, file, signal)
  return (await response.json()).data as { text: string; characters: number }
}

export async function previewWorkspaceFormula(image: Blob, signal: AbortSignal): Promise<string> {
  const response = await realApiProvider.requestWorkspaceConversation('formula-preview', image, signal)
  const data = (await response.json()).data
  if (typeof data?.text !== 'string' || !data.text.trim() || data.text.length > 700) throw new Error('公式识别结果无法读取')
  return data.text
}

export async function findWorkspaceTaskFeedback(taskRef: string): Promise<string | undefined> {
  const response = await realApiProvider.requestWorkspaceConversation(`task-feedback/${encodeURIComponent(taskRef)}`)
  const reference = (await response.json()).data?.feedback_ref
  if (reference === null) return undefined
  if (typeof reference !== 'string' || !/^FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/.test(reference)) {
    throw new Error('暂时无法核对本次测评的反馈')
  }
  return reference
}

export async function updateWorkspaceCat(draftRef: string, action: 'save' | 'approve') {
  const response = await realApiProvider.requestWorkspaceConversation(
    action === 'save' ? 'save-cat-draft' : 'approve-cat-draft', { draft_ref: draftRef },
  )
  return (await response.json()).data as CatDraft
}

export async function previewWorkspaceCatHandoff(ref: string) {
  const response = await realApiProvider.requestWorkspaceConversation('preview-cat-handoff', { handoff_ref: ref })
  return (await response.json()).data as TaskPublicationPreview
}

export async function sendWorkspaceTurn(
  text: string,
  attachment: WorkspaceAttachment | undefined,
  onEvent: (event: WorkspaceEvent) => void,
  signal: AbortSignal,
  catAttachmentRef?: string,
  tableSummary?: WorkspaceTableSummary,
) {
  const response = await realApiProvider.requestWorkspaceConversation('turn', {
    text, synthetic_only: true, ...(attachment ? { attachment } : {}),
    ...(catAttachmentRef ? { cat_attachment_ref: catAttachmentRef } : {}),
    ...(tableSummary ? { table_summary: tableSummary } : {}),
  }, signal)
  if (!response.body) throw new Error('连接未返回会话数据')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let ended = false
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line) continue
        const event = JSON.parse(line) as WorkspaceEvent
        onEvent(event)
        if (event.type === 'end') ended = true
      }
    }
  } finally {
    reader.releaseLock()
  }
  if (!ended) throw new Error('连接中断，可重新读取会话后继续')
}
