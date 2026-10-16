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
  specialistIndependentEducationReviews,
  type IndependentEducationReviewDetail,
  type IndependentEducationSpecialistSummary,
} from '@/services/independent-education-reviews'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const PAGE_SIZE = 20
const session = useSessionStore()
const rows = ref<IndependentEducationSpecialistSummary[]>([])
const total = ref(0)
const offset = ref(0)
const listState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const listError = ref('')
const selectedRef = ref('')
const detail = ref<IndependentEducationReviewDetail | null>(null)
const detailState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const detailError = ref('')
const draftTitle = ref('')
const draftBody = ref('')
const publishConfirmed = ref(false)
const revokeConfirmed = ref(false)
const statusMessage = ref('')
const mutationError = ref('')
const mutationBusy = ref(false)
const pendingMutation = ref<{ label: string; reviewRef: string; key: string; run: () => Promise<unknown> } | null>(null)
const listSequence = ref(0)
const detailSequence = ref(0)
let mounted = false

const isSpecialist = computed(() => session.user?.role === 'psychological_specialist'
  && session.user?.activeContext?.role === 'psychological_specialist')
const hasMore = computed(() => offset.value + rows.value.length < total.value)
const canEditDraft = computed(() => Boolean(detail.value && ['SHARED', 'DRAFT'].includes(detail.value.status)))
const canPublish = computed(() => detail.value?.status === 'DRAFT' && detail.value.reviewed_draft !== null)
const canRevoke = computed(() => detail.value?.status === 'PUBLISHED')

function clearPrivateState() {
  rows.value = []
  total.value = 0
  offset.value = 0
  listError.value = ''
  selectedRef.value = ''
  detail.value = null
  detailError.value = ''
  draftTitle.value = ''
  draftBody.value = ''
  publishConfirmed.value = false
  revokeConfirmed.value = false
  statusMessage.value = ''
  mutationError.value = ''
  pendingMutation.value = null
  listSequence.value += 1
  detailSequence.value += 1
}

function statusLabel(status: IndependentEducationSpecialistSummary['status']) {
  return ({ HELD: '待分享', SHARED: '待核对', DRAFT: '修订草稿', PUBLISHED: '已发布', REVOKED: '已撤回', WITHDRAWN: '已撤回分享' })[status]
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function errorCode(error: unknown) {
  return error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
}

function accessLost(error: unknown) {
  return ['FORBIDDEN', 'RESOURCE_NOT_FOUND', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(errorCode(error))
}

function workflowConflict(error: unknown) {
  return ['WORKFLOW_CONFLICT', 'IDEMPOTENCY_CONFLICT'].includes(errorCode(error))
}

function isRetryable(error: unknown) {
  return Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable === true)
}

function clearDetail() {
  selectedRef.value = ''
  detail.value = null
  detailState.value = 'idle'
  detailError.value = ''
  draftTitle.value = ''
  draftBody.value = ''
  publishConfirmed.value = false
  revokeConfirmed.value = false
  detailSequence.value += 1
}

async function loadList(nextOffset = 0) {
  if (!isSpecialist.value) {
    clearPrivateState()
    listState.value = 'idle'
    return
  }
  const sequence = ++listSequence.value
  listState.value = 'loading'
  listError.value = ''
  mutationError.value = ''
  try {
    const page = await specialistIndependentEducationReviews.list(nextOffset, PAGE_SIZE)
    if (!mounted || sequence !== listSequence.value || !isSpecialist.value) return
    rows.value = page.items
    total.value = page.total
    offset.value = page.offset
    listState.value = 'ready'
    if (selectedRef.value && !page.items.some((item) => item.review_ref === selectedRef.value)) clearDetail()
  } catch (error) {
    if (sequence !== listSequence.value || !isSpecialist.value) return
    if (accessLost(error)) {
      clearPrivateState()
      listState.value = 'error'
      listError.value = '当前指派权限已变化，已清除页面中的复核内容。'
    } else {
      listError.value = userFacingApiError(error, '独立研究教育复核列表暂时无法加载。')
      listState.value = 'error'
    }
  }
}

async function openDetail(reviewRef: string) {
  if (!isSpecialist.value) return
  const sequence = ++detailSequence.value
  selectedRef.value = reviewRef
  detail.value = null
  detailState.value = 'loading'
  detailError.value = ''
  draftTitle.value = ''
  draftBody.value = ''
  publishConfirmed.value = false
  revokeConfirmed.value = false
  statusMessage.value = ''
  try {
    const result = await specialistIndependentEducationReviews.get(reviewRef)
    if (!mounted || sequence !== detailSequence.value || selectedRef.value !== reviewRef || !isSpecialist.value) return
    detail.value = result
    if (result.reviewed_draft) {
      draftTitle.value = result.reviewed_draft.title
      draftBody.value = result.reviewed_draft.body
    }
    detailState.value = 'ready'
  } catch (error) {
    if (sequence !== detailSequence.value || !isSpecialist.value) return
    detail.value = null
    detailState.value = 'error'
    if (accessLost(error)) {
      clearPrivateState()
      detailState.value = 'error'
      detailError.value = '当前指派权限或分享授权已变化，已清除页面中的复核内容。'
    } else {
      detailError.value = userFacingApiError(error, '复核内容暂时无法读取。')
    }
  }
}

function setPending(label: string, run: (key: string) => Promise<unknown>) {
  if (mutationBusy.value || pendingMutation.value || !detail.value) return
  const key = newIndependentEducationReviewIdempotencyKey()
  const reviewRef = detail.value.review_ref
  pendingMutation.value = { label, reviewRef, key, run: () => run(key) }
  void executePending()
}

async function executePending() {
  const operation = pendingMutation.value
  if (!operation || mutationBusy.value) return
  const sequence = detailSequence.value
  const reviewRef = selectedRef.value
  mutationBusy.value = true
  mutationError.value = ''
  statusMessage.value = ''
  try {
    await operation.run()
    if (!mounted || sequence !== detailSequence.value || selectedRef.value !== reviewRef || !isSpecialist.value) return
    pendingMutation.value = null
    publishConfirmed.value = false
    revokeConfirmed.value = false
    const successMessage = operation.label === '保存草稿' ? '修订草稿已保存。发布仍需单独确认。'
      : operation.label === '发布' ? '复核资料已发布给本人。此操作不代表任何专业或正式批准。'
        : '发布已撤回，学生将无法继续查看。'
    if (operation.label === '撤回发布') {
      clearDetail()
      await loadList(offset.value)
    } else {
      await Promise.all([loadList(offset.value), openDetail(operation.reviewRef)])
    }
    statusMessage.value = successMessage
  } catch (error) {
    if (accessLost(error)) {
      clearPrivateState()
      detailState.value = 'error'
      detailError.value = '当前指派权限或分享授权已变化，已清除页面中的复核内容。'
      return
    }
    if (workflowConflict(error)) {
      pendingMutation.value = null
      mutationError.value = '记录版本已变化，正在重新读取当前状态。'
      await Promise.all([loadList(offset.value), openDetail(operation.reviewRef)])
      return
    }
    mutationError.value = userFacingApiError(error, '研究教育复核操作没有完成。')
    if (!isRetryable(error)) pendingMutation.value = null
  } finally {
    mutationBusy.value = false
  }
}

function saveDraft() {
  const current = detail.value
  if (!current || !canEditDraft.value || !draftTitle.value.trim() || !draftBody.value.trim()) return
  const title = draftTitle.value
  const body = draftBody.value
  setPending('保存草稿', (key) => specialistIndependentEducationReviews.saveDraft(current, title, body, key))
}

function publish() {
  const current = detail.value
  if (!current || !canPublish.value || !publishConfirmed.value) return
  setPending('发布', (key) => specialistIndependentEducationReviews.publish(current, key))
}

function revoke() {
  const current = detail.value
  if (!current || !canRevoke.value || !revokeConfirmed.value) return
  setPending('撤回发布', (key) => specialistIndependentEducationReviews.revoke(current, key))
}

watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    clearPrivateState()
    if (mounted && isSpecialist.value) void loadList()
    else listState.value = 'idle'
  },
)

onMounted(() => {
  mounted = true
  if (isSpecialist.value) void loadList()
  else listState.value = 'idle'
})

onBeforeUnmount(() => {
  mounted = false
  clearPrivateState()
})
</script>

<template>
  <section class="independent-education-review-workspace" aria-labelledby="independent-education-review-title">
    <AppStatusCallout tone="info" title="独立研究教育内容复核" body="只查看学生明确分享的一份生成草稿及公开来源，不展示问题或私密对话历史。保存草稿不会发布；发布只代表研究演示工作流完成，不构成专业、临床、心理测量学、伦理或学校生产批准。" />
    <header class="independent-education-review-workspace__header">
      <div><span class="independent-education-review-workspace__kicker">指定分享 · 单稿复核</span><h2 id="independent-education-review-title">研究教育复核</h2><p>仅显示当前账号被明确指派的分享记录。</p></div>
      <AppButton variant="quiet" size="sm" :disabled="listState === 'loading' || mutationBusy" aria-label="刷新独立研究教育复核列表" @click="loadList(offset)"><RotateCcw :size="15" aria-hidden="true" />刷新列表</AppButton>
    </header>
    <p v-if="statusMessage" class="independent-education-review-workspace__notice" role="status">{{ statusMessage }}</p>
    <AppStatusCallout v-if="listState === 'loading'" tone="info" title="正在读取指定记录" body="列表只包含复核编号、状态和更新时间等元数据。" />
    <AppStatusCallout v-else-if="listState === 'error'" tone="attention" title="指定复核列表暂不可用" :body="listError"><AppButton variant="secondary" size="sm" @click="loadList(offset)">重新加载</AppButton></AppStatusCallout>
    <AppCard v-else-if="listState === 'ready' && rows.length === 0" class="independent-education-review-workspace__empty"><strong>暂无指派给你的研究教育复核</strong><p>学生明确分享后，指定记录才会出现在这里。</p></AppCard>
    <div v-else-if="listState === 'ready'" class="independent-education-review-workspace__grid">
      <AppCard class="independent-education-review-workspace__list">
        <h3>已指派记录</h3>
        <ul>
          <li v-for="item in rows" :key="item.review_ref">
            <button :class="{ 'is-selected': selectedRef === item.review_ref }" :aria-pressed="selectedRef === item.review_ref" :disabled="mutationBusy" @click="openDetail(item.review_ref)">
              <span><strong>{{ statusLabel(item.status) }}</strong><small>更新于 {{ formatDate(item.updated_at) }}</small></span>
              <AppBadge :tone="item.status === 'PUBLISHED' ? 'teal' : 'support'" dot>{{ statusLabel(item.status) }}</AppBadge>
            </button>
          </li>
        </ul>
        <footer v-if="total > PAGE_SIZE"><span>{{ offset + 1 }}–{{ offset + rows.length }} / {{ total }}</span><span><AppButton variant="quiet" size="sm" :disabled="mutationBusy || offset === 0" @click="loadList(Math.max(0, offset - PAGE_SIZE))">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="mutationBusy || !hasMore" @click="loadList(offset + PAGE_SIZE)">下一页</AppButton></span></footer>
      </AppCard>
      <div class="independent-education-review-workspace__detail">
        <AppStatusCallout v-if="detailState === 'idle'" tone="info" title="选择一条复核记录" body="选择后只会读取该项已分享的生成草稿、公开来源与安全追溯信息，不会打开对话历史。" />
        <AppStatusCallout v-else-if="detailState === 'loading'" tone="info" title="正在读取复核内容" body="正在验证当前指派与分享范围。" />
        <AppStatusCallout v-else-if="detailState === 'error'" tone="attention" title="复核内容无法读取" :body="detailError"><AppButton v-if="selectedRef" variant="secondary" size="sm" @click="openDetail(selectedRef)">重新读取</AppButton></AppStatusCallout>
        <template v-else-if="detail">
          <AppCard class="independent-education-review-workspace__candidate">
            <header><div><span class="independent-education-review-workspace__kicker">学生分享的原始生成内容</span><h3>原始内容保留不变</h3></div><AppBadge tone="support" dot>{{ statusLabel(detail.status) }}</AppBadge></header>
            <p>{{ detail.candidate.content.summary }}</p>
            <ul v-if="detail.candidate.content.observations.length"><li v-for="(item, index) in detail.candidate.content.observations" :key="`observation-${index}`">{{ item }}</li></ul>
            <ul v-if="detail.candidate.content.suggestions.length"><li v-for="(item, index) in detail.candidate.content.suggestions" :key="`suggestion-${index}`">{{ item.text }}</li></ul>
            <p>{{ detail.candidate.content.disclaimer }}</p>
            <div class="independent-education-review-workspace__citations"><strong>经服务端绑定的引用</strong><ul><li v-for="citation in detail.candidate.citations" :key="citation.citation_id"><span>{{ citation.title || '来源资料' }}</span><small v-if="citation.organization">{{ citation.organization }}</small><small v-if="citation.locator">{{ citation.locator }}</small></li></ul></div>
            <ResearchFeedbackSources :source-cards="detail.candidate.source_cards" />
            <details class="independent-education-review-workspace__provenance">
              <summary>工程追溯信息</summary>
              <dl>
                <div><dt>研究来源</dt><dd>{{ detail.candidate.provenance.source_package_ref }} · {{ detail.candidate.provenance.source_study_ref }}</dd></div>
                <div><dt>来源清单 SHA-256</dt><dd>{{ detail.candidate.provenance.source_manifest_sha256 }}</dd></div>
                <div><dt>检索</dt><dd>{{ detail.candidate.provenance.retrieval_id }} · {{ detail.candidate.provenance.retrieval_bundle_sha256 }}</dd></div>
                <div><dt>生成提示</dt><dd>{{ detail.candidate.provenance.prompt_id }} v{{ detail.candidate.provenance.prompt_version }} · {{ detail.candidate.provenance.prompt_sha256 ?? '未提供静态提示摘要' }}</dd></div>
                <div><dt>模型与运行时</dt><dd>{{ detail.candidate.provenance.model_id }} / {{ detail.candidate.provenance.logical_model_id }} · {{ detail.candidate.provenance.model_version }} · {{ detail.candidate.provenance.runtime_version }}</dd></div>
                <div><dt>原始安全检查</dt><dd>输入 {{ detail.candidate.provenance.input_safety_action }}（{{ detail.candidate.provenance.input_safety_reason_codes.join('、') || '无原因码' }}）；检索 {{ detail.candidate.provenance.retrieval_safety_action }}；输出 {{ detail.candidate.provenance.output_safety_action }}</dd></div>
                <div><dt>边界与引用</dt><dd>{{ detail.candidate.provenance.claim_boundary_status }} · {{ detail.candidate.provenance.citation_binding_status }}</dd></div>
              </dl>
            </details>
          </AppCard>

          <AppCard class="independent-education-review-workspace__draft">
            <header><div><span class="independent-education-review-workspace__kicker">单独保存的人工修订</span><h3>{{ detail.reviewed_draft ? '当前修订草稿' : '撰写修订草稿' }}</h3></div><AppBadge v-if="detail.reviewed_draft" tone="support" dot>未单独发布</AppBadge></header>
            <p v-if="detail.reviewed_draft" class="independent-education-review-workspace__draft-body">{{ detail.reviewed_draft.body }}</p>
            <p v-else class="independent-education-review-workspace__muted">原始生成内容不会自动作为学生可见草稿。请人工撰写并保存单独的标题与正文。</p>
            <form v-if="canEditDraft" class="independent-education-review-workspace__form" @submit.prevent="saveDraft">
              <label for="independent-education-review-title-input">标题</label>
              <input id="independent-education-review-title-input" v-model="draftTitle" maxlength="120" :disabled="mutationBusy || Boolean(pendingMutation)">
              <label for="independent-education-review-body-input">修订正文</label>
              <textarea id="independent-education-review-body-input" v-model="draftBody" maxlength="4000" rows="7" :disabled="mutationBusy || Boolean(pendingMutation)" />
              <p class="independent-education-review-workspace__muted">引用和来源由服务端从原候选复制，不能在此更换。保存后仍需单独发布。</p>
              <AppButton type="submit" size="sm" :disabled="mutationBusy || Boolean(pendingMutation) || !draftTitle.trim() || !draftBody.trim()" :loading="mutationBusy && pendingMutation?.label === '保存草稿'">保存修订草稿</AppButton>
            </form>
            <div v-if="detail.reviewed_draft" class="independent-education-review-workspace__citations">
              <strong>草稿沿用的来源</strong>
              <ResearchFeedbackSources :source-cards="detail.reviewed_draft.source_cards" />
            </div>
            <div v-if="canPublish" class="independent-education-review-workspace__confirm">
              <label><input v-model="publishConfirmed" type="checkbox" :disabled="mutationBusy || Boolean(pendingMutation)">我确认这是独立研究教育内容的工程复核发布，不代表专业、伦理、临床、心理测量学或学校生产批准。</label>
              <AppButton size="sm" :disabled="mutationBusy || Boolean(pendingMutation) || !publishConfirmed" :loading="mutationBusy && pendingMutation?.label === '发布'" @click="publish">发布给本人</AppButton>
            </div>
            <div v-if="canRevoke" class="independent-education-review-workspace__confirm">
              <label><input v-model="revokeConfirmed" type="checkbox" :disabled="mutationBusy || Boolean(pendingMutation)">我确认撤回这份已发布资料，使学生后续无法查看。</label>
              <AppButton variant="secondary" size="sm" :disabled="mutationBusy || Boolean(pendingMutation) || !revokeConfirmed" :loading="mutationBusy && pendingMutation?.label === '撤回发布'" @click="revoke">撤回发布</AppButton>
            </div>
            <AppStatusCallout v-if="pendingMutation && mutationError" tone="attention" title="操作状态未确认" :body="mutationError"><AppButton variant="secondary" size="sm" :disabled="mutationBusy" :loading="mutationBusy" @click="executePending">使用同一请求重试</AppButton></AppStatusCallout>
            <AppStatusCallout v-else-if="mutationError" tone="attention" title="复核状态已变化" :body="mutationError" />
            <p v-if="detail.reviewed_draft" class="independent-education-review-workspace__muted">修订于 {{ formatDate(detail.reviewed_draft.updated_at) }} · 内容版本 {{ detail.reviewed_draft.content_revision }}</p>
          </AppCard>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.independent-education-review-workspace { display: grid; gap: 12px; margin-top: 18px; }
.independent-education-review-workspace__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 14px; }
.independent-education-review-workspace__header h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 22px; }
.independent-education-review-workspace__header p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; }
.independent-education-review-workspace__kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.independent-education-review-workspace__grid { display: grid; grid-template-columns: minmax(220px, 280px) minmax(0, 1fr); align-items: start; gap: 12px; }
.independent-education-review-workspace__list,.independent-education-review-workspace__candidate,.independent-education-review-workspace__draft { display: grid; gap: 12px; min-width: 0; padding: 16px; }
.independent-education-review-workspace__list h3,.independent-education-review-workspace__candidate h3,.independent-education-review-workspace__draft h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.independent-education-review-workspace__list ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.independent-education-review-workspace__list li button { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; padding: 10px; border: 1px solid var(--color-border); border-radius: 9px; color: var(--color-text-primary); background: var(--color-surface); text-align: left; cursor: pointer; }
.independent-education-review-workspace__list li button.is-selected { border-color: #61a295; background: #f2f8f5; }
.independent-education-review-workspace__list li button span { display: grid; gap: 4px; }.independent-education-review-workspace__list li button small,.independent-education-review-workspace__list footer { color: var(--color-text-muted); font-size: 10px; }
.independent-education-review-workspace__list footer { display: flex; justify-content: space-between; gap: 6px; }.independent-education-review-workspace__list footer>span:last-child { display: flex; gap: 4px; }
.independent-education-review-workspace__detail { display: grid; gap: 12px; min-width: 0; }
.independent-education-review-workspace__candidate > header,.independent-education-review-workspace__draft > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.independent-education-review-workspace__candidate > p,.independent-education-review-workspace__candidate li,.independent-education-review-workspace__draft-body { margin: 0; color: var(--color-text-primary); font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.independent-education-review-workspace__candidate ul { display: grid; gap: 5px; margin: 0; padding-left: 20px; }
.independent-education-review-workspace__citations { display: grid; gap: 6px; padding-top: 10px; border-top: 1px solid var(--color-border); color: var(--color-text-secondary); font-size: 11px; }
.independent-education-review-workspace__citations ul { margin: 0; padding-left: 17px; }.independent-education-review-workspace__citations li { display: grid; gap: 2px; }.independent-education-review-workspace__citations small { color: var(--color-text-muted); font-size: 10px; }
.independent-education-review-workspace__provenance { padding-top: 9px; border-top: 1px solid var(--color-border); color: var(--color-text-secondary); font-size: 11px; }
.independent-education-review-workspace__provenance summary { cursor: pointer; font-weight: 700; }.independent-education-review-workspace__provenance dl { display: grid; gap: 7px; margin: 10px 0 0; }
.independent-education-review-workspace__provenance dl div { display: grid; grid-template-columns: minmax(100px, 140px) minmax(0, 1fr); gap: 9px; }.independent-education-review-workspace__provenance dt { color: var(--color-text-muted); }.independent-education-review-workspace__provenance dd { margin: 0; overflow-wrap: anywhere; color: var(--color-text-primary); }
.independent-education-review-workspace__form { display: grid; gap: 8px; }.independent-education-review-workspace__form label { color: var(--color-text-primary); font-size: 11px; font-weight: 700; }
.independent-education-review-workspace__form input,.independent-education-review-workspace__form textarea { width: 100%; padding: 9px 10px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-primary); background: var(--color-surface); font: inherit; }
.independent-education-review-workspace__form textarea { resize: vertical; line-height: 1.65; }.independent-education-review-workspace__muted { margin: 0; color: var(--color-text-muted); font-size: 10px; line-height: 1.6; }
.independent-education-review-workspace__confirm { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-top: 9px; border-top: 1px solid var(--color-border); }.independent-education-review-workspace__confirm label { display: flex; align-items: flex-start; gap: 7px; max-width: 680px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }.independent-education-review-workspace__confirm input { margin-top: 2px; }
.independent-education-review-workspace__empty { display: grid; gap: 6px; padding: 18px; }.independent-education-review-workspace__empty strong { font-size: 13px; }.independent-education-review-workspace__empty p { margin: 0; color: var(--color-text-secondary); font-size: 11px; }.independent-education-review-workspace :deep(.status-callout) { margin: 0; }
@media(max-width:800px) { .independent-education-review-workspace__grid { grid-template-columns: 1fr; }.independent-education-review-workspace__confirm { align-items: flex-start; flex-direction: column; } }
</style>
