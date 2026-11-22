import type { TeacherTaskProgress } from '@/api/client'
import {
  publicDemoTaskDefinition,
  shortTeacherRef,
  taskProgressCount,
  teacherTaskDisplayLabel,
  type TeacherOverviewProgressRow,
} from '@/utils/teacher-task-progress'

export type AnalysisTimeWindow = 'all' | '30' | '90' | '365'

export interface AnalysisTask {
  key: string
  classRef: string
  taskRef: string
  classLabel: string
  taskLabel: string
  activeCount: number
  completedCount: number
  completionRate: number
}

export interface CoverageValue {
  totalCount: number
  reachedCount: number
  percent: number
}

export interface AnalysisCountAnomalies {
  completedAboveActiveCount: number
  completedWithNoActiveCount: number
}

export interface SlopeComparisonSide {
  classRef: string
  classLabel: string
  taskRef: string
  activeCount: number
  completedCount: number
  completionRate: number
}

/**
 * Only create this object after a trusted mapping confirms the same task
 * definition and version for both class assignments.
 */
export interface VerifiedTaskPair {
  key: string
  taskDefinitionRef: string
  taskDefinitionVersion: string
  taskLabel: string
  classA: SlopeComparisonSide
  classB: SlopeComparisonSide
  /** B completion rate minus A completion rate, in percentage points. */
  differencePp: number
}

export const filterTeacherAnalysisRows = (
  rows: TeacherTaskProgress[],
  window: AnalysisTimeWindow,
  now = Date.now(),
) => {
  if (window === 'all') return rows

  const start = now - Number(window) * 24 * 60 * 60 * 1000
  return rows.filter((row) => {
    const openedAt = Date.parse(row.opens_at)
    return Number.isFinite(openedAt) && openedAt >= start && openedAt <= now
  })
}

export const toAnalysisTasks = (rows: TeacherOverviewProgressRow[]): AnalysisTask[] => {
  const classLabels = new Map<string, string>()
  for (const row of rows) {
    const label = row.class_label?.trim()
    if (label && !classLabels.has(row.class_ref)) classLabels.set(row.class_ref, label)
  }
  return rows.map((row) => {
    const activeCount = taskProgressCount(row, 'active_enrollment_count')
    const completedCount = taskProgressCount(row, 'completed_count')
    return {
      key: JSON.stringify([row.class_ref, row.task_ref]),
      classRef: row.class_ref,
      taskRef: row.task_ref,
      classLabel: classLabels.get(row.class_ref) ?? `班级 ${shortTeacherRef(row.class_ref)}`,
      taskLabel: teacherTaskDisplayLabel(row),
      activeCount,
      completedCount,
      completionRate: activeCount > 0 ? Math.min(100, completedCount / activeCount * 100) : 0,
    }
  })
}

export const inspectAnalysisCountAnomalies = (rows: TeacherTaskProgress[]): AnalysisCountAnomalies => rows
  .reduce<AnalysisCountAnomalies>((anomalies, row) => {
    const activeCount = taskProgressCount(row, 'active_enrollment_count')
    const completedCount = taskProgressCount(row, 'completed_count')
    if (completedCount > activeCount) {
      if (activeCount === 0) anomalies.completedWithNoActiveCount += 1
      else anomalies.completedAboveActiveCount += 1
    }
    return anomalies
  }, { completedAboveActiveCount: 0, completedWithNoActiveCount: 0 })

const isFiniteCount = (value: number) => Number.isFinite(value) && Number.isInteger(value) && value >= 0

const matchesCalculatedRate = (side: SlopeComparisonSide) => {
  if (side.activeCount <= 0 || side.completedCount > side.activeCount) return false
  const calculatedRate = side.completedCount / side.activeCount * 100
  return Math.abs(side.completionRate - calculatedRate) <= 0.11
}

export const isUsableVerifiedTaskPair = (pair: VerifiedTaskPair) => {
  const { classA, classB } = pair
  if (!pair.key || !pair.taskDefinitionRef || !pair.taskDefinitionVersion || !pair.taskLabel) return false
  if (classA.classRef === classB.classRef || !classA.classRef || !classB.classRef) return false
  if (!classA.classLabel || !classB.classLabel || !classA.taskRef || !classB.taskRef) return false
  if (![classA.activeCount, classA.completedCount, classB.activeCount, classB.completedCount].every(isFiniteCount)) {
    return false
  }
  if (![classA.completionRate, classB.completionRate, pair.differencePp].every(Number.isFinite)) return false
  if (classA.completionRate < 0 || classA.completionRate > 100 || classB.completionRate < 0 || classB.completionRate > 100) {
    return false
  }
  return matchesCalculatedRate(classA)
    && matchesCalculatedRate(classB)
    && Math.abs(pair.differencePp - (classB.completionRate - classA.completionRate)) <= 0.11
}

export const pairPublicDemoTasks = (
  rows: TeacherTaskProgress[],
  classARef: string,
  classBRef: string,
): VerifiedTaskPair[] => {
  if (!classARef || !classBRef || classARef === classBRef) return []
  const assignments = new Map<string, {
    definition: NonNullable<ReturnType<typeof publicDemoTaskDefinition>>
    classA: SlopeComparisonSide[]
    classB: SlopeComparisonSide[]
  }>()
  for (const row of rows) {
    if (row.class_ref !== classARef && row.class_ref !== classBRef) continue
    const definition = publicDemoTaskDefinition(row)
    if (!definition) continue
    const key = JSON.stringify([definition.ref, definition.version])
    const assignment = assignments.get(key) ?? { definition, classA: [], classB: [] }
    const activeCount = taskProgressCount(row, 'active_enrollment_count')
    const completedCount = taskProgressCount(row, 'completed_count')
    const side = row.class_ref === classARef ? assignment.classA : assignment.classB
    side.push({
      classRef: row.class_ref,
      classLabel: definition.classLabel,
      taskRef: row.task_ref,
      activeCount,
      completedCount,
      completionRate: activeCount ? completedCount / activeCount * 100 : 0,
    })
    assignments.set(key, assignment)
  }
  return [...assignments].flatMap(([key, { definition, classA, classB }]) => {
    if (classA.length !== 1 || classB.length !== 1) return []
    return [{
      key,
      taskDefinitionRef: definition.ref,
      taskDefinitionVersion: definition.version,
      taskLabel: definition.label,
      classA: classA[0],
      classB: classB[0],
      differencePp: classB[0].completionRate - classA[0].completionRate,
    }]
  })
}

export const validAnalysisTasks = (tasks: AnalysisTask[]) => tasks.filter((task) => task.activeCount > 0)

export const coverageAt = (tasks: AnalysisTask[], threshold: number): CoverageValue | null => {
  if (!tasks.length) return null
  const reachedCount = tasks.filter((task) => task.completionRate >= threshold).length
  return {
    totalCount: tasks.length,
    reachedCount,
    percent: reachedCount / tasks.length * 100,
  }
}

export const coverageCurvePoints = (tasks: AnalysisTask[]): [number, number][] => {
  if (!tasks.length) return []

  const countsByRate = new Map<number, number>()
  for (const { completionRate } of tasks) {
    countsByRate.set(completionRate, (countsByRate.get(completionRate) ?? 0) + 1)
  }
  const rates = [...countsByRate.keys()].sort((a, b) => a - b)
  const points: [number, number][] = [[0, 100]]
  let remaining = tasks.length

  for (const rate of rates) {
    if (rate > 0) points.push([rate, remaining / tasks.length * 100])
    remaining -= countsByRate.get(rate) ?? 0
    if (rate < 100) {
      points.push([rate, remaining / tasks.length * 100])
    }
  }

  if (rates[rates.length - 1] < 100) points.push([100, 0])
  return points
}

export const formatAnalysisPercent = (value: number) => {
  const rounded = Math.round(value * 10) / 10
  return String(rounded) + '%'
}

export const formatPercentagePoints = (value: number) => {
  const rounded = Math.round(value * 10) / 10
  const sign = rounded > 0 ? '+' : ''
  return sign + String(rounded) + ' pp'
}

export const formatPercentagePointMagnitude = (value: number) =>
  String(Math.round(Math.abs(value) * 10) / 10) + ' pp'

export const escapeAnalysisText = (value: string) => value.replace(/[&<>"']/g, (character) => {
  const entities: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }
  return entities[character] ?? character
})
