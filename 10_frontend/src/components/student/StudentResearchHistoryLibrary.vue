<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import ResearchFeedbackSources from '@/components/school/ResearchFeedbackSources.vue'
import StudentHistoryLibrary from '@/components/student/StudentHistoryLibrary.vue'
import type { StudentHistoryLibraryItem, StudentHistoryLibraryStatus } from '@/components/student/history-library'
import type { ResearchSessionDiscoveryEntry, ResearchTaskDiscoveryEntry } from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { schoolResearchFeedback, type ResearchEducationSourceCard, type StudentResearchFeedback } from '@/services/school-research-feedback'
import { useSessionStore } from '@/stores/session'

const TASK_PAGE_SIZE = 30
const SESSION_PAGE_SIZE = 30
const FEEDBACK_PAGE_SIZE = 20

const router = useRouter()
const session = useSessionStore()
const tasks = ref<ResearchTaskDiscoveryEntry[]>([])
const sessions = ref<ResearchSessionDiscoveryEntry[]>([])
const feedback = ref<StudentResearchFeedback[]>([])
const errors = ref<string[]>([])
const loadMoreError = ref('')
const loading = ref(true)
const loadingMore = ref(false)
const pendingTask = ref('')
const taskNextOffset = ref<number | null>(null)
const sessionNextOffset = ref<number | null>(null)
const feedbackOffset = ref(0)
const feedbackTotal = ref(0)
const generation = ref(0)
let requestController: AbortController | null = null

const contextKey = computed(() => JSON.stringify([
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
]))
const errorMessage = computed(() => errors.value.join(' '))
const hasMore = computed(() => taskNextOffset.value !== null
  || sessionNextOffset.value !== null
  || feedbackOffset.value + feedback.value.length < feedbackTotal.value)

const compactDateTime = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
const posterFor = (reference: string) => {
  const seed = [...reference].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 0)
  return `/assets/psynova/original-covers/flow-${String(seed % 28 + 1).padStart(2, '0')}.svg`
}
const statusFor = (status: string | null | undefined): StudentHistoryLibraryStatus => {
  if (status === 'IN_PROGRESS') return 'in_progress'
  if (status === 'COMPLETED') return 'completed'
  if (status === 'FAILED' || status === 'ABANDONED') return 'terminal'
  return 'created'
}
const statusLabelFor = (status: string | null | undefined) => {
  if (status === 'IN_PROGRESS') return '进行中'
  if (status === 'COMPLETED') return '已完成'
  if (status === 'FAILED' || status === 'ABANDONED') return '会话已结束'
  return '待开始'
}

const mergeUnique = <T extends { task_ref?: string; session_ref?: string; feedback_ref?: string }>(
  current: T[], incoming: T[], key: 'task_ref' | 'session_ref' | 'feedback_ref',
) => {
  const seen = new Set(current.map((item) => item[key]))
  return [...current, ...incoming.filter((item) => !seen.has(item[key]))]
}

const loadTasks = async (requestGeneration: number, offset: number) => {
  if (!frontendApi.listStudentResearchTasks) throw new Error('research_tasks_unavailable')
  const result = await frontendApi.listStudentResearchTasks({ limit: TASK_PAGE_SIZE, offset, signal: requestController?.signal })
  if (requestGeneration !== generation.value) return
  tasks.value = offset === 0 ? result.data.items : mergeUnique(tasks.value, result.data.items, 'task_ref')
  taskNextOffset.value = result.data.has_more ? result.data.next_offset : null
}

const loadSessions = async (requestGeneration: number, offset: number) => {
  if (!frontendApi.listStudentResearchSessions) throw new Error('research_sessions_unavailable')
  const result = await frontendApi.listStudentResearchSessions({ limit: SESSION_PAGE_SIZE, offset, signal: requestController?.signal })
  if (requestGeneration !== generation.value) return
  sessions.value = offset === 0 ? result.data.items : mergeUnique(sessions.value, result.data.items, 'session_ref')
  sessionNextOffset.value = result.data.has_more ? result.data.next_offset : null
}

const loadFeedback = async (requestGeneration: number, offset: number) => {
  const result = await schoolResearchFeedback.listStudent(offset, FEEDBACK_PAGE_SIZE)
  if (requestGeneration !== generation.value) return
  feedback.value = offset === 0 ? result.items : mergeUnique(feedback.value, result.items, 'feedback_ref')
  feedbackTotal.value = result.total
  feedbackOffset.value = offset
}

const loadFirstPage = async () => {
  requestController?.abort()
  requestController = new globalThis.AbortController()
  const requestGeneration = ++generation.value
  tasks.value = []
  sessions.value = []
  feedback.value = []
  errors.value = []
  loadMoreError.value = ''
  taskNextOffset.value = null
  sessionNextOffset.value = null
  feedbackOffset.value = 0
  feedbackTotal.value = 0
  loading.value = true

  const results = await Promise.allSettled([
    loadTasks(requestGeneration, 0),
    loadSessions(requestGeneration, 0),
    loadFeedback(requestGeneration, 0),
  ])
  if (requestGeneration !== generation.value) return
  if (results[0].status === 'rejected') errors.value.push('研究任务暂时无法读取；当前环境没有可用研究任务服务时，不会显示模拟数据。')
  if (results[1].status === 'rejected') errors.value.push('研究会话记录暂时无法读取；请连接已配置的本地服务后重试。')
  if (results[2].status === 'rejected') errors.value.push('研究演示反馈暂时无法读取。')
  loading.value = false
}

const loadMore = async () => {
  if (loadingMore.value || !hasMore.value) return
  const requestGeneration = generation.value
  loadingMore.value = true
  loadMoreError.value = ''
  const requests: Array<Promise<unknown>> = []
  if (taskNextOffset.value !== null) requests.push(loadTasks(requestGeneration, taskNextOffset.value))
  if (sessionNextOffset.value !== null) requests.push(loadSessions(requestGeneration, sessionNextOffset.value))
  if (feedbackOffset.value + feedback.value.length < feedbackTotal.value) {
    requests.push(loadFeedback(requestGeneration, feedbackOffset.value + feedback.value.length))
  }
  const results = await Promise.allSettled(requests)
  if (requestGeneration === generation.value && results.some((result) => result.status === 'rejected')) {
    loadMoreError.value = '部分研究演示记录暂时无法加载，请重试。'
  }
  if (requestGeneration === generation.value) loadingMore.value = false
}

const openTask = async (task: ResearchTaskDiscoveryEntry) => {
  if (pendingTask.value || task.session_ref) return
  pendingTask.value = task.task_ref
  try {
    await router.push({ name: 'student-research-task-start', params: { taskRef: task.task_ref } })
  } finally {
    pendingTask.value = ''
  }
}
const openSession = async (sessionRef: string) => {
  if (pendingTask.value) return
  pendingTask.value = sessionRef
  try {
    await router.push({ name: 'student-research-session-resume', params: { sessionRef } })
  } finally {
    pendingTask.value = ''
  }
}

const libraryItems = computed<StudentHistoryLibraryItem[]>(() => {
  const taskItems = tasks.value.map((task) => {
    const status = statusFor(task.session_status)
    const canOpenSession = Boolean(task.session_ref && (task.session_status === 'IN_PROGRESS' || task.session_status === 'COMPLETED'))
    return {
      key: `task:${task.task_ref}`,
      kind: 'research-task',
      ref: task.task_ref,
      status,
      statusLabel: statusLabelFor(task.session_status),
      category: '公开研究任务',
      title: task.instrument_id,
      poster: posterFor(task.task_ref),
      dateLabel: `${compactDateTime(task.opens_at)}–${task.due_at ? compactDateTime(task.due_at) : '未设置截止时间'}`,
      activityLabel: task.session_ref ? `${task.items_answered} 项已记录` : '尚未开始',
      actionLabel: canOpenSession
        ? task.session_status === 'COMPLETED' ? '查看记录' : '继续任务'
        : task.session_ref ? undefined : '开始任务',
      actionVariant: task.session_status === 'COMPLETED' ? 'secondary' as const : 'primary' as const,
      actionDisabled: Boolean(pendingTask.value),
    }
  })
  const taskSessionRefs = new Set(tasks.value.map((task) => task.session_ref).filter((value): value is string => Boolean(value)))
  const sessionItems = sessions.value
    .filter((item) => !taskSessionRefs.has(item.session_ref))
    .map((item) => ({
      key: `session:${item.session_ref}`,
      kind: 'research-session',
      ref: item.session_ref,
      status: statusFor(item.status),
      statusLabel: statusLabelFor(item.status),
      category: '研究会话',
      title: `研究任务 ${item.task_ref.slice(-6)}`,
      poster: posterFor(item.session_ref),
      dateLabel: item.completed_at ? compactDateTime(item.completed_at) : '时间未提供',
      activityLabel: `${item.items_answered} 项已记录`,
      actionLabel: item.status === 'IN_PROGRESS' ? '继续' : item.status === 'COMPLETED' ? '查看记录' : undefined,
      actionVariant: 'secondary' as const,
    }))
  const feedbackItems = feedback.value.map((item) => ({
    key: `feedback:${item.feedback_ref}`,
    kind: 'research-feedback',
    ref: item.feedback_ref,
    status: 'completed' as const,
    statusLabel: '已发布',
    category: '研究演示反馈',
    title: item.title,
    poster: posterFor(item.feedback_ref),
    dateLabel: compactDateTime(item.published_at),
    activityLabel: item.source_cards?.length ? `${item.source_cards.length} 个参考来源` : undefined,
  }))
  return [...taskItems, ...sessionItems, ...feedbackItems]
})

const activateRecord = (item: StudentHistoryLibraryItem) => {
  if (item.kind === 'research-session') {
    void openSession(item.ref)
    return
  }
  if (item.kind !== 'research-task') return
  const task = tasks.value.find((candidate) => candidate.task_ref === item.ref)
  if (!task) return
  if (task.session_ref && (task.session_status === 'IN_PROGRESS' || task.session_status === 'COMPLETED')) void openSession(task.session_ref)
  else if (!task.session_ref) void openTask(task)
}

const feedbackFor = (reference: string) => feedback.value.find((item) => item.feedback_ref === reference)
const feedbackSourcesFor = (reference: string): ResearchEducationSourceCard[] => feedbackFor(reference)?.source_cards ?? []

watch(contextKey, () => { void loadFirstPage() })
onMounted(() => { void loadFirstPage() })
onBeforeUnmount(() => {
  generation.value += 1
  requestController?.abort()
})
</script>

<template>
  <div class="student-research-history">
    <AppStatusCallout tone="info" title="仅用于研究演示" body="任务和会话记录不代表量表有效性、临床批准或学校生产授权。" />
    <StudentHistoryLibrary
      :items="libraryItems"
      :loading="loading"
      :error="errorMessage"
      error-title="研究演示记录暂时不可用"
      empty-title="目前没有研究演示记录"
      empty-description="当前账号可访问的研究任务、会话和已发布反馈会显示在这里。"
      :has-more="hasMore"
      :loading-more="loadingMore"
      :load-more-error="loadMoreError"
      @retry="loadFirstPage"
      @load-more="loadMore"
      @activate="activateRecord"
    >
      <template #details="{ item }">
        <div v-if="item.kind === 'research-task'" class="student-research-history__note">
          <span>{{ tasks.find((task) => task.task_ref === item.ref)?.source_population_scope }}</span>
          <span>{{ tasks.find((task) => task.task_ref === item.ref)?.instrument_version }}</span>
          <span>仅用于研究演示</span>
        </div>
        <div v-else-if="item.kind === 'research-feedback'" class="student-research-history__feedback">
          <p>{{ feedbackFor(item.ref)?.body }}</p>
          <ResearchFeedbackSources
            v-if="feedbackSourcesFor(item.ref).length"
            :source-cards="feedbackSourcesFor(item.ref)"
          />
        </div>
      </template>
    </StudentHistoryLibrary>
  </div>
</template>

<style scoped>
.student-research-history { display: grid; gap: 0; }
.student-research-history__note { display: grid; gap: 3px; margin-top: 4px; color: #69717d; font-size: 11px; line-height: 1.45; }
.student-research-history__feedback { display: grid; gap: 12px; margin-top: 4px; }
.student-research-history__feedback > p { margin: 0; color: #424956; font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
</style>
