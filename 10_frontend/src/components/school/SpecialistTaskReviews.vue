<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RotateCcw, ClipboardCheck, ChevronLeft, ChevronRight, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import SpecialistFeedbackPanel from '@/components/school/SpecialistFeedbackPanel.vue'
import {
  newProfessionalReviewIdempotencyKey,
  professionalReviews,
  type EligibleEnrollment,
  type ProfessionalReviewCase,
  type ProfessionalReviewTask,
} from '@/services/professional-reviews'

const pageSize = 10
const tasks = ref<ProfessionalReviewTask[]>([])
const tasksState = ref<'loading' | 'ready' | 'error'>('loading')
const tasksError = ref('')
const selectedTaskRef = ref('')
const enrollments = ref<EligibleEnrollment[]>([])
const enrollmentTotal = ref(0)
const enrollmentOffset = ref(0)
const enrollmentsState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const enrollmentsError = ref('')
const cases = ref<ProfessionalReviewCase[]>([])
const caseTotal = ref(0)
const caseOffset = ref(0)
const casesState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const casesError = ref('')
const selectedEnrollmentRef = ref('')
const selectedCase = ref<ProfessionalReviewCase | null>(null)
const detailState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const detailError = ref('')
const decisionNote = ref('')
const mutationBusy = ref(false)
const mutationError = ref('')
const mutationConflict = ref(false)
const failedRequest = ref<{ label: string; run: () => Promise<ProfessionalReviewCase> } | null>(null)
const accessMessage = ref('')

let tasksSequence = 0
let taskDataSequence = 0
let detailSequence = 0

const selectedTask = computed(() => tasks.value.find((task) => task.task_ref === selectedTaskRef.value) ?? null)
const selectedTaskLabel = computed(() => {
  if (!selectedTask.value) return ''
  return selectedTask.value.class_display_name || `任务 ${String(tasks.value.indexOf(selectedTask.value) + 1).padStart(2, '0')}`
})
const currentEnrollment = computed(() => enrollments.value.find((item) => item.enrollment_ref === selectedEnrollmentRef.value) ?? null)
const canWrite = computed(() => !mutationBusy.value && !failedRequest.value && Boolean(selectedTaskRef.value))
const enrollmentHasMore = computed(() => enrollmentOffset.value + enrollments.value.length < enrollmentTotal.value)
const caseHasMore = computed(() => caseOffset.value + cases.value.length < caseTotal.value)
const terminalCase = computed(() => selectedCase.value?.status === 'APPROVED' || selectedCase.value?.status === 'REJECTED')

const safeError = (error: unknown, fallback: string) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  const retryable = Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable)
  return {
    message: error instanceof Error ? error.message : fallback,
    conflict: code === 'WORKFLOW_CONFLICT' || code === 'IDEMPOTENCY_CONFLICT',
    accessLost: code === 'FORBIDDEN' || code === 'RESOURCE_NOT_FOUND'
      || code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED',
    retryable,
  }
}

function clearPrivateState() {
  selectedTaskRef.value = ''
  selectedEnrollmentRef.value = ''
  enrollments.value = []
  enrollmentTotal.value = 0
  enrollmentOffset.value = 0
  cases.value = []
  caseTotal.value = 0
  caseOffset.value = 0
  selectedCase.value = null
  decisionNote.value = ''
  detailError.value = ''
  detailState.value = 'idle'
  failedRequest.value = null
  ++taskDataSequence
  ++detailSequence
}

const formatDate = (value: string) => {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间待确认'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }).format(parsed)
}

const statusLabel = (status: ProfessionalReviewCase['status']) => ({
  OPEN: '待开始', IN_REVIEW: '处理中', APPROVED: '已完成', REJECTED: '已退回',
}[status])

async function loadTasks() {
  const sequence = ++tasksSequence
  tasksState.value = 'loading'
  tasksError.value = ''
  try {
    const result = await professionalReviews.listTasks()
    if (sequence !== tasksSequence) return
    tasks.value = result
    tasksState.value = 'ready'
    if (selectedTaskRef.value && !result.some((item) => item.task_ref === selectedTaskRef.value)) {
      clearPrivateState()
      accessMessage.value = '任务访问状态已变化，已清除本页缓存。请确认当前指派后重新选择任务。'
    }
  } catch (error) {
    if (sequence !== tasksSequence) return
    const classified = safeError(error, '工作事项暂时无法加载。')
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '当前访问状态已变化，已清除本页缓存。请重新登录或确认当前指派。'
    }
    tasksError.value = classified.message
    tasksState.value = 'error'
  }
}

async function loadTaskData(options: { enrollmentOffset?: number; caseOffset?: number } = {}) {
  const taskRef = selectedTaskRef.value
  if (!taskRef) return
  const sequence = ++taskDataSequence
  if (options.enrollmentOffset !== undefined) enrollmentOffset.value = options.enrollmentOffset
  if (options.caseOffset !== undefined) caseOffset.value = options.caseOffset
  enrollmentsState.value = 'loading'
  casesState.value = 'loading'
  enrollmentsError.value = ''
  casesError.value = ''
  try {
    const [enrollmentPage, casePage] = await Promise.all([
      professionalReviews.listEligibleEnrollments(taskRef, enrollmentOffset.value, pageSize),
      professionalReviews.listCases(taskRef, caseOffset.value, pageSize),
    ])
    if (sequence !== taskDataSequence || taskRef !== selectedTaskRef.value) return
    enrollments.value = enrollmentPage.items
    enrollmentTotal.value = enrollmentPage.total
    cases.value = casePage.items
    caseTotal.value = casePage.total
    enrollmentsState.value = 'ready'
    casesState.value = 'ready'
    accessMessage.value = ''
    if (selectedEnrollmentRef.value && !enrollmentPage.items.some((item) => item.enrollment_ref === selectedEnrollmentRef.value)) {
      selectedEnrollmentRef.value = ''
      selectedCase.value = null
      detailState.value = 'idle'
    }
    if (selectedCase.value && !casePage.items.some((item) => item.case_ref === selectedCase.value?.case_ref)) {
      // Preserve the open detail across pagination; it remains bound to this task.
    }
  } catch (error) {
    if (sequence !== taskDataSequence || taskRef !== selectedTaskRef.value) return
    const classified = safeError(error, '工作记录暂时无法加载。')
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '任务访问状态已变化，已清除本页缓存。请刷新任务列表确认当前指派。'
      enrollmentsState.value = 'idle'
      casesState.value = 'idle'
      return
    }
    enrollmentsError.value = classified.message
    casesError.value = classified.message
    enrollmentsState.value = 'error'
    casesState.value = 'error'
  }
}

async function selectTask(taskRef: string) {
  if (mutationBusy.value || failedRequest.value || taskRef === selectedTaskRef.value) return
  accessMessage.value = ''
  selectedTaskRef.value = taskRef
  selectedEnrollmentRef.value = ''
  selectedCase.value = null
  decisionNote.value = ''
  detailState.value = 'idle'
  enrollmentOffset.value = 0
  caseOffset.value = 0
  ++detailSequence
  await loadTaskData()
}

async function selectEnrollment(enrollment: EligibleEnrollment) {
  if (mutationBusy.value || failedRequest.value) return
  selectedEnrollmentRef.value = enrollment.enrollment_ref
  decisionNote.value = ''
  if (!enrollment.case_ref) {
    selectedCase.value = null
    detailState.value = 'idle'
    return
  }
  await loadCase(enrollment.case_ref)
}

async function loadCase(caseRef: string) {
  const taskRef = selectedTaskRef.value
  if (!taskRef) return
  const sequence = ++detailSequence
  detailState.value = 'loading'
  detailError.value = ''
  try {
    const result = await professionalReviews.getCase(taskRef, caseRef)
    if (sequence !== detailSequence || taskRef !== selectedTaskRef.value) return
    selectedCase.value = result
    decisionNote.value = result.review_note ?? ''
    detailState.value = 'ready'
  } catch (error) {
    if (sequence !== detailSequence || taskRef !== selectedTaskRef.value) return
    detailError.value = safeError(error, '复核记录暂时无法加载。').message
    const classified = safeError(error, '复核记录暂时无法加载。')
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '任务访问状态已变化，已清除本页缓存。请刷新任务列表确认当前指派。'
      return
    }
    selectedCase.value = null
    decisionNote.value = ''
    detailState.value = 'error'
  }
}

async function chooseCase(item: ProfessionalReviewCase) {
  if (mutationBusy.value || failedRequest.value) return
  selectedEnrollmentRef.value = item.enrollment_ref
  await loadCase(item.case_ref)
}

async function runMutation(label: string, run: () => Promise<ProfessionalReviewCase>) {
  if (mutationBusy.value || (failedRequest.value && failedRequest.value.run !== run)) return
  const taskRef = selectedTaskRef.value
  const sequence = detailSequence
  mutationBusy.value = true
  mutationError.value = ''
  mutationConflict.value = false
  try {
    const result = await run()
    if (taskRef !== selectedTaskRef.value || sequence !== detailSequence) return
    failedRequest.value = null
    selectedCase.value = result
    decisionNote.value = result.review_note ?? ''
    detailState.value = 'ready'
    await loadTaskData()
  } catch (error) {
    const classified = safeError(error, `${label}没有完成。`)
    mutationError.value = classified.message
    mutationConflict.value = classified.conflict
    if (classified.accessLost) {
      clearPrivateState()
      accessMessage.value = '任务访问状态已变化，已清除本页缓存。请刷新任务列表确认当前指派。'
    } else {
      failedRequest.value = classified.retryable ? { label, run } : null
    }
  } finally {
    mutationBusy.value = false
  }
}

function createCase() {
  const taskRef = selectedTaskRef.value
  const enrollmentRef = currentEnrollment.value?.enrollment_ref
  if (!taskRef || !enrollmentRef || !canWrite.value) return
  const key = newProfessionalReviewIdempotencyKey()
  void runMutation('建立复核记录', () => professionalReviews.createCase(taskRef, enrollmentRef, key))
}

function openCase() {
  const taskRef = selectedTaskRef.value
  const reviewCase = selectedCase.value
  if (!taskRef || !reviewCase || !canWrite.value) return
  const expectedVersion = reviewCase.version
  const key = newProfessionalReviewIdempotencyKey()
  void runMutation('开始处理', () => professionalReviews.openCase(taskRef, reviewCase.case_ref, expectedVersion, key))
}

function decide(decision: 'APPROVED' | 'REJECTED') {
  const taskRef = selectedTaskRef.value
  const reviewCase = selectedCase.value
  const note = decisionNote.value.trim()
  if (!taskRef || !reviewCase || !note || !canWrite.value || terminalCase.value) return
  const expectedVersion = reviewCase.version
  const key = newProfessionalReviewIdempotencyKey()
  void runMutation(decision === 'APPROVED' ? '确认完成' : '退回记录', () =>
    professionalReviews.decideCase(taskRef, reviewCase.case_ref, expectedVersion, decision, note, key))
}

function retryFailedRequest() {
  const failed = failedRequest.value
  if (!failed || mutationBusy.value) return
  void runMutation(failed.label, failed.run)
}

async function refreshCaseAfterConflict() {
  if (mutationBusy.value || !selectedCase.value) return
  failedRequest.value = null
  const caseRef = selectedCase.value.case_ref
  await loadCase(caseRef)
  if (detailState.value === 'ready') mutationError.value = ''
  await loadTaskData()
  mutationConflict.value = false
}

onMounted(() => { void loadTasks() })
</script>

<template>
  <section class="professional-reviews" aria-label="任务专业复核">
    <AppStatusCallout tone="info" title="合成演示 · 工作流记录" body="此处只处理已指派任务中的完成记录。决定用于演示任务工作流，不构成心理学结论，也不会发布学生报告。" />

    <div class="reviews-toolbar">
      <div><span class="reviews-kicker">任务范围</span><h2>已指派的工作事项</h2><p>选择任务后查看可处理的完成记录与已有复核记录。</p></div>
      <button class="reviews-button reviews-button--quiet" type="button" :disabled="tasksState === 'loading' || mutationBusy" @click="loadTasks"><RotateCcw :size="15" aria-hidden="true" />刷新任务</button>
    </div>
    <p v-if="accessMessage" class="access-message" role="status">{{ accessMessage }}</p>
    <p v-if="tasksState === 'loading'" class="reviews-state" role="status" aria-busy="true">正在读取已指派任务…</p>
    <div v-else-if="tasksState === 'error'" class="reviews-error" role="alert"><span>{{ tasksError }}</span><button type="button" @click="loadTasks">重新加载</button></div>
    <p v-else-if="!tasks.length" class="reviews-empty">当前没有可显示的已指派任务。</p>
    <div v-else class="task-list" aria-label="已指派任务">
      <button v-for="(task, index) in tasks" :key="task.task_ref" class="task-option" :class="{ 'task-option--active': selectedTaskRef === task.task_ref }" type="button" :aria-pressed="selectedTaskRef === task.task_ref" :disabled="mutationBusy || Boolean(failedRequest)" @click="selectTask(task.task_ref)">
        <span class="task-option__number">{{ String(index + 1).padStart(2, '0') }}</span>
        <span class="task-option__copy"><strong>{{ task.class_display_name || `任务 ${String(index + 1).padStart(2, '0')}` }}</strong><small>已发布 · {{ formatDate(task.published_at) }}</small></span>
        <ClipboardCheck :size="17" aria-hidden="true" />
      </button>
    </div>

    <template v-if="selectedTask">
      <div class="review-columns">
        <AppCard class="review-panel">
          <header class="review-panel__header"><div><span class="reviews-kicker">{{ selectedTaskLabel }}</span><h3>已完成记录</h3><p>仅显示完成时间与列表顺序，不展示身份或技术编号。</p></div><button class="reviews-icon-button" type="button" aria-label="刷新完成记录和复核列表" :disabled="enrollmentsState === 'loading' || casesState === 'loading' || mutationBusy" @click="loadTaskData"><RotateCcw :size="16" aria-hidden="true" /></button></header>
          <p v-if="enrollmentsState === 'loading'" class="reviews-state" role="status" aria-busy="true">正在读取完成记录…</p>
          <div v-else-if="enrollmentsState === 'error'" class="reviews-error" role="alert"><span>{{ enrollmentsError }}</span><button type="button" @click="loadTaskData">重新加载</button></div>
          <p v-else-if="!enrollments.length" class="reviews-empty">此任务当前没有可处理的完成记录。</p>
          <div v-else class="record-list">
            <button v-for="(enrollment, index) in enrollments" :key="enrollment.enrollment_ref" class="record-option" :class="{ 'record-option--active': selectedEnrollmentRef === enrollment.enrollment_ref }" type="button" :aria-pressed="selectedEnrollmentRef === enrollment.enrollment_ref" :disabled="mutationBusy || Boolean(failedRequest)" @click="selectEnrollment(enrollment)">
              <span class="record-option__number">记录 {{ enrollmentOffset + index + 1 }}</span><span class="record-option__date">{{ formatDate(enrollment.completed_at) }}</span>
              <span v-if="enrollment.case_ref" class="record-option__tag">已有记录</span><span v-else class="record-option__tag record-option__tag--new">可建立</span>
            </button>
          </div>
          <footer class="pager"><span>{{ enrollmentTotal ? `${enrollmentOffset + 1}–${enrollmentOffset + enrollments.length} / ${enrollmentTotal}` : '0 条记录' }}</span><div><button class="reviews-icon-button" type="button" aria-label="上一页完成记录" :disabled="enrollmentsState === 'loading' || mutationBusy || enrollmentOffset === 0" @click="loadTaskData({ enrollmentOffset: Math.max(0, enrollmentOffset - pageSize) })"><ChevronLeft :size="16" aria-hidden="true" /></button><button class="reviews-icon-button" type="button" aria-label="下一页完成记录" :disabled="enrollmentsState === 'loading' || mutationBusy || !enrollmentHasMore" @click="loadTaskData({ enrollmentOffset: enrollmentOffset + pageSize })"><ChevronRight :size="16" aria-hidden="true" /></button></div></footer>
        </AppCard>

        <AppCard class="review-panel">
          <header class="review-panel__header"><div><span class="reviews-kicker">可追溯工作流</span><h3>复核记录</h3><p>打开记录后可更新流程状态并留下合成演示备注。</p></div><ShieldCheck :size="20" class="review-panel__icon" aria-hidden="true" /></header>
          <p v-if="casesState === 'loading'" class="reviews-state" role="status" aria-busy="true">正在读取复核记录…</p>
          <div v-else-if="casesState === 'error'" class="reviews-error" role="alert"><span>{{ casesError }}</span><button type="button" @click="loadTaskData">重新加载</button></div>
          <p v-else-if="!cases.length" class="reviews-empty">此任务尚无复核记录。</p>
          <div v-else class="case-list" aria-label="已有复核记录">
            <button v-for="(item, index) in cases" :key="item.case_ref" class="case-option" :class="{ 'case-option--active': selectedCase?.case_ref === item.case_ref }" type="button" :aria-pressed="selectedCase?.case_ref === item.case_ref" :disabled="mutationBusy || Boolean(failedRequest)" @click="chooseCase(item)"><span>记录 {{ caseOffset + index + 1 }}</span><strong>{{ statusLabel(item.status) }}</strong><small>{{ formatDate(item.updated_at) }}</small></button>
          </div>
          <footer class="pager"><span>{{ caseTotal ? `${caseOffset + 1}–${caseOffset + cases.length} / ${caseTotal}` : '0 条记录' }}</span><div><button class="reviews-icon-button" type="button" aria-label="上一页复核记录" :disabled="casesState === 'loading' || mutationBusy || caseOffset === 0" @click="loadTaskData({ caseOffset: Math.max(0, caseOffset - pageSize) })"><ChevronLeft :size="16" aria-hidden="true" /></button><button class="reviews-icon-button" type="button" aria-label="下一页复核记录" :disabled="casesState === 'loading' || mutationBusy || !caseHasMore" @click="loadTaskData({ caseOffset: caseOffset + pageSize })"><ChevronRight :size="16" aria-hidden="true" /></button></div></footer>
        </AppCard>
      </div>

      <AppCard v-if="currentEnrollment" class="case-workspace">
        <div class="case-workspace__top"><div><span class="reviews-kicker">记录 {{ enrollments.findIndex((item) => item.enrollment_ref === currentEnrollment.enrollment_ref) + enrollmentOffset + 1 }}</span><h3>处理任务工作流</h3><p>完成时间：{{ formatDate(currentEnrollment.completed_at) }}</p></div><span v-if="selectedCase" class="status-pill" :class="`status-pill--${selectedCase.status.toLowerCase()}`">{{ statusLabel(selectedCase.status) }}</span></div>
        <p v-if="detailState === 'loading'" class="reviews-state" role="status" aria-busy="true">正在读取复核记录…</p>
        <div v-else-if="detailState === 'error'" class="reviews-error" role="alert"><span>{{ detailError }}</span><button type="button" @click="currentEnrollment.case_ref && loadCase(currentEnrollment.case_ref)">重新加载</button></div>
        <div v-else-if="!selectedCase && !currentEnrollment.case_ref" class="case-create"><p>这条完成记录还没有复核记录。</p><button class="reviews-button reviews-button--primary" type="button" :disabled="!canWrite" @click="createCase">建立复核记录</button></div>
        <div v-else-if="selectedCase" class="case-detail">
          <p class="publication-note">复核决定不会自动发布；学生反馈需在下方单独发布。</p>
          <p v-if="selectedCase.status === 'OPEN'" class="case-help">先开始处理，再记录本次工作流决定。</p>
          <button v-if="selectedCase.status === 'OPEN'" class="reviews-button reviews-button--primary" type="button" :disabled="!canWrite" @click="openCase">开始处理</button>
          <template v-else-if="!terminalCase">
            <label class="note-field" for="professional-review-note"><span>本次工作流备注</span><textarea id="professional-review-note" v-model="decisionNote" rows="4" maxlength="2000" :disabled="!canWrite" placeholder="仅填写合成演示备注；不要写姓名、联系方式或原始作答。" /><small>{{ decisionNote.length }} / 2000</small></label>
            <div class="decision-actions"><button class="reviews-button reviews-button--primary" type="button" :disabled="!canWrite || !decisionNote.trim()" @click="decide('APPROVED')">确认完成</button><button class="reviews-button reviews-button--secondary" type="button" :disabled="!canWrite || !decisionNote.trim()" @click="decide('REJECTED')">退回记录</button></div>
          </template>
          <div v-else class="terminal-summary"><strong>{{ selectedCase.status === 'APPROVED' ? '工作流已完成' : '记录已退回' }}</strong><p>{{ selectedCase.review_note || '此记录已完成状态流转。' }}</p></div>
        </div>
      </AppCard>
      <SpecialistFeedbackPanel
        v-if="selectedCase && detailState === 'ready'"
        :case-ref="selectedCase.case_ref"
        :case-version="selectedCase.version"
        :case-status="selectedCase.status"
      />
    </template>

    <div v-if="mutationError" class="mutation-error" role="alert">
      <div><strong>{{ mutationConflict ? '记录状态已变化' : '本次操作未完成' }}</strong><p>{{ mutationError }}</p><p v-if="mutationConflict">请先刷新并核对服务端最新状态，再决定是否重新操作。</p></div>
      <button v-if="mutationConflict" class="reviews-button reviews-button--quiet" type="button" :disabled="mutationBusy" @click="refreshCaseAfterConflict">刷新服务端状态</button>
    </div>
    <div v-if="failedRequest" class="retry-strip" role="status">
      <span>“{{ failedRequest.label }}”结果未确认。重试会沿用原请求内容和标识；请勿重复提交另一条操作。</span>
      <button class="reviews-button reviews-button--primary" type="button" :disabled="mutationBusy" @click="retryFailedRequest">{{ mutationBusy ? '正在重试…' : '使用相同请求重试' }}</button>
    </div>
  </section>
</template>

<style scoped>
.professional-reviews { display: grid; gap: 18px; color: var(--color-text-primary); }
.reviews-toolbar,.review-panel__header,.case-workspace__top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.reviews-toolbar { align-items: end; padding: 3px 2px 0; }.reviews-kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .09em; text-transform: uppercase; }
.reviews-toolbar h2,.review-panel h3,.case-workspace h3 { margin: 5px 0; font-size: 18px; letter-spacing: -.02em; }.reviews-toolbar p,.review-panel__header p,.case-workspace__top p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.task-list { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,260px),1fr)); gap: 10px; }
.task-option { display: flex; align-items: center; gap: 12px; min-height: 72px; padding: 13px 15px; border: 1px solid #dce9e4; border-radius: 13px; color: #3b554d; background: #fff; text-align: left; cursor: pointer; transition: border-color .16s,background .16s,transform .16s; }
.task-option:hover:not(:disabled) { border-color: #84b6a6; transform: translateY(-1px); }.task-option--active { border-color: #438e7b; background: #edf6f2; box-shadow: inset 3px 0 #438e7b; }.task-option:disabled { opacity: .62; cursor: not-allowed; }
.task-option__number { display: grid; width: 32px; height: 32px; flex: 0 0 32px; place-items: center; border-radius: 10px; color: #438174; background: #e8f4ef; font-size: 11px; font-weight: 800; }.task-option__copy { display: grid; flex: 1; gap: 4px; }.task-option__copy strong { font-size: 13px; }.task-option__copy small { color: var(--color-text-muted); font-size: 11px; }
.review-columns { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }.review-panel { min-width: 0; padding: 18px; }.review-panel__header { min-height: 66px; }.review-panel__header h3 { font-size: 15px; }.review-panel__header p { max-width: 390px; }.review-panel__icon { color: #438174; }
.record-list,.case-list { display: grid; gap: 7px; margin-top: 12px; }.record-option,.case-option { width: 100%; border: 1px solid #e4ece8; border-radius: 10px; color: var(--color-text-primary); background: #fff; cursor: pointer; text-align: left; }.record-option { display: grid; grid-template-columns: 1fr auto; gap: 4px 8px; padding: 10px 11px; }.record-option:hover:not(:disabled),.case-option:hover:not(:disabled) { border-color: #83b3a4; }.record-option--active,.case-option--active { border-color: #438e7b; background: #f0f7f4; }.record-option:disabled,.case-option:disabled { opacity: .62; cursor: not-allowed; }.record-option__number { font-size: 12px; font-weight: 750; }.record-option__date { color: var(--color-text-secondary); font-size: 11px; }.record-option__tag { grid-column: 2; grid-row: 1 / span 2; align-self: center; color: #867348; font-size: 10px; }.record-option__tag--new { color: #388576; }
.case-option { display: grid; grid-template-columns: 1fr auto; gap: 4px 8px; padding: 10px 11px; }.case-option span { color: var(--color-text-muted); font-size: 10px; }.case-option strong { grid-column: 2; grid-row: 1 / span 2; align-self: center; color: #438174; font-size: 11px; }.case-option small { color: var(--color-text-secondary); font-size: 11px; }
.pager { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 13px; padding-top: 11px; border-top: 1px solid #edf1ef; color: var(--color-text-muted); font-size: 10px; }.pager > div { display: flex; gap: 4px; }
.case-workspace { padding: 20px; }.case-workspace__top { align-items: center; padding-bottom: 14px; border-bottom: 1px solid #e9efec; }.case-workspace__top h3 { margin: 5px 0 3px; }.status-pill { padding: 6px 9px; border-radius: 999px; color: #517768; background: #eaf3ee; font-size: 10px; font-weight: 750; white-space: nowrap; }.status-pill--rejected { color: #8b5d38; background: #f8eee4; }.status-pill--approved { color: #33715f; background: #e4f3ec; }
.case-create,.case-detail { display: grid; gap: 13px; padding-top: 14px; }.case-create p,.case-help,.publication-note,.terminal-summary p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }.publication-note { padding: 9px 11px; border-radius: 9px; color: #526f64; background: #eff6f2; }.note-field { display: grid; gap: 7px; }.note-field span { font-size: 12px; font-weight: 750; }.note-field textarea { width: 100%; min-height: 106px; resize: vertical; padding: 11px 12px; border: 1px solid #d7e3de; border-radius: 10px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 12px; line-height: 1.6; }.note-field textarea:focus-visible { outline: 3px solid rgb(67 142 123 / 20%); border-color: #438e7b; }.note-field textarea:disabled { background: #f5f7f6; }.note-field small { justify-self: end; color: var(--color-text-muted); font-size: 10px; }.decision-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.reviews-button,.reviews-icon-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 36px; padding: 8px 12px; border: 1px solid transparent; border-radius: 9px; font: inherit; font-size: 11px; font-weight: 750; cursor: pointer; }.reviews-button:disabled,.reviews-icon-button:disabled { opacity: .48; cursor: not-allowed; }.reviews-button--primary { color: #fff; background: #357c6b; }.reviews-button--primary:hover:not(:disabled) { background: #286b5a; }.reviews-button--secondary { color: #6e5944; border-color: #e8d9c8; background: #fbf5ed; }.reviews-button--quiet { color: #4c6c61; border-color: #dce8e3; background: #fff; }.reviews-button--quiet:hover:not(:disabled) { background: #f3f8f5; }.reviews-icon-button { width: 31px; min-height: 30px; padding: 5px; color: #58756a; border-color: #e1eae5; background: #fff; }
.terminal-summary { padding: 12px; border: 1px solid #dce9e2; border-radius: 10px; background: #f5f9f6; }.terminal-summary strong { display: block; margin-bottom: 5px; color: #357c6b; font-size: 12px; }.reviews-state,.reviews-empty { padding: 16px 10px; color: var(--color-text-secondary); font-size: 12px; text-align: center; }.access-message { margin: 0; padding: 10px 12px; border: 1px solid #e9dfc9; border-radius: 10px; color: #6b5637; background: #fbf8ef; font-size: 12px; line-height: 1.6; }.reviews-error,.mutation-error,.retry-strip { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border: 1px solid #ecd8d0; border-radius: 11px; color: #785449; background: #fff8f5; font-size: 12px; }.reviews-error button { color: #347969; border: 0; background: transparent; font: inherit; font-weight: 750; cursor: pointer; }.mutation-error p { margin: 4px 0 0; line-height: 1.55; }.mutation-error strong { color: #754b3f; }.retry-strip { align-items: center; color: #6b5637; border-color: #e9dfc9; background: #fbf8ef; }.retry-strip span { line-height: 1.6; }
@media(max-width:760px) { .reviews-toolbar { align-items: flex-start; }.review-columns { grid-template-columns: 1fr; }.review-panel,.case-workspace { padding: 15px; }.retry-strip,.mutation-error { align-items: flex-start; flex-direction: column; }.task-list { grid-template-columns: 1fr; } }
@media(prefers-reduced-motion:reduce) { .task-option { transition: none; } }
</style>
