/* global AbortSignal */

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
