<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CalendarDays, ClipboardCheck } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppLoadingDots from '@/components/app/AppLoadingDots.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentRefreshButton from '@/components/app/StudentRefreshButton.vue'
import type { StudentSchoolTask } from '@/api/client'
import { frontendApi } from '@/services/mock-api'

const props = withDefaults(defineProps<{ focusEntry?: boolean; autoStartTask?: boolean }>(), { focusEntry: false, autoStartTask: false })
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const tasks = ref<StudentSchoolTask[]>([])
const pendingTask = ref('')
const errorMessage = ref('')
const requestGeneration = ref(0)

const shortRef = (value: string) => value.slice(-6)
const taskPoster = (task: StudentSchoolTask) => {
  const seed = [...task.task_ref].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 0)
  return `/assets/psynova/original-covers/flow-${String(seed % 28 + 1).padStart(2, '0')}.svg`
}
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
const requestMessage = (error: unknown, fallback = '任务暂时无法打开，请稍后重试。') => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前任务暂不可访问，请联系学校管理员确认报名状态。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '任务已不可用，请刷新任务列表。'
  if (code === 'workflow_conflict' || code === 'conflict' || code === '409') return '任务状态已变化，请刷新后重试。'
  return fallback
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
    const availableTasks = props.focusEntry
      ? result.data.filter((task) => task.status.toUpperCase() === 'PUBLISHED' && (task.assessment_status === 'created' || task.assessment_status === 'in_progress'))
      : result.data
    tasks.value = availableTasks
    state.value = 'ready'
    if (props.focusEntry && props.autoStartTask) {
      const singleStartableTask = availableTasks.filter((task) => task.assessment_status === 'created')
      if (singleStartableTask.length === 1) void openTask(singleStartableTask[0])
    }
  } catch (error) {
    if (generation !== requestGeneration.value) return
    state.value = 'error'
    errorMessage.value = requestMessage(error, '暂时无法读取分配给你的任务。')
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

onMounted(() => {
  void load()
})
</script>

<template>
  <section
    class="assigned-tasks"
    :class="{ 'assigned-tasks--focus-entry': props.focusEntry }"
    :aria-labelledby="props.focusEntry ? undefined : 'assigned-tasks-title'"
    :aria-label="props.focusEntry ? '学校测评任务' : undefined"
  >
    <header v-if="!props.focusEntry" class="assigned-tasks__heading">
      <div><span class="assigned-tasks__eyebrow">学校安排</span><h2 id="assigned-tasks-title">班级测评任务</h2></div>
      <StudentRefreshButton :loading="state === 'loading'" @click="load" />
    </header>
    <AppStatusCallout v-if="errorMessage && state !== 'error'" tone="critical" title="任务操作未完成" :body="errorMessage" role="alert" />
    <AppCard v-if="state === 'loading'" class="assigned-tasks__state" aria-busy="true">正在读取分配给你的任务<AppLoadingDots /></AppCard>
    <AppCard v-else-if="state === 'error'" class="assigned-tasks__state assigned-tasks__state--error" role="status"><span>{{ errorMessage }}</span><AppButton variant="secondary" size="sm" @click="load">重新读取</AppButton></AppCard>
    <AppCard v-else-if="!tasks.length" class="assigned-tasks__state assigned-tasks__state--empty" role="status">
      <ClipboardCheck :size="props.focusEntry ? 24 : 18" aria-hidden="true" />
      <span>{{ props.focusEntry ? '学校暂未下发新的测评' : '当前没有分配给你的任务。你仍可使用下方的自主测评。' }}</span>
    </AppCard>
    <div v-else-if="tasks.length" class="assigned-tasks__cards" :class="{ 'assigned-tasks__cards--focus-entry': props.focusEntry }">
      <AppCard v-for="task in tasks" :key="task.task_ref" class="assigned-task" :class="{ 'assigned-task--focus-entry': props.focusEntry }">
        <div v-if="!props.focusEntry" class="assigned-task__poster">
          <img :src="taskPoster(task)" alt="" aria-hidden="true" />
          <span :class="{ 'assigned-task__status--done': task.assessment_status === 'completed' }">{{ statusLabel(task) }}</span>
        </div>
        <div v-else class="assigned-task__icon"><ClipboardCheck :size="18" aria-hidden="true" /></div>
        <div class="assigned-task__body">
          <span v-if="!props.focusEntry" class="assigned-task__category">学校安排</span>
          <div class="assigned-task__title">
            <h3>{{ props.focusEntry ? `任务 ${shortRef(task.task_ref)}` : `班级任务 ${shortRef(task.task_ref)}` }}</h3>
            <span v-if="props.focusEntry" :class="{ 'assigned-task__status--done': task.assessment_status === 'completed' }">{{ statusLabel(task) }}</span>
          </div>
          <p><CalendarDays :size="14" aria-hidden="true" />{{ formatDate(task.opens_at) }} 至 {{ formatDate(task.due_at) }}</p>
          <AppButton class="assigned-task__action" :disabled="Boolean(pendingTask) || task.status.toUpperCase() !== 'PUBLISHED'" :loading="pendingTask === task.task_ref" @click="openTask(task)">{{ actionLabel(task) }}</AppButton>
        </div>
      </AppCard>
    </div>
  </section>
</template>

<style scoped>
.assigned-tasks { display: grid; gap: 12px; margin: 0 0 18px; }
.assigned-tasks--focus-entry { width: 100%; margin: 0; }
.assigned-tasks__heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.assigned-tasks__eyebrow { color: var(--color-primary); font-size: 14px; font-weight: 700; letter-spacing: .02em; }
.assigned-tasks__heading h2 { margin: 4px 0 0; color: var(--color-text-primary); font-size: 13px; font-weight: 600; }
.assigned-tasks__state { display: flex; align-items: center; gap: 10px; min-height: 64px; padding: 15px; color: var(--color-text-secondary); font-size: 12px; }
.assigned-tasks--focus-entry > .assigned-tasks__state:not(.assigned-tasks__state--error) { width: 100%; min-height: clamp(160px, 23svh, 190px); justify-content: center; padding: clamp(18px, 3.5vw, 30px); }
.assigned-tasks--focus-entry > .assigned-tasks__state--empty { gap: 12px; font-size: 16px; }
.assigned-tasks__state--error { justify-content: space-between; color: #8f651d; }
.assigned-tasks__cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: stretch; gap: 24px 20px; }
.assigned-tasks__cards--focus-entry { grid-template-columns: 1fr; gap: 9px; }
.assigned-task { display: flex; min-width: 0; flex-direction: column; overflow: hidden; border: 1px solid #e8edf1; border-radius: 12px; background: #fff; transition: transform var(--motion-fast), box-shadow var(--motion-fast); }
.assigned-task:not(.assigned-task--focus-entry):hover { transform: translateY(-2px); box-shadow: var(--shadow-raised); }
.assigned-task--focus-entry { display: grid; grid-template-columns: 38px minmax(0,1fr); align-items: center; gap: 12px; padding: 13px 15px; }
.assigned-task__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; background: #eaf3f5; }
.assigned-task__poster img { display: block; width: 100%; height: 100%; object-fit: cover; }
.assigned-task__poster > span { position: absolute; top: 12px; right: 12px; padding: 5px 10px; border-radius: 7px; color: #fff; background: #00addf; font-size: 12px; font-weight: 600; line-height: 1.3; }
.assigned-task__poster > span.assigned-task__status--done { background: #568f7d; }
.assigned-task__category { color: #00a9dd; font-size: 13px; line-height: 1.3; }
.assigned-task:not(.assigned-task--focus-entry) .assigned-task__body { display: grid; min-height: 160px; align-content: start; gap: 7px; padding: 14px 16px 16px; }
.assigned-task__action { justify-self: start; margin-top: auto; }
.assigned-task__icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 10px; color: #388576; background: #e8f4ef; }
.assigned-task__body { min-width: 0; }
.assigned-task__title { display: flex; align-items: center; gap: 9px; }
.assigned-task h3 { margin: 0; color: var(--color-text-primary); font-size: 13px; }
.assigned-task__title span { padding: 3px 7px; border-radius: 999px; color: #8f651d; background: #fcf4e3; font-size: 10px; }
.assigned-task__title .assigned-task__status--done { color: #287765; background: #e8f4ef; }
.assigned-task p { display: flex; align-items: center; gap: 5px; margin: 5px 0 0; color: var(--color-text-muted); font-size: 11px; }
@media(max-width:980px) { .assigned-tasks__cards:not(.assigned-tasks__cards--focus-entry) { grid-template-columns: repeat(2, minmax(0,1fr)); } }
@media(max-width:680px) { .assigned-tasks__cards:not(.assigned-tasks__cards--focus-entry) { grid-template-columns: 1fr; gap: 16px; }.assigned-task--focus-entry { grid-template-columns: 34px minmax(0,1fr); }.assigned-task__heading,.assigned-task__title { align-items: flex-start; }.assigned-tasks__heading { align-items: flex-start; flex-wrap: wrap; } }
</style>
