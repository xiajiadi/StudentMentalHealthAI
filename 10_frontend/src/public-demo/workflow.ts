export const roles = {
  admin: '学校管理员', student: '学生', teacher: '班主任', specialist: '心理老师',
} as const

export type Role = keyof typeof roles
type CaseStage = 'none' | 'requested' | 'assigned' | 'reported' | 'closed'
type FeedbackStage = 'none' | 'draft' | 'published'

export const classRows = ['数媒','计算机','电气','经管'].flatMap((discipline, facultyIndex) => (
  Array.from({length: 3}, (_, index) => {
    const classIndex = facultyIndex * 3 + index
    const enrolled = classIndex < 8 ? 67 : 66
    return {id: `C${classIndex + 1}`, name: `${discipline} ${String(index + 1).padStart(2, '0')} 班`, enrolled,
      completed: enrolled - (classIndex * 7 + 3) % 14, teacher: `演示班主任 ${String(classIndex + 1).padStart(2, '0')}`}
  })
))

export const demoClass = classRows[0]!
export const roster = classRows.flatMap((row, classIndex) => Array.from({length: row.enrolled}, (_, index) => ({
  id: `DEMO-${String(classIndex + 1).padStart(2, '0')}-${String(index + 1).padStart(3, '0')}`,
  classId: row.id,
  name: `合成学生 ${String(index + 1).padStart(2, '0')}`,
  previousTaskCompleted: index < row.completed,
})))
export const historicRecords = [
  {name: '新生学习安排练习', date: '2026-09-12', status: '已完成', source: '合成历史记录'},
  {name: '校园资源了解练习', date: '2026-09-20', status: '已完成', source: '合成历史记录'},
  {name: '小组学习计划练习', date: '2026-10-09', status: '已完成', source: '合成历史记录'},
] as const

export const questions = [
  '遇到新的学习任务时，我会先读清楚要求。',
  '我能把一项较大的作业分成几个小步骤。',
  '需要帮助时，我知道可以找谁商量。',
  '我会为学习和休息各留出一段时间。',
  '如果原计划没做完，我愿意重新安排下一步。',
  '班级活动有不清楚的地方时，我会询问老师。',
] as const

export const choices = ['还没这样做', '偶尔这样做', '有时这样做', '经常这样做'] as const

export const feedbackText = '可以试着把下一项课业拆成两个小步骤：先确认要求，再写下今天能完成的一件事。需要时，可以请班主任帮忙核对计划。'

export interface Workspace {
  version: 1
  role: Role
  started: boolean
  published: boolean
  answers: number[]
  completed: boolean
  teacherViewed: boolean
  feedback: FeedbackStage
  support: CaseStage
}

type Action = {type: 'enter'} | {type: 'role'; role: Role} | {type: 'publish'} | {type: 'answer'; value: number}
  | {type: 'complete'} | {type: 'draft'} | {type: 'release'} | {type: 'request'} | {type: 'assign'} | {type: 'report'} | {type: 'close'}

export function newWorkspace(): Workspace {
  return {version: 1, role: 'admin', started: false, published: false, answers: [], completed: false, teacherViewed: false, feedback: 'none', support: 'none'}
}

export function restoreWorkspace(raw: string | null): Workspace {
  try {
    const value = JSON.parse(raw ?? 'null') as Partial<Workspace> | null
    if (!value || value.version !== 1 || !Object.hasOwn(roles, value.role ?? '') ||
      typeof value.started !== 'boolean' || typeof value.published !== 'boolean' || typeof value.completed !== 'boolean' || typeof value.teacherViewed !== 'boolean' ||
      !Array.isArray(value.answers) || value.answers.length > questions.length || !value.answers.every(isAnswer) ||
      !['none', 'draft', 'published'].includes(value.feedback ?? '') ||
      !['none', 'requested', 'assigned', 'reported', 'closed'].includes(value.support ?? '') ||
      (!value.started && (value.published || value.support !== 'none')) ||
      (!value.published && value.answers.length > 0) ||
      (value.completed && value.answers.length !== questions.length) ||
      (value.teacherViewed && !value.completed) ||
      (value.feedback !== 'none' && !value.completed)) return newWorkspace()
    return value as Workspace
  } catch {
    return newWorkspace()
  }
}

function isAnswer(value: number) {
  return Number.isInteger(value) && value >= 0 && value < choices.length
}

export function applyAction(current: Workspace, action: Action): Workspace {
  if (action.type === 'enter') return {...current, started: true}
  if (!current.started) return current
  if (action.type === 'role' && Object.hasOwn(roles, action.role)) return {...current, role: action.role, teacherViewed: current.teacherViewed || (action.role === 'teacher' && current.completed)}
  if (action.type === 'publish' && current.role === 'admin' && !current.published) return {...current, published: true}
  if (action.type === 'answer' && current.role === 'student' && current.published && current.answers.length < questions.length && isAnswer(action.value)) {
    return {...current, answers: [...current.answers, action.value]}
  }
  if (action.type === 'complete' && current.role === 'student' && !current.completed && current.answers.length === questions.length) return {...current, completed: true}
  if (action.type === 'draft' && current.role === 'specialist' && current.completed && current.feedback === 'none') return {...current, feedback: 'draft'}
  if (action.type === 'release' && current.role === 'specialist' && current.feedback === 'draft') return {...current, feedback: 'published'}
  if (action.type === 'request' && current.role === 'student' && current.support === 'none') return {...current, support: 'requested'}
  if (action.type === 'assign' && current.role === 'specialist' && current.support === 'requested') return {...current, support: 'assigned'}
  if (action.type === 'report' && current.role === 'teacher' && current.support === 'assigned') return {...current, support: 'reported'}
  if (action.type === 'close' && current.role === 'specialist' && current.support === 'reported') return {...current, support: 'closed'}
  return current
}

export function studentFeedback(state: Workspace): string | null {
  return state.role === 'student' && state.feedback === 'published' ? feedbackText : null
}
