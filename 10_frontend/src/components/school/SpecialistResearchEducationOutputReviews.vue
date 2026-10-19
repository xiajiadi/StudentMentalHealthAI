<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import ResearchFeedbackSources from '@/components/school/ResearchFeedbackSources.vue'
import {
  newResearchEducationOutputReviewIdempotencyKey,
  schoolResearchEducationOutputReviews,
  type ResearchEducationOutputReviewDetail,
  type ResearchEducationOutputReviewSummary,
  type ResearchEducationOutputReviewTarget,
} from '@/services/school-research-education-output-reviews'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const props = defineProps<{ taskRef: string; disabled?: boolean }>()
const emit = defineEmits<{ candidateCreated: [] }>()
const session = useSessionStore()
const rows = ref<ResearchEducationOutputReviewSummary[]>([])
const selected = ref<ResearchEducationOutputReviewSummary | null>(null)
const detail = ref<ResearchEducationOutputReviewDetail | null>(null)
const offset = ref(0)
const hasMore = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const notice = ref('')
const target = ref<ResearchEducationOutputReviewTarget | ''>('')
const confirmed = ref(false)
const nowMs = ref(Date.now())
let sequence = 0
let alive = true
let clockTimer: number | undefined

const allowed = computed(() => session.user?.role === 'psychological_specialist')
const selectedExpired = computed(() => Boolean(
  selected.value && Date.parse(selected.value.expires_at) <= nowMs.value,
))
const canResolve = computed(() => Boolean(
  allowed.value && !props.disabled && !busy.value && selected.value?.status === 'PENDING'
  && selected.value.state_version === 1 && !selectedExpired.value,
))

function clearState() {
  ++sequence
  rows.value = []
  selected.value = null
  detail.value = null
  offset.value = 0
  hasMore.value = false
  busy.value = false
  errorMessage.value = ''
  notice.value = ''
  target.value = ''
  confirmed.value = false
}

function isCurrent(current: number, taskRef: string): boolean {
  return alive && current === sequence && allowed.value && taskRef === props.taskRef
}

function mustRefreshAfterConflict(error: unknown): boolean {
  const code = error && typeof error === 'object' && 'code' in error
    ? String((error as { code?: unknown }).code).toUpperCase()
    : ''
  return [
    'FORBIDDEN', 'RESOURCE_NOT_FOUND', 'NOT_FOUND', 'WORKFLOW_CONFLICT',
    'OUTPUT_REVIEW_EXPIRED', 'VALIDATION_FAILED',
  ].includes(code)
}

async function load(nextOffset = 0, preserveFeedback = false) {
  if (!allowed.value || !props.taskRef) return
  const taskRef = props.taskRef
  const current = ++sequence
  busy.value = true
  if (!preserveFeedback) {
    errorMessage.value = ''
    notice.value = ''
  }
  selected.value = null
  detail.value = null
  target.value = ''
  confirmed.value = false
  try {
    const page = await schoolResearchEducationOutputReviews.list(taskRef, nextOffset, 20)
    if (!isCurrent(current, taskRef)) return
    rows.value = page.items
    offset.value = page.offset
    hasMore.value = page.has_more
  } catch (error) {
    if (!isCurrent(current, taskRef)) return
    rows.value = []
    hasMore.value = false
    errorMessage.value = userFacingApiError(error, '输出复核列表暂时无法加载。')
  } finally {
    if (current === sequence) busy.value = false
  }
}

async function open(item: ResearchEducationOutputReviewSummary) {
  if (!allowed.value || busy.value || item.task_ref !== props.taskRef) return
  const taskRef = props.taskRef
  const current = ++sequence
  busy.value = true
  errorMessage.value = ''
  notice.value = ''
  selected.value = item
  detail.value = null
  target.value = ''
  confirmed.value = false
  try {
    const value = await schoolResearchEducationOutputReviews.get(taskRef, item.output_review_ref)
    if (!isCurrent(current, taskRef)) return
    if (value.task_ref !== taskRef || value.output_review_ref !== item.output_review_ref) {
      throw new Error('Output review response did not match its task and reference.')
    }
    detail.value = value
    selected.value = value
  } catch (error) {
    if (!isCurrent(current, taskRef)) return
    selected.value = null
    detail.value = null
    errorMessage.value = userFacingApiError(error, '输出复核详情暂时无法加载。')
  } finally {
    if (current === sequence) busy.value = false
  }
}

async function resolveSelected() {
  const row = selected.value
  const disposition = target.value
  if (!row || !canResolve.value || !confirmed.value || !disposition
    || Date.parse(row.expires_at) <= Date.now()) return
  let key: string
  try {
    key = newResearchEducationOutputReviewIdempotencyKey()
  } catch (error) {
    errorMessage.value = userFacingApiError(error, '无法安全建立本次复核请求。')
    return
  }

  const taskRef = props.taskRef
  const current = ++sequence
  busy.value = true
  errorMessage.value = ''
  notice.value = ''
  let refresh = false
  let preserveFeedback = false
  try {
    const result = await schoolResearchEducationOutputReviews.resolve(taskRef, row, disposition, key)
    if (!isCurrent(current, taskRef)) return
    rows.value = rows.value.map((item) => (
      item.output_review_ref === result.output_review.output_review_ref ? result.output_review : item
    ))
    if (disposition === 'CREATE_HELD_CANDIDATE') {
      if (!result.candidate || result.candidate.task_ref !== taskRef || result.candidate.status !== 'HELD') {
        throw new Error('Held candidate response did not match its task.')
      }
      notice.value = '已转为待审候选。仍需单独采纳、复核并创建反馈草稿；本操作不代表 Safety 允许、心理专业批准或学生发布。'
      emit('candidateCreated')
    } else {
      notice.value = disposition === 'REJECTED'
        ? '已拒绝此输出复核记录。'
        : '已撤销此输出复核记录。'
    }
    selected.value = null
    detail.value = null
    target.value = ''
    confirmed.value = false
    refresh = true
    preserveFeedback = true
  } catch (error) {
    if (!isCurrent(current, taskRef)) return
    errorMessage.value = userFacingApiError(error, '输出复核操作未完成。')
    if (mustRefreshAfterConflict(error)) {
      selected.value = null
      detail.value = null
      target.value = ''
      confirmed.value = false
      refresh = true
      preserveFeedback = true
    }
  } finally {
    if (current === sequence) busy.value = false
  }
  if (refresh && current === sequence && allowed.value && taskRef === props.taskRef) {
    await load(offset.value, preserveFeedback)
  }
}

function statusLabel(status: ResearchEducationOutputReviewSummary['status']): string {
  return ({ PENDING: '待复核', REJECTED: '已拒绝', REVOKED: '已撤销', CONSUMED: '已转为候选' })[status]
}

function dateLabel(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
}

watch(() => [
  props.taskRef,
  session.user?.role,
  session.user?.userId,
  session.user?.subjectId,
  session.user?.activeContext?.role,
  session.user?.activeContext?.schoolRef,
] as const, () => {
  clearState()
  if (allowed.value) void load(0)
}, { immediate: true })

onMounted(() => {
  clockTimer = window.setInterval(() => { nowMs.value = Date.now() }, 30_000)
})

onBeforeUnmount(() => {
  alive = false
  if (clockTimer !== undefined) window.clearInterval(clockTimer)
  clearState()
})
</script>

<template>
  <AppCard v-if="allowed" class="output-reviews">
    <header class="output-reviews__header">
      <div>
        <h3>研究生成内容复核</h3>
        <p>仅供当前任务授权的心理老师复核。此操作不改变 Safety 决策，不代表 Safety 允许，也不代表心理专业批准。</p>
      </div>
      <AppButton variant="quiet" size="sm" :disabled="busy" @click="load(offset)">刷新</AppButton>
    </header>

    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="busy" role="status" aria-busy="true">正在加载…</p>
    <AppStatusCallout v-if="errorMessage" tone="critical" title="输出复核未完成" :body="errorMessage" />
    <p v-if="!busy && !rows.length && !errorMessage">当前任务没有输出复核记录。</p>

    <ul v-if="rows.length" class="output-reviews__list" aria-label="输出复核列表">
      <li v-for="(item, index) in rows" :key="item.output_review_ref">
        <button
          type="button"
          class="output-reviews__row"
          :aria-current="selected?.output_review_ref === item.output_review_ref ? 'true' : undefined"
          :disabled="busy || disabled"
          @click="open(item)"
        >
          <span>记录 {{ offset + index + 1 }}，{{ statusLabel(item.status) }}</span>
          <small>生成 {{ dateLabel(item.created_at) }}，到期 {{ dateLabel(item.expires_at) }}</small>
        </button>
      </li>
    </ul>
    <nav v-if="offset || hasMore" class="output-reviews__pagination" aria-label="输出复核分页">
      <AppButton variant="quiet" size="sm" :disabled="busy || offset === 0" @click="load(Math.max(0, offset - 20))">上一页</AppButton>
      <span>第 {{ Math.floor(offset / 20) + 1 }} 页</span>
      <AppButton variant="quiet" size="sm" :disabled="busy || !hasMore" @click="load(offset + 20)">下一页</AppButton>
    </nav>

    <section v-if="detail" class="output-reviews__detail" aria-labelledby="output-review-title">
      <h4 id="output-review-title">原始研究生成内容</h4>
      <dl>
        <div><dt>状态</dt><dd>{{ statusLabel(detail.status) }}</dd></div>
        <div><dt>Safety 状态</dt><dd>需要人工复核</dd></div>
        <div><dt>原因</dt><dd>内容需要核对（CONTENT_CONTROVERSIAL）</dd></div>
        <div><dt>创建时间</dt><dd>{{ dateLabel(detail.created_at) }}</dd></div>
        <div><dt>到期时间</dt><dd>{{ dateLabel(detail.expires_at) }}</dd></div>
      </dl>

      <p v-if="selectedExpired" class="output-reviews__expired" role="status">此记录已过期，不能再变更状态。</p>
      <div class="output-reviews__content">
        <h5>概述</h5><p>{{ detail.review_payload.content.summary }}</p>
        <h5>观察</h5>
        <ul><li v-for="(item, index) in detail.review_payload.content.observations" :key="index">{{ item }}</li></ul>
        <h5>建议</h5>
        <ul><li v-for="(item, index) in detail.review_payload.content.suggestions" :key="index">{{ item.text }}</li></ul>
        <h5>说明</h5><p>{{ detail.review_payload.content.disclaimer }}</p>
      </div>
      <ResearchFeedbackSources
        :source-cards="detail.review_payload.source_cards"
        title="检索来源（引用关系待校验）"
      />
      <p class="output-reviews__citation-note">
        当前来源卡表示检索到的材料，不代表已验证的正文引用；转为待审候选时仍会重新校验引用与来源。
      </p>
      <details class="output-reviews__provenance">
        <summary>生成与安全处理信息</summary>
        <dl>
          <div><dt>来源范围</dt><dd>{{ detail.review_payload.provenance.source_package_ref }}，{{ detail.review_payload.provenance.source_study_ref }}，{{ detail.review_payload.provenance.source_age_scope }} 岁</dd></div>
          <div><dt>生成模型</dt><dd>{{ detail.review_payload.provenance.model_id }}，{{ detail.review_payload.provenance.model_version }}</dd></div>
          <div><dt>提示版本</dt><dd>{{ detail.review_payload.provenance.prompt_version }}</dd></div>
          <div><dt>Safety 结果</dt><dd>输入 {{ detail.review_payload.provenance.input_safety_action }}；检索 {{ detail.review_payload.provenance.retrieval_safety_action }}；输出 {{ detail.review_payload.provenance.output_safety_action }}（需要人工复核）</dd></div>
        </dl>
      </details>

      <p class="output-reviews__boundary">
        复核并转为待审候选不等于 Safety 允许或心理专业批准。候选仍须独立采纳、进入个案复核、创建反馈草稿并单独发布；不会自动向学生展示。
      </p>
      <div v-if="detail.status === 'PENDING' && !selectedExpired" class="output-reviews__actions">
        <label for="output-review-target">确认处理</label>
        <select id="output-review-target" v-model="target" :disabled="!canResolve">
          <option value="">请选择</option>
          <option value="REJECTED">拒绝此输出复核</option>
          <option value="REVOKED">撤销此输出复核</option>
          <option value="CREATE_HELD_CANDIDATE">转为待审候选（HELD）</option>
        </select>
        <label class="output-reviews__confirm">
          <input v-model="confirmed" type="checkbox" :disabled="!canResolve">
          我已查看生成内容与检索来源，并确认上述操作
        </label>
        <AppButton
          variant="secondary"
          size="sm"
          :disabled="!canResolve || !target || !confirmed"
          @click="resolveSelected"
        >
          {{ target === 'CREATE_HELD_CANDIDATE' ? '确认转为待审候选' : target === 'REJECTED' ? '确认拒绝' : target === 'REVOKED' ? '确认撤销' : '确认处理' }}
        </AppButton>
      </div>
    </section>
  </AppCard>
</template>

<style scoped>
.output-reviews { display: grid; gap: 12px; padding: 17px; min-width: 0; }
.output-reviews__header,.output-reviews__pagination,.output-reviews__actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.output-reviews__header { justify-content: space-between; align-items: flex-start; }
.output-reviews h3,.output-reviews h4,.output-reviews h5 { margin: 0; font-size: 15px; }
.output-reviews p,.output-reviews li,.output-reviews dt,.output-reviews dd,.output-reviews label { margin: 4px 0; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.output-reviews__list { display: grid; gap: 6px; list-style: none; margin: 0; padding: 0; }
.output-reviews__row { display: flex; width: 100%; flex-wrap: wrap; justify-content: space-between; gap: 8px; border: 1px solid #dce8e2; border-radius: 8px; padding: 9px 11px; background: white; color: var(--color-text-primary); text-align: left; cursor: pointer; }
.output-reviews__row[aria-current='true'] { border-color: #438e7b; background: #f3faf6; }
.output-reviews__row small { color: var(--color-text-secondary); }
.output-reviews__pagination { justify-content: flex-end; }
.output-reviews__detail { display: grid; gap: 10px; border-top: 1px solid #e4ece8; padding-top: 14px; }
.output-reviews dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 6px 14px; margin: 0; }
.output-reviews dl div { min-width: 0; }
.output-reviews dt { color: var(--color-text-secondary); }
.output-reviews dd { margin-inline-start: 0; }
.output-reviews__content { display: grid; gap: 7px; border-top: 1px solid #e4ece8; padding-top: 12px; }
.output-reviews__content ul { margin: 0; padding-inline-start: 20px; }
.output-reviews__content p { white-space: pre-wrap; }
.output-reviews__citation-note,.output-reviews__boundary { border-inline-start: 3px solid #b27b20; padding-inline-start: 10px; }
.output-reviews__boundary { margin-top: 0; color: var(--color-text-secondary); }
.output-reviews__expired { color: #7a4300; }
.output-reviews__provenance summary { cursor: pointer; font-size: 12px; font-weight: 650; }
.output-reviews__actions select { max-width: 100%; padding: 7px; border: 1px solid #d7e3de; border-radius: 6px; background: white; color: var(--color-text-primary); }
.output-reviews__confirm { display: flex; align-items: center; gap: 6px; }
.output-reviews :focus-visible { outline: 2px solid #438e7b; outline-offset: 3px; }
</style>
