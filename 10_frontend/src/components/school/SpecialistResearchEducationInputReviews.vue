<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import {
  newResearchEducationInputReviewIdempotencyKey,
  schoolResearchEducationInputReviews,
  type ResearchEducationInputReviewDetail,
  type ResearchEducationInputReviewSummary,
  type ResearchEducationInputReviewTarget,
} from '@/services/school-research-education-input-reviews'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const props = defineProps<{ taskRef: string; disabled?: boolean }>()
const session = useSessionStore()
const rows = ref<ResearchEducationInputReviewSummary[]>([])
const detail = ref<ResearchEducationInputReviewDetail | null>(null)
const selected = ref<ResearchEducationInputReviewSummary | null>(null)
const offset = ref(0)
const hasMore = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const notice = ref('')
const target = ref<ResearchEducationInputReviewTarget | ''>('')
const confirmed = ref(false)
const pending = ref<(() => Promise<ResearchEducationInputReviewSummary>) | null>(null)
const nowMs = ref(Date.now())
let sequence = 0
let alive = true
let clockTimer: number | undefined

const allowed = computed(() => session.user?.role === 'psychological_specialist')
const canResolve = computed(() => Boolean(
  allowed.value && !busy.value && !props.disabled && !pending.value
  && selected.value?.status === 'PENDING'
  && Date.parse(selected.value.expires_at) > nowMs.value,
))
const selectedExpired = computed(() => Boolean(
  selected.value?.status === 'PENDING' && Date.parse(selected.value.expires_at) <= nowMs.value,
))

function clearState() {
  ++sequence
  rows.value = []
  detail.value = null
  selected.value = null
  offset.value = 0
  hasMore.value = false
  busy.value = false
  errorMessage.value = ''
  notice.value = ''
  target.value = ''
  confirmed.value = false
  pending.value = null
}

async function load(nextOffset = 0) {
  if (!allowed.value || !props.taskRef || pending.value) return
  const taskRef = props.taskRef
  const current = ++sequence
  busy.value = true
  errorMessage.value = ''
  notice.value = ''
  selected.value = null
  detail.value = null
  target.value = ''
  confirmed.value = false
  try {
    const page = await schoolResearchEducationInputReviews.list(taskRef, nextOffset, 20)
    if (!alive || current !== sequence || !allowed.value || taskRef !== props.taskRef) return
    rows.value = page.items
    offset.value = page.offset
    hasMore.value = page.has_more
  } catch (error) {
    if (current !== sequence) return
    rows.value = []
    errorMessage.value = userFacingApiError(error, '输入复核列表暂时无法加载。')
  } finally {
    if (current === sequence) busy.value = false
  }
}

async function open(item: ResearchEducationInputReviewSummary) {
  if (!allowed.value || busy.value || pending.value || item.task_ref !== props.taskRef) return
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
    const value = await schoolResearchEducationInputReviews.get(taskRef, item.input_review_ref)
    if (!alive || current !== sequence || !allowed.value || taskRef !== props.taskRef) return
    if (value.task_ref !== taskRef || value.input_review_ref !== item.input_review_ref) {
      throw new Error('Input review response did not match its task and reference.')
    }
    detail.value = value
    selected.value = value
  } catch (error) {
    if (current !== sequence) return
    selected.value = null
    detail.value = null
    errorMessage.value = userFacingApiError(error, '输入复核详情暂时无法加载。')
  } finally {
    if (current === sequence) busy.value = false
  }
}

async function sendPending() {
  const run = pending.value
  if (!run || busy.value || props.disabled || !allowed.value) return
  const current = ++sequence
  busy.value = true
  errorMessage.value = ''
  notice.value = ''
  try {
    const updated = await run()
    if (!alive || current !== sequence || !allowed.value) return
    pending.value = null
    selected.value = updated
    if (detail.value?.input_review_ref === updated.input_review_ref) {
      detail.value = Object.freeze({ ...detail.value, ...updated })
    }
    rows.value = rows.value.map((item) => (
      item.input_review_ref === updated.input_review_ref ? updated : item
    ))
    target.value = ''
    confirmed.value = false
    notice.value = updated.status === 'REJECTED' ? '已拒绝此输入复核请求。' : '已撤销此输入复核记录。'
  } catch (error) {
    if (current !== sequence) return
    errorMessage.value = userFacingApiError(error, '操作未完成。')
    const retryable = error && typeof error === 'object' && 'retryable' in error && error.retryable
    if (!retryable) pending.value = null
  } finally {
    if (current === sequence) busy.value = false
  }
}

function resolveSelected() {
  const row = selected.value
  const disposition = target.value
  if (!row || !canResolve.value || !confirmed.value || !disposition
    || row.status !== 'PENDING' || Date.parse(row.expires_at) <= Date.now()) return
  let key: string
  try {
    key = newResearchEducationInputReviewIdempotencyKey()
  } catch (error) {
    errorMessage.value = userFacingApiError(error, '无法安全建立本次复核请求。')
    return
  }
  const taskRef = props.taskRef
  pending.value = () => schoolResearchEducationInputReviews.resolve(taskRef, row, disposition, key)
  void sendPending()
}

function statusLabel(status: ResearchEducationInputReviewSummary['status']): string {
  return ({ PENDING: '待核对', REJECTED: '已拒绝', REVOKED: '已撤销' })[status]
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
  <AppCard v-if="allowed" class="input-reviews">
    <header class="input-reviews__header">
      <div>
        <h3>研究输入复核</h3>
        <p>核对固定研究请求，并记录拒绝或撤销决定。</p>
      </div>
      <AppButton variant="quiet" size="sm" :disabled="busy || Boolean(pending)" @click="load(offset)">刷新</AppButton>
    </header>

    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="busy" role="status" aria-busy="true">正在加载…</p>
    <AppStatusCallout v-if="errorMessage" tone="critical" title="输入复核不可用" :body="errorMessage">
      <AppButton v-if="pending" size="sm" :disabled="busy" @click="sendPending">使用同一请求重试</AppButton>
    </AppStatusCallout>

    <p v-if="!busy && !rows.length && !errorMessage">当前任务没有输入复核记录。</p>
    <ul v-if="rows.length" class="input-reviews__list" aria-label="输入复核列表">
      <li v-for="(item, index) in rows" :key="item.input_review_ref">
        <button
          type="button"
          class="input-reviews__row"
          :aria-current="selected?.input_review_ref === item.input_review_ref ? 'true' : undefined"
          :disabled="busy || Boolean(pending)"
          @click="open(item)"
        >
          <span>记录 {{ offset + index + 1 }} · {{ statusLabel(item.status) }}</span>
          <small>到期 {{ dateLabel(item.expires_at) }}</small>
        </button>
      </li>
    </ul>
    <nav v-if="offset || hasMore" class="input-reviews__pagination" aria-label="输入复核分页">
      <AppButton variant="quiet" size="sm" :disabled="busy || Boolean(pending) || offset === 0" @click="load(Math.max(0, offset - 20))">上一页</AppButton>
      <span>第 {{ Math.floor(offset / 20) + 1 }} 页</span>
      <AppButton variant="quiet" size="sm" :disabled="busy || Boolean(pending) || !hasMore" @click="load(offset + 20)">下一页</AppButton>
    </nav>

    <section v-if="detail" class="input-reviews__detail" aria-labelledby="input-review-title">
      <h4 id="input-review-title">输入内容需要核对</h4>
      <dl>
        <div><dt>状态</dt><dd>{{ statusLabel(detail.status) }}</dd></div>
        <div><dt>原因</dt><dd>输入内容需要核对</dd></div>
        <div><dt>创建时间</dt><dd>{{ dateLabel(detail.created_at) }}</dd></div>
        <div><dt>到期时间</dt><dd>{{ dateLabel(detail.expires_at) }}</dd></div>
      </dl>
      <h5>固定研究请求</h5>
      <blockquote>{{ detail.fixed_request }}</blockquote>
      <p v-if="selectedExpired" class="input-reviews__expired" role="status">此记录已过期，不能再进行状态变更。</p>
      <div v-if="detail.status === 'PENDING' && !selectedExpired" class="input-reviews__actions">
        <label for="input-review-disposition">确认处理</label>
        <select id="input-review-disposition" v-model="target" :disabled="!canResolve">
          <option value="">请选择</option>
          <option value="REJECTED">拒绝此输入复核请求</option>
          <option value="REVOKED">撤销此待处理记录</option>
        </select>
        <label class="input-reviews__confirm">
          <input v-model="confirmed" type="checkbox" :disabled="!canResolve">
          我已核对固定请求，并确认上述操作
        </label>
        <AppButton
          variant="secondary"
          size="sm"
          :disabled="!canResolve || !target || !confirmed"
          @click="resolveSelected"
        >
          确认{{ target === 'REJECTED' ? '拒绝' : target === 'REVOKED' ? '撤销' : '处理' }}
        </AppButton>
      </div>
    </section>
  </AppCard>
</template>

<style scoped>
.input-reviews { display: grid; gap: 12px; padding: 17px; min-width: 0; }
.input-reviews__header,.input-reviews__pagination,.input-reviews__actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.input-reviews__header { justify-content: space-between; align-items: flex-start; }
.input-reviews h3,.input-reviews h4,.input-reviews h5 { margin: 0; font-size: 15px; }
.input-reviews p,.input-reviews dt,.input-reviews dd,.input-reviews label,.input-reviews blockquote { margin: 4px 0; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.input-reviews__list { display: grid; gap: 6px; list-style: none; margin: 0; padding: 0; }
.input-reviews__row { display: flex; width: 100%; flex-wrap: wrap; justify-content: space-between; gap: 8px; border: 1px solid #dce8e2; border-radius: 8px; padding: 9px 11px; background: white; color: var(--color-text-primary); text-align: left; cursor: pointer; }
.input-reviews__row[aria-current='true'] { border-color: #438e7b; background: #f3faf6; }
.input-reviews__row small { color: var(--color-text-secondary); }
.input-reviews__pagination { justify-content: flex-end; }
.input-reviews__detail { display: grid; gap: 9px; border-top: 1px solid #e4ece8; padding-top: 14px; }
.input-reviews dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 6px 14px; margin: 0; }
.input-reviews dl div { min-width: 0; }
.input-reviews dt { color: var(--color-text-secondary); }
.input-reviews dd { margin-inline-start: 0; }
.input-reviews blockquote { border-inline-start: 3px solid #438e7b; padding: 8px 12px; background: #f7faf8; white-space: pre-wrap; }
.input-reviews__actions select { max-width: 100%; padding: 7px; border: 1px solid #d7e3de; border-radius: 6px; background: white; color: var(--color-text-primary); }
.input-reviews__confirm { display: flex; align-items: center; gap: 6px; }
.input-reviews__expired { color: #7a4300; }
.input-reviews :focus-visible { outline: 2px solid #438e7b; outline-offset: 3px; }
</style>
