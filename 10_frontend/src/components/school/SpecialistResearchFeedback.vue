<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw, ShieldCheck } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import ResearchFeedbackSources from '@/components/school/ResearchFeedbackSources.vue'
import SpecialistResearchEducationCandidates from '@/components/school/SpecialistResearchEducationCandidates.vue'
import type { ResearchEducationCandidateDetail } from '@/services/school-research-education-candidates'
import {
  newResearchFeedbackIdempotencyKey,
  schoolResearchFeedback,
  type ResearchEligibleSession,
  type ResearchFeedback,
  type ResearchReviewCase,
  type ResearchReviewTask,
} from '@/services/school-research-feedback'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const PAGE_SIZE = 20
const session = useSessionStore()
const tasks = ref<ResearchReviewTask[]>([])
const tasksState = ref<'loading' | 'ready' | 'error' | 'idle'>('idle')
const tasksError = ref('')
const selectedTaskRef = ref('')
const sessions = ref<ResearchEligibleSession[]>([])
const sessionTotal = ref(0)
const sessionOffset = ref(0)
const sessionsState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const sessionsError = ref('')
const cases = ref<ResearchReviewCase[]>([])
const caseTotal = ref(0)
const caseOffset = ref(0)
const casesState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const casesError = ref('')
const selectedSessionRef = ref('')
const selectedCase = ref<ResearchReviewCase | null>(null)
const caseState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const caseError = ref('')
const reviewNote = ref('')
const feedbackRows = ref<ResearchFeedback[]>([])
const feedbackTotal = ref(0)
const feedbackState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const feedbackError = ref('')
const draftTitle = ref('')
const draftBody = ref('')
const draftCandidateRef = ref<string | undefined>()
const confirmation = ref('')
const mutationBusy = ref(false)
const mutationError = ref('')
const mutationConflict = ref(false)
const failedRequest = ref<{ label: string; run: () => Promise<unknown> } | null>(null)
const accessMessage = ref('')

let taskSequence = 0
let taskDataSequence = 0
let detailSequence = 0
let mounted = false

const isSpecialist = computed(() => session.user?.role === 'psychological_specialist')
const selectedTask = computed(() => tasks.value.find((task) => task.task_ref === selectedTaskRef.value) ?? null)
const selectedSession = computed(() => sessions.value.find((item) => item.session_ref === selectedSessionRef.value) ?? null)
const sessionHasMore = computed(() => sessionOffset.value + sessions.value.length < sessionTotal.value)
const caseHasMore = computed(() => caseOffset.value + cases.value.length < caseTotal.value)
const selectedCaseIsTerminal = computed(() => selectedCase.value?.status === 'APPROVED' || selectedCase.value?.status === 'REJECTED')
const canMutate = computed(() => isSpecialist.value && !mutationBusy.value && !failedRequest.value)

function classify(error: unknown, fallback: string) {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  return {
    message: userFacingApiError(error, fallback),
    conflict: code === 'WORKFLOW_CONFLICT' || code === 'IDEMPOTENCY_CONFLICT',
    accessLost: ['FORBIDDEN', 'RESOURCE_NOT_FOUND', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(code),
    retryable: Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable),
  }
}

function clearSelectedData() {
  clearDraft()
  selectedTaskRef.value = ''
  selectedSessionRef.value = ''
  sessions.value = []
  sessionTotal.value = 0
  sessionOffset.value = 0
  cases.value = []
  caseTotal.value = 0
  caseOffset.value = 0
  selectedCase.value = null
  feedbackRows.value = []
  feedbackTotal.value = 0
  reviewNote.value = ''
  confirmation.value = ''
  failedRequest.value = null
  ++taskSequence
  ++taskDataSequence
  ++detailSequence
}

function clearPrivateState() {
  clearSelectedData()
  tasks.value = []
  tasksState.value = 'idle'
  tasksError.value = ''
}

function clearDraft() {
  draftCandidateRef.value = undefined
  draftTitle.value = ''
  draftBody.value = ''
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function caseStatusLabel(status: ResearchReviewCase['status']) {
  return ({ OPEN: '待开始', IN_REVIEW: '处理中', APPROVED: '已完成', REJECTED: '已退回' })[status]
}

function feedbackStatusLabel(status: ResearchFeedback['status']) {
  return ({ DRAFT: '草稿', PUBLISHED: '学生演示账户可见', REVOKED: '已撤回' })[status]
}

async function loadTasks() {
  const sequence = ++taskSequence
  tasksState.value = 'loading'
  tasksError.value = ''
  accessMessage.value = ''
  try {
    const rows = await schoolResearchFeedback.listTasks()
    if (!mounted || sequence !== taskSequence || !isSpecialist.value) return
    tasks.value = rows
    tasksState.value = 'ready'
    if (selectedTaskRef.value && !rows.some((row) => row.task_ref === selectedTaskRef.value)) {
      clearSelectedData()
      accessMessage.value = '当前任务权限发生变化，已清除此页记录。刷新列表后重新选择。'
    }
  } catch (error) {
    if (sequence !== taskSequence || !isSpecialist.value) return
    const classified = classify(error, '研究工作事项暂时无法加载。')
    if (classified.accessLost) clearPrivateState()
    tasksError.value = classified.message
    tasksState.value = 'error'
  }
}

async function loadTaskData(options: { sessionOffset?: number; caseOffset?: number } = {}) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !isSpecialist.value) return
  const sequence = ++taskDataSequence
  if (options.sessionOffset !== undefined) sessionOffset.value = options.sessionOffset
  if (options.caseOffset !== undefined) caseOffset.value = options.caseOffset
  sessionsState.value = 'loading'
  casesState.value = 'loading'
  sessionsError.value = ''
  casesError.value = ''
  try {
    const [sessionPage, casePage] = await Promise.all([
      schoolResearchFeedback.listEligibleSessions(taskRef, sessionOffset.value, PAGE_SIZE),
      schoolResearchFeedback.listCases(taskRef, caseOffset.value, PAGE_SIZE),
    ])
    if (!mounted || sequence !== taskDataSequence || taskRef !== selectedTaskRef.value || !isSpecialist.value) return
    sessions.value = sessionPage.items
    sessionTotal.value = sessionPage.total
    cases.value = casePage.items
    caseTotal.value = casePage.total
    sessionsState.value = 'ready'
    casesState.value = 'ready'
    accessMessage.value = ''
    if (selectedSessionRef.value && !sessionPage.items.some((item) => item.session_ref === selectedSessionRef.value)) {
      selectedSessionRef.value = ''
      selectedCase.value = null
      caseState.value = 'idle'
      feedbackRows.value = []
      feedbackState.value = 'idle'
      reviewNote.value = ''
      clearDraft()
    }
  } catch (error) {
    if (sequence !== taskDataSequence || taskRef !== selectedTaskRef.value) return
    const classified = classify(error, '研究记录暂时无法加载。')
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '当前任务访问状态发生变化，已清除此页记录。请刷新工作事项。'
      sessionsState.value = 'idle'
      casesState.value = 'idle'
      return
    }
    sessionsError.value = classified.message
    casesError.value = classified.message
    sessionsState.value = 'error'
    casesState.value = 'error'
  }
}

async function selectTask(taskRef: string) {
  if (!canMutate.value || taskRef === selectedTaskRef.value) return
  selectedTaskRef.value = taskRef
  clearDraft()
  selectedSessionRef.value = ''
  selectedCase.value = null
  sessions.value = []
  cases.value = []
  feedbackRows.value = []
  sessionOffset.value = 0
  caseOffset.value = 0
  reviewNote.value = ''
  ++detailSequence
  await loadTaskData()
}

async function selectSession(item: ResearchEligibleSession) {
  if (!canMutate.value) return
  clearDraft()
  selectedSessionRef.value = item.session_ref
  confirmation.value = ''
  reviewNote.value = ''
  if (item.case_ref) {
    await loadCase(item.case_ref)
    return
  }
  selectedCase.value = null
  caseState.value = 'idle'
  caseError.value = ''
  feedbackRows.value = []
  feedbackState.value = 'idle'
}

async function selectCase(item: ResearchReviewCase) {
  if (!canMutate.value) return
  selectedSessionRef.value = sessions.value.find((sessionRow) => sessionRow.session_ref === item.session_ref)?.session_ref ?? ''
  await loadCase(item.case_ref)
}

async function loadCase(caseRef: string) {
  const taskRef = selectedTaskRef.value
  if (!taskRef || !isSpecialist.value) return
  const sequence = ++detailSequence
  clearDraft()
  caseState.value = 'loading'
  caseError.value = ''
  feedbackRows.value = []
  feedbackState.value = 'loading'
  try {
    const [reviewCase, feedbackPage] = await Promise.all([
      schoolResearchFeedback.getCase(taskRef, caseRef),
      schoolResearchFeedback.listFeedback(caseRef, 0, PAGE_SIZE),
    ])
    if (!mounted || sequence !== detailSequence || taskRef !== selectedTaskRef.value || !isSpecialist.value) return
    selectedCase.value = reviewCase
    reviewNote.value = reviewCase.review_note ?? ''
    caseState.value = 'ready'
    feedbackRows.value = feedbackPage.items
    feedbackTotal.value = feedbackPage.total
    feedbackState.value = 'ready'
    confirmation.value = ''
    draftTitle.value = ''
    draftBody.value = ''
  } catch (error) {
    if (sequence !== detailSequence || taskRef !== selectedTaskRef.value) return
    const classified = classify(error, '研究复核记录暂时无法加载。')
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '当前访问状态发生变化，已清除此页记录。请刷新任务列表。'
      return
    }
    selectedCase.value = null
    caseError.value = classified.message
    caseState.value = 'error'
    feedbackError.value = classified.message
    feedbackState.value = 'error'
  }
}

async function refreshCurrent() {
  if (!selectedTaskRef.value || mutationBusy.value) return
  const caseRef = selectedCase.value?.case_ref
  await loadTaskData()
  if (caseRef && selectedTaskRef.value) await loadCase(caseRef)
}

async function runMutation(label: string, run: () => Promise<unknown>, retry = false) {
  if (!isSpecialist.value || mutationBusy.value || (!retry && failedRequest.value)) return
  const taskRef = selectedTaskRef.value
  const sequence = detailSequence
  mutationBusy.value = true
  mutationError.value = ''
  mutationConflict.value = false
  try {
    const result = await run()
    if (!mounted || taskRef !== selectedTaskRef.value || sequence !== detailSequence) return
    failedRequest.value = null
    if (result && typeof result === 'object' && 'case_ref' in result && 'version' in result) {
      const row = result as ResearchReviewCase
      selectedCase.value = row
      reviewNote.value = row.review_note ?? ''
      caseState.value = 'ready'
      await loadTaskData()
      await loadCase(row.case_ref)
    } else if (result && typeof result === 'object' && 'feedback_ref' in result) {
      const currentCaseRef = selectedCase.value?.case_ref
      if (currentCaseRef) await loadCase(currentCaseRef)
    }
  } catch (error) {
    if (!mounted || taskRef !== selectedTaskRef.value || sequence !== detailSequence || !isSpecialist.value) return
    const classified = classify(error, `${label}没有完成。`)
    mutationError.value = classified.message
    mutationConflict.value = classified.conflict
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '当前访问状态发生变化，已清除此页记录。请刷新工作事项。'
    } else {
      failedRequest.value = classified.retryable ? { label, run } : null
    }
  } finally {
    mutationBusy.value = false
  }
}

function createCase() {
  const taskRef = selectedTaskRef.value
  const sessionRef = selectedSession.value?.session_ref
  if (!taskRef || !sessionRef || selectedSession.value?.case_ref || !canMutate.value) return
  const key = newResearchFeedbackIdempotencyKey()
  const run = () => schoolResearchFeedback.createCase(taskRef, sessionRef, key)
  void runMutation('建立复核记录', run)
}

function transitionCase(status: 'IN_REVIEW' | 'APPROVED' | 'REJECTED') {
  const row = selectedCase.value
  const taskRef = selectedTaskRef.value
  const note = reviewNote.value.trim()
  if (!row || !taskRef || !note || !canMutate.value || selectedCaseIsTerminal.value) return
  const key = newResearchFeedbackIdempotencyKey()
  const run = () => schoolResearchFeedback.transitionCase(taskRef, row.case_ref, row.version, status, note, key)
  void runMutation(status === 'IN_REVIEW' ? '开始处理' : status === 'APPROVED' ? '标记复核完成' : '退回记录', run)
}

function createDraft() {
  const row = selectedCase.value
  if (!row || row.status !== 'APPROVED' || !canMutate.value) return
  const key = newResearchFeedbackIdempotencyKey()
  const title = draftTitle.value.trim()
  const body = draftBody.value.trim()
  const candidateRef = draftCandidateRef.value
  const run = () => schoolResearchFeedback.createDraft(row.case_ref, row.version, title, body, key, candidateRef)
  void runMutation('建立教育反馈草稿', run)
}

function useCandidate(candidate: ResearchEducationCandidateDetail) {
  if (!canMutate.value || selectedCase.value?.status !== 'APPROVED'
    || candidate.status !== 'ADOPTED' || candidate.task_ref !== selectedTaskRef.value
    || candidate.session_ref !== selectedCase.value.session_ref) return
  const content = candidate.candidate_payload.content
  draftCandidateRef.value = candidate.candidate_ref
  draftTitle.value = '日常学习与生活支持'
  draftBody.value = [content.summary, ...content.observations, ...content.suggestions.map(item => item.text), content.disclaimer].join('\n\n')
}

function publish(item: ResearchFeedback) {
  if (item.status !== 'DRAFT' || confirmation.value !== `publish:${item.feedback_ref}` || !canMutate.value) return
  const key = newResearchFeedbackIdempotencyKey()
  const run = () => schoolResearchFeedback.publish(item, key)
  void runMutation('发布到学生演示账户', run)
}

function revoke(item: ResearchFeedback) {
  if (item.status !== 'PUBLISHED' || confirmation.value !== `revoke:${item.feedback_ref}` || !canMutate.value) return
  const key = newResearchFeedbackIdempotencyKey()
  const run = () => schoolResearchFeedback.revoke(item, key)
  void runMutation('撤回学生演示账户反馈', run)
}

function retryFailedRequest() {
  const failed = failedRequest.value
  if (!failed || mutationBusy.value) return
  void runMutation(failed.label, failed.run, true)
}

async function refreshAfterConflict() {
  if (!selectedCase.value || mutationBusy.value) return
  failedRequest.value = null
  mutationError.value = ''
  await loadCase(selectedCase.value.case_ref)
  await loadTaskData()
  mutationConflict.value = false
}

watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    clearPrivateState()
    accessMessage.value = '当前身份或学校范围已变化，已清除此页记录。'
    if (next[0] === 'psychological_specialist') void loadTasks()
    else tasksState.value = 'idle'
  },
)

onMounted(() => {
  mounted = true
  if (isSpecialist.value) void loadTasks()
  else tasksState.value = 'idle'
})

onBeforeUnmount(() => {
  mounted = false
  ++taskSequence
  clearPrivateState()
})
</script>

<template>
  <section class="research-feedback" aria-label="研究模拟教育反馈工作流">
    <AppStatusCallout
      tone="info"
      title="研究模拟 · 教育支持工作流"
      body="只处理已完成记录的服务端元数据与独立教育反馈文本，不展示测评分数或原始回答。页面状态不构成临床、心理测量学、伦理或正式研究批准。"
    />

    <div class="research-feedback__toolbar">
      <div><span class="research-feedback__kicker">独立研究工作流</span><h2>研究教育反馈</h2><p>选择研究任务，查看已完成记录并单独管理学生可见的演示反馈。</p></div>
      <AppButton variant="quiet" size="sm" :disabled="tasksState === 'loading' || mutationBusy" @click="loadTasks"><RotateCcw :size="15" aria-hidden="true" />刷新任务</AppButton>
    </div>
    <p v-if="accessMessage" class="research-feedback__notice" role="status">{{ accessMessage }}</p>
    <p v-if="tasksState === 'loading'" class="research-feedback__state" role="status" aria-busy="true">正在读取研究工作事项…</p>
    <AppStatusCallout v-else-if="tasksState === 'error'" tone="critical" title="研究工作事项暂不可用" :body="tasksError"><AppButton variant="secondary" size="sm" @click="loadTasks">重新加载</AppButton></AppStatusCallout>
    <p v-else-if="!tasks.length" class="research-feedback__empty">当前没有可处理的研究工作事项。</p>
    <div v-else class="research-feedback__tasks" aria-label="研究工作事项">
      <button v-for="(task, index) in tasks" :key="task.task_ref" type="button" class="research-feedback__task" :class="{ 'research-feedback__task--active': selectedTaskRef === task.task_ref }" :aria-pressed="selectedTaskRef === task.task_ref" :disabled="mutationBusy || Boolean(failedRequest)" @click="selectTask(task.task_ref)">
        <span class="research-feedback__task-index">{{ String(index + 1).padStart(2, '0') }}</span>
        <span><strong>{{ task.class_display_name || `研究任务 ${index + 1}` }}</strong><small>已发布 · {{ formatDate(task.published_at) }}</small></span>
        <ShieldCheck :size="17" aria-hidden="true" />
      </button>
    </div>

    <template v-if="selectedTask">
      <SpecialistResearchEducationCandidates :key="selectedTaskRef" :task-ref="selectedTaskRef" :session-ref="selectedCase?.session_ref" :can-use-source="selectedCase?.status === 'APPROVED'" :disabled="!canMutate" @source="useCandidate" />
      <div class="research-feedback__columns">
        <AppCard class="research-feedback__panel">
          <header class="research-feedback__panel-head"><div><span class="research-feedback__kicker">{{ selectedTask.class_display_name || '研究任务' }}</span><h3>已完成记录</h3><p>列表不显示学生身份或原始作答。</p></div><AppButton variant="quiet" size="sm" aria-label="刷新研究记录" :disabled="sessionsState === 'loading' || casesState === 'loading' || mutationBusy" @click="loadTaskData"><RotateCcw :size="15" aria-hidden="true" /></AppButton></header>
          <p v-if="sessionsState === 'loading'" class="research-feedback__state" role="status" aria-busy="true">正在读取完成记录…</p>
          <AppStatusCallout v-else-if="sessionsState === 'error'" tone="critical" title="完成记录暂不可用" :body="sessionsError"><AppButton variant="secondary" size="sm" @click="loadTaskData">重新加载</AppButton></AppStatusCallout>
          <p v-else-if="!sessions.length" class="research-feedback__empty">此任务当前没有可处理的完成记录。</p>
          <div v-else class="research-feedback__rows">
            <button v-for="(item, index) in sessions" :key="item.session_ref" type="button" class="research-feedback__row" :class="{ 'research-feedback__row--active': selectedSessionRef === item.session_ref }" :aria-pressed="selectedSessionRef === item.session_ref" :disabled="mutationBusy || Boolean(failedRequest)" @click="selectSession(item)">
              <span>记录 {{ sessionOffset + index + 1 }}</span><small>{{ formatDate(item.completed_at) }} · {{ item.items_answered }} 项</small><AppBadge :tone="item.case_ref ? 'neutral' : 'teal'" dot>{{ item.case_ref ? '已有复核记录' : '可建立复核' }}</AppBadge>
            </button>
          </div>
          <footer v-if="sessionTotal > PAGE_SIZE" class="research-feedback__pager"><span>{{ sessions.length ? `${sessionOffset + 1}–${sessionOffset + sessions.length} / ${sessionTotal}` : `共 ${sessionTotal} 条` }}</span><span><AppButton variant="quiet" size="sm" :disabled="sessionOffset === 0 || sessionsState === 'loading'" @click="loadTaskData({ sessionOffset: Math.max(0, sessionOffset - PAGE_SIZE) })">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="!sessionHasMore || sessionsState === 'loading'" @click="loadTaskData({ sessionOffset: sessionOffset + PAGE_SIZE })">下一页</AppButton></span></footer>
        </AppCard>

        <AppCard class="research-feedback__panel">
          <header class="research-feedback__panel-head"><div><span class="research-feedback__kicker">任务范围</span><h3>复核记录</h3><p>状态变化不会自动发布学生可见反馈。</p></div><span class="research-feedback__count">{{ caseTotal }} 条</span></header>
          <p v-if="casesState === 'loading'" class="research-feedback__state" role="status" aria-busy="true">正在读取复核记录…</p>
          <AppStatusCallout v-else-if="casesState === 'error'" tone="critical" title="复核记录暂不可用" :body="casesError"><AppButton variant="secondary" size="sm" @click="loadTaskData">重新加载</AppButton></AppStatusCallout>
          <p v-else-if="!cases.length" class="research-feedback__empty">此任务还没有复核记录。</p>
          <div v-else class="research-feedback__rows">
            <button v-for="(item, index) in cases" :key="item.case_ref" type="button" class="research-feedback__row" :class="{ 'research-feedback__row--active': selectedCase?.case_ref === item.case_ref }" :aria-pressed="selectedCase?.case_ref === item.case_ref" :disabled="mutationBusy || Boolean(failedRequest)" @click="selectCase(item)">
              <span>复核 {{ caseOffset + index + 1 }}</span><small>{{ formatDate(item.updated_at) }}</small><AppBadge :tone="item.status === 'APPROVED' ? 'teal' : item.status === 'REJECTED' ? 'amber' : 'neutral'" dot>{{ caseStatusLabel(item.status) }}</AppBadge>
            </button>
          </div>
          <footer v-if="caseTotal > PAGE_SIZE" class="research-feedback__pager"><span>{{ cases.length ? `${caseOffset + 1}–${caseOffset + cases.length} / ${caseTotal}` : `共 ${caseTotal} 条` }}</span><span><AppButton variant="quiet" size="sm" :disabled="caseOffset === 0 || casesState === 'loading'" @click="loadTaskData({ caseOffset: Math.max(0, caseOffset - PAGE_SIZE) })">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="!caseHasMore || casesState === 'loading'" @click="loadTaskData({ caseOffset: caseOffset + PAGE_SIZE })">下一页</AppButton></span></footer>
        </AppCard>
      </div>

      <AppCard v-if="selectedSession && !selectedSession.case_ref && !selectedCase" class="research-feedback__detail">
        <h3>建立复核记录</h3><p>该记录已完成。建立复核记录不会读取或展示原始回答。</p>
        <AppButton size="sm" :disabled="!canMutate" @click="createCase">建立复核记录</AppButton>
      </AppCard>

      <AppCard v-if="selectedCase || caseState === 'loading' || caseState === 'error'" class="research-feedback__detail">
        <p v-if="caseState === 'loading'" class="research-feedback__state" role="status" aria-busy="true">正在读取复核内容…</p>
        <AppStatusCallout v-else-if="caseState === 'error'" tone="critical" title="复核内容暂不可用" :body="caseError"><AppButton variant="secondary" size="sm" @click="refreshCurrent">重新加载</AppButton></AppStatusCallout>
        <template v-else-if="selectedCase">
          <header class="research-feedback__detail-head"><div><span class="research-feedback__kicker">研究模拟 · 独立教育反馈</span><h3>复核工作记录</h3><p>版本 {{ selectedCase.version }} · 更新于 {{ formatDate(selectedCase.updated_at) }}</p></div><AppBadge :tone="selectedCase.status === 'APPROVED' ? 'teal' : selectedCase.status === 'REJECTED' ? 'amber' : 'neutral'" dot>{{ caseStatusLabel(selectedCase.status) }}</AppBadge></header>
          <p v-if="selectedCase.status === 'APPROVED'" class="research-feedback__boundary">复核流程已完成。此状态不代表心理测量学、临床或正式研究批准。学生可见反馈仍需单独发布。</p>
          <label class="research-feedback__field"><span>复核备注</span><textarea v-model="reviewNote" maxlength="4000" rows="3" :disabled="!canMutate || selectedCaseIsTerminal" placeholder="记录工作流备注；不要粘贴原始作答或身份信息。" /><small>{{ reviewNote.length }}/4000</small></label>
          <div v-if="!selectedCaseIsTerminal" class="research-feedback__actions">
            <AppButton v-if="selectedCase.status === 'OPEN'" size="sm" :disabled="!canMutate || !reviewNote.trim()" @click="transitionCase('IN_REVIEW')">开始处理</AppButton>
            <template v-else-if="selectedCase.status === 'IN_REVIEW'"><AppButton size="sm" :disabled="!canMutate || !reviewNote.trim()" @click="transitionCase('APPROVED')">完成复核</AppButton><AppButton variant="secondary" size="sm" :disabled="!canMutate || !reviewNote.trim()" @click="transitionCase('REJECTED')">退回记录</AppButton></template>
          </div>

          <section class="research-feedback__versions" aria-label="教育反馈版本">
            <header><div><h4>学生可见的演示反馈</h4><p>仅限研究模拟；“发布”不会赋予正式发布或运营许可。</p></div><span>{{ feedbackTotal }} 条</span></header>
            <p v-if="feedbackState === 'loading'" class="research-feedback__state" role="status" aria-busy="true">正在读取反馈版本…</p>
            <AppStatusCallout v-else-if="feedbackState === 'error'" tone="critical" title="反馈版本暂不可用" :body="feedbackError"><AppButton variant="secondary" size="sm" @click="loadCase(selectedCase!.case_ref)">重新加载</AppButton></AppStatusCallout>
            <p v-else-if="!feedbackRows.length" class="research-feedback__empty">尚无单独建立的学生反馈。</p>
            <ol v-else class="research-feedback__versions-list">
              <li v-for="item in feedbackRows" :key="item.feedback_ref" class="research-feedback__version">
                <header><div><h5>{{ item.title }}</h5><small>修订 {{ item.content_revision }} · 状态版本 {{ item.state_version }}</small></div><AppBadge :tone="item.status === 'PUBLISHED' ? 'teal' : item.status === 'REVOKED' ? 'amber' : 'neutral'" dot>{{ feedbackStatusLabel(item.status) }}</AppBadge></header>
                <p class="research-feedback__body">{{ item.body }}</p>
                <ResearchFeedbackSources :source-cards="item.source_cards ?? []" />
                <p class="research-feedback__time">建立于 {{ formatDate(item.created_at) }}<span v-if="item.published_at"> · 发布于 {{ formatDate(item.published_at) }}</span><span v-if="item.revoked_at"> · 撤回于 {{ formatDate(item.revoked_at) }}</span></p>
                <label v-if="item.status === 'DRAFT' && selectedCase.status === 'APPROVED'" class="research-feedback__confirm"><input v-model="confirmation" type="radio" :value="`publish:${item.feedback_ref}`" :disabled="!canMutate"><span>我确认只在当前合成演示账户中提供这条内容。</span></label>
                <AppButton v-if="item.status === 'DRAFT' && selectedCase.status === 'APPROVED'" size="sm" :disabled="!canMutate || confirmation !== `publish:${item.feedback_ref}`" @click="publish(item)">发布到演示学生账户</AppButton>
                <label v-if="item.status === 'PUBLISHED'" class="research-feedback__confirm"><input v-model="confirmation" type="radio" :value="`revoke:${item.feedback_ref}`" :disabled="!canMutate"><span>我确认撤回这条学生可见版本。</span></label>
                <AppButton v-if="item.status === 'PUBLISHED'" variant="secondary" size="sm" :disabled="!canMutate || confirmation !== `revoke:${item.feedback_ref}`" @click="revoke(item)">撤回学生可见版本</AppButton>
              </li>
            </ol>
          </section>

          <form v-if="selectedCase.status === 'APPROVED'" class="research-feedback__draft" @submit.prevent="createDraft">
            <h4>建立新的教育反馈版本</h4><p>只写一般教育支持内容，不要加入诊断、治疗、分数解释或复核备注。</p>
            <p v-if="draftCandidateRef">已关联当前记录的候选来源。请核对并修订正文，原始候选保持不变。<AppButton variant="quiet" size="sm" :disabled="!canMutate" @click="draftCandidateRef = undefined">取消来源关联</AppButton></p>
            <label for="research-feedback-title">标题</label><input id="research-feedback-title" v-model="draftTitle" maxlength="120" required :disabled="!canMutate" placeholder="输入简短标题">
            <label for="research-feedback-body">正文</label><textarea id="research-feedback-body" v-model="draftBody" maxlength="4000" rows="4" required :disabled="!canMutate" placeholder="填写供当前合成学生账户查看的教育支持内容。" />
            <div class="research-feedback__draft-footer"><small>{{ draftTitle.length }}/120 · {{ draftBody.length }}/4000</small><AppButton type="submit" size="sm" :disabled="!canMutate || !draftTitle.trim() || !draftBody.trim() || draftTitle.length > 120 || draftBody.length > 4000">建立草稿</AppButton></div>
          </form>
        </template>
      </AppCard>

      <div v-if="mutationError" class="research-feedback__error" role="alert">
        <div><strong>{{ mutationConflict ? '记录已更新' : '操作未完成' }}</strong><p>{{ mutationError }}</p></div>
        <AppButton v-if="failedRequest" size="sm" :disabled="mutationBusy" @click="retryFailedRequest">使用相同请求重试</AppButton>
        <AppButton v-else-if="mutationConflict" variant="secondary" size="sm" :disabled="mutationBusy" @click="refreshAfterConflict">重新读取记录</AppButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.research-feedback { display: grid; gap: 15px; margin-top: 24px; }
.research-feedback__toolbar,.research-feedback__panel-head,.research-feedback__detail-head,.research-feedback__versions>header,.research-feedback__version>header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.research-feedback__toolbar h2,.research-feedback__panel-head h3,.research-feedback__detail h3,.research-feedback__versions h4,.research-feedback__version h5,.research-feedback__draft h4 { margin: 4px 0; color: var(--color-text-primary); }
.research-feedback__toolbar h2 { font-family: var(--font-display); font-size: 22px; }
.research-feedback__toolbar p,.research-feedback__panel-head p,.research-feedback__detail-head p,.research-feedback__versions header p,.research-feedback__draft p,.research-feedback__detail>p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.research-feedback__kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.research-feedback__tasks { display: grid; grid-template-columns: repeat(auto-fit,minmax(210px,1fr)); gap: 9px; }
.research-feedback__task { display: grid; grid-template-columns: 28px 1fr auto; align-items: center; gap: 10px; min-height: 62px; padding: 10px 12px; border: 1px solid #e0eae5; border-radius: 10px; color: var(--color-text-primary); background: #fff; text-align: left; cursor: pointer; }
.research-feedback__task:hover:not(:disabled),.research-feedback__task--active { border-color: #75a997; background: #f2f8f5; }
.research-feedback__task:disabled { opacity: .6; cursor: not-allowed; }
.research-feedback__task-index { color: #438174; font-size: 12px; font-weight: 800; }
.research-feedback__task strong,.research-feedback__task small { display: block; }
.research-feedback__task strong { font-size: 12px; }
.research-feedback__task small { margin-top: 4px; color: var(--color-text-muted); font-size: 10px; }
.research-feedback__task svg { color: #438174; }
.research-feedback__columns { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
.research-feedback__panel,.research-feedback__detail { min-width: 0; padding: 17px; }
.research-feedback__panel-head h3,.research-feedback__detail h3 { font-size: 15px; }
.research-feedback__panel-head p { max-width: 340px; }
.research-feedback__count,.research-feedback__versions>header>span { color: var(--color-text-muted); font-size: 11px; }
.research-feedback__rows { display: grid; gap: 7px; margin-top: 12px; }
.research-feedback__row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 5px 10px; width: 100%; padding: 10px 11px; border: 1px solid #e4ece8; border-radius: 9px; color: var(--color-text-primary); background: #fff; text-align: left; cursor: pointer; }
.research-feedback__row:hover:not(:disabled),.research-feedback__row--active { border-color: #75a997; background: #f2f8f5; }
.research-feedback__row:disabled { opacity: .6; cursor: not-allowed; }
.research-feedback__row>span { font-size: 12px; font-weight: 750; }
.research-feedback__row>small { color: var(--color-text-secondary); font-size: 10px; }
.research-feedback__row>.app-badge { grid-column: 2; grid-row: 1 / span 2; }
.research-feedback__pager { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px solid #edf1ef; color: var(--color-text-muted); font-size: 10px; }
.research-feedback__pager>span:last-child { display: flex; gap: 5px; }
.research-feedback__state,.research-feedback__empty { padding: 14px 8px; color: var(--color-text-secondary); font-size: 12px; text-align: center; }
.research-feedback__detail { display: grid; gap: 14px; }
.research-feedback__detail-head { padding-bottom: 12px; border-bottom: 1px solid #e9efec; }
.research-feedback__detail-head h3 { margin: 4px 0; }
.research-feedback__boundary { padding: 10px 12px; border-radius: 8px; color: #526f64 !important; background: #eff6f2; }
.research-feedback__field { display: grid; gap: 6px; }
.research-feedback__field>span,.research-feedback__draft label { color: var(--color-text-primary); font-size: 11px; font-weight: 750; }
.research-feedback__field textarea,.research-feedback__draft textarea,.research-feedback__draft input { width: 100%; padding: 10px 11px; border: 1px solid #d7e3de; border-radius: 9px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 12px; line-height: 1.6; }
.research-feedback__field textarea { resize: vertical; }
.research-feedback__field small { justify-self: end; color: var(--color-text-muted); font-size: 10px; }
.research-feedback__field :focus-visible,.research-feedback__draft :focus-visible { outline: 3px solid rgb(67 142 123 / 20%); border-color: #438e7b; }
.research-feedback__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.research-feedback__versions { display: grid; gap: 10px; padding-top: 13px; border-top: 1px solid #e9efec; }
.research-feedback__versions h4 { font-size: 13px; }
.research-feedback__versions header p { font-size: 11px; }
.research-feedback__versions-list { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.research-feedback__version { display: grid; gap: 9px; padding: 12px; border: 1px solid #e4ece8; border-radius: 9px; background: #fff; }
.research-feedback__version h5 { font-size: 12px; }
.research-feedback__version small,.research-feedback__time,.research-feedback__draft-footer small { color: var(--color-text-muted); font-size: 10px; }
.research-feedback__body { margin: 0; color: var(--color-text-primary); font-size: 12px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.research-feedback__time { margin: 0; }
.research-feedback__confirm { display: flex; align-items: flex-start; gap: 7px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.research-feedback__confirm input { margin-top: 2px; accent-color: #438e7b; }
.research-feedback__draft { display: grid; gap: 8px; padding-top: 13px; border-top: 1px solid #e9efec; }
.research-feedback__draft h4 { font-size: 13px; }
.research-feedback__draft p { margin: 0 0 3px; font-size: 11px; }
.research-feedback__draft textarea { resize: vertical; }
.research-feedback__draft-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.research-feedback__error,.research-feedback__notice { padding: 10px 12px; border: 1px solid #ecd8d0; border-radius: 9px; color: #785449; background: #fff8f5; font-size: 12px; line-height: 1.55; }
.research-feedback__error { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.research-feedback__error p { margin: 4px 0 0; }
.research-feedback__notice { border-color: #e9dfc9; color: #6b5637; background: #fbf8ef; }
@media(max-width:760px) { .research-feedback__columns { grid-template-columns: 1fr; }.research-feedback__toolbar,.research-feedback__detail-head { align-items: flex-start; flex-direction: column; }.research-feedback__error { align-items: flex-start; flex-direction: column; } }
</style>
