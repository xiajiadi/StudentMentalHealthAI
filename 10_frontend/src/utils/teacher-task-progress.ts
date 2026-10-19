import type { TeacherTaskProgress } from '@/api/client'

export interface TeacherOverviewProgressRow extends TeacherTaskProgress {
  class_label?: string
  task_label?: string
  task_group?: string
}

export const teacherChartColors = {
  blue: '#2563eb',
  teal: '#0f766e',
  sky: '#53a9cf',
  amber: '#b7791f',
  violet: '#817bd1',
  rose: '#d46a7e',
  grid: '#e4e7ec',
  muted: '#737985',
} as const

export const teacherTaskStatusPalette = {
  completed: { color: '#079db7', ink: '#08798e', wash: '#e6f6f8' },
  inProgress: { color: '#76c8b8', ink: '#27796c', wash: '#e9f6f2' },
  notStarted: { color: '#5b97b4', ink: '#356d87', wash: '#e8f1f6' },
  ended: { color: '#e1a76b', ink: '#875615', wash: '#fbf1e4' },
} as const

export type TeacherTaskPhase = 'upcoming' | 'in_progress' | 'ended' | 'cancelled' | 'unpublished'

export interface TeacherClassSummary {
  classRef: string
  taskCount: number
  activeEnrollmentCount: number
  completedCount: number
  pendingCount: number
  revokedCount: number
  completionRate: number
  tasks: TeacherTaskProgress[]
}

export interface TeacherProgressSummary {
  classCount: number
  currentTaskCount: number
  activeEnrollmentCount: number
  completedCount: number
  pendingCount: number
  revokedCount: number
  completionRate: number
  notStartedCount: number
  inProgressCount: number
  endedCount: number
}

const count = (value: number | null | undefined) => Math.max(0, Number.isFinite(value) ? Math.floor(Number(value)) : 0)

export const shortTeacherRef = (value: string) => value.slice(-6)

type TeacherTaskProgressWithDisplayLabels = TeacherTaskProgress & {
  class_label?: string
  task_label?: string
  task_group?: string
}

export const teacherClassDisplayLabel = (classRef: string, rows: TeacherTaskProgress[]) => {
  const label = rows
    .filter((row) => row.class_ref === classRef)
    .map((row) => (row as TeacherTaskProgressWithDisplayLabels).class_label?.trim())
    .find((value): value is string => Boolean(value))
  return label ?? `班级 ${shortTeacherRef(classRef)}`
}

export const teacherTaskDisplayLabel = (row: TeacherTaskProgress) => {
  const label = (row as TeacherTaskProgressWithDisplayLabels).task_label?.trim()
  return label || `任务 ${shortTeacherRef(row.task_ref)}`
}

export const teacherTaskHeatmapDimension = (row: TeacherTaskProgress) => {
  const labeled = row as TeacherTaskProgressWithDisplayLabels
  const group = labeled.task_group?.trim()
  if (group) return { key: `group:${group}`, label: group }
  return {
    key: `task:${row.task_ref}`,
    label: labeled.task_label?.trim() || `任务 ${shortTeacherRef(row.task_ref)}`,
  }
}

export const taskProgressCount = (row: TeacherTaskProgress, key: keyof Pick<
  TeacherTaskProgress,
  | 'published_enrollment_count'
  | 'active_enrollment_count'
  | 'revoked_enrollment_count'
  | 'not_started_count'
  | 'created_count'
  | 'in_progress_count'
  | 'completed_count'
  | 'abandoned_count'
  | 'invalid_count'
>) => count(row[key])

export const taskCompletionRate = (row: TeacherTaskProgress) => {
  const active = taskProgressCount(row, 'active_enrollment_count')
  if (active === 0) return 0
  return Math.min(100, Math.round(taskProgressCount(row, 'completed_count') / active * 100))
}

export const taskActionablePendingCount = (row: TeacherTaskProgress) =>
  taskProgressCount(row, 'not_started_count')
  + taskProgressCount(row, 'created_count')
  + taskProgressCount(row, 'in_progress_count')

export const teacherTaskPhase = (row: TeacherTaskProgress, now = Date.now()): TeacherTaskPhase => {
  const status = row.task_status.trim().toUpperCase()
  if (status === 'CANCELLED' || status === 'CANCELED') return 'cancelled'
  if (status !== 'PUBLISHED') return 'unpublished'

  const opensAt = Date.parse(row.opens_at)
  const dueAt = row.due_at ? Date.parse(row.due_at) : Number.NaN
  if (Number.isFinite(opensAt) && opensAt > now) return 'upcoming'
  if (Number.isFinite(dueAt) && dueAt < now) return 'ended'
  return 'in_progress'
}

export const teacherTaskPhaseLabel = (phase: TeacherTaskPhase) => ({
  upcoming: '待开始',
  in_progress: '进行中',
  ended: '已结束',
  cancelled: '已取消',
  unpublished: '未发布',
}[phase])

export const teacherTaskStatusLabel = (status: string) => ({
  PUBLISHED: '已发布',
  CANCELLED: '已取消',
  CANCELED: '已取消',
  DRAFT: '未发布',
  UNPUBLISHED: '未发布',
}[status.trim().toUpperCase()] ?? '状态待确认')

export const formatTeacherDate = (value: string | null, emptyLabel = '未设置') => {
  if (!value) return emptyLabel
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '时间待确认'
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

export const summarizeTeacherProgress = (rows: TeacherTaskProgress[], now = Date.now()): TeacherProgressSummary => {
  const classes = new Set(rows.map((row) => row.class_ref))
  const activeEnrollmentCount = rows.reduce((total, row) => total + taskProgressCount(row, 'active_enrollment_count'), 0)
  const completedCount = rows.reduce((total, row) => total + taskProgressCount(row, 'completed_count'), 0)
  const pendingCount = rows.reduce((total, row) => total + taskActionablePendingCount(row), 0)
  const currentTaskCount = rows.filter((row) => teacherTaskPhase(row, now) === 'in_progress').length

  return {
    classCount: classes.size,
    currentTaskCount,
    activeEnrollmentCount,
    completedCount,
    pendingCount,
    revokedCount: rows.reduce((total, row) => total + taskProgressCount(row, 'revoked_enrollment_count'), 0),
    completionRate: activeEnrollmentCount === 0 ? 0 : Math.min(100, Math.round(completedCount / activeEnrollmentCount * 100)),
    notStartedCount: rows.reduce((total, row) => total + taskProgressCount(row, 'not_started_count') + taskProgressCount(row, 'created_count'), 0),
    inProgressCount: rows.reduce((total, row) => total + taskProgressCount(row, 'in_progress_count'), 0),
    endedCount: rows.reduce((total, row) => total + taskProgressCount(row, 'abandoned_count') + taskProgressCount(row, 'invalid_count'), 0),
  }
}

export const summarizeTeacherClasses = (rows: TeacherTaskProgress[]): TeacherClassSummary[] => {
  const grouped = new Map<string, TeacherTaskProgress[]>()
  for (const row of rows) {
    const current = grouped.get(row.class_ref) ?? []
    current.push(row)
    grouped.set(row.class_ref, current)
  }

  return [...grouped.entries()].map(([classRef, tasks]) => {
    const activeEnrollmentCount = tasks.reduce((total, row) => total + taskProgressCount(row, 'active_enrollment_count'), 0)
    const completedCount = tasks.reduce((total, row) => total + taskProgressCount(row, 'completed_count'), 0)
    return {
      classRef,
      taskCount: tasks.length,
      activeEnrollmentCount,
      completedCount,
      pendingCount: tasks.reduce((total, row) => total + taskActionablePendingCount(row), 0),
      revokedCount: tasks.reduce((total, row) => total + taskProgressCount(row, 'revoked_enrollment_count'), 0),
      completionRate: activeEnrollmentCount === 0 ? 0 : Math.min(100, Math.round(completedCount / activeEnrollmentCount * 100)),
      tasks: [...tasks].sort((a, b) => (Date.parse(a.due_at ?? '') || Number.MAX_SAFE_INTEGER) - (Date.parse(b.due_at ?? '') || Number.MAX_SAFE_INTEGER)),
    }
  }).sort((a, b) => a.classRef.localeCompare(b.classRef, 'zh-CN'))
}

export const teacherEnrollmentStatusBreakdown = (rows: TeacherTaskProgress[]) => {
  const totals = rows.reduce((result, row) => ({
    notStarted: result.notStarted + taskProgressCount(row, 'not_started_count'),
    inProgress: result.inProgress + taskProgressCount(row, 'created_count') + taskProgressCount(row, 'in_progress_count'),
    completed: result.completed + taskProgressCount(row, 'completed_count'),
    ended: result.ended + taskProgressCount(row, 'abandoned_count') + taskProgressCount(row, 'invalid_count'),
    revoked: result.revoked + taskProgressCount(row, 'revoked_enrollment_count'),
  }), { notStarted: 0, inProgress: 0, completed: 0, ended: 0, revoked: 0 })

  return [
    { key: 'notStarted', label: '未开始', value: totals.notStarted },
    { key: 'inProgress', label: '进行中', value: totals.inProgress },
    { key: 'completed', label: '已完成', value: totals.completed },
    { key: 'ended', label: '已结束 / 不可继续', value: totals.ended },
    { key: 'revoked', label: '已撤销', value: totals.revoked },
  ]
}
