import type { TeacherOverviewProgressRow } from '@/utils/teacher-task-progress'
import {
  isUsableVerifiedTaskPair,
  type VerifiedTaskPair,
} from '@/utils/teacher-analysis-aggregations'

interface SyntheticTaskDefinition {
  definitionRef: string
  versionRef: string
  displayName: string
  baseCompletionRate: number
}

export interface TeacherAnalyticsDemoAssignment {
  row: TeacherOverviewProgressRow
  taskDefinitionRef: string
  taskDefinitionVersion: string
  taskDefinitionLabel: string
}

export interface TeacherAnalyticsDemoDataset {
  rows: TeacherOverviewProgressRow[]
  assignments: TeacherAnalyticsDemoAssignment[]
}

const demoClasses = Array.from({ length: 8 }, (_, index) => ({
  ref: `DEMO_24G${index + 1}`,
  label: `24级${index + 1}班`,
}))

const sharedDefinitions: SyntheticTaskDefinition[] = [
  { definitionRef: 'SYNTH_ANALYTICS_DEF_01', versionRef: 'synthetic-v1', displayName: '适应主题（合成示例）', baseCompletionRate: 84 },
  { definitionRef: 'SYNTH_ANALYTICS_DEF_02', versionRef: 'synthetic-v1', displayName: '学习节奏（合成示例）', baseCompletionRate: 73 },
  { definitionRef: 'SYNTH_ANALYTICS_DEF_03', versionRef: 'synthetic-v1', displayName: '校园体验（合成示例）', baseCompletionRate: 66 },
  { definitionRef: 'SYNTH_ANALYTICS_DEF_04', versionRef: 'synthetic-v1', displayName: '压力应对（合成示例）', baseCompletionRate: 58 },
  { definitionRef: 'SYNTH_ANALYTICS_DEF_05', versionRef: 'synthetic-v1', displayName: '人际主题（合成示例）', baseCompletionRate: 79 },
  { definitionRef: 'SYNTH_ANALYTICS_DEF_06', versionRef: 'synthetic-v1', displayName: '自我认识（合成示例）', baseCompletionRate: 69 },
]

const classRateOffsets = [0, -7, 5, -3, 8, -10, 3, -5]
const dateAtOffset = (offsetDays: number) => {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offsetDays)
  return date.toISOString()
}

const createAssignment = (
  demoClass: (typeof demoClasses)[number],
  classIndex: number,
  taskIndex: number,
  taskCode: string,
  taskLabel: string,
  taskDefinitionRef: string,
  taskDefinitionVersion: string,
): TeacherAnalyticsDemoAssignment => {
  const activeCount = 18 + ((classIndex * 5 + taskIndex * 3) % 9)
  const baseRate = sharedDefinitions[taskIndex % sharedDefinitions.length]?.baseCompletionRate ?? 62
  const smallOffset = ((classIndex + taskIndex) % 3 - 1) * 2
  const targetRate = Math.max(42, Math.min(96, baseRate + (classRateOffsets[classIndex] ?? 0) + smallOffset))
  const completedCount = Math.round(activeCount * targetRate / 100)
  const remainingCount = activeCount - completedCount
  const notStartedCount = Math.ceil(remainingCount * 0.45)
  const createdCount = Math.floor(remainingCount * 0.15)
  const inProgressCount = remainingCount - notStartedCount - createdCount
  const opensOffset = -1 - ((classIndex * 2 + taskIndex) % 25)

  return {
    row: {
      class_ref: demoClass.ref,
      task_ref: `SYNTH_ANALYTICS_${classIndex + 1}_${taskCode}`,
      task_status: 'PUBLISHED',
      opens_at: dateAtOffset(opensOffset),
      due_at: dateAtOffset(10 + ((classIndex + taskIndex) % 12)),
      published_enrollment_count: activeCount,
      active_enrollment_count: activeCount,
      revoked_enrollment_count: 0,
      not_started_count: notStartedCount,
      created_count: createdCount,
      in_progress_count: inProgressCount,
      completed_count: completedCount,
      abandoned_count: 0,
      invalid_count: 0,
      class_label: demoClass.label,
      task_label: taskLabel,
      task_group: taskLabel,
    },
    taskDefinitionRef,
    taskDefinitionVersion,
    taskDefinitionLabel: taskLabel,
  }
}

export const createTeacherAnalyticsDemoDataset = (): TeacherAnalyticsDemoDataset => {
  const assignments = demoClasses.flatMap((demoClass, classIndex) => [
    ...sharedDefinitions.map((definition, taskIndex) => createAssignment(
      demoClass,
      classIndex,
      taskIndex,
      `SHARED_${String(taskIndex + 1).padStart(2, '0')}`,
      definition.displayName,
      definition.definitionRef,
      // These version-only differences prove that matching definitions alone
      // cannot create a pair; the eighth class has no shared exact versions.
      classIndex === 7 || (classIndex === 2 && taskIndex === 4)
        ? 'synthetic-v2'
        : definition.versionRef,
    )),
    createAssignment(
      demoClass,
      classIndex,
      sharedDefinitions.length,
      `CLASS_ONLY_${classIndex + 1}`,
      `班级专属任务 ${classIndex + 1}（合成示例）`,
      `SYNTH_ANALYTICS_CLASS_ONLY_${demoClass.ref}`,
      'synthetic-v1',
    ),
  ])

  return { rows: assignments.map((assignment) => assignment.row), assignments }
}

const taskIdentity = (assignment: TeacherAnalyticsDemoAssignment) =>
  JSON.stringify([assignment.taskDefinitionRef, assignment.taskDefinitionVersion])

const completionRate = (assignment: TeacherAnalyticsDemoAssignment) =>
  assignment.row.active_enrollment_count > 0
    ? assignment.row.completed_count / assignment.row.active_enrollment_count * 100
    : 0

const pairSide = (assignment: TeacherAnalyticsDemoAssignment) => ({
  classRef: assignment.row.class_ref,
  classLabel: assignment.row.class_label ?? assignment.row.class_ref,
  taskRef: assignment.row.task_ref,
  activeCount: assignment.row.active_enrollment_count,
  completedCount: assignment.row.completed_count,
  completionRate: completionRate(assignment),
})

export const createTeacherAnalyticsDemoPairs = (
  assignments: TeacherAnalyticsDemoAssignment[],
  classARef: string,
  classBRef: string,
): VerifiedTaskPair[] => {
  if (!classARef || !classBRef || classARef === classBRef) return []

  const identitiesInClassA = new Set(assignments
    .filter((assignment) => assignment.row.class_ref === classARef)
    .map(taskIdentity))

  return [...identitiesInClassA].flatMap((identity) => {
    const matchesA = assignments.filter((assignment) =>
      assignment.row.class_ref === classARef && taskIdentity(assignment) === identity)
    const matchesB = assignments.filter((assignment) =>
      assignment.row.class_ref === classBRef && taskIdentity(assignment) === identity)
    if (matchesA.length !== 1 || matchesB.length !== 1) return []

    const assignmentA = matchesA[0]
    const assignmentB = matchesB[0]
    const pair: VerifiedTaskPair = {
      key: identity,
      taskDefinitionRef: assignmentA.taskDefinitionRef,
      taskDefinitionVersion: assignmentA.taskDefinitionVersion,
      taskLabel: assignmentA.taskDefinitionLabel,
      classA: pairSide(assignmentA),
      classB: pairSide(assignmentB),
      differencePp: completionRate(assignmentB) - completionRate(assignmentA),
    }
    return isUsableVerifiedTaskPair(pair) ? [pair] : []
  }).sort((first, second) => first.taskDefinitionRef.localeCompare(second.taskDefinitionRef, 'en'))
}
