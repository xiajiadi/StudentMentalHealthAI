<script setup lang="ts">
/* global AbortController, DragEvent, Event, File, HTMLInputElement, HTMLTextAreaElement, KeyboardEvent, TextDecoder */
import { computed, nextTick, onUnmounted, ref, watch, type Component } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowUp, ArrowUpRight, BookOpen, CalendarDays, CalendarHeart, ChartNoAxesCombined, ChevronRight, ClipboardCheck, ClipboardList, FileCheck2, FileUp, FolderOpen, HeartHandshake, Inbox, Layers, MessagesSquare, Network, Paperclip, Plus, Send, Server, ShieldCheck, Sparkles, Square, UsersRound } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import AppTextarea from '@/components/app/AppTextarea.vue'
import { educationTopics, previewWorkspaceDocument, runWorkspaceAgent, type EducationTopic, type WorkspaceAgentResult } from '@/services/workspace-agent'
import { useSessionStore } from '@/stores/session'
import type { Role } from '@/types/contracts'
import SupportChatView from '@/views/student/SupportChatView.vue'
import WorkspaceConversation from '@/components/workspace/WorkspaceConversation.vue'
import WorkspaceTablePreview from '@/components/workspace/WorkspaceTablePreview.vue'
import { WORKBOOK_INVALID, type LocalWorkspaceSheet, type WorkspaceTableSummary } from '@/services/workspace-table'

type WorkspaceRole = 'student' | 'teacher' | 'psychological_specialist' | 'school_admin'
type Entry = { label: string; to: string; icon: Component; note?: string }
type Workspace = {
  label: string
  title: string
  example: string
  taskTitle: string
  sectionTitle: string
  entries: Entry[]
  records: [Entry, Entry, Entry]
}

defineProps<{ openNavigation?: () => void }>()

const workspaces: Record<WorkspaceRole, Workspace> = {
  student: {
    label: '学生工作区',
    title: '今天，你感觉怎么样？',
    example: '学习压力大时该怎么办？',
    taskTitle: '我的测评任务',
    sectionTitle: '继续探索',
    entries: [
      { label: '开始心理测评', to: '/student/assessments', icon: ClipboardCheck, note: '开始或继续作答' },
      { label: '学习心理知识', to: '/student/knowledge', icon: BookOpen, note: '了解情绪、压力和睡眠' },
      { label: '获取心理支持', to: '/student/workspace?chat=1#workspace-agent-composer', icon: HeartHandshake, note: '和智能体聊聊' },
      { label: '联系心理教师', to: '/student/school-support', icon: CalendarHeart, note: '查看校内支持渠道' },
    ],
    records: [
      { label: '我的心理测评', to: '/student/assessments', icon: ClipboardList, note: '查看待完成任务' },
      { label: '最近的支持对话', to: '/student/workspace?chat=1&history=1#workspace-agent-conversation', icon: MessagesSquare, note: '继续上次对话' },
      { label: '我的测评反馈', to: '/student/feedback', icon: FileCheck2, note: '查看已发布反馈' },
    ],
  },
  psychological_specialist: {
    label: '心理教师工作区',
    title: '今天，有什么需要协助？',
    example: '查看测评复核任务',
    taskTitle: '可复核的测评任务',
    sectionTitle: '待处理工作',
    entries: [
      { label: '心理测评分析', to: '/specialist/tasks', icon: ChartNoAxesCombined, note: '查看测评结果与专业复核' },
      { label: '学生心理支持', to: '/specialist/school-support', icon: HeartHandshake, note: '受理请求并制定支持计划' },
      { label: '专业知识库', to: '/specialist/resources', icon: BookOpen, note: '查阅专业资料和来源' },
      { label: 'CAT 题库与方案', to: '/specialist/cat', icon: Layers, note: '管理测评方案与模拟' },
    ],
    records: [
      { label: '测评结果复核', to: '/specialist/tasks', icon: ClipboardCheck, note: '打开专业复核工作区' },
      { label: '学生支持请求', to: '/specialist/school-support', icon: Inbox, note: '查看已授权的支持事项' },
      { label: '专业资料审核', to: '/specialist/resources', icon: FolderOpen, note: '核对资料来源与授权' },
    ],
  },
  teacher: {
    label: '普通教师工作区',
    title: '今天，如何更好地支持学生？',
    example: '查看班级进度',
    taskTitle: '班级测评进度',
    sectionTitle: '工作事项',
    entries: [
      { label: '查看班级进度', to: '/teacher/classes', icon: UsersRound, note: '查看授权班级的完成情况' },
      { label: '测评任务', to: '/teacher/tasks', icon: ClipboardList, note: '核对任务安排与截止时间' },
      { label: '班级数据分析', to: '/teacher/analytics', icon: ChartNoAxesCombined, note: '查看完成情况与趋势' },
      { label: '学生支持转介', to: '/teacher/school-support', icon: HeartHandshake, note: '与心理教师协作' },
    ],
    records: [
      { label: '近期测评任务', to: '/teacher/tasks', icon: CalendarDays, note: '查看近期安排' },
      { label: '班级完成情况', to: '/teacher/overview', icon: ChartNoAxesCombined, note: '打开班级进度概览' },
      { label: '支持转介记录', to: '/teacher/school-support', icon: Send, note: '查看提交与处理状态' },
    ],
  },
  school_admin: {
    label: '学校管理员工作区',
    title: '今天，想完成什么工作？',
    example: '查看学校测评任务',
    taskTitle: '学校测评任务',
    sectionTitle: '工作事项',
    entries: [
      { label: '组织与班级管理', to: '/admin/overview#admin-school-operations', icon: Network, note: '查看学校目录与班级配置' },
      { label: '账号与名单管理', to: '/admin/users', icon: UsersRound, note: '导入名单与下载初始凭据' },
      { label: '发布测评任务', to: '/admin/tasks', icon: ClipboardList, note: '配置测评方案和任务' },
      { label: '运营与系统状态', to: '/admin/settings', icon: Server, note: '查看服务运行情况' },
    ],
    records: [
      { label: '名单导入工作', to: '/admin/users', icon: FileUp, note: '下载模板或继续导入' },
      { label: '测评任务管理', to: '/admin/tasks', icon: CalendarDays, note: '查看发布情况' },
      { label: '运营与审计记录', to: '/admin/audit', icon: ShieldCheck, note: '核对近期平台操作' },
    ],
  },
}
const session = useSessionStore()
const route = useRoute()
function isWorkspaceRole(role: Role | null): role is WorkspaceRole {
  return role != null && Object.hasOwn(workspaces, role)
}

const role = computed<WorkspaceRole>(() => isWorkspaceRole(session.role) ? session.role : 'student')
const config = computed(() => workspaces[role.value])
const isPublicDemo = computed(() => session.user?.activeContext?.schoolRef.startsWith('PUBLICDEMO_'))
const command = ref('')
const chat = ref<InstanceType<typeof SupportChatView>>()
const chatVisible = ref(false)
const chatSending = ref(false)
const researchMode = computed(() => route.query.mode === 'research')
const workspaceAgent = ref<InstanceType<typeof WorkspaceConversation>>()
const agentBusy = ref(false)
const rosterFile = ref<File>()
const catFile = ref<File>()
const agentMode = computed(() => isPublicDemo.value && !researchMode.value
  && !(role.value === 'student' && (route.query.chat || route.query.history || route.query.conversation || route.query.topic)))
const workspaceScope = computed(() => JSON.stringify([session.user?.userId, session.user?.activeContext?.schoolRef, role.value]))
const maxCommandLength = computed(() => agentMode.value ? 3000 : role.value === 'student' ? 20000 : 160)
const fileInput = ref<HTMLInputElement>()
const attachmentOpen = ref(false)
type DocumentPreview = { file: File; characters: number; previewLength: number }
const attachment = ref<{ name: string; content: string; image?: boolean; document?: DocumentPreview }>()
const attachmentError = ref('')
const attachmentReading = ref<false | 'image' | 'document' | 'table'>(false)
const tablePreview = ref<{ name: string; sheets: LocalWorkspaceSheet[] }>()
const tableSummary = ref<WorkspaceTableSummary>()
const overview = ref<WorkspaceAgentResult | null>(null)
const result = ref<WorkspaceAgentResult | null>(null)
const overviewLoading = ref(false)
const overviewError = ref(false)
const running = ref(false)
const confirming = ref(false)
const confirmOpen = ref(false)
const examplesOpen = ref(false)
const formError = ref('')
const responseArea = ref<HTMLElement | null>(null)
const suggestedCommands = computed(() => {
  if (role.value === 'student') return ['还有哪些测评没做', config.value.example, '帮我制定复习计划']
  if (role.value === 'school_admin' && isPublicDemo.value) return [config.value.example, '新建班级 ']
  return [config.value.example]
})

let overviewRequest: AbortController | undefined
let taskRequest: AbortController | undefined
let attachmentRequest: AbortController | undefined
const taskPrompts: Record<WorkspaceRole, readonly string[]> = {
  student: ['看看我还有哪些测评要完成', '打开心理知识学习工作台', '打开学校心理支持入口', '帮我查看学校的支持渠道'],
  teacher: ['查看最近的班级测评完成情况', '帮我查一下班里有哪些测评任务和截止时间', '按任务汇总我们班的测评完成情况', '打开学生支持转介工作台'],
  psychological_specialist: ['查一下我有哪些授权测评可以复核，再打开专业复核工作台', '打开学生支持工作台', '打开专业资料工作台', '打开 CAT 题库和测评方案工作台'],
  school_admin: ['核对学校学生账号数和各班级人数', '打开学生名单导入工作台，准备自动分班和初始账号', '打开测评发布工作台，我要准备一个新测评', '打开系统状态工作台'],
}

async function loadOverview() {
  overviewRequest?.abort()
  const request = new AbortController()
  overviewRequest = request
  overviewLoading.value = true
  overviewError.value = false
  try {
    const data = await runWorkspaceAgent({ operation: 'snapshot' }, request.signal)
    if (!request.signal.aborted) overview.value = data
  } catch {
    if (!request.signal.aborted) overviewError.value = true
  } finally {
    if (!request.signal.aborted) overviewLoading.value = false
  }
}

watch(workspaceScope, () => {
  taskRequest?.abort()
  command.value = ''
  result.value = null
  overview.value = null
  formError.value = ''
  running.value = false
  confirming.value = false
  confirmOpen.value = false
  examplesOpen.value = false
  chatSending.value = false
  cancelAttachmentRead()
  attachmentOpen.value = false
  attachment.value = undefined
  attachmentError.value = ''
  tablePreview.value = undefined
  tableSummary.value = undefined
  rosterFile.value = undefined
  catFile.value = undefined
  agentBusy.value = false
  if (session.user?.activeContext) void loadOverview()
  else {
    overviewRequest?.abort()
    overviewLoading.value = false
    overviewError.value = false
  }
}, { immediate: true })

watch(agentMode, (enabled) => {
  if (enabled) return
  cancelAttachmentRead()
  tablePreview.value = undefined
  tableSummary.value = undefined
  if (attachment.value?.image || attachment.value?.document) {
    attachmentOpen.value = false
    attachment.value = undefined
  }
})

watch(() => [route.query.chat, route.query.conversation, route.query.history, route.query.topic, route.query.mode, workspaceScope.value], async () => {
  if (role.value !== 'student') return
  const { chat: open, conversation, history, topic } = route.query
  chatVisible.value = Boolean(open || conversation || history || topic || researchMode.value)
  if (typeof topic === 'string' && Object.hasOwn(educationTopics, topic)) {
    command.value = educationTopics[topic as EducationTopic]
  }
  await nextTick()
  if (typeof conversation === 'string' || history === '1') {
    await chat.value?.showHistory(typeof conversation === 'string' ? conversation : undefined)
  } else if (open === '1') {
    responseArea.value?.querySelector('textarea')?.focus({ preventScroll: true })
  }
}, { immediate: true, flush: 'post' })

onUnmounted(() => {
  overviewRequest?.abort()
  taskRequest?.abort()
  attachmentRequest?.abort()
})

async function sendChat(text: string) {
  const scope = workspaceScope.value
  chatVisible.value = true
  chatSending.value = true
  const conversationMode = researchMode.value
  try {
    if (await chat.value?.submitFromWorkspace(text)
        && workspaceScope.value === scope && researchMode.value === conversationMode
        && command.value.trim() === text) command.value = ''
  } finally {
    if (workspaceScope.value === scope) chatSending.value = false
  }
}

async function run() {
  const text = command.value.trim()
  if (agentMode.value) {
    if (!text || agentBusy.value) return
    if (await workspaceAgent.value?.submit(text) && command.value.trim() === text) command.value = ''
    return
  }
  if (!text || running.value || chatSending.value || confirming.value || chat.value?.composerBlocked) return
  const isStudent = role.value === 'student'
  const taskQuery = /^(?:(?:查看)?我的测评(?:任务)?|还有哪些测评(?:没做)?|继续测评)$/.test(text.replace(/[？?。！!]+$/, '').trim())
  if (isStudent && (researchMode.value || chat.value?.needsRetry || !taskQuery)) {
    formError.value = ''
    result.value = null
    await sendChat(text)
    return
  }
  const request = new AbortController()
  taskRequest = request
  running.value = true
  formError.value = ''
  result.value = null
  try {
    const data = await runWorkspaceAgent({ operation: 'run', text }, request.signal)
    if (!request.signal.aborted) {
      result.value = data
      if (isStudent && command.value.trim() === text) command.value = ''
      if (data.kind.endsWith('_tasks') || data.kind === 'class_progress') overview.value = data
    }
  } catch {
    if (!request.signal.aborted) formError.value = '暂时无法处理，请重试'
  } finally {
    if (!request.signal.aborted) running.value = false
  }
}

function handleComposerKey(event: KeyboardEvent) {
  if (!agentMode.value && role.value !== 'student' && !event.ctrlKey && !event.metaKey) return
  if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  if (!event.repeat) void run()
}

function chooseAttachment() {
  attachmentError.value = ''
  fileInput.value?.click()
}

async function readAttachment(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  input.value = ''
  await openAttachment(file)
}

function cancelAttachmentRead() {
  attachmentRequest?.abort()
  attachmentReading.value = false
}

async function openAttachment(file: File) {
  cancelAttachmentRead()
  attachment.value = undefined
  attachmentOpen.value = false
  attachmentError.value = ''
  tablePreview.value = undefined
  tableSummary.value = undefined
  if (agentMode.value) {
    if (role.value === 'school_admin' && /\.(csv|xlsx)$/i.test(file.name)) {
      selectRoster(file)
      return
    }
    if (role.value === 'psychological_specialist' && /\.(csv|json)$/i.test(file.name)) {
      selectCatBank(file)
      return
    }
  }
  const request = new AbortController()
  attachmentRequest = request
  const image = agentMode.value && /\.(png|jpe?g|webp)$/i.test(file.name)
  const kind = agentMode.value ? /\.(docx|pdf)$/i.exec(file.name)?.[1]?.toLowerCase() : undefined
  const tableFormat = agentMode.value && ['student', 'teacher'].includes(role.value)
    && /\.(csv|xlsx)$/i.exec(file.name)?.[1].toLowerCase()
  try {
    if (tableFormat) {
      attachmentReading.value = 'table'
      let sheets: LocalWorkspaceSheet[]
      if (tableFormat === 'xlsx') {
        const { readWorkspaceXlsx } = await import('@/services/workspace-workbook-client')
        sheets = await readWorkspaceXlsx(file, request.signal)
      } else {
        const { readWorkspaceCsv } = await import('@/services/workspace-table')
        sheets = [{ name: '', table: await readWorkspaceCsv(file) }]
      }
      if (!request.signal.aborted) tablePreview.value = { name: file.name, sheets }
      return
    }
    let content: string
    let documentPreview: DocumentPreview | undefined
    if (image) {
      attachmentReading.value = 'image'
      const { readWorkspaceImage } = await import('@/services/workspace-image-text')
      content = await readWorkspaceImage(file, request.signal)
    } else if (kind === 'pdf' || kind === 'docx') {
      if (!file.size || file.size > 5 * 1024 * 1024) throw new Error('请选择不超过 5 MiB 的 PDF 或 DOCX')
      attachmentReading.value = 'document'
      const result = await previewWorkspaceDocument(file, kind, request.signal)
      content = result.text
      documentPreview = { file, characters: result.characters, previewLength: Array.from(content).length }
    } else {
      if (!/\.(txt|md|markdown)$/i.test(file.name) || file.size > 16 * 1024) {
        throw new Error('请选择不超过 16 KB 的 TXT 或 Markdown 文件')
      }
      content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()).trim()
    }
    const hasControlCharacter = Array.from(content).some((character) =>
      character.charCodeAt(0) < 32 && !['\t', '\r', '\n'].includes(character))
    if (!content || hasControlCharacter) throw new Error()
    if (!request.signal.aborted) {
      attachment.value = { name: file.name, content, image, document: documentPreview }
      attachmentOpen.value = true
    }
  } catch (error) {
    if (!request.signal.aborted) {
      const known = error instanceof Error && /^(请选择|图片中未识别到文字|Excel 暂时无法读取)/.test(error.message)
      attachmentError.value = known ? error.message : image
        ? '图片识别未能完成，请检查图片后重试'
        : tableFormat === 'csv' ? 'CSV 暂时无法读取，请检查编码、列数和引号'
          : tableFormat === 'xlsx' ? WORKBOOK_INVALID
          : kind ? '无法提取文字，请检查文档是否可选取文字、受密码保护或损坏'
          : '无法读取文本，请检查文件是否为空或使用 UTF-8 编码'
    }
  } finally {
    if (attachmentRequest === request) attachmentReading.value = false
  }
}

function confirmTable(summary: WorkspaceTableSummary) {
  tableSummary.value = summary
  tablePreview.value = undefined
  if (!command.value.trim()) command.value = '请解读这份表格的统计摘要，并给我可下载的统计表'
}

function insertAttachment() {
  if (!attachment.value || chatSending.value || chat.value?.needsRetry) return
  const editor = document.getElementById('workspace-attachment-excerpt') as HTMLTextAreaElement | null
  const selected = editor?.value.slice(editor.selectionStart, editor.selectionEnd).trim()
  const text = [command.value.trim(), selected || attachment.value.content.trim()].filter(Boolean).join('\n\n')
  if (text.length > maxCommandLength.value) {
    attachmentError.value = '内容超过输入框字数上限，请选中需要的段落后再试'
    return
  }
  command.value = text
  attachmentOpen.value = false
  attachment.value = undefined
  void nextTick(() => responseArea.value?.querySelector('textarea')?.focus())
}

async function reviewDocumentForLibrary() {
  const file = attachment.value?.document?.file
  if (role.value !== 'psychological_specialist' || !file) return
  const scope = workspaceScope.value
  attachmentOpen.value = false
  attachment.value = undefined
  await nextTick()
  if (workspaceScope.value === scope) workspaceAgent.value?.openSchoolLibrary(file)
}

function selectRoster(file: File) {
  if (!/\.(csv|xlsx)$/i.test(file.name) || file.size > 1024 * 1024) {
    attachmentError.value = '请选择不超过 1 MiB 的 CSV 或 XLSX 学生名单'
    return
  }
  rosterFile.value = file
  attachmentError.value = ''
  if (!command.value.trim()) command.value = '帮我检查这份学生名单，准备导入、分班和生成初始账号'
}

function selectCatBank(file: File) {
  if (!/\.(csv|json)$/i.test(file.name) || file.size > 1_500_000) {
    attachmentError.value = '请选择不超过 1.5 MB 的 JSON 或 CSV 题库'
    return
  }
  catFile.value = file
  attachmentError.value = ''
  if (!command.value.trim()) command.value = /\.json$/i.test(file.name)
    ? '帮我验证这份合成 CAT 题库'
    : '请打开独立 CAT 工作台，核对我选中的 CSV'
}

const attachmentFormats = computed(() => {
  const text = '.txt,.md,.markdown'
  if (!agentMode.value) return text
  return text + ',.png,.jpg,.jpeg,.webp,.pdf,.docx' + ({
    school_admin: ',.csv,.xlsx', psychological_specialist: ',.csv,.json', teacher: ',.csv,.xlsx', student: ',.csv,.xlsx',
  }[role.value])
})

function handleAttachmentDrop(event: DragEvent) {
  if (!agentMode.value) return
  event.preventDefault()
  const file = event.dataTransfer?.files[0]
  if (file && !agentBusy.value && !attachmentReading.value) void openAttachment(file)
}

function cancelRun() {
  if (agentMode.value) {
    workspaceAgent.value?.cancel()
    return
  }
  taskRequest?.abort()
  running.value = false
}

async function confirm() {
  if (confirming.value || !result.value?.token) return
  const request = new AbortController()
  taskRequest = request
  confirming.value = true
  formError.value = ''
  try {
    const data = await runWorkspaceAgent({ operation: 'confirm', token: result.value.token }, request.signal)
    if (!request.signal.aborted) {
      result.value = data
      confirmOpen.value = false
    }
  } catch {
    if (!request.signal.aborted) formError.value = '操作未确认，请重试或重新生成预览'
  } finally {
    if (!request.signal.aborted) confirming.value = false
  }
}

async function useExample(value: string) {
  command.value = value
  examplesOpen.value = false
  await nextTick()
  responseArea.value?.querySelector('textarea')?.focus()
}

async function startQuickTask(index: number) {
  if (agentBusy.value) return
  command.value = taskPrompts[role.value][index] ?? config.value.example
  await run()
}

const statusLabels: Record<string, string> = {
  not_started: '待开始', created: '待继续', in_progress: '进行中',
  completed: '已完成', abandoned: '已结束', invalid: '已失效',
  PUBLISHED: '已发布', CLOSED: '已关闭', REVOKED: '已撤回',
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value))
}
</script>

<template>
  <div class="workspace-agent">
    <header class="workspace-agent__hero">
      <span class="workspace-agent__mark"><Sparkles :size="28" aria-hidden="true" /></span>
      <span class="workspace-agent__role">{{ config.label }}</span>
      <h1>{{ config.title }}</h1>
    </header>

    <section aria-label="PsyNova Agent">
      <WorkspaceConversation
        v-if="agentMode"
        :key="workspaceScope"
        ref="workspaceAgent"
        :role="role"
        :roster-file="rosterFile"
        :cat-file="catFile"
        :table-summary="tableSummary"
        @busy="agentBusy = $event"
        @changed="loadOverview"
        @support="$router.push({ name: 'student-workspace', query: { chat: '1' } })"
      />
      <SupportChatView
        v-if="role === 'student' && !agentMode"
        v-show="chatVisible"
        :key="workspaceScope + researchMode"
        id="workspace-agent-conversation"
        ref="chat"
        :research-mode="researchMode"
        embedded
      />
      <form id="workspace-agent-composer" ref="responseArea" class="workspace-agent__composer" @submit.prevent="run" @dragover="(event) => { if (agentMode) event.preventDefault() }" @drop="handleAttachmentDrop">
        <AppTextarea
          id="workspace-agent-input"
          v-model="command"
          :label="role === 'student' ? '输入消息' : '输入任务'"
          :placeholder="config.example"
          :maxlength="maxCommandLength"
          :readonly="chatSending || chat?.needsRetry"
          :rows="2"
          hide-label
          @keydown="handleComposerKey"
        />
        <div class="workspace-agent__controls">
          <div class="workspace-agent__tools">
            <AppButton class="workspace-agent__tool" variant="quiet" aria-label="任务示例" title="任务示例" :disabled="chatSending || chat?.needsRetry" @click="examplesOpen = true">
              <Plus :size="20" aria-hidden="true" />
            </AppButton>
            <input ref="fileInput" type="file" :accept="attachmentFormats" hidden @change="readAttachment" />
            <AppButton class="workspace-agent__tool" variant="quiet" aria-label="添加附件" title="添加附件" :disabled="agentBusy || attachmentReading || chatSending || chat?.needsRetry" @click="chooseAttachment">
              <Paperclip :size="20" aria-hidden="true" />
            </AppButton>
          </div>
          <span class="workspace-agent__name"><Sparkles :size="17" aria-hidden="true" />PsyNova Agent</span>
          <AppButton v-if="running || agentBusy" class="workspace-agent__tool" variant="quiet" aria-label="取消任务" title="取消任务" @click="cancelRun">
            <Square :size="16" aria-hidden="true" />
          </AppButton>
          <AppButton v-else class="workspace-agent__send" type="submit" :loading="chatSending" :disabled="(!command.trim() && !chat?.needsRetry) || confirming || chat?.composerBlocked" :aria-label="role === 'student' ? (chat?.needsRetry ? '重试发送' : '发送消息') : '发送任务'">
            <ArrowUp :size="21" aria-hidden="true" />
          </AppButton>
        </div>
        <div v-if="attachmentReading" class="workspace-agent__receipt">
          <span role="status">{{ attachmentReading === 'image' ? '正在这台设备上识别文字' : attachmentReading === 'table' ? '正在这台设备上计算表格' : '正在学校服务中提取文字' }}</span>
          <AppButton variant="quiet" @click="cancelAttachmentRead">取消处理</AppButton>
        </div>
        <div v-if="tableSummary" class="workspace-agent__receipt">
          <span>已选表格统计 · {{ tableSummary.columns.length }} 列</span>
          <AppButton variant="quiet" :disabled="agentBusy" @click="tableSummary = undefined">移除表格统计</AppButton>
        </div>
        <div v-if="agentMode && (rosterFile || catFile)" class="workspace-agent__receipt">
          <span>{{ (rosterFile || catFile)?.name }}</span>
          <AppButton v-if="catFile" variant="quiet" :disabled="agentBusy" @click="workspaceAgent?.openIndependentCat()">打开独立 CAT 工作台</AppButton>
          <AppButton variant="quiet" :disabled="agentBusy" @click="rosterFile = undefined; catFile = undefined">移除附件</AppButton>
        </div>
      </form>
      <p v-if="chatSending" class="workspace-agent__chat-status" role="status">正在回复…</p>
      <p v-if="attachmentError && !attachmentOpen" class="workspace-agent__error" role="alert">{{ attachmentError }}</p>
      <div v-if="role === 'student' && !chatSending && !chat?.needsRetry && (researchMode || isPublicDemo || chat?.researchAvailable)" class="workspace-agent__chat-links">
        <RouterLink v-if="!agentMode && isPublicDemo" :to="{ name: 'student-workspace' }">返回智能体对话</RouterLink>
        <RouterLink v-else-if="researchMode" :to="{ name: 'student-workspace', query: { chat: '1' } }">返回日常对话</RouterLink>
        <RouterLink v-else :to="{ name: 'student-workspace', query: { mode: 'research' } }">高中场景研究演示</RouterLink>
      </div>

      <AppCard v-if="running || result || (formError && !confirmOpen)" class="workspace-agent__response" aria-live="polite">
        <p v-if="running">正在查询</p>
        <AppStatusCallout v-else-if="formError && !confirmOpen" tone="attention" :title="formError" />
        <template v-else-if="result?.kind === 'unknown'">
          <p>试试输入框里的任务示例</p>
        </template>
        <div v-else-if="result?.kind === 'preview_class'" class="workspace-agent__receipt">
          <span>新建班级 {{ result.class_ref }}</span>
          <AppButton variant="secondary" @click="formError = ''; confirmOpen = true">核对并确认</AppButton>
        </div>
        <p v-else-if="result?.kind === 'class_created'">已创建班级 {{ result.class_ref }}</p>
        <template v-else-if="result">
          <p>{{ config.taskTitle }}共 {{ result.total }} 项</p>
          <ul v-if="result.rows.length" class="workspace-agent__data">
            <li v-for="(row, index) in result.rows" :key="row.ref">
              <span>{{ row.label || `测评任务 ${index + 1}` }}</span>
              <small v-if="row.completed !== null && row.total !== null">已完成 {{ row.completed }} / {{ row.total }}</small>
              <small v-else-if="row.due_at">{{ dateLabel(row.due_at) }}截止</small>
              <small v-else-if="row.status">{{ statusLabels[row.status] || '查看详情' }}</small>
            </li>
          </ul>
        </template>
      </AppCard>
    </section>

    <nav class="workspace-agent__quick" aria-label="常用功能">
      <AppCard v-for="(entry, index) in config.entries" :key="entry.label" class="workspace-agent__tile" :class="'workspace-agent__tile--' + index">
        <component
          :is="agentMode ? 'button' : 'RouterLink'"
          :aria-label="entry.label"
          v-bind="agentMode ? { type: 'button', disabled: agentBusy, onClick: () => startQuickTask(index) } : { to: entry.to }"
          class="workspace-agent__entry"
        >
          <div class="workspace-agent__tile-top">
            <span class="workspace-agent__tile-icon"><component :is="entry.icon" :size="22" aria-hidden="true" /></span>
            <ArrowUpRight :size="16" aria-hidden="true" />
          </div>
          <strong>{{ entry.label }}</strong>
          <small v-if="entry.note">{{ entry.note }}</small>
        </component>
      </AppCard>
    </nav>

    <section class="workspace-agent__tasks" aria-labelledby="workspace-agent-tasks">
      <div class="workspace-agent__task-head">
        <h2 id="workspace-agent-tasks">{{ config.sectionTitle }}</h2>
        <AppButton class="workspace-agent__all" variant="quiet" @click="openNavigation?.()">全部入口 <ChevronRight :size="16" aria-hidden="true" /></AppButton>
      </div>
      <AppCard class="workspace-agent__records">
        <ul>
          <li v-for="(entry, index) in config.records" :key="entry.label">
            <RouterLink :to="entry.to" :aria-label="entry.label">
              <span class="workspace-agent__record-icon"><component :is="entry.icon" :size="21" aria-hidden="true" /></span>
              <span class="workspace-agent__record-copy">
                <strong>{{ entry.label }}</strong>
                <small v-if="index === 0 && overview && !overviewLoading && !overviewError && role !== 'school_admin'">{{ overview.total }} 项可查看</small>
                <small v-else>{{ entry.note }}</small>
              </span>
              <ChevronRight :size="17" aria-hidden="true" />
            </RouterLink>
          </li>
        </ul>
      </AppCard>
    </section>

    <p v-if="role === 'student' && isPublicDemo" class="workspace-agent__notice">
      <ShieldCheck :size="16" aria-hidden="true" />体验时请使用虚构内容
    </p>

    <AppDialog v-model:open="examplesOpen" title="任务示例" description="选择后可在输入框中修改">
      <div class="workspace-agent__examples">
        <AppButton v-for="example in suggestedCommands" :key="example" variant="secondary" :disabled="running || confirming" @click="useExample(example)">
          {{ example.trim() }}
        </AppButton>
      </div>
    </AppDialog>
    <WorkspaceTablePreview v-if="tablePreview" :name="tablePreview.name" :sheets="tablePreview.sheets" @close="tablePreview = undefined" @confirm="confirmTable" />
    <AppDialog
      :open="attachmentOpen"
      :title="attachment?.image ? '图片文字预览' : attachment?.document ? '文档文字预览' : '附件预览'"
      :description="attachment?.image ? '文字在这台设备上识别。请核对内容并删除个人信息后再插入' : attachment?.document ? '可选中要交给智能体处理的段落。插入前请移除个人信息和未经授权的内容' : role === 'student' ? '请先检查内容，移除姓名、学号等个人信息' : '文件内容在当前页面预览'"
      @update:open="attachmentOpen = $event; if (!$event) attachment = undefined"
    >
      <strong>{{ attachment?.name }}</strong>
      <small v-if="attachment?.document && attachment.document.characters > attachment.document.previewLength">显示前 {{ attachment.document.previewLength }} 字，共提取 {{ attachment.document.characters }} 字</small>
      <AppTextarea v-if="attachment?.image || attachment?.document" id="workspace-attachment-excerpt" v-model="attachment.content" :label="attachment.image ? '识别出的文字' : '提取的文字'" :rows="5" :maxlength="attachment.image ? 3000 : 12000" />
      <pre v-else class="workspace-agent__attachment">{{ attachment?.content }}</pre>
      <p v-if="attachmentError" class="workspace-agent__error" role="alert">{{ attachmentError }}</p>
      <div class="workspace-agent__confirm">
        <AppButton variant="secondary" @click="attachmentOpen = false; attachment = undefined">关闭</AppButton>
        <AppButton v-if="attachment?.document && role === 'psychological_specialist'" variant="secondary" @click="reviewDocumentForLibrary">核对并入库</AppButton>
        <AppButton v-if="role === 'student' || agentMode" @click="insertAttachment">插入到输入框</AppButton>
      </div>
    </AppDialog>
    <AppDialog
      :open="confirmOpen"
      title="确认新建班级"
      :description="`班级编号 ${result?.class_ref || ''}`"
      @update:open="(open) => { if (!confirming) confirmOpen = open }"
    >
      <AppStatusCallout v-if="formError" tone="attention" :title="formError" />
      <div class="workspace-agent__confirm">
        <AppButton variant="secondary" :disabled="confirming" @click="confirmOpen = false">返回</AppButton>
        <AppButton :loading="confirming" @click="confirm">确认创建</AppButton>
      </div>
    </AppDialog>
  </div>
</template>

<style scoped>
.workspace-agent { display: grid; gap: clamp(16px, 2.2vw, 28px); width: min(100% - 2 * clamp(16px, 2.8vw, 36px), 1220px); margin-inline: auto; padding: clamp(38px, 6vw, 78px) 0 30px; }
.workspace-agent__hero { display: grid; justify-items: center; gap: clamp(8px, 1.5vw, 16px); padding-bottom: clamp(6px, 1.7vw, 18px); text-align: center; }
.workspace-agent__hero h1 { margin: 0; font: 700 clamp(24px, 3.7vw, 42px)/1.23 var(--font-display); letter-spacing: -0.025em; }
.workspace-agent__mark { display: grid; place-items: center; width: clamp(48px, 6vw, 64px); aspect-ratio: 1; color: var(--color-primary-active); background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 50%; }
.workspace-agent__role { color: var(--color-text-secondary); font-size: clamp(13px, 1.8vw, 17px); }
.workspace-agent__composer { display: grid; gap: 3px; padding: clamp(10px, 1.7vw, 18px); border: 1px solid var(--color-border-strong); border-radius: calc(var(--radius-card) * 2.5); background: var(--color-surface); }
.workspace-agent__composer:focus-within { border-color: var(--color-primary); }
.workspace-agent__composer :deep(.app-textarea) { min-height: clamp(55px, 7vw, 78px); padding: 2px 4px; border: 0; outline: none; box-shadow: none; background: transparent; resize: none; font-size: clamp(16px, 2vw, 20px); }
.workspace-agent__composer :deep(.app-textarea::placeholder) { color: var(--color-text-secondary); opacity: 0.88; }
.workspace-agent__controls { display: flex; align-items: center; gap: clamp(6px, 1.7vw, 12px); min-width: 0; }
.workspace-agent__tools { display: flex; align-items: center; flex: 1; min-width: 0; }
.workspace-agent__tool, .workspace-agent__send { display: inline-grid; width: 44px; height: 44px; padding: 0; flex: 0 0 44px; place-items: center; }
.workspace-agent__send { border-radius: 50%; }
.workspace-agent__name, .workspace-agent__link { display: inline-flex; align-items: center; gap: 6px; }
.workspace-agent__name { color: var(--color-text-secondary); font-size: clamp(13px, 1.9vw, 17px); white-space: nowrap; }
.workspace-agent__name svg, .workspace-agent__link, .workspace-agent__all, .workspace-agent__record-icon { color: var(--color-primary-active); }
.workspace-agent__notice { display: flex; align-items: center; justify-content: center; gap: 6px; color: var(--color-text-secondary); font-size: 12px; }
.workspace-agent__response { display: grid; gap: 8px; margin-top: 10px; padding: 14px; border: 1px solid var(--color-border); font-size: 14px; }
.workspace-agent__receipt, .workspace-agent__task-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.workspace-agent__data { display: grid; gap: 6px; padding: 0; }
.workspace-agent__data li { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-block: 6px; border-top: 1px solid var(--color-border); }
.workspace-agent__data small { color: var(--color-text-secondary); }
.workspace-agent__quick { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(8px, 1.15vw, 14px); }
.workspace-agent__tile { border-radius: calc(var(--radius-card) * 2); box-shadow: none; }
.workspace-agent__tile--0 { background: color-mix(in srgb, var(--color-primary) 10%, var(--color-surface)); color: var(--color-primary-active); }
.workspace-agent__tile--1 { background: color-mix(in srgb, var(--color-chart-blue) 10%, var(--color-surface)); color: var(--indigo-11); }
.workspace-agent__tile--2 { background: color-mix(in srgb, var(--color-support) 10%, var(--color-surface)); color: var(--teal-11); }
.workspace-agent__tile--3 { background: color-mix(in srgb, var(--color-attention) 12%, var(--color-surface)); color: var(--amber-11); }
.workspace-agent__entry { display: grid; align-content: start; height: 100%; min-height: clamp(104px, 10.3vw, 148px); gap: clamp(4px, 1vw, 10px); padding: clamp(10px, 1.7vw, 20px); border: 1px solid transparent; border-radius: inherit; color: inherit; }
.workspace-agent__tile-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workspace-agent__tile-icon, .workspace-agent__record-icon { display: inline-grid; width: clamp(34px, 4.5vw, 48px); aspect-ratio: 1; place-items: center; border-radius: calc(var(--radius-card) * 1.6); background: var(--color-surface); }
.workspace-agent__entry strong, .workspace-agent__record-copy strong { color: var(--color-text-primary); font-size: clamp(14px, 1.65vw, 19px); font-weight: 600; overflow-wrap: anywhere; }
.workspace-agent__entry small, .workspace-agent__record-copy small { color: var(--color-text-secondary); font-size: clamp(11px, 1.35vw, 14px); line-height: 1.4; overflow-wrap: anywhere; }
.workspace-agent__entry:hover, .workspace-agent__entry:focus-visible { border-color: currentColor; }
button.workspace-agent__entry { width: 100%; text-align: start; background: transparent; cursor: pointer; }
.workspace-agent__tasks { display: grid; gap: 8px; min-width: 0; }
.workspace-agent__task-head h2 { margin: 0; font-size: clamp(17px, 2vw, 23px); font-weight: 690; }
.workspace-agent__all { min-height: 44px; padding: 0 0 0 10px; }
.workspace-agent__link { min-height: 38px; width: fit-content; font-size: 13px; }
.workspace-agent__link:hover { text-decoration: underline; }
.workspace-agent__records { padding: 0 clamp(10px, 1.7vw, 20px); border: 1px solid var(--color-border); border-radius: calc(var(--radius-card) * 2); box-shadow: none; }
.workspace-agent__records ul { margin: 0; padding: 0; list-style: none; }
.workspace-agent__records li + li { border-top: 1px solid var(--color-border); }
.workspace-agent__records li a { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: clamp(8px, 1.7vw, 16px); min-height: clamp(66px, 7vw, 90px); padding: 8px 2px; }
.workspace-agent__records li a:hover { background: var(--color-surface-muted); }
.workspace-agent__record-icon { background: var(--color-surface-muted); }
.workspace-agent__record-copy { display: grid; gap: 3px; min-width: 0; }
.workspace-agent__records li a > svg { color: var(--color-text-muted); }
.workspace-agent__confirm, .workspace-agent__examples { display: flex; flex-wrap: wrap; gap: 8px; }
.workspace-agent__confirm { justify-content: flex-end; margin-top: 12px; }
.workspace-agent__chat-links { display: flex; justify-content: flex-end; color: var(--color-primary-active); font-size: 13px; }
.workspace-agent__chat-links a { padding-block: 8px; }
.workspace-agent__error { color: var(--color-attention); font-size: 13px; }
.workspace-agent__chat-status { margin: 8px 4px 0; color: var(--color-text-secondary); font-size: 13px; }
.workspace-agent__attachment { max-height: 40vh; overflow: auto; padding: 12px; border-radius: var(--radius-control); background: var(--color-surface-muted); font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; }
#workspace-agent-composer, #workspace-agent-conversation { scroll-margin-top: 88px; }
</style>
