export const studentAssessmentStatusFilters = [
  { id: 'all', label: '全部' },
  { id: 'created', label: '待开始' },
  { id: 'in_progress', label: '进行中' },
  { id: 'completed', label: '已完成' },
] as const

export type StudentAssessmentStatusFilterValue = (typeof studentAssessmentStatusFilters)[number]['id']
