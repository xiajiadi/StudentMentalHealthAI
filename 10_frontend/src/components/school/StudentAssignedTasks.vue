<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CalendarDays, ClipboardCheck, RotateCcw } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import type { StudentSchoolTask, StudentSchoolTaskHistory } from '@/api/client'
import { frontendApi } from '@/services/mock-api'

const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const tasks = ref<StudentSchoolTask[]>([])
const historyState = ref<'loading' | 'ready' | 'error'>('loading')
const history = ref<StudentSchoolTaskHistory[]>([])
const historyErrorMessage = ref('')
const pendingTask = ref('')
const errorMessage = ref('')
const requestGeneration = ref(0)

const shortRef = (value: string) => value.slice(-6)
const statusLabel = (task: StudentSchoolTask) => {
  if (task.assessment_status === 'completed') return '已完成'
  if (task.assessment_status === 'in_progress') return '进行中'
  if (task.assessment_status === 'created') return '待开始'
  if (task.status.toUpperCase() !== 'PUBLISHED') return '暂不可开始'
  return '待开始'
}
const actionLabel = (task: StudentSchoolTask) => task.assessment_status === 'completed'
  ? '查看完成记录'
  : task.assessment_id ? '继续任务' : '开始任务'
const formatDate = (value: string | null) => {
  if (!value) return '未设置截止时间'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间待确认' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}
const historyStatusLabel = (entry: StudentSchoolTaskHistory) => {
  const enrollment = entry.enrollment_status.toUpperCase()
  if (enrollment === 'REVOKED') return '报名已撤销'
  if (entry.assessment_status === 'completed') return '已完成'
  if (entry.assessment_status === 'in_progress') return '进行中'
  if (entry.assessment_status === 'created') return '尚未开始'
  const taskStatus = entry.task_status.toUpperCase()
  if (taskStatus === 'EXPIRED') return '任务已过期'
  if (taskStatus === 'CLOSED' || taskStatus === 'CANCELLED') return '任务已结束'
  return '尚无测评记录'
}
const historyDates = (entry: StudentSchoolTaskHistory) => {
  const dates = []
  if (entry.started_at) dates.push(`开始于 ${formatDate(entry.started_at)}`)
  if (entry.completed_at) dates.push(`完成于 ${formatDate(entry.completed_at)}`)
  return dates.length ? dates.join(' · ') : '没有开始或完成时间记录'
}
const requestMessage = (error: unknown, fallback = '任务暂时无法打开，请稍后重试。') => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前任务暂不可访问，请联系学校管理员确认报名状态。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '任务已不可用，请刷新任务列表。'
  if (code === 'workflow_conflict' || code === 'conflict' || code === '409') return '任务状态已变化，请刷新后重试。'
  return fallback
}
const historyRequestMessage = (error: unknown) => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前账号暂时无法查看任务历史。'
  return '暂时无法读取你的任务历史。'
}

const load = async () => {
  const generation = ++requestGeneration.value
  state.value = 'loading'
  errorMessage.value = ''
  tasks.value = []
  if (!frontendApi.listStudentSchoolTasks) {
    state.value = 'error'
    errorMessage.value = '当前运行环境未提供学校任务服务。'
    return
  }
  try {
    const result = await frontendApi.listStudentSchoolTasks()
    if (generation !== requestGeneration.value) return
    tasks.value = result.data
    state.value = 'ready'
  } catch (error) {
    if (generation !== requestGeneration.value) return
    state.value = 'error'
    errorMessage.value = requestMessage(error, '暂时无法读取分配给你的任务。')
  }
}

const loadHistory = async () => {
  historyState.value = 'loading'
  historyErrorMessage.value = ''
  history.value = []
  if (!frontendApi.listStudentSchoolTaskHistory) {
    historyState.value = 'error'
    historyErrorMessage.value = '当前运行环境未提供任务历史服务。'
    return
  }
  try {
    const result = await frontendApi.listStudentSchoolTaskHistory()
    history.value = result.data
    historyState.value = 'ready'
  } catch (error) {
    historyState.value = 'error'
    historyErrorMessage.value = historyRequestMessage(error)
  }
}

const openTask = async (task: StudentSchoolTask) => {
  if (pendingTask.value) return
  errorMessage.value = ''
  if (task.assessment_status === 'completed' && task.assessment_id) {
    await router.push(`/student/assessment/${encodeURIComponent(task.assessment_id)}/result`)
    return
  }
  if (!frontendApi.startStudentSchoolTask) {
    errorMessage.value = '当前运行环境未提供学校任务服务。'
    return
  }
  pendingTask.value = task.task_ref
  try {
    const result = await frontendApi.startStudentSchoolTask(task.task_ref)
    const session = result.data
    if (!session.assessment_id) throw new Error('task_session_unavailable')
    if (session.status === 'completed') {
      await router.push(`/student/assessment/${encodeURIComponent(session.assessment_id)}/result`)
      return
    }
    await router.push(`/student/assessment/${encodeURIComponent(session.assessment_id)}`)
  } catch (error) {
    errorMessage.value = requestMessage(error)
  } finally { pendingTask.value = '' }
}

onMounted(() => { void load(); void loadHistory() })
</script>

<template>
  <section class="assigned-tasks" aria-labelledby="assigned-tasks-title">
    <header class="assigned-tasks__heading">
      <div><span class="assigned-tasks__eyebrow">学校安排</span><h2 id="assigned-tasks-title">班级测评任务</h2><p>这是分配给当前账号的任务；开始后可继续完成已保存的会话。</p></div>
      <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="load"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton>
    </header>
    <AppStatusCallout v-if="errorMessage && state !== 'error'" tone="critical" title="任务操作未完成" :body="errorMessage" role="alert" />
    <AppCard v-if="state === 'loading'" class="assigned-tasks__state" aria-busy="true">正在读取分配给你的任务…</AppCard>
    <AppCard v-else-if="state === 'error'" class="assigned-tasks__state assigned-tasks__state--error" role="status"><span>{{ errorMessage }}</span><AppButton variant="secondary" size="sm" @click="load">重新读取</AppButton></AppCard>
    <AppCard v-else-if="!tasks.length" class="assigned-tasks__state" role="status"><ClipboardCheck :size="18" aria-hidden="true" /><span>当前没有分配给你的任务。你仍可使用下方的自主测评。</span></AppCard>
    <div v-else class="assigned-tasks__list">
      <AppCard v-for="task in tasks" :key="task.task_ref" class="assigned-task">
        <div class="assigned-task__icon"><ClipboardCheck :size="18" aria-hidden="true" /></div>
        <div class="assigned-task__body">
          <div class="assigned-task__title"><h3>任务 {{ shortRef(task.task_ref) }}</h3><span :class="{ 'assigned-task__status--done': task.assessment_status === 'completed' }">{{ statusLabel(task) }}</span></div>
          <p><CalendarDays :size="14" aria-hidden="true" />{{ formatDate(task.opens_at) }} 至 {{ formatDate(task.due_at) }}</p>
        </div>
        <AppButton :disabled="Boolean(pendingTask) || task.status.toUpperCase() !== 'PUBLISHED'" :loading="pendingTask === task.task_ref" @click="openTask(task)">{{ actionLabel(task) }}</AppButton>
      </AppCard>
    </div>

    <section class="task-history" aria-labelledby="task-history-title">
      <header class="task-history__heading">
        <div><span class="assigned-tasks__eyebrow">本人记录</span><h2 id="task-history-title">任务历史</h2><p>这里只显示任务状态和时间，不展示测评内容或结果。</p></div>
        <AppButton variant="secondary" size="sm" :disabled="historyState === 'loading'" @click="loadHistory"><RotateCcw :size="15" aria-hidden="true" />刷新历史</AppButton>
      </header>
      <AppCard v-if="historyState === 'loading'" class="assigned-tasks__state" aria-busy="true">正在读取任务历史…</AppCard>
      <AppCard v-else-if="historyState === 'error'" class="assigned-tasks__state assigned-tasks__state--error" role="status"><span>{{ historyErrorMessage }}</span><AppButton variant="secondary" size="sm" @click="loadHistory">重新读取</AppButton></AppCard>
      <AppCard v-else-if="!history.length" class="assigned-tasks__state" role="status">当前没有任务历史。</AppCard>
      <div v-else class="task-history__list">
        <AppCard v-for="entry in history" :key="`${entry.task_ref}:${entry.enrollment_status}`" class="task-history__entry">
          <div><h3>任务 {{ shortRef(entry.task_ref) }}</h3><p>{{ historyDates(entry) }}</p></div>
          <span :class="{ 'task-history__status--revoked': entry.enrollment_status.toUpperCase() === 'REVOKED', 'task-history__status--done': entry.assessment_status === 'completed' }">{{ historyStatusLabel(entry) }}</span>
        </AppCard>
      </div>
    </section>
  </section>
</template>

<style scoped>
.assigned-tasks { display: grid; gap: 12px; margin: 0 0 18px; }
.assigned-tasks__heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.assigned-tasks__eyebrow { color: #54809c; font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.assigned-tasks__heading h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 18px; }
.assigned-tasks__heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.assigned-tasks__state { display: flex; align-items: center; gap: 10px; min-height: 64px; padding: 15px; color: var(--color-text-secondary); font-size: 12px; }
.assigned-tasks__state--error { justify-content: space-between; color: #8f651d; }
.assigned-tasks__list { display: grid; gap: 9px; }
.task-history { display: grid; gap: 10px; margin-top: 6px; }
.task-history__heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.task-history__heading h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 16px; }
.task-history__heading p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.task-history__list { display: grid; gap: 8px; }
.task-history__entry { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 15px; }
.task-history__entry h3 { margin: 0; color: var(--color-text-primary); font-size: 12px; }
.task-history__entry p { margin: 5px 0 0; color: var(--color-text-muted); font-size: 10px; }
.task-history__entry > span { flex: none; color: #687985; font-size: 11px; }
.task-history__entry > .task-history__status--revoked { color: #8f651d; }
.task-history__entry > .task-history__status--done { color: #287765; }
.assigned-task { display: grid; grid-template-columns: 38px minmax(0,1fr) auto; align-items: center; gap: 12px; padding: 13px 15px; }
.assigned-task__icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 10px; color: #388576; background: #e8f4ef; }
.assigned-task__body { min-width: 0; }
.assigned-task__title { display: flex; align-items: center; gap: 9px; }
.assigned-task h3 { margin: 0; color: var(--color-text-primary); font-size: 13px; }
.assigned-task__title span { padding: 3px 7px; border-radius: 999px; color: #8f651d; background: #fcf4e3; font-size: 10px; }
.assigned-task__title .assigned-task__status--done { color: #287765; background: #e8f4ef; }
.assigned-task p { display: flex; align-items: center; gap: 5px; margin: 5px 0 0; color: var(--color-text-muted); font-size: 11px; }
@media(max-width:680px) { .assigned-task { grid-template-columns: 34px minmax(0,1fr); }.assigned-task > button { grid-column: 2; justify-self: start; }.assigned-tasks__heading,.task-history__heading { align-items: flex-start; } }
</style>
