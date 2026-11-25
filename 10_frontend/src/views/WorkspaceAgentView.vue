<script setup lang="ts">
/* global AbortController */
import { computed, nextTick, onUnmounted, ref, watch, type Component } from 'vue'
import { ArrowUp, ArrowUpRight, BookOpen, CalendarDays, CalendarHeart, ChartNoAxesCombined, ChevronRight, ClipboardCheck, ClipboardList, FileCheck2, FileUp, FolderOpen, HeartHandshake, Inbox, Layers, MessagesSquare, Network, Paperclip, Plus, Send, Server, ShieldCheck, Sparkles, Square, UsersRound } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import AppTextarea from '@/components/app/AppTextarea.vue'
import { runWorkspaceAgent, type WorkspaceAgentResult } from '@/services/workspace-agent'
import { useSessionStore } from '@/stores/session'
import type { Role } from '@/types/contracts'

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
      { label: '学习心理知识', to: '/student/support?topic=small_steps', icon: BookOpen, note: '从学习目标与压力应对开始' },
      { label: '获取心理支持', to: '/student/support', icon: HeartHandshake, note: '打开教育支持对话' },
      { label: '联系心理教师', to: '/student/school-support', icon: CalendarHeart, note: '查看校内支持渠道' },
    ],
    records: [
      { label: '我的心理测评', to: '/student/assessments', icon: ClipboardList, note: '查看待完成任务' },
      { label: '最近的支持对话', to: '/student/support', icon: MessagesSquare, note: '继续上次对话' },
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
function isWorkspaceRole(role: Role | null): role is WorkspaceRole {
  return role != null && Object.hasOwn(workspaces, role)
}

const role = computed<WorkspaceRole>(() => isWorkspaceRole(session.role) ? session.role : 'student')
const config = computed(() => workspaces[role.value])
const isPublicDemo = computed(() => session.user?.activeContext?.schoolRef.startsWith('PUBLICDEMO_'))
const command = ref('')
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

watch(() => [session.user?.userId, session.user?.activeContext?.schoolRef, role.value], () => {
  taskRequest?.abort()
  command.value = ''
  result.value = null
  overview.value = null
  formError.value = ''
  running.value = false
  confirming.value = false
  confirmOpen.value = false
  examplesOpen.value = false
  if (session.user?.activeContext) void loadOverview()
  else {
    overviewRequest?.abort()
    overviewLoading.value = false
    overviewError.value = false
  }
}, { immediate: true })

onUnmounted(() => {
  overviewRequest?.abort()
  taskRequest?.abort()
})

async function run() {
  const text = command.value.trim()
  if (!text || running.value || confirming.value) return
  const request = new AbortController()
  taskRequest = request
  running.value = true
  formError.value = ''
  result.value = null
  try {
    const data = await runWorkspaceAgent({ operation: 'run', text }, request.signal)
    if (!request.signal.aborted) {
      result.value = data
      if (data.kind.endsWith('_tasks') || data.kind === 'class_progress') overview.value = data
    }
  } catch {
    if (!request.signal.aborted) formError.value = '暂时无法处理，请重试'
  } finally {
    if (!request.signal.aborted) running.value = false
  }
}

function cancelRun() {
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
      <form ref="responseArea" class="workspace-agent__composer" @submit.prevent="run">
        <AppTextarea
          id="workspace-agent-input"
          v-model="command"
          label="输入任务"
          :placeholder="config.example"
          :maxlength="160"
          :rows="2"
          hide-label
          @keydown.ctrl.enter.prevent="run"
          @keydown.meta.enter.prevent="run"
        />
        <div class="workspace-agent__controls">
          <div class="workspace-agent__tools">
            <AppButton class="workspace-agent__tool" variant="quiet" aria-label="任务示例" title="任务示例" @click="examplesOpen = true">
              <Plus :size="20" aria-hidden="true" />
            </AppButton>
            <RouterLink v-if="role === 'school_admin'" class="workspace-agent__tool workspace-agent__tool-link" to="/admin/users" aria-label="导入名单" title="导入名单">
              <Paperclip :size="20" aria-hidden="true" />
            </RouterLink>
          </div>
          <span class="workspace-agent__name"><Sparkles :size="17" aria-hidden="true" />PsyNova Agent</span>
          <AppButton v-if="running" class="workspace-agent__tool" variant="quiet" aria-label="取消查询" title="取消查询" @click="cancelRun">
            <Square :size="16" aria-hidden="true" />
          </AppButton>
          <AppButton v-else class="workspace-agent__send" type="submit" :disabled="!command.trim() || confirming" aria-label="发送任务" title="发送任务">
            <ArrowUp :size="21" aria-hidden="true" />
          </AppButton>
        </div>
      </form>

      <AppCard v-if="running || result || (formError && !confirmOpen)" class="workspace-agent__response" aria-live="polite">
        <p v-if="running">正在查询</p>
        <AppStatusCallout v-else-if="formError && !confirmOpen" tone="attention" :title="formError" />
        <template v-else-if="result?.kind === 'unknown'">
          <p>试试输入框里的任务示例</p>
          <RouterLink v-if="role === 'student'" class="workspace-agent__link" to="/student/support">打开教育支持对话 <ChevronRight :size="16" /></RouterLink>
        </template>
        <RouterLink v-else-if="result?.kind === 'education_topic' && result.topic" class="workspace-agent__link" :to="{ path: '/student/support', query: { topic: result.topic } }">
          在教育支持中提问 <ChevronRight :size="16" />
        </RouterLink>
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
        <RouterLink :aria-label="entry.label" :to="entry.to" class="workspace-agent__entry">
          <div class="workspace-agent__tile-top">
            <span class="workspace-agent__tile-icon"><component :is="entry.icon" :size="22" aria-hidden="true" /></span>
            <ArrowUpRight :size="16" aria-hidden="true" />
          </div>
          <strong>{{ entry.label }}</strong>
          <small v-if="entry.note">{{ entry.note }}</small>
        </RouterLink>
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
.workspace-agent__tool-link { color: var(--color-text-secondary); border-radius: var(--radius-button); }
.workspace-agent__tool-link:hover { background: var(--color-surface-muted); color: var(--color-text-primary); }
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
</style>
