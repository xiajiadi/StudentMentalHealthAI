import type { TeacherTaskProgress } from '@/api/client'
import {
  taskActionablePendingCount,
  taskCompletionRate,
  taskProgressCount,
  teacherClassDisplayLabel,
  teacherTaskDisplayLabel,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
  type TeacherTaskPhase,
} from '@/utils/teacher-task-progress'

export type PlannerFilterPhase = 'all' | TeacherTaskPhase
export type PlannerEventKind = 'start' | 'due'

export interface PlannerTask {
  key: string
  row: TeacherTaskProgress
  label: string
  classLabel: string
  phase: TeacherTaskPhase
  phaseLabel: string
  activeCount: number
  completedCount: number
  notStartedCount: number
  inProgressCount: number
  endedCount: number
  revokedCount: number
  pendingCount: number
  completionRate: number | null
  opensAt: Date | null
  dueAt: Date | null
  isDueSoon: boolean
}

export interface PlannerEvent {
  key: string
  dateKey: string
  kind: PlannerEventKind
  timestamp: number
  timeLabel: string
  task: PlannerTask
}

export interface PlannerAgendaItem {
  key: string
  task: PlannerTask
  events: PlannerEvent[]
}

export interface PlannerCalendarCell {
  dateKey: string
  dayNumber: number
  inCurrentMonth: boolean
  isToday: boolean
  isSelected: boolean
  events: PlannerEvent[]
  moreCount: number
}

const parseDate = (value: string | null | undefined) => {
  if (!value) return null
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp) : null
}

export const localDateKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`

export const dateFromKey = (key: string) => {
  const [year, month, day] = key.split('-').map(Number)
  if (![year, month, day].every(Number.isFinite)) return new Date()
  return new Date(year, month - 1, day)
}

export const formatPlannerDate = (date: Date | null, emptyLabel = '未设置') => {
  if (!date) return emptyLabel
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date)
}

const formatTime = (date: Date) => new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
}).format(date)

export const createPlannerTask = (row: TeacherTaskProgress, rows: TeacherTaskProgress[], now: number): PlannerTask => {
  const activeCount = taskProgressCount(row, 'active_enrollment_count')
  const completedCount = taskProgressCount(row, 'completed_count')
  const phase = teacherTaskPhase(row, now)
  const opensAt = parseDate(row.opens_at)
  const dueAt = parseDate(row.due_at)
  const dueTime = dueAt?.getTime() ?? Number.NaN

  return {
    key: JSON.stringify([row.class_ref, row.task_ref]),
    row,
    label: teacherTaskDisplayLabel(row),
    classLabel: teacherClassDisplayLabel(row.class_ref, rows),
    phase,
    phaseLabel: teacherTaskPhaseLabel(phase),
    activeCount,
    completedCount,
    notStartedCount: taskProgressCount(row, 'not_started_count'),
    inProgressCount: taskProgressCount(row, 'created_count') + taskProgressCount(row, 'in_progress_count'),
    endedCount: taskProgressCount(row, 'abandoned_count') + taskProgressCount(row, 'invalid_count'),
    revokedCount: taskProgressCount(row, 'revoked_enrollment_count'),
    pendingCount: taskActionablePendingCount(row),
    completionRate: activeCount > 0 ? taskCompletionRate(row) : null,
    opensAt,
    dueAt,
    isDueSoon: ['upcoming', 'in_progress'].includes(phase)
      && Number.isFinite(dueTime)
      && dueTime >= now
      && dueTime <= now + 7 * 24 * 60 * 60 * 1000,
  }
}

export const buildPlannerEvents = (tasks: PlannerTask[]) => {
  const byDate = new Map<string, PlannerEvent[]>()

  const addEvent = (task: PlannerTask, kind: PlannerEventKind, date: Date | null) => {
    if (!date) return
    const key = localDateKey(date)
    const events = byDate.get(key) ?? []
    events.push({
      key: `${task.key}:${kind}`,
      dateKey: key,
      kind,
      timestamp: date.getTime(),
      timeLabel: formatTime(date),
      task,
    })
    byDate.set(key, events)
  }

  for (const task of tasks) {
    addEvent(task, 'start', task.opensAt)
    addEvent(task, 'due', task.dueAt)
  }

  for (const events of byDate.values()) {
    events.sort((first, second) => first.timestamp - second.timestamp || first.task.label.localeCompare(second.task.label, 'zh-CN'))
  }
  return byDate
}

export const buildAgendaItems = (events: PlannerEvent[]) => {
  const grouped = new Map<string, PlannerAgendaItem>()
  for (const event of events) {
    const item = grouped.get(event.task.key) ?? { key: event.task.key, task: event.task, events: [] }
    item.events.push(event)
    grouped.set(event.task.key, item)
  }
  return [...grouped.values()].sort((first, second) => {
    const firstTime = Math.min(...first.events.map((event) => event.timestamp))
    const secondTime = Math.min(...second.events.map((event) => event.timestamp))
    return firstTime - secondTime || first.task.label.localeCompare(second.task.label, 'zh-CN')
  })
}

export const buildCalendarCells = (
  month: Date,
  eventsByDate: Map<string, PlannerEvent[]>,
  todayKey: string,
  selectedKey: string,
  maxVisibleEvents = 2,
) => {
  const year = month.getFullYear()
  const monthIndex = month.getMonth()
  const firstOffset = (new Date(year, monthIndex, 1).getDay() + 6) % 7
  const dayCount = new Date(year, monthIndex + 1, 0).getDate()
  const weekCount = Math.ceil((firstOffset + dayCount) / 7)
  const firstDay = new Date(year, monthIndex, 1 - firstOffset)

  return Array.from({ length: weekCount * 7 }, (_, index): PlannerCalendarCell => {
    const date = new Date(firstDay.getFullYear(), firstDay.getMonth(), firstDay.getDate() + index)
    const key = localDateKey(date)
    const events = eventsByDate.get(key) ?? []
    return {
      dateKey: key,
      dayNumber: date.getDate(),
      inCurrentMonth: date.getMonth() === monthIndex,
      isToday: key === todayKey,
      isSelected: key === selectedKey,
      events: events.slice(0, maxVisibleEvents),
      moreCount: Math.max(0, events.length - maxVisibleEvents),
    }
  })
}
