<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookOpenCheck, RotateCcw, ShieldCheck } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import {
  newProgrammeGenerationBatchIdempotencyKey,
  newProgrammeCandidateIdempotencyKey,
  schoolResearchProgrammeCandidates,
  type ProgrammeGenerationBatchReceipt,
  type ProgrammeGenerationJob,
  type ProgrammeCandidateDetail,
  type ProgrammeCandidateStatus,
  type ProgrammeCandidateSummary,
  type ProgrammeGenerationReceipt,
  type ProgrammeGenerationStatus,
  type ProgrammeGenerationStatusCounts,
} from '@/services/school-research-programme-candidates'
import type { ResearchReviewTask } from '@/services/school-research-feedback'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const PAGE_SIZE = 20
const GENERATION_JOB_PAGE_SIZE = 25
const BATCH_SIZE_OPTIONS = [2, 25, 100]
const GENERATION_JOB_STATUSES: ProgrammeGenerationStatus[] = [
  'QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED',
]
const session = useSessionStore()
const tasks = ref<ResearchReviewTask[]>([])
const candidates = ref<ProgrammeCandidateSummary[]>([])
const selectedTaskRef = ref('')
const selectedCandidateRef = ref('')
const detail = ref<ProgrammeCandidateDetail | null>(null)
const taskState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const listState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const detailState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const taskError = ref('')
const listError = ref('')
const detailError = ref('')
const accessNotice = ref('')
const offset = ref(0)
const hasMore = ref(false)
const confirmation = ref(false)
const mutationBusy = ref(false)
const mutationError = ref('')
const retryAction = ref<(() => Promise<void>) | null>(null)
const mutationConflict = ref(false)
const generationReceipt = ref<ProgrammeGenerationReceipt | null>(null)
const generationBusy = ref(false)
const generationConfirmation = ref(false)
const generationError = ref('')
const generationRetry = ref<(() => Promise<void>) | null>(null)
const batchReceipt = ref<ProgrammeGenerationBatchReceipt | null>(null)
const batchBusy = ref(false)
const batchSize = ref(25)
const batchConfirmation = ref(false)
const batchError = ref('')
const batchRetry = ref<(() => Promise<void>) | null>(null)
const generationJobs = ref<ProgrammeGenerationJob[]>([])
const generationJobsState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const generationJobsError = ref('')
const generationJobsOffset = ref(0)
const generationJobsTotal = ref(0)
const generationJobsHasMore = ref(false)
const generationJobStatusCounts = ref<ProgrammeGenerationStatusCounts | null>(null)

let taskSequence = 0
let listSequence = 0
let detailSequence = 0
let generationJobsSequence = 0
let taskActionEpoch = 0
let mounted = false

const isSpecialist = computed(() => session.user?.role === 'psychological_specialist')
const selectedTask = computed(() => tasks.value.find((task) => task.task_ref === selectedTaskRef.value) ?? null)
const selectedCandidate = computed(() => candidates.value.find((item) => item.candidate_ref === selectedCandidateRef.value) ?? null)
const canAct = computed(() => isSpecialist.value && Boolean(detail.value?.status === 'HELD') && !mutationBusy.value && !retryAction.value)
const canQueueGeneration = computed(() => isSpecialist.value && Boolean(selectedTaskRef.value)
  && !generationBusy.value && !generationReceipt.value && !generationRetry.value
  && !batchBusy.value && !batchRetry.value && !mutationBusy.value && !retryAction.value)
const canQueueBatch = computed(() => isSpecialist.value && Boolean(selectedTaskRef.value)
  && !batchBusy.value && !generationBusy.value && !generationRetry.value && !mutationBusy.value && !retryAction.value)

function classify(error: unknown, fallback: string) {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  const unavailable = code === 'DEPENDENCY_UNAVAILABLE' || code === 'SERVICE_UNAVAILABLE'
  return {
    message: unavailable ? '参考候选功能当前未启用或暂不可用。' : userFacingApiError(error, fallback),
    lost: ['FORBIDDEN', 'RESOURCE_NOT_FOUND', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(code),
    conflict: ['WORKFLOW_CONFLICT', 'IDEMPOTENCY_CONFLICT'].includes(code),
    unavailable,
  }
}

function clearTaskState() {
  ++taskActionEpoch
  selectedTaskRef.value = ''
  selectedCandidateRef.value = ''
  candidates.value = []
  detail.value = null
  offset.value = 0
  hasMore.value = false
  confirmation.value = false
  retryAction.value = null
  mutationError.value = ''
  mutationConflict.value = false
  generationReceipt.value = null
  generationBusy.value = false
  generationConfirmation.value = false
  generationError.value = ''
  generationRetry.value = null
  batchReceipt.value = null
  batchBusy.value = false
  batchConfirmation.value = false
  batchError.value = ''
  batchRetry.value = null
  generationJobs.value = []
  generationJobsState.value = 'idle'
  generationJobsError.value = ''
  generationJobsOffset.value = 0
  generationJobsTotal.value = 0
  generationJobsHasMore.value = false
  generationJobStatusCounts.value = null
  ++listSequence
  ++detailSequence
  ++generationJobsSequence
}

function clearAll() {
  clearTaskState()
  tasks.value = []
  taskState.value = 'idle'
  listState.value = 'idle'
  detailState.value = 'idle'
  taskError.value = ''
  listError.value = ''
  detailError.value = ''
  ++taskSequence
}

function isCurrentTaskAction(taskRef: string, actionEpoch: number) {
  return mounted && actionEpoch === taskActionEpoch
    && selectedTaskRef.value === taskRef && isSpecialist.value
}

function statusLabel(status: ProgrammeCandidateStatus) {
  return ({ HELD: '待教职工查看', ADOPTED: '已采纳为参考', DISCARDED: '已丢弃' })[status]
}

function generationStatusLabel(status: ProgrammeGenerationStatus) {
  return ({
    QUEUED: '已排队', LEASED: '处理中', RETRY: '待重试', HELD: '候选已保存',
    ABSTAINED: '已按规则停止生成', REVIEW_REQUIRED: '需进一步人工复核',
    CRISIS_ROUTED: '已按安全规则停止普通生成', FAILED: '处理失败', CANCELLED: '已取消',
  })[status]
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间暂不可用' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

async function loadTasks() {
  const sequence = ++taskSequence
  taskState.value = 'loading'
  taskError.value = ''
  try {
    const rows = await schoolResearchProgrammeCandidates.listTasks()
    if (!mounted || sequence !== taskSequence || !isSpecialist.value) return
    tasks.value = rows
    taskState.value = 'ready'
    if (selectedTaskRef.value && !rows.some((item) => item.task_ref === selectedTaskRef.value)) {
      clearTaskState()
      accessNotice.value = '当前任务授权已变化，已清除此页候选内容。请刷新后重新选择。'
    }
  } catch (error) {
    if (sequence !== taskSequence || !isSpecialist.value) return
    const result = classify(error, '授权工作事项暂时无法加载。')
    if (result.lost) {
      clearAll()
      accessNotice.value = '当前授权列表不可用，已清除先前显示的任务与候选内容。'
    }
    taskError.value = result.message
    taskState.value = 'error'
  }
}

async function loadCandidates(nextOffset = 0, append = false) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !isSpecialist.value) return
  const sequence = ++listSequence
  listState.value = 'loading'
  listError.value = ''
  if (!append) {
    candidates.value = []
    detail.value = null
    selectedCandidateRef.value = ''
  }
  try {
    const rows = await schoolResearchProgrammeCandidates.list(taskRef, nextOffset, PAGE_SIZE)
    if (!mounted || sequence !== listSequence || taskRef !== selectedTaskRef.value || !isSpecialist.value) return
    candidates.value = append
      ? [...candidates.value, ...rows.filter((row) => !candidates.value.some((existing) => existing.candidate_ref === row.candidate_ref))]
      : rows
    offset.value = nextOffset
    hasMore.value = rows.length === PAGE_SIZE
    listState.value = 'ready'
    if (selectedCandidateRef.value && !candidates.value.some((row) => row.candidate_ref === selectedCandidateRef.value)) {
      selectedCandidateRef.value = ''
      detail.value = null
    }
  } catch (error) {
    if (sequence !== listSequence || taskRef !== selectedTaskRef.value) return
    const result = classify(error, '候选资料暂时无法加载。')
    if (result.lost) {
      clearTaskState()
      accessNotice.value = '当前任务访问状态已变化，候选内容已清除。请刷新授权列表。'
      return
    }
    listError.value = result.message
    listState.value = 'error'
  }
}

async function loadGenerationJobs(nextOffset = 0, append = false) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !isSpecialist.value) return
  const sequence = ++generationJobsSequence
  generationJobsState.value = 'loading'
  generationJobsError.value = ''
  if (!append) {
    generationJobs.value = []
    generationJobsOffset.value = 0
    generationJobsTotal.value = 0
    generationJobsHasMore.value = false
    generationJobStatusCounts.value = null
  }
  try {
    const page = await schoolResearchProgrammeCandidates.listGenerationJobs(taskRef, nextOffset, GENERATION_JOB_PAGE_SIZE)
    if (!mounted || sequence !== generationJobsSequence || taskRef !== selectedTaskRef.value || !isSpecialist.value) return
    generationJobs.value = append
      ? [...generationJobs.value, ...page.items.filter((row) => !generationJobs.value.some((existing) => existing.job_ref === row.job_ref))]
      : page.items
    generationJobsOffset.value = nextOffset
    generationJobsTotal.value = page.total
    generationJobsHasMore.value = page.has_more
    generationJobStatusCounts.value = page.status_counts
    generationJobsState.value = 'ready'
  } catch (error) {
    if (sequence !== generationJobsSequence || taskRef !== selectedTaskRef.value) return
    const result = classify(error, '生成任务状态暂时无法读取。')
    if (result.lost) {
      clearTaskState()
      accessNotice.value = '当前任务授权已变化，已清除此页候选与生成状态。请刷新授权列表。'
      return
    }
    generationJobsError.value = result.message
    generationJobsState.value = 'error'
  }
}

async function loadDetail(candidateRef: string) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !candidateRef || !isSpecialist.value) return
  const sequence = ++detailSequence
  selectedCandidateRef.value = candidateRef
  detail.value = null
  detailError.value = ''
  detailState.value = 'loading'
  confirmation.value = false
  try {
    const result = await schoolResearchProgrammeCandidates.get(taskRef, candidateRef)
    if (!mounted || sequence !== detailSequence || taskRef !== selectedTaskRef.value || candidateRef !== selectedCandidateRef.value || !isSpecialist.value) return
    detail.value = result
    detailState.value = 'ready'
  } catch (error) {
    if (sequence !== detailSequence || taskRef !== selectedTaskRef.value || candidateRef !== selectedCandidateRef.value) return
    const result = classify(error, '候选详情暂时无法加载。')
    if (result.lost) {
      clearTaskState()
      accessNotice.value = '当前候选授权已变化，内容已清除。请刷新授权列表。'
      return
    }
    detailError.value = result.message
    detailState.value = 'error'
  }
}

function selectTask(taskRef: string) {
  if (mutationBusy.value || retryAction.value || generationBusy.value || generationRetry.value
    || batchBusy.value || batchRetry.value || taskRef === selectedTaskRef.value) return
  ++taskActionEpoch
  selectedTaskRef.value = taskRef
  selectedCandidateRef.value = ''
  candidates.value = []
  detail.value = null
  offset.value = 0
  hasMore.value = false
  confirmation.value = false
  mutationError.value = ''
  retryAction.value = null
  mutationConflict.value = false
  generationReceipt.value = null
  generationBusy.value = false
  generationConfirmation.value = false
  generationError.value = ''
  generationRetry.value = null
  batchReceipt.value = null
  batchConfirmation.value = false
  batchError.value = ''
  batchRetry.value = null
  generationJobs.value = []
  generationJobsState.value = 'idle'
  generationJobsError.value = ''
  generationJobsOffset.value = 0
  generationJobsTotal.value = 0
  generationJobsHasMore.value = false
  generationJobStatusCounts.value = null
  ++generationJobsSequence
  void loadCandidates()
  void loadGenerationJobs()
}

async function queueGeneration(key = newProgrammeCandidateIdempotencyKey()) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !isSpecialist.value || !generationConfirmation.value || generationReceipt.value) return
  const actionEpoch = taskActionEpoch
  generationBusy.value = true
  generationError.value = ''
  try {
    const receipt = await schoolResearchProgrammeCandidates.queueGeneration(taskRef, key)
    if (!isCurrentTaskAction(taskRef, actionEpoch)) return
    generationReceipt.value = receipt
    generationRetry.value = null
    generationConfirmation.value = false
    await loadCandidates(0)
  } catch (error) {
    if (!isCurrentTaskAction(taskRef, actionEpoch)) return
    const result = classify(error, '参考资料生成请求未完成。')
    if (result.lost) {
      clearAll()
      accessNotice.value = '当前任务授权已变化，已清除此页任务、候选内容与排队状态。正在刷新授权列表。'
      void loadTasks()
      return
    }
    generationError.value = result.message
    generationRetry.value = () => queueGeneration(key)
  } finally {
    if (isCurrentTaskAction(taskRef, actionEpoch)) generationBusy.value = false
  }
}

function retryGeneration() {
  if (!generationRetry.value || generationBusy.value) return
  void generationRetry.value()
}

async function queueGenerationBatch(afterJobRef: string | null = null, key = newProgrammeGenerationBatchIdempotencyKey(batchSize.value), retrying = false, limit = batchSize.value) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !isSpecialist.value || (!retrying && (!batchConfirmation.value || batchRetry.value))
    || (retrying && !batchRetry.value) || !canQueueBatch.value) return
  const actionEpoch = taskActionEpoch
  batchBusy.value = true
  batchError.value = ''
  try {
    const receipt = await schoolResearchProgrammeCandidates.queueGenerationBatch(taskRef, key, limit, afterJobRef)
    if (!isCurrentTaskAction(taskRef, actionEpoch)) return
    batchReceipt.value = receipt
    batchRetry.value = null
    batchConfirmation.value = false
    await Promise.all([loadCandidates(0), loadGenerationJobs(0)])
  } catch (error) {
    if (!isCurrentTaskAction(taskRef, actionEpoch)) return
    const result = classify(error, '批次生成请求未完成。')
    if (result.lost) {
      clearAll()
      accessNotice.value = '当前任务授权已变化，已清除此页任务、候选内容与批次状态。正在刷新授权列表。'
      void loadTasks()
      return
    }
    batchError.value = result.message
    batchRetry.value = () => queueGenerationBatch(afterJobRef, key, true, limit)
  } finally {
    if (isCurrentTaskAction(taskRef, actionEpoch)) batchBusy.value = false
  }
}

function retryBatchGeneration() {
  if (!batchRetry.value || batchBusy.value) return
  void batchRetry.value()
}

async function performTransition(action: 'adopt' | 'discard', key = newProgrammeCandidateIdempotencyKey()) {
  const taskRef = selectedTaskRef.value
  const candidate = selectedCandidate.value
  if (!taskRef || !candidate || !detail.value || detail.value.status !== 'HELD' || !isSpecialist.value) return
  mutationBusy.value = true
  mutationError.value = ''
  mutationConflict.value = false
  try {
    await schoolResearchProgrammeCandidates.transition(taskRef, { ...candidate, state_version: detail.value.state_version }, action, key)
    if (!mounted || !isSpecialist.value || selectedTaskRef.value !== taskRef) return
    const priorCandidateRef = selectedCandidateRef.value
    retryAction.value = null
    confirmation.value = false
    await loadCandidates(0)
    if (selectedTaskRef.value === taskRef && priorCandidateRef && candidates.value.some((row) => row.candidate_ref === priorCandidateRef)) {
      await loadDetail(priorCandidateRef)
    }
  } catch (error) {
    if (!mounted || selectedTaskRef.value !== taskRef) return
    const result = classify(error, '候选操作未完成。')
    mutationError.value = result.message
    mutationConflict.value = result.conflict
    retryAction.value = () => performTransition(action, key)
  } finally {
    mutationBusy.value = false
  }
}

function retryMutation() {
  if (!retryAction.value || mutationBusy.value) return
  void retryAction.value()
}

async function resolveConflict() {
  mutationError.value = ''
  retryAction.value = null
  mutationConflict.value = false
  await loadCandidates(0)
  if (selectedCandidateRef.value) await loadDetail(selectedCandidateRef.value)
}

watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    clearAll()
    accessNotice.value = '当前身份或学校范围已变化，已清除此页授权内容。'
    if (next[0] === 'psychological_specialist') void loadTasks()
  },
)

watch(batchSize, () => {
  if (batchBusy.value || batchRetry.value) return
  batchReceipt.value = null
  batchConfirmation.value = false
  batchError.value = ''
  batchRetry.value = null
})

onMounted(() => {
  mounted = true
  if (isSpecialist.value) void loadTasks()
})

onBeforeUnmount(() => {
  mounted = false
  clearAll()
})
</script>

<template>
  <section class="programme-candidates" aria-label="教职工研究参考资料">
    <AppStatusCallout tone="info" title="教职工参考资料" body="候选内容仅供授权教职工在研究模拟中查看。采纳不代表专业审核或正式发布，也不会生成学生反馈。" />

    <div class="programme-candidates__toolbar">
      <div><span class="programme-candidates__kicker">研究模拟，工作事项范围</span><h2>方案参考候选</h2><p>只显示服务端已保存的候选；排队完成后，新候选会显示在此处。</p></div>
      <AppButton variant="quiet" size="sm" :disabled="taskState === 'loading' || mutationBusy || generationBusy || batchBusy" @click="loadTasks"><RotateCcw :size="15" aria-hidden="true" />刷新授权</AppButton>
    </div>
    <p v-if="accessNotice" class="programme-candidates__notice" role="status">{{ accessNotice }}</p>
    <p v-if="!isSpecialist" class="programme-candidates__empty">请切换到心理专业人员身份查看授权事项。</p>
    <p v-else-if="taskState === 'loading'" class="programme-candidates__state" role="status" aria-busy="true">正在读取授权事项…</p>
    <AppStatusCallout v-else-if="taskState === 'error'" tone="critical" title="授权事项暂不可用" :body="taskError"><AppButton variant="secondary" size="sm" @click="loadTasks">重新加载</AppButton></AppStatusCallout>
    <p v-else-if="taskState === 'ready' && tasks.length === 0" class="programme-candidates__empty">当前没有可查看的授权工作事项。</p>

    <template v-else-if="taskState === 'ready'">
      <div class="programme-candidates__tasks" aria-label="授权研究工作事项">
        <button v-for="(task, index) in tasks" :key="task.task_ref" type="button" class="programme-candidates__task" :class="{ 'programme-candidates__task--active': selectedTaskRef === task.task_ref }" :aria-pressed="selectedTaskRef === task.task_ref" :disabled="mutationBusy || Boolean(retryAction) || generationBusy || Boolean(generationRetry) || batchBusy || Boolean(batchRetry)" @click="selectTask(task.task_ref)">
          <span class="programme-candidates__task-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span><strong>{{ task.class_display_name || `授权工作事项 ${index + 1}` }}</strong><small>仅限此事项范围，{{ formatDate(task.published_at) }}</small></span>
          <ShieldCheck :size="17" aria-hidden="true" />
        </button>
      </div>

      <div v-if="selectedTask" class="programme-candidates__columns">
        <AppCard class="programme-candidates__panel">
          <header class="programme-candidates__panel-head"><div><span class="programme-candidates__kicker">{{ selectedTask.class_display_name || '授权研究事项' }}</span><h3>已保存候选</h3><p>列表仅显示候选状态，不展示个体测评资料。</p></div><span class="programme-candidates__count">{{ candidates.length }} 条</span></header>
          <p v-if="listState === 'loading'" class="programme-candidates__state" role="status" aria-busy="true">正在读取候选…</p>
          <AppStatusCallout v-else-if="listState === 'error'" tone="critical" title="候选列表暂不可用" :body="listError"><AppButton variant="secondary" size="sm" @click="loadCandidates(0)">重新加载</AppButton></AppStatusCallout>
          <p v-else-if="listState === 'ready' && candidates.length === 0" class="programme-candidates__empty">此事项暂无已保存的参考候选。</p>
          <div v-else class="programme-candidates__rows">
            <button v-for="(candidate, index) in candidates" :key="candidate.candidate_ref" type="button" class="programme-candidates__row" :class="{ 'programme-candidates__row--active': selectedCandidateRef === candidate.candidate_ref }" :aria-pressed="selectedCandidateRef === candidate.candidate_ref" :disabled="mutationBusy || Boolean(retryAction)" @click="loadDetail(candidate.candidate_ref)">
              <span class="programme-candidates__row-icon"><BookOpenCheck :size="17" aria-hidden="true" /></span>
              <span><strong>参考候选 {{ offset + index + 1 }}</strong><small>{{ formatDate(candidate.created_at) }}</small></span>
              <AppBadge :tone="candidate.status === 'ADOPTED' ? 'teal' : candidate.status === 'DISCARDED' ? 'amber' : 'neutral'" dot>{{ statusLabel(candidate.status) }}</AppBadge>
            </button>
          </div>
          <AppButton v-if="hasMore" variant="secondary" size="sm" :loading="listState === 'loading'" :disabled="mutationBusy || Boolean(retryAction)" @click="loadCandidates(offset + PAGE_SIZE, true)">加载更多</AppButton>
        </AppCard>

        <AppCard class="programme-candidates__panel programme-candidates__detail">
          <p v-if="detailState === 'idle'" class="programme-candidates__empty">选择一条候选，查看正文与可核对来源。</p>
          <p v-else-if="detailState === 'loading'" class="programme-candidates__state" role="status" aria-busy="true">正在读取候选详情…</p>
          <AppStatusCallout v-else-if="detailState === 'error'" tone="critical" title="候选详情暂不可用" :body="detailError"><AppButton variant="secondary" size="sm" @click="selectedCandidateRef && loadDetail(selectedCandidateRef)">重新加载</AppButton></AppStatusCallout>
          <template v-else-if="detail">
            <header class="programme-candidates__detail-head"><div><span class="programme-candidates__kicker">教职工参考，研究模拟</span><h3>{{ detail.content.title }}</h3><p>状态：{{ statusLabel(detail.status) }}，{{ formatDate(detail.created_at) }}</p></div><AppBadge :tone="detail.status === 'ADOPTED' ? 'teal' : detail.status === 'DISCARDED' ? 'amber' : 'neutral'" dot>{{ statusLabel(detail.status) }}</AppBadge></header>
            <p v-if="detail.content.content_origin === 'VERIFIED_SOURCE_METADATA' && detail.content.generation_mode === 'MODEL_SOURCE_SELECTION'" class="programme-candidates__origin programme-candidates__origin--metadata">来源索引，模型仅选择来源。标题与目录正文来自已校验来源元数据，不是模型撰写建议。</p>
            <p v-else class="programme-candidates__origin programme-candidates__origin--legacy">旧版模型撰写文本。以下正文由模型撰写，仅作历史研究候选查看，不代表专业审核或批准。</p>
            <p class="programme-candidates__body">{{ detail.content.body }}</p>
            <section class="programme-candidates__citations" aria-labelledby="programme-citations-heading"><h4 id="programme-citations-heading">来源</h4><ol><li v-for="citation in detail.content.citations" :key="citation.citation_id"><a :href="citation.source_url" target="_blank" rel="noopener noreferrer">{{ citation.source_title }}</a><span>{{ citation.source_organization }}<template v-if="citation.source_locator">，{{ citation.source_locator }}</template></span></li></ol></section>
            <p class="programme-candidates__boundary">采纳只表示将此候选保留为教职工参考资料；不表示专业、心理测量学、伦理或正式发布批准。该内容不适用于学生发布。</p>
            <template v-if="detail.status === 'HELD'">
              <label class="programme-candidates__confirm"><input v-model="confirmation" type="checkbox" :disabled="!canAct"><span>我确认此操作仅用于授权工作事项中的教职工参考资料。</span></label>
              <div class="programme-candidates__actions"><AppButton size="sm" :disabled="!canAct || !confirmation" @click="performTransition('adopt')">采纳为参考</AppButton><AppButton variant="danger" size="sm" :disabled="!canAct || !confirmation" @click="performTransition('discard')">丢弃候选</AppButton></div>
            </template>
          </template>
        </AppCard>
      </div>

      <AppCard v-if="selectedTask" class="programme-candidates__queue">
        <div><span class="programme-candidates__kicker">研究模拟，服务端排队</span><h3>生成教职工参考候选</h3><p>系统将按此授权事项的服务端规则选择输入并排队。此操作不发布内容，也不创建学生反馈。</p></div>
        <label v-if="!generationReceipt" class="programme-candidates__confirm"><input v-model="generationConfirmation" type="checkbox" :disabled="generationBusy || Boolean(generationRetry)"><span>我确认请求仅用于此授权事项中的教职工参考资料。</span></label>
        <AppButton v-if="!generationReceipt" size="sm" :loading="generationBusy" :disabled="!canQueueGeneration || !generationConfirmation" @click="queueGeneration()">请求生成参考候选</AppButton>
        <div v-if="generationReceipt" class="programme-candidates__receipt" role="status"><AppBadge :tone="generationReceipt.status === 'HELD' ? 'teal' : ['FAILED', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'CANCELLED'].includes(generationReceipt.status) ? 'amber' : 'neutral'" dot>{{ generationStatusLabel(generationReceipt.status) }}</AppBadge><span>任务范围：{{ selectedTask.class_display_name || '当前授权工作事项' }}。结果仅供教职工参考，未获准用于学生发布或正式运营。</span></div>
        <div v-if="generationError" class="programme-candidates__error" role="alert"><div><strong>生成请求未完成</strong><p>{{ generationError }}</p></div><AppButton v-if="generationRetry" size="sm" :disabled="generationBusy" @click="retryGeneration">使用相同请求重试</AppButton></div>

        <div class="programme-candidates__batch">
          <h4>批次排队</h4>
          <p>按当前授权事项的服务端规则排入教职工研究模拟任务。批次回执数量可能包含已有任务。</p>
          <label class="programme-candidates__batch-size">每批数量<select v-model.number="batchSize" :disabled="batchBusy || Boolean(batchRetry)" aria-label="每批生成任务数量"><option v-for="size in BATCH_SIZE_OPTIONS" :key="size" :value="size">{{ size }} 项</option></select></label>
          <label v-if="!batchReceipt || batchReceipt.next_cursor" class="programme-candidates__confirm"><input v-model="batchConfirmation" type="checkbox" :disabled="batchBusy || Boolean(batchRetry)"><span>我确认每批上限为 {{ batchSize }} 项，仅用于此授权事项的教职工研究模拟，不发布学生反馈。</span></label>
          <AppButton v-if="!batchReceipt || batchReceipt.next_cursor" size="sm" :loading="batchBusy" :disabled="!canQueueBatch || !batchConfirmation || Boolean(batchRetry)" @click="queueGenerationBatch(batchReceipt?.next_cursor ?? null)">{{ batchReceipt ? `请求下一批（最多 ${batchSize} 项）` : `请求首批（最多 ${batchSize} 项）` }}</AppButton>
          <p v-else class="programme-candidates__empty">当前授权范围没有更多批次。</p>
          <div v-if="batchReceipt" class="programme-candidates__receipt" role="status"><AppBadge tone="neutral" dot>批次已回执</AppBadge><span>回执包含 {{ batchReceipt.job_count }} 项任务记录（可能包含已有任务）；处理状态以服务端列表为准。仅供教职工研究模拟，未获准用于学生发布或正式运营。</span></div>
          <div v-if="batchError" class="programme-candidates__error" role="alert"><div><strong>批次请求未完成</strong><p>{{ batchError }}</p></div><AppButton v-if="batchRetry" size="sm" :disabled="batchBusy" @click="retryBatchGeneration">使用相同请求重试</AppButton></div>
        </div>
      </AppCard>

      <AppCard v-if="selectedTask" class="programme-candidates__jobs">
        <header class="programme-candidates__panel-head"><div><span class="programme-candidates__kicker">服务端任务状态</span><h3>批次处理情况</h3><p>状态和数量来自当前授权事项的服务端读取结果。</p></div><AppButton variant="quiet" size="sm" :disabled="generationJobsState === 'loading' || batchBusy || generationBusy" @click="loadGenerationJobs(0)"><RotateCcw :size="15" aria-hidden="true" />刷新状态</AppButton></header>
        <p v-if="generationJobsState === 'loading'" class="programme-candidates__state" role="status" aria-busy="true">正在读取生成任务状态…</p>
        <AppStatusCallout v-else-if="generationJobsState === 'error'" tone="critical" title="生成任务状态暂不可用" :body="generationJobsError"><AppButton variant="secondary" size="sm" @click="loadGenerationJobs(0)">重新读取</AppButton></AppStatusCallout>
        <template v-else-if="generationJobsState === 'ready' && generationJobStatusCounts">
          <p class="programme-candidates__job-total">共 {{ generationJobsTotal }} 项任务</p>
          <div class="programme-candidates__job-counts" aria-label="任务状态汇总">
            <span v-for="status in GENERATION_JOB_STATUSES" :key="status"><AppBadge :tone="status === 'HELD' ? 'teal' : ['FAILED', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'CANCELLED'].includes(status) ? 'amber' : 'neutral'" dot>{{ generationStatusLabel(status) }}，{{ generationJobStatusCounts[status] }}</AppBadge></span>
          </div>
          <p v-if="generationJobs.length === 0" class="programme-candidates__empty">当前没有生成任务。</p>
          <ul v-else class="programme-candidates__job-list">
            <li v-for="(job, index) in generationJobs" :key="job.job_ref"><span><strong>任务 {{ generationJobsOffset + index + 1 }}</strong><small>最近更新：{{ formatDate(job.updated_at) }}，已尝试 {{ job.attempt_count }} 次</small></span><AppBadge :tone="job.status === 'HELD' ? 'teal' : ['FAILED', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'CANCELLED'].includes(job.status) ? 'amber' : 'neutral'" dot>{{ generationStatusLabel(job.status) }}</AppBadge></li>
          </ul>
          <AppButton v-if="generationJobsHasMore" variant="secondary" size="sm" :loading="generationJobsState === 'loading'" :disabled="batchBusy || generationBusy" @click="loadGenerationJobs(generationJobsOffset + GENERATION_JOB_PAGE_SIZE, true)">加载更多任务</AppButton>
        </template>
      </AppCard>
    </template>

    <div v-if="mutationError" class="programme-candidates__error" role="alert"><div><strong>{{ mutationConflict ? '候选状态已变化' : '操作未完成' }}</strong><p>{{ mutationError }}</p></div><AppButton v-if="retryAction" size="sm" :disabled="mutationBusy" @click="retryMutation">使用相同请求重试</AppButton><AppButton v-else-if="mutationConflict" variant="secondary" size="sm" :disabled="mutationBusy" @click="resolveConflict">重新读取</AppButton></div>
  </section>
</template>

<style scoped>
.programme-candidates { display: grid; gap: 14px; margin-top: 24px; }
.programme-candidates__toolbar,.programme-candidates__panel-head,.programme-candidates__detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.programme-candidates__toolbar h2,.programme-candidates__panel-head h3,.programme-candidates__detail-head h3 { margin: 4px 0; color: var(--color-text-primary); }
.programme-candidates__toolbar h2 { font-family: var(--font-display); font-size: 22px; }
.programme-candidates__toolbar p,.programme-candidates__panel-head p,.programme-candidates__detail-head p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.programme-candidates__kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.programme-candidates__tasks { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 9px; }
.programme-candidates__task { display: grid; grid-template-columns: 28px minmax(0,1fr) auto; align-items: center; gap: 10px; min-height: 62px; padding: 10px 12px; border: 1px solid #e0eae5; border-radius: 10px; color: var(--color-text-primary); background: #fff; text-align: left; cursor: pointer; }
.programme-candidates__task:hover:not(:disabled),.programme-candidates__task--active { border-color: #75a997; background: #f2f8f5; }.programme-candidates__task:disabled { opacity: .6; cursor: not-allowed; }
.programme-candidates__task-index { color: #438174; font-size: 12px; font-weight: 800; }.programme-candidates__task strong,.programme-candidates__task small { display: block; overflow-wrap: anywhere; }.programme-candidates__task strong { font-size: 12px; }.programme-candidates__task small { margin-top: 4px; color: var(--color-text-muted); font-size: 10px; }.programme-candidates__task svg { color: #438174; }
.programme-candidates__columns { display: grid; grid-template-columns: minmax(260px,.78fr) minmax(0,1.22fr); gap: 13px; align-items: start; }.programme-candidates__panel { display: grid; gap: 12px; min-width: 0; padding: 17px; }.programme-candidates__count { color: var(--color-text-muted); font-size: 11px; }
.programme-candidates__rows { display: grid; gap: 7px; }.programme-candidates__row { display: grid; grid-template-columns: 32px minmax(0,1fr) auto; align-items: center; gap: 9px; padding: 10px; border: 1px solid #e4ece8; border-radius: 9px; background: #fff; color: var(--color-text-primary); text-align: left; cursor: pointer; }.programme-candidates__row--active,.programme-candidates__row:hover:not(:disabled) { border-color: #75a997; background: #f2f8f5; }.programme-candidates__row:disabled { opacity: .65; cursor: not-allowed; }.programme-candidates__row-icon { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 8px; color: #388576; background: #e8f4ef; }.programme-candidates__row strong,.programme-candidates__row small { display: block; }.programme-candidates__row strong { font-size: 12px; }.programme-candidates__row small { margin-top: 3px; color: var(--color-text-muted); font-size: 10px; }
.programme-candidates__detail-head h3 { font-size: 18px; line-height: 1.5; overflow-wrap: anywhere; }.programme-candidates__body { margin: 0; color: var(--color-text-primary); font-size: 13px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }.programme-candidates__citations { padding-top: 11px; border-top: 1px solid var(--color-border); }.programme-candidates__citations h4 { margin: 0 0 8px; color: var(--color-text-primary); font-size: 12px; }.programme-candidates__citations ol { display: grid; gap: 8px; margin: 0; padding-left: 20px; }.programme-candidates__citations li { padding-left: 2px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.55; }.programme-candidates__citations a { color: #167e9b; font-weight: 700; overflow-wrap: anywhere; }.programme-candidates__citations span { display: block; color: var(--color-text-muted); }.programme-candidates__boundary { margin: 0; padding: 10px 12px; border-radius: 8px; color: #68531f; background: #fbf5e6; font-size: 11px; line-height: 1.6; }
.programme-candidates__origin { margin: 0; padding: 9px 11px; border-radius: 8px; font-size: 11px; line-height: 1.6; }.programme-candidates__origin--metadata { color: #365e51; background: #eef7f4; }.programme-candidates__origin--legacy { color: #68531f; background: #fbf5e6; }
.programme-candidates__confirm { display: flex; align-items: flex-start; gap: 8px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }.programme-candidates__confirm input { margin-top: 3px; accent-color: #388576; }.programme-candidates__actions { display: flex; flex-wrap: wrap; gap: 8px; }.programme-candidates__state,.programme-candidates__empty,.programme-candidates__notice { margin: 0; padding: 14px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }.programme-candidates__notice { border-radius: 9px; color: #42665c; background: #eef7f4; }.programme-candidates__error { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border: 1px solid #f1d0cc; border-radius: 10px; color: #782a22; background: #fff7f6; }.programme-candidates__error p { margin: 4px 0 0; font-size: 12px; }
.programme-candidates__queue { display: grid; gap: 10px; padding: 17px; }.programme-candidates__queue h3 { margin: 4px 0; color: var(--color-text-primary); font-size: 15px; }.programme-candidates__queue p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }.programme-candidates__receipt { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.programme-candidates__batch { display: grid; gap: 9px; padding-top: 12px; border-top: 1px solid var(--color-border-subtle); }.programme-candidates__batch h4 { margin: 0; color: var(--color-text-primary); }.programme-candidates__batch p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }.programme-candidates__batch-size { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }.programme-candidates__batch-size select { min-height: 34px; padding: 4px 9px; border: 1px solid var(--color-border-subtle); border-radius: 8px; color: var(--color-text-primary); background: var(--color-surface); }
.programme-candidates__jobs { display: grid; gap: 12px; }.programme-candidates__job-total { margin: 0; color: var(--color-text-secondary); font-size: 12px; }.programme-candidates__job-counts { display: flex; flex-wrap: wrap; gap: 8px; }.programme-candidates__job-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }.programme-candidates__job-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px solid var(--color-border-subtle); border-radius: 9px; }.programme-candidates__job-list li span { display: grid; gap: 3px; }.programme-candidates__job-list small { color: var(--color-text-secondary); font-size: 11px; }
@media(max-width:760px) { .programme-candidates__toolbar { align-items: flex-start; }.programme-candidates__columns { grid-template-columns: 1fr; }.programme-candidates__panel { padding: 14px; }.programme-candidates__row { grid-template-columns: 30px minmax(0,1fr); }.programme-candidates__row :deep(.app-badge) { grid-column: 2; justify-self: start; } }
</style>
