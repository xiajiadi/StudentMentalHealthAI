<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import ResearchFeedbackSources from '@/components/school/ResearchFeedbackSources.vue'
import {
  newIndependentEducationReviewIdempotencyKey,
  studentIndependentEducationReviews,
  type IndependentEducationReviewSummary,
  type IndependentEducationReviewer,
} from '@/services/independent-education-reviews'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const PAGE_SIZE = 20
const props = defineProps<{ conversationId: string; refreshToken?: number }>()
const session = useSessionStore()
const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const rows = ref<IndependentEducationReviewSummary[]>([])
const reviewers = ref<IndependentEducationReviewer[]>([])
const total = ref(0)
const offset = ref(0)
const requestError = ref('')
const statusMessage = ref('')
const pendingAction = ref<{ reviewRef: string; label: string; key: string; run: () => Promise<IndependentEducationReviewSummary> } | null>(null)
const mutationError = ref('')
const mutationBusy = ref(false)
const selectedReviewer = ref<Record<string, string>>({})
const shareConsent = ref<Record<string, boolean>>({})
const sequence = ref(0)
let mounted = false
let lastLoadedRefreshToken = props.refreshToken ?? 0

const isStudent = computed(() => session.user?.role === 'student'
  && session.user?.activeContext?.role === 'student')
const hasMore = computed(() => offset.value + rows.value.length < total.value)

function clearPrivateState() {
  rows.value = []
  reviewers.value = []
  total.value = 0
  offset.value = 0
  requestError.value = ''
  statusMessage.value = ''
  mutationError.value = ''
  pendingAction.value = null
  selectedReviewer.value = {}
  shareConsent.value = {}
  sequence.value += 1
}

function statusLabel(status: IndependentEducationReviewSummary['status']) {
  return ({ HELD: '待分享', SHARED: '已分享给心理老师', DRAFT: '老师正在修订', PUBLISHED: '已发布复核资料', REVOKED: '已撤回发布', WITHDRAWN: '已撤回分享' })[status]
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function accessLost(error: unknown) {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  return ['FORBIDDEN', 'RESOURCE_NOT_FOUND', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(code)
}

function workflowConflict(error: unknown) {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  return code === 'WORKFLOW_CONFLICT' || code === 'IDEMPOTENCY_CONFLICT'
}

function isRetryable(error: unknown) {
  return Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable === true)
}

async function load(nextOffset = 0) {
  if (!isStudent.value || !props.conversationId) {
    clearPrivateState()
    state.value = 'idle'
    return
  }
  const current = ++sequence.value
  const conversationId = props.conversationId
  lastLoadedRefreshToken = props.refreshToken ?? 0
  state.value = 'loading'
  requestError.value = ''
  mutationError.value = ''
  try {
    const page = await studentIndependentEducationReviews.list(conversationId, nextOffset, PAGE_SIZE)
    if (!mounted || current !== sequence.value || conversationId !== props.conversationId || !isStudent.value) return
    rows.value = page.items
    total.value = page.total
    offset.value = page.offset
    selectedReviewer.value = {}
    shareConsent.value = {}
    if (page.items.some((row) => row.status === 'HELD' || row.reviewer_ref !== null)) {
      const reviewerPage = await studentIndependentEducationReviews.listReviewers(conversationId, 0, PAGE_SIZE)
      if (!mounted || current !== sequence.value || conversationId !== props.conversationId || !isStudent.value) return
      reviewers.value = reviewerPage.items
    } else {
      reviewers.value = []
    }
    state.value = 'ready'
  } catch (error) {
    if (!mounted || current !== sequence.value || conversationId !== props.conversationId || !isStudent.value) return
    rows.value = []
    reviewers.value = []
    total.value = 0
    state.value = 'error'
    if (accessLost(error)) {
      clearPrivateState()
      requestError.value = '当前会话权限已变化，已清除页面中的研究复核信息。'
    } else {
      requestError.value = userFacingApiError(error, '研究教育复核信息暂时无法加载。')
    }
  }
}

async function executePending() {
  const operation = pendingAction.value
  if (!operation || mutationBusy.value) return
  const conversationId = props.conversationId
  const current = sequence.value
  mutationBusy.value = true
  mutationError.value = ''
  statusMessage.value = ''
  try {
    const updated = await operation.run()
    if (!mounted || current !== sequence.value || conversationId !== props.conversationId || !isStudent.value) return
    rows.value = rows.value.map((row) => row.review_ref === updated.review_ref ? updated : row)
    pendingAction.value = null
    statusMessage.value = operation.label === '分享' ? '分享状态已更新。' : '撤回状态已更新，老师将无法继续查看这份资料。'
    await load(offset.value)
  } catch (error) {
    if (!mounted || current !== sequence.value || conversationId !== props.conversationId || !isStudent.value) return
    if (accessLost(error)) {
      clearPrivateState()
      state.value = 'error'
      requestError.value = '当前会话权限已变化，已清除页面中的研究复核信息。'
      return
    }
    if (workflowConflict(error)) {
      pendingAction.value = null
      mutationError.value = '记录状态已变化，正在刷新当前状态。'
      await load(offset.value)
      return
    }
    mutationError.value = userFacingApiError(error, '研究教育复核操作没有完成。')
    if (!isRetryable(error)) pendingAction.value = null
  } finally {
    mutationBusy.value = false
    if (mounted && conversationId === props.conversationId && isStudent.value
      && lastLoadedRefreshToken !== (props.refreshToken ?? 0)) {
      void load(offset.value)
    }
  }
}

function share(row: IndependentEducationReviewSummary) {
  const reviewerRef = selectedReviewer.value[row.review_ref] ?? ''
  if (row.status !== 'HELD' || !reviewerRef || !shareConsent.value[row.review_ref] || pendingAction.value) return
  const key = newIndependentEducationReviewIdempotencyKey()
  const conversationId = props.conversationId
  pendingAction.value = {
    reviewRef: row.review_ref,
    label: '分享',
    key,
    run: () => studentIndependentEducationReviews.share(conversationId, row, reviewerRef, key),
  }
  void executePending()
}

function withdraw(row: IndependentEducationReviewSummary) {
  if (row.status === 'WITHDRAWN' || pendingAction.value) return
  const key = newIndependentEducationReviewIdempotencyKey()
  const conversationId = props.conversationId
  pendingAction.value = {
    reviewRef: row.review_ref,
    label: '撤回',
    key,
    run: () => studentIndependentEducationReviews.withdraw(conversationId, row, key),
  }
  void executePending()
}

watch(
  () => [props.conversationId, session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    clearPrivateState()
    if (mounted && isStudent.value) void load()
    else state.value = 'idle'
  },
)

watch(
  () => props.refreshToken ?? 0,
  (next, previous) => {
    if (next === previous || !mounted || !isStudent.value) return
    if (!mutationBusy.value) void load(offset.value)
  },
)

onMounted(() => {
  mounted = true
  if (isStudent.value) void load()
  else state.value = 'idle'
})

onBeforeUnmount(() => {
  mounted = false
  clearPrivateState()
})
</script>

<template>
  <section class="independent-education-reviews" aria-labelledby="independent-education-reviews-title">
    <header class="independent-education-reviews__header">
      <div><span class="independent-education-reviews__kicker">独立研究教育支持</span><h2 id="independent-education-reviews-title">资料分享与复核状态</h2><p>未分享的草稿正文不会显示在这里。</p></div>
      <AppButton variant="quiet" size="sm" :disabled="state === 'loading' || mutationBusy" aria-label="刷新研究教育复核状态" @click="load(offset)"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton>
    </header>
    <AppStatusCallout tone="info" title="按需分享一份资料" body="分享仅涉及这份生成草稿和公开来源，可能包含问题中反映的信息；不会共享原始问题、其他消息或历史、测评作答或报告。分享给心理老师不代表专业批准。撤回后老师将不能继续查看，已发布内容也会停止显示。" />
    <p v-if="statusMessage" class="independent-education-reviews__notice" role="status">{{ statusMessage }}</p>
    <p v-if="state === 'loading'" class="independent-education-reviews__state" role="status" aria-busy="true">正在读取复核状态…</p>
    <AppStatusCallout v-else-if="state === 'error'" tone="attention" title="研究复核状态暂不可用" :body="requestError"><AppButton variant="secondary" size="sm" @click="load(offset)">重新加载</AppButton></AppStatusCallout>
    <AppCard v-else-if="state === 'ready' && rows.length === 0" class="independent-education-reviews__empty"><strong>当前会话没有可显示的复核记录</strong><p>生成内容须经过独立分享与复核流程后才可能显示。</p></AppCard>
    <div v-else-if="state === 'ready'" class="independent-education-reviews__list">
      <AppCard v-for="item in rows" :key="item.review_ref" class="independent-education-reviews__item">
        <header><div><h3>{{ statusLabel(item.status) }}</h3><p>更新于 {{ formatDate(item.updated_at) }}</p></div><AppBadge :tone="item.status === 'PUBLISHED' ? 'teal' : 'support'" dot>{{ statusLabel(item.status) }}</AppBadge></header>
        <div v-if="item.status === 'HELD'" class="independent-education-reviews__share">
          <label :for="`education-reviewer-${item.review_ref}`">选择一位本校心理老师</label>
          <select :id="`education-reviewer-${item.review_ref}`" v-model="selectedReviewer[item.review_ref]" :disabled="mutationBusy || Boolean(pendingAction)">
            <option value="">请选择</option>
            <option v-for="reviewer in reviewers" :key="reviewer.reviewer_ref" :value="reviewer.reviewer_ref">{{ reviewer.display_name }}</option>
          </select>
          <p v-if="reviewers.length === 0" class="independent-education-reviews__muted">当前没有可选的本校心理老师。</p>
          <label class="independent-education-reviews__consent"><input v-model="shareConsent[item.review_ref]" type="checkbox" :disabled="mutationBusy || Boolean(pendingAction)"><span>我已了解分享范围和撤回影响，并同意仅向上方所选心理老师分享这份草稿及其公开来源。</span></label>
          <AppButton size="sm" :disabled="mutationBusy || Boolean(pendingAction) || !selectedReviewer[item.review_ref] || !shareConsent[item.review_ref]" @click="share(item)">分享给所选心理老师</AppButton>
        </div>
        <div v-if="item.status !== 'WITHDRAWN'" class="independent-education-reviews__withdraw">
          <AppButton variant="quiet" size="sm" :disabled="mutationBusy || Boolean(pendingAction)" @click="withdraw(item)">撤回分享</AppButton>
        </div>
        <AppStatusCallout v-if="pendingAction?.reviewRef === item.review_ref && mutationError" tone="attention" title="操作状态未确认" :body="mutationError">
          <AppButton variant="secondary" size="sm" :disabled="mutationBusy" :loading="mutationBusy" @click="executePending">使用同一请求重试</AppButton>
        </AppStatusCallout>
        <AppStatusCallout v-else-if="mutationError && !pendingAction" tone="attention" title="记录已变化" :body="mutationError" />
        <div v-if="item.status === 'PUBLISHED' && item.published_content" class="independent-education-reviews__published">
          <h4>{{ item.published_content.title }}</h4>
          <p class="independent-education-reviews__body">{{ item.published_content.body }}</p>
          <ResearchFeedbackSources :source-cards="item.published_content.source_cards" />
          <p class="independent-education-reviews__muted">发布时间：{{ formatDate(item.published_content.published_at) }}</p>
          <p class="independent-education-reviews__boundary">这是经人工修订后单独发布的一般教育资料，不是个人测评解释、诊断或治疗建议，也不代表正式心理、伦理或学校生产批准。</p>
        </div>
      </AppCard>
    </div>
    <footer v-if="state === 'ready' && total > PAGE_SIZE" class="independent-education-reviews__pager">
      <span>{{ offset + 1 }}–{{ offset + rows.length }} / {{ total }}</span>
      <span><AppButton variant="quiet" size="sm" :disabled="state === 'loading' || mutationBusy || offset === 0" @click="load(Math.max(0, offset - PAGE_SIZE))">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="state === 'loading' || mutationBusy || !hasMore" @click="load(offset + PAGE_SIZE)">下一页</AppButton></span>
    </footer>
  </section>
</template>

<style scoped>
.independent-education-reviews { display: grid; gap: 12px; margin-top: 22px; }
.independent-education-reviews__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 14px; }
.independent-education-reviews__header h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 22px; }
.independent-education-reviews__header p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.independent-education-reviews__kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.independent-education-reviews__list { display: grid; gap: 10px; }
.independent-education-reviews__item { display: grid; gap: 12px; padding: 16px 18px; }
.independent-education-reviews__item > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.independent-education-reviews__item h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.independent-education-reviews__item header p,.independent-education-reviews__muted,.independent-education-reviews__state { margin: 5px 0 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
.independent-education-reviews__share { display: grid; gap: 9px; padding-top: 10px; border-top: 1px solid var(--color-border); }
.independent-education-reviews__share > label:first-child { color: var(--color-text-primary); font-size: 12px; font-weight: 700; }
.independent-education-reviews__share select { width: min(100%, 420px); min-height: 38px; padding: 7px 10px; border: 1px solid var(--color-border); border-radius: 9px; color: var(--color-text-primary); background: var(--color-surface); }
.independent-education-reviews__consent { display: flex; align-items: flex-start; gap: 8px; max-width: 760px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.independent-education-reviews__consent input { margin-top: 2px; }
.independent-education-reviews__withdraw { justify-self: end; }
.independent-education-reviews__published { display: grid; gap: 9px; padding-top: 12px; border-top: 1px solid var(--color-border); }
.independent-education-reviews__published h4 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.independent-education-reviews__body { margin: 0; color: var(--color-text-primary); font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.independent-education-reviews__boundary { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.independent-education-reviews__pager { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--color-text-muted); font-size: 10px; }
.independent-education-reviews__pager > span:last-child { display: flex; gap: 5px; }
.independent-education-reviews :deep(.status-callout) { margin: 0; }
@media(max-width:680px) { .independent-education-reviews__header,.independent-education-reviews__item > header { align-items: flex-start; flex-direction: column; }.independent-education-reviews__pager { align-items: flex-start; flex-direction: column; } }
</style>
