/* global AbortSignal, TextDecoder */

import { realApiProvider } from './real-api'

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

export type WorkflowPanel = 'review' | 'cat' | 'resources' | 'support' | 'knowledge' | 'feedback' | 'publish' | 'system'
export type WorkspaceAttachment = 'student_roster' | 'cat_bank'
export type TaskPublicationPreview = {
  kind: 'preview_task'
  class_ref: string
  class_label: string
  opens_at: string
  due_at: string
  enrolled: number
  token: string
}
export type WorkspaceAgentView =
  | { kind: 'student_tasks' | 'class_progress' | 'review_tasks' | 'school_tasks' | 'school_student_counts'; rows: WorkspaceAgentRow[]; total: number; class_count?: number; active?: number }
  | { kind: 'assessment_picker'; task_ref: string; due_at: string | null }
  | { kind: 'preview_class'; class_ref: string; token: string }
  | TaskPublicationPreview
  | { kind: 'roster_import' }
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

export async function sendWorkspaceTurn(
  text: string,
  attachment: WorkspaceAttachment | undefined,
  onEvent: (event: WorkspaceEvent) => void,
  signal: AbortSignal,
) {
  const response = await realApiProvider.requestWorkspaceConversation('turn', {
    text, synthetic_only: true, ...(attachment ? { attachment } : {}),
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
