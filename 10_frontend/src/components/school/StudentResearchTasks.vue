<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookOpenCheck, CalendarDays, ClipboardCheck, History } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppLoadingDots from '@/components/app/AppLoadingDots.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentRefreshButton from '@/components/app/StudentRefreshButton.vue'
import type {
  ResearchSessionDiscoveryEntry,
  ResearchTaskDiscoveryEntry,
} from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'

const PAGE_SIZE = 30
const props = withDefaults(defineProps<{ tasksOnly?: boolean }>(), { tasksOnly: false })
const router = useRouter()
const session = useSessionStore()
const generation = ref(0)
const tasks = ref<ResearchTaskDiscoveryEntry[]>([])
const sessions = ref<ResearchSessionDiscoveryEntry[]>([])
const taskState = ref<'loading' | 'ready' | 'error'>('loading')
const sessionState = ref<'loading' | 'ready' | 'error'>('loading')
const taskError = ref('')
const sessionError = ref('')
const taskLoadMoreError = ref('')
const sessionLoadMoreError = ref('')
const taskNextOffset = ref<number | null>(null)
const sessionNextOffset = ref<number | null>(null)
const taskLoadingMore = ref(false)
const sessionLoadingMore = ref(false)
const pendingTask = ref('')
let discoveryController: ReturnType<typeof globalThis.AbortController> | null = null

const contextKey = computed(() => JSON.stringify([
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
]))

const formatDate = (value: string | null) => {
  if (!value) return '未设置截止时间'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '时间待确认'
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const taskStatus = (task: ResearchTaskDiscoveryEntry) => {
  if (task.session_status === 'IN_PROGRESS') return '进行中'
  if (task.session_status === 'COMPLETED') return '已完成'
  if (task.session_status === 'FAILED' || task.session_status === 'ABANDONED') return '会话已结束'
  return task.status === 'PUBLISHED' ? '待开始' : '暂不可用'
}
const taskPoster = (task: ResearchTaskDiscoveryEntry) => {
  const seed = [...task.task_ref].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 0)
  return `/assets/psynova/original-covers/flow-${String(seed % 28 + 1).padStart(2, '0')}.svg`
}

const openTask = async (task: ResearchTaskDiscoveryEntry) => {
  if (pendingTask.value || task.session_status === 'COMPLETED' || task.session_ref) return
  pendingTask.value = task.task_ref
  await router.push({ name: 'student-research-task-start', params: { taskRef: task.task_ref } })
  pendingTask.value = ''
}

const openSession = async (sessionRef: string) => {
  if (pendingTask.value) return
  pendingTask.value = sessionRef
  await router.push({ name: 'student-research-session-resume', params: { sessionRef } })
  pendingTask.value = ''
}

const mergeUnique = <T extends { task_ref?: string; session_ref?: string }>(current: T[], incoming: T[], key: 'task_ref' | 'session_ref') => {
  const seen = new Set(current.map((item) => item[key]))
  return [...current, ...incoming.filter((item) => !seen.has(item[key]))]
}

const loadTasks = async (requestGeneration: number, offset = 0) => {
  if (!frontendApi.listStudentResearchTasks) throw new Error('research_service_unavailable')
  const page = (await frontendApi.listStudentResearchTasks({ limit: PAGE_SIZE, offset, signal: discoveryController?.signal })).data
  if (requestGeneration !== generation.value) return
  tasks.value = offset === 0 ? page.items : mergeUnique(tasks.value, page.items, 'task_ref')
  taskNextOffset.value = page.has_more ? page.next_offset : null
  taskState.value = 'ready'
}

const loadSessions = async (requestGeneration: number, offset = 0) => {
  if (!frontendApi.listStudentResearchSessions) throw new Error('research_service_unavailable')
  const page = (await frontendApi.listStudentResearchSessions({ limit: PAGE_SIZE, offset, signal: discoveryController?.signal })).data
  if (requestGeneration !== generation.value) return
  sessions.value = offset === 0 ? page.items : mergeUnique(sessions.value, page.items, 'session_ref')
  sessionNextOffset.value = page.has_more ? page.next_offset : null
  sessionState.value = 'ready'
}

const loadFirstPage = async () => {
  discoveryController?.abort()
  discoveryController = new globalThis.AbortController()
  const requestGeneration = ++generation.value
  tasks.value = []
  sessions.value = []
  taskError.value = ''
  sessionError.value = ''
  taskLoadMoreError.value = ''
  sessionLoadMoreError.value = ''
  taskNextOffset.value = null
  sessionNextOffset.value = null
  taskState.value = 'loading'
  sessionState.value = props.tasksOnly ? 'ready' : 'loading'
  if (props.tasksOnly) {
    try {
      await loadTasks(requestGeneration)
    } catch {
      if (requestGeneration !== generation.value) return
      taskState.value = 'error'
      taskError.value = '研究任务暂时无法读取；当前环境没有可用研究任务服务时，不会显示模拟数据。'
    }
    return
  }
  const results = await Promise.allSettled([
    loadTasks(requestGeneration),
    loadSessions(requestGeneration),
  ])
  if (requestGeneration !== generation.value) return
  if (results[0].status === 'rejected') {
    taskState.value = 'error'
    taskError.value = '研究任务暂时无法读取；当前环境没有可用研究任务服务时，不会显示模拟数据。'
  }
  if (results[1].status === 'rejected') {
    sessionState.value = 'error'
    sessionError.value = '研究会话记录暂时无法读取；请连接已配置的本地服务后重试。'
  }
}

const loadMoreTasks = async () => {
  const offset = taskNextOffset.value
  if (offset === null || taskLoadingMore.value || taskState.value !== 'ready') return
  const requestGeneration = generation.value
  taskLoadingMore.value = true
  taskLoadMoreError.value = ''
  try {
    await loadTasks(requestGeneration, offset)
  } catch {
    if (requestGeneration === generation.value) taskLoadMoreError.value = '更多研究任务暂时无法加载。'
  } finally {
    if (requestGeneration === generation.value) taskLoadingMore.value = false
  }
}

const loadMoreSessions = async () => {
  const offset = sessionNextOffset.value
  if (offset === null || sessionLoadingMore.value || sessionState.value !== 'ready') return
  const requestGeneration = generation.value
  sessionLoadingMore.value = true
  sessionLoadMoreError.value = ''
  try {
    await loadSessions(requestGeneration, offset)
  } catch {
    if (requestGeneration === generation.value) sessionLoadMoreError.value = '更多研究记录暂时无法加载。'
  } finally {
    if (requestGeneration === generation.value) sessionLoadingMore.value = false
  }
}

watch(contextKey, () => { void loadFirstPage() })
onMounted(() => { void loadFirstPage() })
onBeforeUnmount(() => {
  generation.value += 1
  discoveryController?.abort()
})
</script>

<template>
  <section class="student-research" aria-labelledby="student-research-title">
    <header class="student-research__heading">
      <div>
        <span class="student-research__label"><BookOpenCheck :size="15" aria-hidden="true" />公开研究任务</span>
        <h2 id="student-research-title">{{ tasksOnly ? '分配给我的研究任务' : '研究演示' }}</h2>
        <p>{{ tasksOnly ? '开放和截止时间由任务记录提供。' : '题目和选项按来源原文展示；此流程只记录作答进度，不生成个人分数或解释。' }}</p>
      </div>
      <span v-if="tasksOnly && taskState === 'ready'" class="student-research__count">{{ tasks.length }} 项</span>
      <StudentRefreshButton :loading="taskState === 'loading' || (!tasksOnly && sessionState === 'loading')" :label="tasksOnly ? '刷新任务' : '刷新'" @click="loadFirstPage" />
    </header>

    <AppStatusCallout tone="info" title="仅用于研究演示" body="任务的研究资格不代表量表有效性、临床批准或学校生产授权。" />

    <section class="student-research__section" aria-labelledby="research-tasks-heading">
      <div v-if="!tasksOnly" class="student-research__subheading">
        <div><h3 id="research-tasks-heading">分配给我的任务</h3><p>开放和截止时间由任务记录提供。</p></div>
        <span v-if="taskState === 'ready'" class="student-research__count">{{ tasks.length }} 项</span>
      </div>
      <AppCard v-if="taskState === 'loading'" class="student-research__state" aria-busy="true">正在读取研究任务<AppLoadingDots /></AppCard>
      <AppCard v-else-if="taskState === 'error'" class="student-research__state student-research__state--error" role="status">
        <span>{{ taskError }}</span><AppButton variant="secondary" size="sm" @click="loadFirstPage">重新读取</AppButton>
      </AppCard>
      <AppCard v-else-if="!tasks.length" class="student-research__state" role="status">当前没有分配给你的研究任务。</AppCard>
      <div v-else class="student-research__cards">
        <AppCard v-for="task in tasks" :key="task.task_ref" class="student-research__task-card">
          <div class="student-research__poster">
            <img :src="taskPoster(task)" alt="" aria-hidden="true" />
            <span>{{ taskStatus(task) }}</span>
          </div>
          <div class="student-research__task-body">
            <span class="student-research__task-category">研究演示</span>
            <h4>{{ task.instrument_id }}</h4>
            <p>{{ task.source_population_scope }}，{{ task.instrument_version }}</p>
            <p class="student-research__dates"><CalendarDays :size="14" aria-hidden="true" />{{ formatDate(task.opens_at) }} 至 {{ formatDate(task.due_at) }}</p>
            <small>公开来源研究演示，尚未批准用于发布或日常运营</small>
            <AppButton
              v-if="task.session_status === 'IN_PROGRESS' && task.session_ref"
              :disabled="Boolean(pendingTask)"
              :loading="pendingTask === task.session_ref"
              @click="openSession(task.session_ref)"
            >
              继续任务
            </AppButton>
            <AppButton
              v-else-if="!task.session_ref"
              :disabled="Boolean(pendingTask) || task.status !== 'PUBLISHED'"
              :loading="pendingTask === task.task_ref"
              @click="openTask(task)"
            >
              开始研究任务
            </AppButton>
            <AppButton
              v-else-if="task.session_status === 'COMPLETED' && task.session_ref"
              variant="secondary"
              :disabled="Boolean(pendingTask)"
              :loading="pendingTask === task.session_ref"
              @click="openSession(task.session_ref)"
            >
              查看完成记录
            </AppButton>
            <span v-else class="student-research__terminal">{{ task.session_status === 'COMPLETED' ? '完成记录已保存' : '此会话已结束' }}</span>
          </div>
        </AppCard>
      </div>
      <div v-if="taskNextOffset !== null && taskState === 'ready'" class="student-research__more">
        <button type="button" :disabled="taskLoadingMore" @click="loadMoreTasks">{{ taskLoadingMore ? '正在加载…' : '加载更多任务' }}</button>
        <p v-if="taskLoadMoreError" role="alert">{{ taskLoadMoreError }}</p>
      </div>
    </section>

    <section v-if="!tasksOnly" class="student-research__section" aria-labelledby="research-history-heading">
      <div class="student-research__subheading">
        <div><h3 id="research-history-heading">研究会话记录</h3><p>这里只显示状态和时间，不展示原始作答。</p></div>
        <span v-if="sessionState === 'ready'" class="student-research__count"><History :size="14" aria-hidden="true" />{{ sessions.length }} 项</span>
      </div>
      <AppCard v-if="sessionState === 'loading'" class="student-research__state" aria-busy="true">正在读取研究记录<AppLoadingDots /></AppCard>
      <AppCard v-else-if="sessionState === 'error'" class="student-research__state student-research__state--error" role="status">
        <span>{{ sessionError }}</span><AppButton variant="secondary" size="sm" @click="loadFirstPage">重新读取</AppButton>
      </AppCard>
      <AppCard v-else-if="!sessions.length" class="student-research__state" role="status">还没有研究会话记录。</AppCard>
      <div v-else class="student-research__history">
        <AppCard v-for="item in sessions" :key="item.session_ref" class="student-research__record">
          <div><strong>研究任务 {{ item.task_ref.slice(-6) }}</strong><p>{{ item.items_answered }} 项已记录<span v-if="item.completed_at">，{{ formatDate(item.completed_at) }}</span></p></div>
          <span>{{ item.status === 'IN_PROGRESS' ? '进行中' : item.status === 'COMPLETED' ? '已完成' : '会话已结束' }}</span>
          <AppButton v-if="item.status === 'IN_PROGRESS'" variant="secondary" size="sm" :disabled="Boolean(pendingTask)" @click="openSession(item.session_ref)">继续</AppButton>
          <AppButton v-else-if="item.status === 'COMPLETED'" variant="secondary" size="sm" :disabled="Boolean(pendingTask)" @click="openSession(item.session_ref)">查看记录</AppButton>
        </AppCard>
      </div>
      <div v-if="sessionNextOffset !== null && sessionState === 'ready'" class="student-research__more">
        <button type="button" :disabled="sessionLoadingMore" @click="loadMoreSessions">{{ sessionLoadingMore ? '正在加载…' : '加载更多记录' }}</button>
        <p v-if="sessionLoadMoreError" role="alert">{{ sessionLoadMoreError }}</p>
      </div>
    </section>
  </section>
</template>

<style scoped>
.student-research { display: grid; gap: 16px; margin: 18px 0; padding: 22px; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); box-shadow: var(--shadow-rest); }
.student-research__heading,.student-research__subheading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.student-research__heading h2 { margin: 7px 0 4px; color: var(--color-text-primary); font-family: var(--font-sans); font-size: 18px; font-weight: 650; }
.student-research__heading p,.student-research__subheading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.student-research__label { display: inline-flex; align-items: center; gap: 6px; color: #388576; font-size: 11px; font-weight: 750; }
.student-research__section { display: grid; gap: 10px; }
.student-research__subheading h3 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 14px; font-weight: 650; }
.student-research__count { display: inline-flex; align-items: center; gap: 4px; color: var(--color-text-muted); font-size: 11px; }
.student-research__state { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 54px; padding: 13px 15px; color: var(--color-text-secondary); font-size: 12px; }
.student-research__state--error { color: #8f651d; }
.student-research__list,.student-research__history { display: grid; gap: 8px; }
.student-research__cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.student-research__task-card { overflow: hidden; border: 1px solid #e8edf1; box-shadow: none; }
.student-research__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; background: #eaf3f5; }
.student-research__poster img { display: block; width: 100%; height: 100%; object-fit: cover; }
.student-research__poster > span { position: absolute; top: 12px; right: 12px; padding: 5px 10px; border-radius: 7px; color: #fff; background: #568f7d; font-size: 12px; font-weight: 600; }
.student-research__task-body { display: grid; min-height: 220px; align-content: start; gap: 7px; padding: 15px 16px 16px; }
.student-research__task-category { color: #00a9dd; font-size: 13px; }
.student-research__task-body h4 { margin: 0; color: var(--color-text-primary); font-size: 16px; font-weight: 650; overflow-wrap: anywhere; }
.student-research__task-body p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.student-research__task-body .student-research__dates { display: flex; align-items: center; gap: 5px; color: var(--color-text-muted); }
.student-research__task-body small { display: block; margin-top: 2px; color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.student-research__task-body > button { justify-self: start; margin-top: auto; }
.student-research__terminal { color: var(--color-text-muted); font-size: 11px; }
.student-research__record { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 12px; padding: 11px 14px; }
.student-research__record strong { color: var(--color-text-primary); font-size: 12px; }
.student-research__record p { margin: 4px 0 0; color: var(--color-text-muted); font-size: 10px; }
.student-research__record > span { color: var(--color-text-secondary); font-size: 11px; }
.student-research__more { display: grid; justify-items: center; gap: 6px; }
.student-research__more button { padding: 7px 12px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; font: inherit; font-size: 11px; }
.student-research__more button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.student-research__more button:disabled { opacity: .6; cursor: wait; }
.student-research__more p { margin: 0; color: #8f651d; font-size: 11px; }
@media(max-width:680px) {
  .student-research { padding: 16px; }
  .student-research__heading { align-items: flex-start; }
  .student-research__cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .student-research__task-body { min-height: 0; }
  .student-research__record { grid-template-columns: minmax(0, 1fr) auto; }
  .student-research__record > button { grid-column: 1 / -1; justify-self: start; }
}
@media(max-width:520px) { .student-research__cards { grid-template-columns: 1fr; } }
</style>
