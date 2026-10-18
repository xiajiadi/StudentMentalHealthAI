import type { TeacherOverviewProgressRow } from '@/utils/teacher-task-progress'

/** Synthetic browser-only records for local visual review. They are never sent to the API. */
const demoClasses = Array.from({ length: 8 }, (_, index) => ({
  ref: `DEMO_24G${index + 1}`,
  label: `24级${index + 1}班`,
}))

const demoTasks = [
  { code: 'ADAPT', label: '适应测评' },
  { code: 'STUDY', label: '学习状态' },
  { code: 'CAMPUS', label: '校园体验' },
  { code: 'STRESS', label: '压力与应对' },
  { code: 'RELATE', label: '人际关系' },
  { code: 'RHYTHM', label: '学习节奏' },
]

const activeCounts = [18, 20, 21, 22, 22, 22]
const completedTargetsByClass = [106, 96, 90, 71, 100, 85, 98, 84]
const completionOffsets = [0.06, -0.04, 0.01, -0.08, 0.03]

const dateAtOffset = (offset: number) => {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offset)
  return date.toISOString()
}

export function createTeacherOverviewDemoRows(seed = 0): TeacherOverviewProgressRow[] {
  return demoClasses.flatMap((demoClass, classIndex) => {
    const rowCompleted = activeCounts.map((active, taskIndex) => Math.round(
      active * (completedTargetsByClass[classIndex] / 125 + (completionOffsets[taskIndex] ?? 0)),
    ))
    rowCompleted[5] = completedTargetsByClass[classIndex] - rowCompleted.slice(0, 5).reduce((sum, value) => sum + value, 0)

    return demoTasks.map((demoTask, taskIndex) => {
      const active = activeCounts[taskIndex]
      const completed = rowCompleted[taskIndex]
      const isCurrent = classIndex < 4 && taskIndex < 3
      const isUpcoming = taskIndex === 3
      const dueOffset = isCurrent
        ? 1 + ((classIndex * 2 + taskIndex * 3 + seed) % 12)
        : isUpcoming
          ? 8 + ((classIndex + seed) % 10)
          : -1 - ((classIndex * 3 + taskIndex + seed) % 15)
      const opensOffset = isCurrent
        ? -7 - ((classIndex + taskIndex) % 9)
        : isUpcoming
          ? 1 + ((classIndex + seed) % 5)
          : dueOffset - 18
      const incomplete = active - completed
      const abandoned = isCurrent || isUpcoming ? 0 : Math.min(incomplete, 1 + ((classIndex + taskIndex) % 3))
      const invalid = !isCurrent && !isUpcoming && (classIndex + taskIndex) % 5 === 0
        ? Math.min(Math.max(0, incomplete - abandoned), 1)
        : 0
      const actionable = Math.max(0, incomplete - abandoned - invalid)
      const created = Math.round(actionable * (taskIndex % 2 === 0 ? 0.13 : 0.16))
      const inProgress = Math.round(actionable * 0.42)
      const notStarted = Math.max(0, actionable - created - inProgress)
      const revoked = (classIndex * 2 + taskIndex) % 7 === 0 ? 1 : 0

      return {
        class_ref: demoClass.ref,
        task_ref: `DEMO_${demoClass.ref}_${demoTask.code}`,
        task_status: 'PUBLISHED',
        opens_at: dateAtOffset(opensOffset),
        due_at: dateAtOffset(dueOffset),
        published_enrollment_count: active + revoked,
        active_enrollment_count: active,
        revoked_enrollment_count: revoked,
        not_started_count: notStarted,
        created_count: created,
        in_progress_count: inProgress,
        completed_count: completed,
        abandoned_count: abandoned,
        invalid_count: invalid,
        class_label: demoClass.label,
        task_label: demoTask.label,
        task_group: demoTask.label,
      }
    })
  })
}
