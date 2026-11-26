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
import { supportCaseStates, supportCategories, type TeacherReferral } from '@/services/school-support'
import {
  confirmWorkspacePublication, loadWorkspaceConversation, resetWorkspaceConversation,
  previewWorkspaceCatHandoff, runWorkspaceAgent, sendWorkspaceTurn, updateWorkspaceCat,
  uploadWorkspaceCat, type CatDraft, type TaskPublicationPreview, type WorkflowPanel, type WorkspaceEvent,
} from '@/services/workspace-agent'

const props = defineProps<{
  rosterFile?: File
  catFile?: File
  role: 'student' | 'teacher' | 'psychological_specialist' | 'school_admin'
}>()
const emit = defineEmits<{ busy: [value: boolean]; support: []; changed: [] }>()
const Assessment = defineAsyncComponent(() => import('@/views/student/AssessmentView.vue'))
const Roster = defineAsyncComponent(() => import('@/views/admin/AccountLifecycleWorkspace.vue'))
const panels = {
  review: defineAsyncComponent(() => import('@/components/school/SpecialistTaskReviews.vue')),
  cat: defineAsyncComponent(() => import('@/components/school/SpecialistCatWorkspace.vue')),
  resources: defineAsyncComponent(() => import('@/components/school/SchoolResearchSourceCatalog.vue')),
  support: defineAsyncComponent(() => import('@/views/school/SchoolSupportView.vue')),
  knowledge: defineAsyncComponent(() => import('@/views/student/StudentKnowledgeView.vue')),
  feedback: defineAsyncComponent(() => import('@/views/student/StudentFeedbackView.vue')),
  publish: defineAsyncComponent(() => import('@/components/school/AdminTaskDispatch.vue')),
  system: defineAsyncComponent(() => import('@/components/admin/AdminSystemHealth.vue')),
}
const panelLabels = {
  review: '专业复核', cat: 'CAT 题库与方案', resources: '专业资料', support: '学校支持',
  knowledge: '心理知识', feedback: '测评反馈', roster: '学生名单导入',
  publish: '测评发布', system: '系统状态',
}
const headings = {
  student_tasks: '我的测评任务', class_progress: '授权班级测评进度',
  review_tasks: '可复核测评', school_tasks: '学校测评任务', school_student_counts: '学生账号和分班人数',
}
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
const running = ref(false)
const progress = ref('')
const message = ref('')
const consent = ref(false)
const consentOpen = ref(false)
const panel = ref<WorkflowPanel | 'roster'>()
const feedbackRef = ref<string>()
const reviewTaskRef = ref<string>()
const referral = ref<{ key: string; draft: TeacherReferral }>()
const assessmentTask = ref('')
const assessmentId = ref('')
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
const viewport = ref<HTMLElement>()
let runRequest: AbortController | undefined
const historyRequest = new AbortController()
let disposed = false
let consentDecision: ((accepted: boolean) => void) | undefined
let initialHistory: Promise<void> | undefined
let uploadedCat: { file: File; ref: string } | undefined

const audience = computed(() => props.role === 'psychological_specialist' ? 'specialist' : props.role)
const latestPanel = computed(() => panel.value && panel.value !== 'roster' ? panels[panel.value] : undefined)
watch(() => props.rosterFile, (file) => { if (file) panel.value = 'roster' })
watch(() => props.catFile, (file) => {
  uploadedCat = undefined
  if (file && /\.csv$/i.test(file.name)) panel.value = 'cat'
})

async function refresh() {
  const previous = await loadWorkspaceConversation(historyRequest.signal)
  if (disposed) return
  events.value = previous.events
  if (previous.active) message.value = '此工作区正在处理任务，可稍后刷新会话'
}

onMounted(() => {
  initialHistory = refresh().catch(() => {
    if (!disposed) message.value = '暂时无法读取智能体会话'
  })
})
onUnmounted(() => {
  disposed = true
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
  if (disposed || running.value || consentOpen.value || !text.trim()) return false
  if (!consent.value) {
    consentOpen.value = true
    if (!await new Promise<boolean>((resolve) => { consentDecision = resolve })) return false
  }
  if (disposed) return false
  const request = new AbortController()
  runRequest = request
  lastText.value = text
  message.value = ''
  progress.value = '正在连接'
  running.value = true
  emit('busy', true)
  try {
    const file = props.catFile
    let catRef: string | undefined
    if (file && /\.json$/i.test(file.name)) {
      progress.value = '正在上传合成题库'
      try {
        if (uploadedCat?.file !== file) {
          const submitted = await uploadWorkspaceCat(file, request.signal)
          uploadedCat = { file, ref: submitted.ref }
        }
        catRef = uploadedCat.ref
      } catch {
        if (!disposed && !request.signal.aborted) {
          message.value = '题库上传失败。请检查是否为学校合成 GRM JSON（最多 240 KiB），或稍后重试'
        }
        return false
      }
    }
    const attachment = props.rosterFile ? 'student_roster' : catRef ? 'cat_bank' : undefined
    await sendWorkspaceTurn(text, attachment, (event) => {
      if (disposed || request.signal.aborted) return
      events.value.push(event)
      if (event.type === 'status') progress.value = progressLabels[event.status]
      if (event.type === 'tool_started') progress.value = event.label
      if (event.type === 'tool_result' && event.view.kind === 'roster_import') panel.value = 'roster'
      if (event.type === 'tool_result' && props.catFile && event.view.kind === 'workflow' && event.view.workflow === 'cat') panel.value = 'cat'
      void nextTick(() => { if (viewport.value) viewport.value.scrollTop = viewport.value.scrollHeight })
    }, request.signal, catRef)
    return true
  } catch {
    if (!disposed) {
      message.value = request.signal.aborted ? '已停止接收回复' : '连接中断，可刷新会话后继续'
      await refresh().catch(() => undefined)
    }
    return false
  } finally {
    if (!disposed) {
      running.value = false
      emit('busy', false)
    }
  }
}

async function reload() {
  message.value = ''
  try { await refresh() } catch { message.value = '暂时无法读取智能体会话' }
}

async function reset() {
  try {
    await resetWorkspaceConversation()
    events.value = []
    message.value = ''
    lastText.value = ''
  } catch {
    message.value = '暂时无法清空会话，请稍后重试'
  }
}

function selectAssessment(taskRef: string) {
  assessmentId.value = ''
  assessmentComplete.value = false
  assessmentTask.value = taskRef
}

function openPanel(workflow?: WorkflowPanel) {
  referral.value = undefined
  feedbackRef.value = undefined
  reviewTaskRef.value = undefined
  panel.value = workflow
}

function openFeedback(ref?: string) {
  openPanel('feedback')
  feedbackRef.value = ref
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
  if (!assessmentTask.value || assessmentStarting.value || !frontendApi.startStudentSchoolTask) return
  assessmentStarting.value = true
  message.value = ''
  try {
    const result = await frontendApi.startStudentSchoolTask(assessmentTask.value)
    assessmentId.value = result.data.assessment_id
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

function download(filename: string, markdown: string) {
  const href = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(href), 2000)
}

function cancel() { runRequest?.abort() }
function openIndependentCat() { panel.value = 'cat' }
defineExpose({ submit, cancel, openIndependentCat })
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
          <template v-if="'rows' in event.view">
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
                <AppButton v-if="event.view.kind === 'student_tasks' && ['not_started', 'created', 'in_progress'].includes(row.status || '')" variant="secondary" @click="selectAssessment(row.ref)">打开测评</AppButton>
              </li>
            </ul>
            <AppButton v-if="event.view.artifact" variant="secondary" @click="download(event.view.artifact.filename, event.view.artifact.markdown)">下载班级统计简报</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'assessment_picker'" variant="secondary" @click="selectAssessment(event.view.task_ref)">阅读说明并打开测评</AppButton>
          <template v-else-if="event.view.kind === 'feedback_index'">
            <strong>{{ event.view.total ? `已发布反馈 · ${event.view.total} 份` : '暂时没有已发布的反馈' }}</strong>
            <AppButton v-if="event.view.total" variant="secondary" @click="openFeedback()">在会话中查看反馈</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'feedback_picker'" variant="secondary" @click="openFeedback(event.view.feedback_ref)">在会话中阅读反馈</AppButton>
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
          <template v-else-if="event.view.kind === 'teacher_support_status' || event.view.kind === 'specialist_support_status'">
            <strong>授权支持请求 · {{ event.view.total }} 项</strong>
            <small v-if="event.view.shown < event.view.total">以下统计最近 {{ event.view.shown }} 项</small>
            <ul v-if="event.view.shown" class="agent-thread__rows">
              <li v-for="(count, status) in event.view.counts" :key="status">{{ supportCaseStates[status] }} · {{ count }} 项</li>
            </ul>
            <AppButton variant="secondary" @click="openPanel('support')">查看支持记录</AppButton>
          </template>
          <template v-else-if="event.view.kind === 'professional_review_queue'">
            <strong>已建复核记录 · {{ event.view.open_count + event.view.in_review_count }} 项待处理</strong>
            <small>{{ event.view.open_count }} 项待开始 · {{ event.view.in_review_count }} 项处理中</small>
            <small v-if="event.view.task_count > event.view.tasks.length">显示最新 {{ event.view.tasks.length }} 项测评任务</small>
            <ul v-if="event.view.tasks.length" class="agent-thread__rows">
              <li v-for="task in event.view.tasks" :key="task.task_ref">
                <span>{{ task.class_label }}</span>
                <small>{{ task.open_count }} 项待开始 · {{ task.in_review_count }} 项处理中</small>
                <AppButton variant="secondary" @click="openReviewTask(task.task_ref)">查看该任务复核记录</AppButton>
              </li>
            </ul>
            <AppButton variant="secondary" @click="openPanel('review')">查看所有已指派任务</AppButton>
          </template>
          <AppButton v-else-if="event.view.kind === 'roster_import'" variant="secondary" @click="panel = 'roster'">打开名单预览</AppButton>
          <AppButton v-else-if="event.view.kind === 'workflow'" variant="secondary" @click="openPanel(event.view.workflow)">打开{{ panelLabels[event.view.workflow] }}</AppButton>
          <AppButton v-else-if="event.view.kind === 'markdown'" variant="secondary" @click="download(event.view.filename, event.view.markdown)">下载 {{ event.view.filename }}</AppButton>
        </AppCard>
        <p v-else-if="event.type === 'tool_failed'" class="agent-thread__problem">{{ event.label }}未完成 · {{ event.code }}</p>
        <AppStatusCallout v-else-if="event.type === 'safety'" tone="attention" :title="event.text || '本条消息或回复需要额外的安全检查'">
          <AppButton v-if="event.support" variant="secondary" @click="emit('support')">打开学生支持对话</AppButton>
        </AppStatusCallout>
        <p v-else-if="event.type === 'end' && event.status in finishLabels" class="agent-thread__problem">{{ finishLabels[event.status as keyof typeof finishLabels] }}</p>
      </template>
    </div>
    <p v-if="running" role="status">{{ progress }}…</p>
    <div v-if="message" class="agent-thread__inline">
      <p class="agent-thread__problem" role="alert">{{ message }}</p>
      <AppButton v-if="lastText && !running" variant="quiet" @click="submit(lastText)">重试任务</AppButton>
    </div>
    <AppCard v-if="assessmentTask" class="agent-thread__card">
      <header class="agent-thread__inline"><strong>心理测评</strong><AppButton variant="quiet" :disabled="assessmentStarting" @click="assessmentTask = ''; assessmentId = ''">暂时退出</AppButton></header>
      <template v-if="!assessmentId">
        <p>请按自己的实际情况选答，已提交的题目会保存。你可以暂时退出并稍后继续</p>
        <AppButton :loading="assessmentStarting" @click="startAssessment">我已阅读，开始或继续</AppButton>
      </template>
      <Assessment v-else :key="assessmentId" :embedded-assessment-id="assessmentId" @completed="assessmentComplete = true; emit('changed')" />
      <AppButton v-if="assessmentComplete" variant="secondary" @click="openFeedback()">查看已发布反馈</AppButton>
    </AppCard>
    <AppCard v-if="panel" class="agent-thread__card">
      <header class="agent-thread__inline"><strong>{{ panelLabels[panel] }}</strong><AppButton variant="quiet" @click="openPanel()">收起工作台</AppButton></header>
      <Roster v-if="panel === 'roster'" embedded-roster :initial-roster-file="rosterFile" />
      <component :is="panels.feedback" v-else-if="panel === 'feedback'" :key="feedbackRef || 'feedback'" embedded :initial-feedback-ref="feedbackRef" @support="openPanel('support')" />
      <component :is="panels.review" v-else-if="panel === 'review'" :key="reviewTaskRef || 'review'" :initial-task-ref="reviewTaskRef" />
      <component :is="latestPanel" v-else-if="latestPanel" :key="panel === 'support' ? referral?.key || panel : panel" v-bind="panel === 'support' ? { audience, initialReferral: referral?.draft } : panel === 'cat' ? { initialBankFile: catFile } : {}" />
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
.agent-thread__problem { color: var(--color-text-secondary); }
</style>
