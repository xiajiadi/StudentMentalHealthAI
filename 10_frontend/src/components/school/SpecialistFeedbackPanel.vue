<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { getActivePinia } from 'pinia'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { useSessionStore } from '@/stores/session'
import {
  newSchoolFeedbackIdempotencyKey,
  schoolFeedback,
  type SchoolFeedback,
} from '@/services/school-feedback'
import { RealApiError } from '@/services/real-api'

const props = defineProps<{
  caseRef: string
  caseVersion: number
  caseStatus: 'OPEN' | 'IN_REVIEW' | 'APPROVED' | 'REJECTED'
}>()

const activePinia = getActivePinia()
const session = activePinia ? useSessionStore(activePinia) : null
const state = ref<'loading' | 'ready' | 'error'>('loading')
const rows = ref<SchoolFeedback[]>([])
const total = ref(0)
const errorMessage = ref('')
const title = ref('')
const body = ref('')
const busy = ref(false)
const confirmation = ref('')
const conflict = ref(false)
const failedRequest = ref<{ label: string; run: () => Promise<SchoolFeedback> } | null>(null)

let requestGeneration = 0
let mounted = true
const contextKey = () => session?.user?.activeContext ?? null

const formatDate = (value: string | null) => {
  if (!value) return '尚未发布'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const statusLabel = (status: SchoolFeedback['status']) => ({
  DRAFT: '草稿', PUBLISHED: '已发布', REVOKED: '已撤回',
}[status])

const accessLost = (error: unknown) => error instanceof RealApiError
  && ['FORBIDDEN', 'RESOURCE_NOT_FOUND', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(error.code)

function clearPrivateState() {
  ++requestGeneration
  rows.value = []
  total.value = 0
  title.value = ''
  body.value = ''
  confirmation.value = ''
  failedRequest.value = null
}

async function load() {
  const caseRef = props.caseRef
  const generation = ++requestGeneration
  rows.value = []
  total.value = 0
  title.value = ''
  body.value = ''
  confirmation.value = ''
  failedRequest.value = null
  errorMessage.value = ''
  conflict.value = false
  state.value = 'loading'
  try {
    const result = await schoolFeedback.listCase(caseRef)
    if (!mounted || generation !== requestGeneration || caseRef !== props.caseRef) return
    if (result.items.some((item) => item.case_ref !== caseRef)) {
      throw new RealApiError('API_INVALID_RESPONSE', '反馈记录与当前复核范围不一致。')
    }
    rows.value = result.items
    total.value = result.total
    state.value = 'ready'
  } catch (error) {
    if (!mounted || generation !== requestGeneration) return
    clearPrivateState()
    state.value = 'error'
    errorMessage.value = accessLost(error)
      ? '当前反馈访问状态已变化，页面缓存已清除。请刷新任务并确认当前指派。'
      : error instanceof Error ? error.message : '反馈记录暂时无法加载。'
  }
}

async function refreshAfterWrite() {
  await load()
}

async function execute(label: string, run: () => Promise<SchoolFeedback>) {
  if (busy.value || (failedRequest.value && failedRequest.value.run !== run)) return
  const generation = requestGeneration
  busy.value = true
  errorMessage.value = ''
  conflict.value = false
  try {
    const updated = await run()
    if (!mounted || generation !== requestGeneration || props.caseRef !== updated.case_ref) return
    failedRequest.value = null
    confirmation.value = ''
    if (label === '建立草稿') {
      title.value = ''
      body.value = ''
    }
    await refreshAfterWrite()
  } catch (error) {
    if (!mounted || generation !== requestGeneration) return
    if (accessLost(error)) clearPrivateState()
    else if (error instanceof RealApiError && ['WORKFLOW_CONFLICT', 'IDEMPOTENCY_CONFLICT'].includes(error.code)) {
      failedRequest.value = null
      conflict.value = true
      clearPrivateState()
    } else {
      const retryable = error instanceof RealApiError && (error.retryable
        || ['API_INVALID_RESPONSE', 'DEPENDENCY_TIMEOUT', 'DEPENDENCY_UNAVAILABLE'].includes(error.code))
      failedRequest.value = retryable ? { label, run } : null
    }
    state.value = accessLost(error) || conflict.value ? 'error' : 'ready'
    errorMessage.value = accessLost(error)
      ? '当前反馈访问状态已变化，页面缓存已清除。请刷新任务并确认当前指派。'
      : conflict.value
        ? '复核或反馈版本已变化，页面缓存已清除。请刷新后核对最新状态。'
        : error instanceof Error ? error.message : `${label}暂未完成。`
  } finally {
    if (mounted) busy.value = false
  }
}

function createDraft() {
  if (props.caseStatus !== 'APPROVED' || !title.value.trim() || !body.value.trim() || busy.value || failedRequest.value) return
  const requestTitle = title.value
  const requestBody = body.value
  const expectedCaseVersion = props.caseVersion
  const caseRef = props.caseRef
  const key = newSchoolFeedbackIdempotencyKey()
  const run = () => schoolFeedback.createDraft(caseRef, expectedCaseVersion, requestTitle, requestBody, key)
  void execute('建立草稿', run)
}

function publish(item: SchoolFeedback) {
  if (props.caseStatus !== 'APPROVED' || confirmation.value !== `publish:${item.feedback_ref}`
    || item.status !== 'DRAFT' || busy.value || failedRequest.value) return
  const key = newSchoolFeedbackIdempotencyKey()
  const run = () => schoolFeedback.publish(item, key)
  void execute('发布反馈', run)
}

function revoke(item: SchoolFeedback) {
  if (confirmation.value !== `revoke:${item.feedback_ref}` || item.status !== 'PUBLISHED'
    || busy.value || failedRequest.value) return
  const key = newSchoolFeedbackIdempotencyKey()
  const run = () => schoolFeedback.revoke(item, key)
  void execute('撤回反馈', run)
}

function retry() {
  if (!failedRequest.value || busy.value) return
  void execute(failedRequest.value.label, failedRequest.value.run)
}

watch(
  () => [props.caseRef, props.caseVersion, props.caseStatus, contextKey(), session?.user?.userId ?? null, session?.user?.role ?? null] as const,
  (next, previous) => {
    if (previous && (next[3] !== previous[3] || next[4] !== previous[4] || next[5] !== previous[5])
      && session?.user && session.user.role !== 'psychological_specialist') {
      clearPrivateState()
      state.value = 'error'
      errorMessage.value = '当前身份已变化，反馈页面缓存已清除。'
      return
    }
    void load()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  mounted = false
  clearPrivateState()
})
</script>

<template>
  <AppCard class="specialist-feedback" aria-label="任务反馈发布">
    <header class="specialist-feedback__header">
      <div>
        <span class="specialist-feedback__kicker">独立反馈版本</span>
        <h3>学生反馈</h3>
        <p>复核决定不会自动发布。这里单独保存、发布或撤回合成演示反馈。</p>
      </div>
      <AppButton variant="quiet" size="sm" :disabled="state === 'loading' || busy" aria-label="刷新反馈记录" @click="load">
        <RotateCcw :size="15" aria-hidden="true" />刷新
      </AppButton>
    </header>

    <AppStatusCallout
      tone="info"
      title="仅限合成演示 · L3"
      body="发布表示确认这条合成工作流记录可由当前学生查看，不代表测量学验证或临床批准。此处不提供 L2 反馈目录。"
    />

    <p v-if="props.caseStatus !== 'APPROVED'" class="specialist-feedback__gate">
      当前复核状态为“{{ props.caseStatus === 'REJECTED' ? '已退回' : props.caseStatus === 'OPEN' ? '待开始' : '处理中' }}”。复核获批后，才可建立或发布独立反馈。
    </p>

    <p v-if="state === 'loading'" class="specialist-feedback__state" role="status" aria-busy="true">正在读取反馈修订…</p>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="反馈记录暂不可用" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load">重新加载</AppButton>
    </AppStatusCallout>
    <template v-else>
      <div v-if="!rows.length" class="specialist-feedback__empty">这条复核记录还没有独立反馈。</div>
      <ol v-else class="feedback-revisions" aria-label="反馈修订">
        <li v-for="item in rows" :key="item.feedback_ref" class="feedback-revision">
          <header class="feedback-revision__header">
            <div><h4>{{ item.title }}</h4><small>修订 {{ item.content_revision }} · 状态版本 {{ item.state_version }}</small></div>
            <AppBadge :tone="item.status === 'PUBLISHED' ? 'teal' : item.status === 'REVOKED' ? 'amber' : 'neutral'" dot>{{ statusLabel(item.status) }}</AppBadge>
          </header>
          <p class="feedback-revision__body">{{ item.body }}</p>
          <p class="feedback-revision__time">建立于 {{ formatDate(item.created_at) }}<span v-if="item.published_at"> · 发布于 {{ formatDate(item.published_at) }}</span><span v-if="item.revoked_at"> · 撤回于 {{ formatDate(item.revoked_at) }}</span></p>
          <label v-if="item.status === 'DRAFT' && props.caseStatus === 'APPROVED'" class="feedback-confirmation">
            <input v-model="confirmation" type="radio" :value="`publish:${item.feedback_ref}`" :disabled="busy || Boolean(failedRequest)">
            <span>我确认仅在本任务的合成演示中发布这条反馈。</span>
          </label>
          <AppButton
            v-if="item.status === 'DRAFT' && props.caseStatus === 'APPROVED'"
            size="sm" :loading="busy" :disabled="confirmation !== `publish:${item.feedback_ref}` || Boolean(failedRequest)"
            @click="publish(item)"
          >
            发布给当前学生
          </AppButton>
          <label v-if="item.status === 'PUBLISHED'" class="feedback-confirmation">
            <input v-model="confirmation" type="radio" :value="`revoke:${item.feedback_ref}`" :disabled="busy || Boolean(failedRequest)">
            <span>我确认撤回这条反馈，学生将无法继续查看。</span>
          </label>
          <AppButton
            v-if="item.status === 'PUBLISHED'" variant="secondary" size="sm" :loading="busy"
            :disabled="confirmation !== `revoke:${item.feedback_ref}` || Boolean(failedRequest)"
            @click="revoke(item)"
          >
            撤回学生可见反馈
          </AppButton>
        </li>
      </ol>

      <form v-if="props.caseStatus === 'APPROVED'" class="feedback-draft" @submit.prevent="createDraft">
        <h4>建立不可覆盖的反馈修订</h4>
        <label for="feedback-title">标题</label>
        <input id="feedback-title" v-model="title" maxlength="120" required :disabled="busy || Boolean(failedRequest)" placeholder="输入简短标题">
        <label for="feedback-body">正文</label>
        <textarea id="feedback-body" v-model="body" maxlength="2000" rows="4" required :disabled="busy || Boolean(failedRequest)" placeholder="只写可供当前学生查看的合成教育反馈，不要粘贴复核备注。" />
        <div class="feedback-draft__footer"><small>{{ title.length }}/120 · {{ body.length }}/2000</small><AppButton type="submit" size="sm" :loading="busy" :disabled="!title.trim() || !body.trim() || Boolean(failedRequest)">建立草稿</AppButton></div>
      </form>
    </template>

    <div v-if="errorMessage && state === 'ready'" class="feedback-error" role="alert">
      <span>{{ errorMessage }}</span>
      <AppButton v-if="failedRequest" size="sm" :disabled="busy" @click="retry">{{ busy ? '正在重试…' : '使用相同请求重试' }}</AppButton>
      <AppButton v-else-if="conflict" variant="secondary" size="sm" :disabled="busy" @click="load">刷新反馈版本</AppButton>
    </div>
    <p class="specialist-feedback__count">{{ total }} 条反馈修订</p>
  </AppCard>
</template>

<style scoped>
.specialist-feedback { display: grid; gap: 14px; padding: 20px; }
.specialist-feedback__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.specialist-feedback__kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .06em; }
.specialist-feedback__header h3 { margin: 5px 0; color: var(--color-text-primary); font-size: 17px; }
.specialist-feedback__header p, .specialist-feedback__gate, .specialist-feedback__empty { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; }
.specialist-feedback__state { margin: 0; padding: 12px; color: var(--color-text-secondary); font-size: 12px; }
.feedback-revisions { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.feedback-revision { display: grid; gap: 9px; padding: 14px; border: 1px solid #e2ebe6; border-radius: 11px; background: #fff; }
.feedback-revision__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.feedback-revision__header h4, .feedback-draft h4 { margin: 0; color: var(--color-text-primary); font-size: 13px; }
.feedback-revision__header small, .feedback-revision__time, .feedback-draft__footer small { color: var(--color-text-muted); font-size: 10px; }
.feedback-revision__body { margin: 0; color: var(--color-text-primary); font-size: 12px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.feedback-revision__time { margin: 0; line-height: 1.5; }
.feedback-confirmation { display: flex; align-items: flex-start; gap: 8px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.feedback-confirmation input { margin-top: 2px; accent-color: #438e7b; }
.feedback-draft { display: grid; gap: 8px; padding-top: 14px; border-top: 1px solid #e9efec; }
.feedback-draft label { color: var(--color-text-primary); font-size: 11px; font-weight: 700; }
.feedback-draft input, .feedback-draft textarea { width: 100%; padding: 10px 11px; border: 1px solid #d7e3de; border-radius: 9px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 12px; line-height: 1.6; }
.feedback-draft textarea { resize: vertical; }
.feedback-draft input:focus-visible, .feedback-draft textarea:focus-visible { outline: 3px solid rgb(67 142 123 / 20%); border-color: #438e7b; }
.feedback-draft__footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.feedback-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 13px; border: 1px solid #ecd8d0; border-radius: 10px; color: #785449; background: #fff8f5; font-size: 12px; line-height: 1.55; }
.specialist-feedback__count { margin: 0; color: var(--color-text-muted); font-size: 10px; text-align: right; }
@media (max-width: 600px) {
  .specialist-feedback { padding: 15px; }
  .specialist-feedback__header, .feedback-revision__header { align-items: flex-start; flex-direction: column; }
  .feedback-error { align-items: flex-start; flex-direction: column; }
}
</style>
