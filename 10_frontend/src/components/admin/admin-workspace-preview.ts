import type { EChartsOption } from 'echarts/core'

export type AdminPreviewState = 'loading' | 'ready' | 'error'

export type AdminPreviewMetric = {
  label: string
  value: string
}

export type AdminDependencyRow = {
  name: string
  connection: string
  state: string
}

export type AdminChartPreviewSummary = {
  presentation: 'chart'
  headlineLabel: string
  headlineValue: string
  metrics: AdminPreviewMetric[]
  chartTitle: string
  chartLabel: string
  chartEmptyMessage: string
  chartOption: EChartsOption | null
}

export type AdminTablePreviewSummary = {
  presentation: 'table'
  tableLabel: string
  dependencyRows: AdminDependencyRow[]
}

export type AdminPreviewSummary = AdminChartPreviewSummary | AdminTablePreviewSummary

export type FolderOrigin = {
  x: number
  y: number
  width: number
  height: number
  coverOcclusion?: number
}

export type FolderOrigins = FolderOrigin[]

export type AdminDemoClass = {
  label: string
  students: number
  teachers: number
  isActive: boolean
}

export type AdminDemoOperationDay = {
  offset: number
  accounts: number
  tasks: number
  classes: number
}

export type AdminOverviewDemoData = {
  classes: AdminDemoClass[]
  accounts: {
    students: number
    teachers: number
    pendingActivation: number
  }
  operations: AdminDemoOperationDay[]
}
