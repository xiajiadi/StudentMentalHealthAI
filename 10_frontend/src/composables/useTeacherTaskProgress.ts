import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { TeacherTaskProgress } from '@/api/client'
import { frontendApi } from '@/services/mock-api'

export type TeacherTaskProgressState = 'loading' | 'ready' | 'error'

const errorMessageFor = (error: unknown) => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前账号暂时无法查看这些任务。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '任务信息已变化，请刷新列表。'
  return '暂时无法读取任务进度，请稍后重试。'
}

export function useTeacherTaskProgress() {
  const state = ref<TeacherTaskProgressState>('loading')
  const rows = ref<TeacherTaskProgress[]>([])
  const errorMessage = ref('')
  let requestGeneration = 0

  const refresh = async () => {
    const generation = ++requestGeneration
    state.value = 'loading'
    errorMessage.value = ''
    rows.value = []

    if (!frontendApi.listTeacherSchoolTaskProgress) {
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
      state.value = 'error'
    }
  }

  onMounted(() => { void refresh() })
  onBeforeUnmount(() => { requestGeneration += 1 })

  return { state, rows, errorMessage, refresh }
}
