import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { TeacherTaskProgress } from '@/api/client'
import { frontendApi } from '@/services/mock-api'

export type TeacherTaskProgressState = 'loading' | 'ready' | 'error'
const teacherPreviewSourceKey = 'psynova.teacher.preview.dataMode'
const isLocalTeacherPreview = () => import.meta.env.DEV
  && typeof window !== 'undefined'
  && ['127.0.0.1', 'localhost'].includes(window.location.hostname)
  && window.location.port === '4206'

const errorMessageFor = (error: unknown) => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前账号暂时无法查看这些任务。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '任务信息已变化，请刷新列表。'
  return '暂时无法读取任务进度，请稍后重试。'
}

export function useTeacherTaskProgress(options: { autoLoad?: boolean; demoMode?: boolean } = {}) {
  const state = ref<TeacherTaskProgressState>('loading')
  const rows = ref<TeacherTaskProgress[]>([])
  const errorMessage = ref('')
  let demoSeed = 0
  let useLocalDemo = false
  if (options.demoMode && isLocalTeacherPreview()) {
    try {
      useLocalDemo = window.localStorage.getItem(teacherPreviewSourceKey) !== 'real'
    } catch {
      useLocalDemo = true
    }
  }
  let requestGeneration = 0

  const refresh = async (options: { preserveExisting?: boolean } = {}) => {
    const preserveExisting = options.preserveExisting === true && state.value === 'ready'
    const generation = ++requestGeneration
    errorMessage.value = ''
    if (!preserveExisting) {
      state.value = 'loading'
      rows.value = []
    }

    if (useLocalDemo) {
      try {
        const { createTeacherOverviewDemoRows } = await import('@/data/teacher-overview-demo-data')
        if (generation !== requestGeneration) return
        rows.value = createTeacherOverviewDemoRows(demoSeed++)
        state.value = 'ready'
      } catch {
        if (generation !== requestGeneration) return
        errorMessage.value = '无法载入本地示意数据。'
        state.value = 'error'
      }
      return
    }

    if (!frontendApi.listTeacherSchoolTaskProgress) {
      if (preserveExisting) {
        errorMessage.value = '当前运行环境未提供教师任务汇总服务。'
        return
      }
      state.value = 'error'
      errorMessage.value = '当前运行环境未提供教师任务汇总服务。'
      return
    }

    try {
      const result = await frontendApi.listTeacherSchoolTaskProgress()
      if (generation !== requestGeneration) return
      rows.value = result.data
      state.value = 'ready'
    } catch (error) {
      if (generation !== requestGeneration) return
      errorMessage.value = errorMessageFor(error)
      if (!preserveExisting) state.value = 'error'
    }
  }

  if (options.autoLoad !== false) onMounted(() => { void refresh() })
  onBeforeUnmount(() => { requestGeneration += 1 })

  return { state, rows, errorMessage, refresh, isDemo: useLocalDemo }
}
