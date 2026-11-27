<script setup lang="ts">
/* global AbortController, Blob, URL, File */
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Check, RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import WorkspaceAnswer from './WorkspaceAnswer.vue'
import WorkspaceCatDraft from './WorkspaceCatDraft.vue'
import { frontendApi } from '@/services/mock-api'
import { RealApiError } from '@/services/real-api'
import { supportCaseStates, supportCategories, type TeacherReferral } from '@/services/school-support'
import { articlesForTopics } from '@/services/student-education'
import type { RosterAttachment } from '@/services/school-roster-file'
import {
  auditActionLabel, auditCategoryLabel, auditResultLabel, dependencyNames, dependencyStatusLabels,
} from '@/services/school-operations-display'
import type { WorkspaceTableSummary } from '@/services/workspace-table'
import {
  cancelWorkspaceTurn, confirmWorkspacePublication, loadWorkspaceConversation, resetWorkspaceConversation,
  previewWorkspaceCatHandoff, runWorkspaceAgent, sendWorkspaceTurn, updateWorkspaceCat,
  uploadWorkspaceCat, type CatDraft, type TaskPublicationPreview, type WorkflowPanel, type WorkspaceEvent,
} from '@/services/workspace-agent'

const props = defineProps<{
  roster?: RosterAttachment
  catFile?: File
  catCsvConfirmed?: boolean
  tableSummary?: WorkspaceTableSummary
  role: 'student' | 'teacher' | 'psychological_specialist' | 'school_admin'
  scope: string
}>()
const emit = defineEmits<{ busy: [value: boolean]; support: []; changed: [] }>()
const Assessment = defineAsyncComponent(() => import('@/views/student/AssessmentView.vue'))
const Roster = defineAsyncComponent(() => import('@/views/admin/AccountLifecycleWorkspace.vue'))
type RosterPanel = 'roster' | 'staff'
const panels = {
  review: defineAsyncComponent(() => import('@/components/school/SpecialistTaskReviews.vue')),
  cat: defineAsyncComponent(() => import('@/components/school/SpecialistCatWorkspace.vue')),
  resources: defineAsyncComponent(() => import('@/components/school/SchoolResearchSourceCatalog.vue')),
  library: defineAsyncComponent(() => import('@/components/school/SchoolResearchLibrary.vue')),
  support: defineAsyncComponent(() => import('@/views/school/SchoolSupportView.vue')),
  knowledge: defineAsyncComponent(() => import('@/views/student/StudentKnowledgeView.vue')),
  feedback: defineAsyncComponent(() => import('@/views/student/StudentFeedbackView.vue')),
  publish: defineAsyncComponent(() => import('@/components/school/AdminTaskDispatch.vue')),
  system: defineAsyncComponent(() => import('@/components/admin/AdminSystemHealth.vue')),
}
const panelLabels = {
  review: '专业复核', cat: 'CAT 题库与方案', resources: '专业资料', library: '本校资料库', support: '学校支持',
  knowledge: '心理知识', feedback: '测评反馈', roster: '学生名单导入', staff: '教职工名单导入',
  publish: '测评发布', system: '系统状态',
}
const headings = {
  student_tasks: '我的测评任务', class_progress: '授权班级测评进度',
  review_tasks: '可复核测评', school_tasks: '学校测评任务', school_student_counts: '学生账号和分班人数',
}
const operationsTime = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'short', timeStyle: 'medium', timeZone: 'Asia/Shanghai', hour12: false,
})
const statuses: Record<string, string> = {
  not_started: '待开始', created: '待继续', in_progress: '进行中', completed: '已完成',
  abandoned: '已结束', invalid: '已失效', PUBLISHED: '已发布', CLOSED: '已关闭', REVOKED: '已撤回',
}
const progressLabels = { screening: '正在检查输入', model: '正在处理任务', checking_response: '正在核对回复' }
const finishLabels = {
  failed: '处理遇到故障，你可以重试',
  interrupted: '本次运行已中断，可继续发送需求',
  step_limit: '本次运行已达到步骤上限，可继续补充需求',
}
const events = ref<WorkspaceEvent[]>([])
const timeline = computed(() => events.value.filter((event) => !['start', 'status', 'tool_started'].includes(event.type)
  && (event.type !== 'end' || event.status in finishLabels)))
const sending = ref(false)
const activeRun = ref<string>()
const stopping = ref(false)
const scopeBlocked = ref(false)
const running = computed(() => sending.value || Boolean(activeRun.value))
const progress = ref('')
const message = ref('')
const consent = ref(false)
const consentOpen = ref(false)
const panel = ref<WorkflowPanel | RosterPanel>()
const rosterWorkbench = ref<{ busy: boolean }>()
const feedbackRef = ref<string>()
const feedbackTaskRef = ref<string>()
const prepareSupportPlan = ref(false)
const reviewTaskRef = ref<string>()
const libraryFile = ref<File>()
const libraryImport = ref(false)
const libraryQuery = ref('')
const schoolLibrary = ref<{ search: (query: string) => Promise<void> }>()
const referral = ref<{ key: string; draft: TeacherReferral }>()
const assessmentTask = ref('')
const assessmentId = ref('')
const assessmentChecking = ref(false)
const assessmentStarting = ref(false)
const assessmentComplete = ref(false)
const pendingClass = ref<{ class_ref: string; token: string }>()
const submittedClasses = ref(new Set<string>())
const classBusy = ref(false)
const pendingPublication = ref<TaskPublicationPreview & { catDraft?: CatDraft }>()
const publicationBusy = ref(false)
const publishedTokens = ref(new Set<string>())
const catReceipts = ref(new Map<string, CatDraft>())
const pendingCat = ref<{ draft: CatDraft; action: 'save' | 'approve' }>()
const catBusy = ref(false)
const lastText = ref('')
const lastSentRun = ref('')
const failedRun = computed(() => {
  const event = events.value.at(-1)
  return event?.type === 'end' && ['failed', 'interrupted'].includes(event.status) ? event.run_id : undefined
})
const retryNeedsAttachment = computed(() => Boolean(failedRun.value && events.value.some((event) =>
  event.run_id === failedRun.value && event.type === 'start' && event.requires_attachment)))
const retryText = computed(() => {
  if (!failedRun.value || retryNeedsAttachment.value) return ''
  if (failedRun.value === lastSentRun.value) return lastText.value
  const user = events.value.findLast((event) => event.run_id === failedRun.value && event.type === 'user')
  return user?.type === 'user' ? user.text : ''
})
const viewport = ref<HTMLElement>()
let runRequest: AbortController | undefined
const historyRequest = new AbortController()
let pollTimer: number | undefined
let refreshSequence = 0
let historyVersion: string | undefined
let awaitingStart = false
let disposed = false
let consentDecision: ((accepted: boolean) => void) | undefined
let initialHistory: Promise<void> | undefined
let uploadedCat: { file: File; ref: string } | undefined

const audience = computed(() => props.role === 'psychological_specialist' ? 'specialist' : props.role)
const latestPanel = computed(() => panel.value && panel.value !== 'roster' && panel.value !== 'staff'
  ? panels[panel.value] : undefined)
watch(() => props.roster, (roster) => {
  if (roster?.kind === 'student_roster') openPanel('roster')
})
watch(() => props.catFile, (file) => {
  uploadedCat = undefined
  if (file && /\.csv$/i.test(file.name)) panel.value = 'cat'
})

function showProgress(event: WorkspaceEvent) {
  if (event.type === 'status') progress.value = progressLabels[event.status]
  if (event.type === 'tool_started') progress.value = event.label
}

function historyFailure(cause: unknown, fallback: string) {
  if (disposed) return
  const code = cause instanceof RealApiError ? cause.code.toLowerCase() : ''
  if (['auth_session_expired', 'auth_session_revoked', 'forbidden'].includes(code)) {
    scopeBlocked.value = true
    events.value = []
    activeRun.value = undefined
    stopping.value = false
    lastText.value = lastSentRun.value = ''
    panel.value = undefined
    assessmentTask.value = assessmentId.value = ''
    message.value = '工作区访问已变化，请重新登录或切换到当前角色'
    return
  }
  message.value = fallback
}

async function refresh(incremental = false) {
  const sequence = ++refreshSequence
  const previous = await loadWorkspaceConversation(historyRequest.signal, incremental ? historyVersion : undefined)
  if (disposed || sequence !== refreshSequence) return
  const { user_id, school_ref, role } = previous.scope
  if (JSON.stringify([user_id, school_ref, role === 'ADMIN' ? 'school_admin' : role.toLowerCase()]) !== props.scope) {
    throw new RealApiError('forbidden', '当前会话与工作区不一致')
  }
  scopeBlocked.value = false
  historyVersion = previous.revision
  if (previous.events) events.value = previous.events
  activeRun.value = previous.active_run_id ?? undefined
  if (!activeRun.value) {
    stopping.value = false
    return
  }
  const step = events.value.findLast((event) => event.run_id === activeRun.value
    && (event.type === 'status' || event.type === 'tool_started'))
  progress.value = '正在恢复任务进度'
  if (step) showProgress(step)
}

function scheduleProgressRead() {
  window.clearTimeout(pollTimer)
  if (disposed || !activeRun.value || sending.value) return
  pollTimer = window.setTimeout(async () => {
    try {
      await refresh(true)
      if (!disposed) message.value = ''
    } catch (cause) {
      historyFailure(cause, '连接暂时中断，恢复后会继续读取任务进度')
    } finally {
      scheduleProgressRead()
    }
  }, 1500)
}

watch([activeRun, sending], scheduleProgressRead)
watch(running, (value) => emit('busy', value))

onMounted(() => {
  initialHistory = refresh().catch((cause) => {
    historyFailure(cause, '暂时无法读取智能体会话')
  })
})
onUnmounted(() => {
  disposed = true
  window.clearTimeout(pollTimer)
  historyRequest.abort()
  runRequest?.abort()
  consentDecision?.(false)
})

function decideConsent(accepted: boolean) {
  consent.value = accepted
  consentOpen.value = false
  consentDecision?.(accepted)
  consentDecision = undefined
}

async function submit(text: string) {
  await initialHistory
  if (disposed || scopeBlocked.value || running.value || rosterWorkbench.value?.busy || consentOpen.value || !text.trim()) return false
  const file = props.catFile
  const csv = Boolean(file && /\.csv$/i.test(file.name))
  if (csv && !props.catCsvConfirmed) return false
  if (!consent.value) {
    consentOpen.value = true
    if (!await new Promise<boolean>((resolve) => { consentDecision = resolve })) return false
  }
  if (disposed || props.catFile !== file || (csv && !props.catCsvConfirmed)) return false
  const request = new AbortController()
  runRequest = request
  lastText.value = text
  lastSentRun.value = ''
  message.value = ''
  progress.value = '正在连接'
  sending.value = true
  try {
    let catRef: string | undefined
    if (file) {
      progress.value = '正在上传合成题库'
      try {
        if (uploadedCat?.file !== file) {
          const submitted = await uploadWorkspaceCat(csv ? file.slice(0, file.size, 'text/csv') : file, request.signal)
          uploadedCat = { file, ref: submitted.ref }
        }
        catRef = uploadedCat.ref
      } catch (cause) {
        if (!disposed && !request.signal.aborted) {
          message.value = cause instanceof RealApiError && cause.message !== '工作区请求暂时不可用'
            ? cause.message
            : '题库上传失败，请检查合成 GRM JSON 或 UTF-8 CSV 的格式和大小（最多 240 KiB），也可稍后重试'
        }
        return false
      }
    }
    const attachment = props.roster?.kind ?? (catRef ? 'cat_bank' : undefined)
    awaitingStart = true
    await sendWorkspaceTurn(text, attachment, (event) => {
      if (disposed || request.signal.aborted) return
      events.value.push(event)
      if (event.type === 'start') {
        awaitingStart = false
        activeRun.value = lastSentRun.value = event.run_id
        if (stopping.value) void requestStop(event.run_id)
      }
      if (event.type === 'end' && activeRun.value === event.run_id) {
        activeRun.value = undefined
        stopping.value = false
      }
      showProgress(event)
      if (event.type === 'tool_result' && event.view.kind === 'roster_import') openPanel('roster')
      if (event.type === 'tool_result' && event.view.kind === 'staff_roster_import') openPanel('staff')
      if (event.type === 'tool_result' && props.catFile && event.view.kind === 'workflow' && event.view.workflow === 'cat') panel.value = 'cat'
      void nextTick(() => { if (viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight })
    }, request.signal, catRef, props.tableSummary)
    return true
  } catch {
    if (!disposed) {
      message.value = request.signal.aborted ? '已取消附件上传' : '连接中断，正在核对已提交的任务'
      await refresh().catch((cause) => historyFailure(cause, '连接中断，可刷新对话后继续'))
      if (!disposed && !activeRun.value && !failedRun.value && !scopeBlocked.value) message.value = '连接中断，可刷新对话后继续'
    }
    return false
  } finally {
    if (!disposed) {
      awaitingStart = false
      sending.value = false
    }
  }
}

async function reload() {
  message.value = ''
  try { await refresh() } catch (cause) { historyFailure(cause, '暂时无法读取智能体会话') }
}

async function reset() {
  try {
    await resetWorkspaceConversation()
    events.value = []
    message.value = ''
    lastText.value = ''
    lastSentRun.value = ''
  } catch {
    message.value = '暂时无法清空会话，请稍后重试'
  }
}

async function selectAssessment(taskRef: string) {
  if (assessmentChecking.value || assessmentStarting.value || assessmentTask.value === taskRef) return
  assessmentId.value = ''
  assessmentComplete.value = false
  assessmentTask.value = taskRef
  message.value = ''
  if (!frontendApi.listStudentSchoolTaskHistory) return

  assessmentChecking.value = true
  try {
    const history = await frontendApi.listStudentSchoolTaskHistory()
    assessmentComplete.value = history.data.some((entry) => entry.task_ref === taskRef && entry.assessment_status === 'completed')
  } catch {
    // The original start endpoint still checks permission and current task status.
  } finally {
    assessmentChecking.value = false
  }
}

function openPanel(workflow?: WorkflowPanel | RosterPanel) {
  if (rosterWorkbench.value?.busy) return
  referral.value = undefined
  feedbackRef.value = undefined
  feedbackTaskRef.value = undefined
  prepareSupportPlan.value = false
  reviewTaskRef.value = undefined
  libraryFile.value = undefined
  libraryImport.value = false
  libraryQuery.value = ''
  panel.value = workflow
}

function openSchoolLibrary(file?: File) {
  if (props.role !== 'psychological_specialist') return
  openPanel('library')
  libraryFile.value = file
  libraryImport.value = Boolean(file)
}

function openFeedback(ref?: string) {
  openPanel('feedback')
  feedbackRef.value = ref
}

function openTaskFeedback() {
  openPanel('feedback')
  feedbackTaskRef.value = assessmentTask.value
}

function openSupportPlan() {
  openPanel('support')
  prepareSupportPlan.value = true
}

function openReviewTask(taskRef: string) {
  openPanel('review')
  reviewTaskRef.value = taskRef
}

function openTeacherReferral(draft: TeacherReferral, key: string) {
  referral.value = { draft, key }
  panel.value = 'support'
}

async function startAssessment() {
  if (!assessmentTask.value || assessmentChecking.value || assessmentStarting.value || assessmentComplete.value || !frontendApi.startStudentSchoolTask) return
  assessmentStarting.value = true
  message.value = ''
  try {
    const result = await frontendApi.startStudentSchoolTask(assessmentTask.value)
    if (result.data.status === 'completed') assessmentComplete.value = true
    else assessmentId.value = result.data.assessment_id
  } catch {
    message.value = '无法打开该测评，可能已截止或已完成，请重新查询'
  } finally {
    assessmentStarting.value = false
  }
}

async function confirmClass() {
  const preview = pendingClass.value
  if (classBusy.value || !preview) return
  classBusy.value = true
  message.value = ''
  try {
    const receipt = await runWorkspaceAgent({ operation: 'confirm', token: preview.token })
    if (receipt.kind !== 'class_created') throw new Error()
    submittedClasses.value.add(preview.token)
    pendingClass.value = undefined
    emit('changed')
  } catch {
    message.value = '无法确认班级已创建，请重新查询班级或生成新预览'
    pendingClass.value = undefined
  } finally {
    classBusy.value = false
  }
}

async function publishTask() {
  const preview = pendingPublication.value
  if (!preview || publicationBusy.value) return
  publicationBusy.value = true
  message.value = ''
  try {
    const receipt = await confirmWorkspacePublication(preview.token)
    if (receipt.status !== 'PUBLISHED' || !receipt.task_ref) throw new Error()
    publishedTokens.value.add(preview.token)
    if (preview.catDraft) {
      const draft = preview.catDraft
      catReceipts.value.set(draft.draft_ref, { ...draft, state: 'PUBLISHED' })
    }
    pendingPublication.value = undefined
    emit('changed')
  } catch {
    message.value = '暂时无法核实发布结果，请查询学校任务'
    pendingPublication.value = undefined
  } finally {
    publicationBusy.value = false
  }
}

async function handleCat(draft: CatDraft, action: 'save' | 'approve' | 'publish') {
  if (catBusy.value) return
  if (action !== 'publish') {
    pendingCat.value = { draft, action }
    return
  }
  catBusy.value = true
  message.value = ''
  try {
    const preview = await previewWorkspaceCatHandoff(draft.draft_ref)
    pendingPublication.value = { ...preview, catDraft: draft }
  } catch {
    message.value = '无法准备发布。请核对班级、截止时间和方案批准状态'
  } finally {
    catBusy.value = false
  }
}

async function confirmCat() {
  const pending = pendingCat.value
  if (!pending || catBusy.value) return
  catBusy.value = true
  message.value = ''
  try {
    const receipt = await updateWorkspaceCat(pending.draft.draft_ref, pending.action)
    catReceipts.value.set(receipt.draft_ref, receipt)
    pendingCat.value = undefined
  } catch {
    message.value = '暂时无法确认操作结果。可重试或重新查询草案状态'
  } finally {
    catBusy.value = false
  }
}

function download(filename: string, content: string, type = 'text/markdown;charset=utf-8') {
  const href = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(href), 2000)
}

function downloadTable(summary: WorkspaceTableSummary) {
  const lines = ['列号,数据行数,数字个数,最小值,最大值,平均值,合计']
  for (const { column, count, min, max, mean, sum } of summary.columns) {
    lines.push([column, summary.rows, count, min, max, mean, sum].join(','))
  }
  download('表格统计.csv', '\uFEFF' + lines.join('\r\n'), 'text/csv;charset=utf-8')
}

async function requestStop(runId: string) {
  try {
    await cancelWorkspaceTurn(runId, historyRequest.signal)
    if (!disposed && !sending.value) await refresh()
  } catch {
    if (!disposed) {
      stopping.value = false
      message.value = '暂时无法确认任务是否停止，请稍后重试'
    }
  }
}

function cancel() {
  if (stopping.value) return
  if (activeRun.value) {
    stopping.value = true
    void requestStop(activeRun.value)
  } else if (awaitingStart) {
    stopping.value = true
  } else {
    runRequest?.abort()
  }
}
function openIndependentCat() { panel.value = 'cat' }
defineExpose({ submit, cancel, openIndependentCat, openSchoolLibrary })
</script>

<template>
  <section v-if="timeline.length || running || message || assessmentTask || panel" class="agent-thread" aria-label="智能体会话">
    <div v-if="events.length" class="agent-thread__head">
      <strong>当前对话</strong>
      <div>
        <AppButton variant="quiet" :disabled="running" @click="reload"><RotateCcw :size="15" /> 刷新对话</AppButton>
        <AppButton variant="quiet" :disabled="running || Boolean(panel) || Boolean(assessmentId)" @click="reset">清空对话</AppButton>
      </div>
    </div>
    <div v-if="timeline.length" ref="viewport" class="agent-thread__timeline">
      <template v-for="(event, index) in timeline" :key="event.run_id + ':' + index">
        <div v-if="event.type === 'user'" class="agent-thread__user">{{ event.text }}</div>
        <div v-else-if="event.type === 'answer'" class="agent-thread__answer">
          <strong>PsyNova</strong>
          <WorkspaceAnswer :text="event.text" />
        </div>
        <AppCard v-else-if="event.type === 'tool_result'" class="agent-thread__card">
          <p class="agent-thread__receipt"><Check :size="17" />{{ event.label }}</p>
          <template v-if="event.view.kind === 'table_statistics'">
            <strong>表格统计 · {{ event.view.rows }} 行数据</strong>
            <div class="agent-thread__table">
              <table aria-label="所选列的统计结果">
                <thead><tr><th>列号</th><th>数字个数</th><th>最小值</th><th>最大值</th><th>平均值</th><th>合计</th></tr></thead>
                <tbody>
                  <tr v-for="column in event.view.columns" :key="column.column">
                    <th scope="row">第 {{ column.column }} 列</th><td>{{ column.count }}</td><td>{{ column.min }}</td><td>{{ column.max }}</td><td>{{ column.mean }}</td><td>{{ column.sum }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <AppButton variant="secondary" @click="downloadTable(event.view)">下载统计 CSV</AppButton>
          </template>
          <template v-else-if="'rows' in event.view">
            <strong>{{ headings[event.view.kind] }} · {{ event.view.total }}{{ event.view.kind === 'school_student_counts' ? ' 名学生' : ' 项' }}</strong>
            <small v-if="event.view.kind === 'school_student_counts'">{{ event.view.class_count }} 个班级 · {{ event.view.active }} 个在用账号</small>
            <ul v-if="event.view.rows.length" class="agent-thread__rows">
              <li v-for="(row, rowIndex) in event.view.rows" :key="row.ref">
                <span>{{ row.label || `测评任务 ${rowIndex + 1}` }}</span>
                <small v-if="row.due_at">{{ new Date(row.due_at).toLocaleString('zh-CN') }} 截止</small>
                <template v-if="typeof row.completed === 'number' && typeof row.total === 'number'">
                  <small>已完成 {{ row.completed }} / {{ row.total }}</small>
                  <progress v-if="row.total > 0" :value="row.completed" :max="row.total" :aria-label="`${row.label || '班级'}完成比例`" />
                </template>
                <small v-else-if="typeof row.total === 'number'">{{ row.total }} 人</small>
                <small v-else-if="row.status">{{ statuses[row.status] || row.status }}</small>
                <AppButton v-if="event.view.kind === 'student_tasks' && ['not_started', 'created', 'in_progress', 'completed'].includes(row.status || '')" variant="secondary" :disabled="assessmentChecking || assessmentStarting" @click="selectAssessment(row.ref)">{{ row.status === 'completed' ? '查看完成记录' : '打开测评' }}</AppButton>
              </li>
            </ul>
            <AppButton v-if="event.view.artifact" variant="secondary" @click="download(event.view.artifact.filename, event.view.artifact.markdown)">下载班级统计简报</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'assessment_picker'" variant="secondary" :disabled="assessmentChecking || assessmentStarting" @click="selectAssessment(event.view.task_ref)">阅读说明并打开测评</AppButton>
          <template v-else-if="event.view.kind === 'feedback_index'">
            <strong>{{ event.view.total ? `已发布反馈 · ${event.view.total} 份` : '暂时没有已发布的反馈' }}</strong>
            <AppButton v-if="event.view.total" variant="secondary" @click="openFeedback()">在会话中查看反馈</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'feedback_picker'" variant="secondary" @click="openFeedback(event.view.feedback_ref)">在会话中阅读反馈</AppButton>
          <div v-else-if="event.view.kind === 'education_articles'" class="agent-thread__sources">
            <details v-for="article in articlesForTopics(event.view.topics)" :key="article.id">
              <summary>{{ article.title }}</summary>
              <p v-for="paragraph in article.paragraphs" :key="paragraph">{{ paragraph }}</p>
              <a :href="article.url" target="_blank" rel="noopener noreferrer">{{ article.source }}</a>
            </details>
          </div>
          <template v-else-if="event.view.kind === 'school_library_inventory'">
            <strong>本校资料库 · {{ event.view.total }} 份资料</strong>
            <small>{{ event.view.chunks }} 个可检索片段</small>
            <AppButton variant="secondary" @click="openSchoolLibrary()">查看本校资料库</AppButton>
          </template>
          <div v-else-if="event.view.kind === 'preview_class'" class="agent-thread__inline">
            <span>{{ event.view.class_ref }}</span>
            <AppButton variant="secondary" :disabled="submittedClasses.has(event.view.token)" @click="pendingClass = event.view">{{ submittedClasses.has(event.view.token) ? '已创建' : '核对并确认' }}</AppButton>
          </div>
          <div v-else-if="event.view.kind === 'preview_task'" class="agent-thread__inline">
            <span>{{ event.view.class_label }} · {{ event.view.enrolled }} 名学生</span>
            <AppButton variant="secondary" :disabled="publishedTokens.has(event.view.token)" @click="pendingPublication = event.view">{{ publishedTokens.has(event.view.token) ? '已发布' : '核对发布计划' }}</AppButton>
          </div>
          <div v-else-if="event.view.kind === 'cat_inspection'">
            <strong>题库结构验证通过</strong>
            <p>{{ event.view.item_count }} 道题 · {{ event.view.dimension_count }} 个维度 · {{ event.view.attachment_has_config ? '包含方案配置' : '可选学校合成工程模板' }}</p>
          </div>
          <WorkspaceCatDraft v-else-if="event.view.kind === 'cat_draft'" :draft="catReceipts.get(event.view.draft_ref) || event.view" :administrator="false" :busy="catBusy" @action="handleCat" />
          <div v-else-if="event.view.kind === 'cat_drafts' || event.view.kind === 'cat_handoffs'">
            <p v-if="!event.view.drafts.length">当前没有可查看的 CAT 草案</p>
            <WorkspaceCatDraft v-for="draft in event.view.drafts" :key="draft.draft_ref" :draft="catReceipts.get(draft.draft_ref) || draft" :administrator="event.view.kind === 'cat_handoffs'" :busy="catBusy" @action="handleCat" />
          </div>
          <template v-else-if="event.view.kind === 'teacher_referral'">
            <strong>{{ supportCategories[event.view.category_code] }} · 支持转介草案</strong>
            <p>{{ event.view.observation }}</p>
            <AppButton variant="secondary" @click="openTeacherReferral(event.view, event.run_id + ':' + event.call_id)">核对转介草案</AppButton>
          </template>
          <template v-else-if="event.view.kind === 'teacher_support_status' || event.view.kind === 'specialist_support_status' || event.view.kind === 'specialist_support_plan'">
            <strong>授权支持请求 · {{ event.view.total }} 项</strong>
            <small v-if="event.view.shown < event.view.total">以下统计最近 {{ event.view.shown }} 项</small>
            <ul v-if="event.view.shown" class="agent-thread__rows">
              <li v-for="(count, status) in event.view.counts" :key="status">{{ supportCaseStates[status] }} · {{ count }} 项</li>
            </ul>
            <AppButton v-if="event.view.kind === 'specialist_support_plan'" variant="secondary" @click="openSupportPlan">打开支持计划草案</AppButton>
            <AppButton v-else variant="secondary" @click="openPanel('support')">查看支持记录</AppButton>
          </template>
          <template v-else-if="event.view.kind === 'professional_review_queue'">
            <strong>已建复核记录 · {{ event.view.open_count + event.view.in_review_count }} 项待处理</strong>
            <small>{{ event.view.open_count }} 项待开始 · {{ event.view.in_review_count }} 项处理中</small>
            <small v-if="event.view.unfiled_count !== undefined">已完成测评中，{{ event.view.unfiled_count }} 份尚未建立复核记录，需人工查看</small>
            <small v-if="event.view.task_count > event.view.tasks.length">显示最新 {{ event.view.tasks.length }} 项测评任务</small>
            <ul v-if="event.view.tasks.length" class="agent-thread__rows">
              <li v-for="task in event.view.tasks" :key="task.task_ref">
                <span>{{ task.class_label }}</span>
                <small>{{ task.open_count }} 项待开始 · {{ task.in_review_count }} 项处理中</small>
                <small v-if="task.unfiled_count !== undefined">{{ task.unfiled_count }} 份已完成测评未建立复核记录</small>
                <AppButton variant="secondary" @click="openReviewTask(task.task_ref)">查看该任务测评与复核</AppButton>
              </li>
            </ul>
            <AppButton variant="secondary" @click="openPanel('review')">查看所有已指派任务</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'roster_import'" variant="secondary" @click="openPanel('roster')">打开名单预览</AppButton>
          <AppButton v-else-if="event.view.kind === 'staff_roster_import'" variant="secondary" @click="openPanel('staff')">打开教职工名单预览</AppButton>
          <template v-else-if="event.view.kind === 'staff_invitation_status'">
            <strong>本校教职工邀请</strong>
            <p>待接受 {{ event.view.issued }} · 已接受 {{ event.view.accepted }} · 已过期 {{ event.view.expired }} · 已撤销 {{ event.view.revoked }}</p>
          </template>
          <template v-else-if="event.view.kind === 'school_audit'">
            <strong>本校运营记录 · {{ event.view.query.category ? auditCategoryLabel[event.view.query.category] : '全部类别' }}</strong>
            <small>从第 {{ event.view.query.offset + 1 }} 条起 · 本页 {{ event.view.visible_count }} 条<span v-if="event.view.has_more"> · 后面还有记录</span></small>
            <ul v-if="event.view.items.length" class="agent-thread__rows" aria-label="本校运营记录">
              <li v-for="(row, index) in event.view.items" :key="index">
                <span>{{ auditActionLabel[row.action] }} · {{ auditResultLabel[row.result] }}</span>
                <time :datetime="row.created_at">{{ operationsTime.format(new Date(row.created_at)) }}</time>
                <small v-if="row.record_count !== null">{{ row.record_count }} 个账号</small>
              </li>
            </ul>
            <p v-else>这个范围内没有记录</p>
          </template>
          <template v-else-if="event.view.kind === 'system_health'">
            <strong>系统依赖状态</strong>
            <small>检查时间 <time :datetime="event.view.checked_at">{{ operationsTime.format(new Date(event.view.checked_at)) }}</time></small>
            <ul class="agent-thread__rows" aria-label="系统依赖状态">
              <li v-for="(status, key) in event.view.statuses" :key="key">
                <span>{{ dependencyNames[key] }}</span>
                <small>{{ dependencyStatusLabels[status] }}</small>
              </li>
            </ul>
            <AppButton variant="secondary" @click="openPanel('system')">查看系统详情</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'workflow'" variant="secondary" @click="openPanel(event.view.workflow)">打开{{ panelLabels[event.view.workflow] }}</AppButton>
          <AppButton v-else-if="event.view.kind === 'markdown'" variant="secondary" @click="download(event.view.filename, event.view.markdown)">下载 {{ event.view.filename }}</AppButton>
        </AppCard>
        <p v-else-if="event.type === 'tool_failed'" class="agent-thread__problem">{{ event.label }}未完成 · {{ event.code }}</p>
        <AppStatusCallout v-else-if="event.type === 'safety'" tone="attention" :title="event.text || '本条消息或回复需要额外的安全检查'">
          <AppButton v-if="event.support" variant="secondary" @click="emit('support')">打开学生支持对话</AppButton>
        </AppStatusCallout>
        <p v-else-if="event.type === 'end' && event.status in finishLabels" class="agent-thread__problem">{{ event.code === 'dependency_timeout' ? '服务响应超时，可重试任务' : finishLabels[event.status as keyof typeof finishLabels] }}</p>
      </template>
    </div>
    <p v-if="running" role="status">{{ stopping ? '正在停止任务' : progress }}…</p>
    <div v-if="message" class="agent-thread__inline">
      <p class="agent-thread__problem" role="alert">{{ message }}</p>
    </div>
    <p v-if="retryNeedsAttachment && !running">重新添加附件后可继续任务</p>
    <AppButton v-if="retryText && !running" variant="quiet" @click="submit(retryText)">重试任务</AppButton>
    <AppCard v-if="assessmentTask" class="agent-thread__card">
      <header class="agent-thread__inline"><strong>心理测评</strong><AppButton variant="quiet" :disabled="assessmentChecking || assessmentStarting" @click="assessmentTask = ''; assessmentId = ''">{{ assessmentComplete ? '收起测评' : '暂时退出' }}</AppButton></header>
      <p v-if="assessmentChecking" role="status">正在核对测评进度</p>
      <template v-else-if="assessmentComplete">
        <AppStatusCallout tone="support" title="已保存测评作答" body="反馈将按学校发布流程出现在测评反馈中" />
        <AppButton variant="secondary" @click="openTaskFeedback">查看本次测评反馈</AppButton>
      </template>
      <template v-else-if="!assessmentId">
        <p>请按自己的实际情况选答，已提交的题目会保存。你可以暂时退出并稍后继续</p>
        <AppButton :loading="assessmentStarting" @click="startAssessment">我已阅读，开始或继续</AppButton>
      </template>
      <Assessment v-else :key="assessmentId" :embedded-assessment-id="assessmentId" @completed="assessmentComplete = true; emit('changed')" />
    </AppCard>
    <AppCard v-if="panel" class="agent-thread__card">
      <header class="agent-thread__inline"><strong>{{ panelLabels[panel] }}</strong><AppButton variant="quiet" :disabled="rosterWorkbench?.busy" @click="openPanel()">收起工作台</AppButton></header>
      <Roster v-if="panel === 'roster' || panel === 'staff'" :key="panel" ref="rosterWorkbench" :embedded-section="panel" :initial-roster-file="roster?.kind === (panel === 'staff' ? 'staff_roster' : 'student_roster') ? roster.file : undefined" />
      <component :is="panels.feedback" v-else-if="panel === 'feedback'" :key="feedbackTaskRef || feedbackRef || 'feedback'" embedded :initial-feedback-ref="feedbackRef" :initial-task-ref="feedbackTaskRef" @support="openPanel('support')" />
      <component :is="panels.review" v-else-if="panel === 'review'" :key="reviewTaskRef || 'review'" :initial-task-ref="reviewTaskRef" />
      <template v-else-if="panel === 'library'">
        <form class="agent-thread__inline" @submit.prevent="schoolLibrary?.search(libraryQuery)">
          <input v-model="libraryQuery" aria-label="检索本校资料" maxlength="160" placeholder="输入检索词" />
          <AppButton type="submit" variant="secondary" :disabled="!libraryQuery.trim()">检索</AppButton>
          <AppButton variant="quiet" @click="libraryImport = true">导入资料</AppButton>
        </form>
        <component :is="panels.library" ref="schoolLibrary" v-model:show-import="libraryImport" :show-results="true" :show-empty="true" :initial-file="libraryFile" />
      </template>
      <component :is="latestPanel" v-else-if="latestPanel" :key="panel === 'support' ? referral?.key || panel : panel" v-bind="panel === 'support' ? { audience, initialReferral: referral?.draft, preparePlan: prepareSupportPlan } : panel === 'cat' ? { initialBankFile: catFile } : {}" />
    </AppCard>
  </section>
  <AppDialog :open="consentOpen" title="合成学校智能体" description="通过安全检查的消息会用于 DeepSeek 推理。请使用虚构内容，名单请作为文件添加" @update:open="(open) => { if (!open) decideConsent(false) }">
    <div class="agent-thread__inline"><AppButton variant="secondary" @click="decideConsent(false)">返回</AppButton><AppButton @click="decideConsent(true)">同意并发送</AppButton></div>
  </AppDialog>
  <AppDialog :open="Boolean(pendingClass)" title="确认创建班级" :description="pendingClass?.class_ref" @update:open="(open) => { if (!open && !classBusy) pendingClass = undefined }">
    <div class="agent-thread__inline"><AppButton variant="secondary" :disabled="classBusy" @click="pendingClass = undefined">返回</AppButton><AppButton :loading="classBusy" @click="confirmClass">确认创建</AppButton></div>
  </AppDialog>
  <AppDialog :open="Boolean(pendingPublication)" title="确认发布学校测评" @update:open="(open) => { if (!open && !publicationBusy) pendingPublication = undefined }">
    <template v-if="pendingPublication">
      <p>{{ pendingPublication.plan_label || '学校默认合成测评' }} · {{ pendingPublication.class_label }}</p>
      <p>开放 {{ new Date(pendingPublication.opens_at).toLocaleString('zh-CN') }}</p>
      <p>截止 {{ new Date(pendingPublication.due_at).toLocaleString('zh-CN') }}</p>
      <p>当前班级 {{ pendingPublication.enrolled }} 名学生</p>
    </template>
    <div class="agent-thread__inline"><AppButton variant="secondary" :disabled="publicationBusy" @click="pendingPublication = undefined">返回</AppButton><AppButton :loading="publicationBusy" @click="publishTask">确认发布</AppButton></div>
  </AppDialog>
  <AppDialog :open="Boolean(pendingCat)" :title="pendingCat?.action === 'approve' ? '批准合成施测并交接' : '确认保存 CAT 草案'" @update:open="(open) => { if (!open && !catBusy) pendingCat = undefined }">
    <p v-if="pendingCat">{{ pendingCat.draft.plan_name }} · {{ pendingCat.draft.class_designation }}</p>
    <p v-if="pendingCat?.action === 'approve'">本次批准限合成工程施测。班级和时间由学校管理员核对并发布</p>
    <p v-else>将保存题库和方案的首版。保存后可以审阅合成施测资格</p>
    <div class="agent-thread__inline"><AppButton variant="secondary" :disabled="catBusy" @click="pendingCat = undefined">返回</AppButton><AppButton :loading="catBusy" @click="confirmCat">{{ pendingCat?.action === 'approve' ? '确认批准并交接' : '确认保存' }}</AppButton></div>
  </AppDialog>
</template>

<style scoped>
.agent-thread__table { min-width: 0; overflow-x: auto; }
.agent-thread__table table { width: 100%; border-collapse: collapse; text-align: start; font-variant-numeric: tabular-nums; }
.agent-thread__table th, .agent-thread__table td { padding: 6px 8px; border-bottom: 1px solid var(--color-border); white-space: nowrap; }
.agent-thread { display: grid; gap: 12px; margin-bottom: 14px; min-width: 0; }
.agent-thread__head, .agent-thread__inline { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.agent-thread__timeline { display: grid; gap: 10px; max-height: min(64vh, 720px); overflow: auto; padding: 2px; }
.agent-thread__user { justify-self: end; max-width: 90%; background: var(--color-info-wash); border-radius: var(--radius-card); padding: 10px 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-thread__answer, .agent-thread__card { display: grid; gap: 8px; padding: 14px; min-width: 0; }
.agent-thread__receipt { display: flex; align-items: center; gap: 6px; color: var(--color-primary-active); }
.agent-thread__card > button { justify-self: start; }
.agent-thread__rows { display: grid; gap: 4px; list-style: none; padding: 0; margin: 0; }
.agent-thread__rows li { display: flex; gap: 8px 14px; align-items: center; flex-wrap: wrap; border-top: 1px solid var(--color-border); padding-top: 7px; }
.agent-thread__rows li small { color: var(--color-text-secondary); }
.agent-thread__sources { display: grid; gap: 8px; overflow-wrap: anywhere; }
.agent-thread__sources summary { font-weight: 600; cursor: pointer; }
.agent-thread__sources p { margin: 7px 0; }
.agent-thread__sources a { color: var(--color-primary-active); text-decoration: underline; }
.agent-thread__problem { color: var(--color-text-secondary); }
</style>
