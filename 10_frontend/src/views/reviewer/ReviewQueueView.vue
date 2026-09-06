<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { FileCheck2 } from '@lucide/vue'
import { Filter } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { ReviewCase, ReviewQueueViewModel } from '@/types/view-models'

const state = ref<'loading' | 'ready' | 'error'>('loading')
const data = ref<ReviewQueueViewModel | null>(null)
const errorMessage = ref('')
const statusFilter = ref<'all' | ReviewCase['status']>('all')
const priorityFilter = ref<'all' | ReviewCase['priority']>('all')

const filteredCases = computed(() => {
  if (!data.value) return []
  return data.value.cases.filter((item) => (statusFilter.value === 'all' || item.status === statusFilter.value) && (priorityFilter.value === 'all' || item.priority === priorityFilter.value))
})

const statusLabel = (status: ReviewCase['status']) => ({ PENDING: '待处理', IN_REVIEW: '复核中', APPROVED: '已通过', REJECTED: '已退回' }[status])
const statusTone = (status: ReviewCase['status']) => status === 'APPROVED' ? 'teal' : status === 'REJECTED' ? 'neutral' : status === 'IN_REVIEW' ? 'blue' : 'amber'
const priorityLabel = (priority: ReviewCase['priority']) => ({ NORMAL: '常规', HIGH: '需要确认', CRITICAL: '紧急流程' }[priority])

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const response = await frontendApi.getReviewQueue()
    data.value = response.data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '复核队列暂时无法加载。'
  }
}

onMounted(load)
</script>

<template>
  <div class="content-wrap review-queue">
    <div v-if="state === 'loading'" class="queue-loading" aria-busy="true" aria-label="正在加载复核队列"><div class="skeleton skeleton--small"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--table"></div></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="复核队列暂时无法加载" :body="errorMessage"><button class="inline-retry" type="button" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</button></AppStatusCallout>
    <template v-else-if="data">
      <AppPageHeader eyebrow="安全复核" title="复核队列" intro="需要人工确认的流程会停在这里。先查看安全状态和授权摘要，再记录审核动作。" :fixture-label="data.fixtureLabel">
        <template #actions><AppBadge tone="amber" dot>{{ data.cases.filter((item) => item.status === 'PENDING').length }} 条待处理</AppBadge></template>
      </AppPageHeader>

      <AppStatusCallout tone="attention" title="风险会改变流程" body="进入复核后，普通个性化生成不会继续。此页面不发送通知，也不替代学校已审核的支持流程。" />

      <AppCard class="queue-filters">
        <div class="queue-filters__label"><Filter :size="16" aria-hidden="true" /><span>筛选当前队列</span></div>
        <label class="queue-select" for="status-filter"><span>状态</span><select id="status-filter" v-model="statusFilter"><option value="all">全部状态</option><option value="PENDING">待处理</option><option value="IN_REVIEW">复核中</option><option value="APPROVED">已通过</option><option value="REJECTED">已退回</option></select></label>
        <label class="queue-select" for="priority-filter"><span>优先级</span><select id="priority-filter" v-model="priorityFilter"><option value="all">全部优先级</option><option value="NORMAL">常规</option><option value="HIGH">需要确认</option><option value="CRITICAL">紧急流程</option></select></label>
        <span class="queue-filters__count">显示 {{ filteredCases.length }} / {{ data.cases.length }} 条</span>
      </AppCard>

      <AppCard v-if="filteredCases.length" class="queue-table" flush>
        <div class="queue-table__head"><span>案例 / 匿名主体</span><span>流程状态</span><span>优先级</span><span>更新时间</span><span class="sr-only">查看</span></div>
        <RouterLink v-for="item in filteredCases" :key="item.review_case_id" :to="`/reviewer/cases/${item.review_case_id}`" class="queue-row" :data-testid="`review-case-${item.review_case_id}`">
          <div class="queue-row__identity"><span class="queue-row__icon" aria-hidden="true"><FileCheck2 :size="17" /></span><span><strong>{{ item.review_case_id }}</strong><small>{{ item.subject_id }}</small></span></div>
          <div><AppBadge :tone="statusTone(item.status)" dot>{{ statusLabel(item.status) }}</AppBadge><small class="queue-row__subline">{{ item.summary }}</small></div>
          <span class="queue-row__priority" :class="{ 'queue-row__priority--high': item.priority !== 'NORMAL' }">{{ priorityLabel(item.priority) }}</span>
          <span class="queue-row__time">{{ item.updated_at }}</span>
          <ArrowRight class="queue-row__arrow" :size="16" aria-hidden="true" />
        </RouterLink>
      </AppCard>

      <AppCard v-else class="queue-empty">
        <FileCheck2 :size="22" aria-hidden="true" /><strong>{{ data.cases.length ? '没有符合筛选条件的记录' : '当前没有待处理记录' }}</strong><p>{{ data.cases.length ? '可以放宽状态或优先级筛选。' : '新的人工复核记录会在安全流程停止后出现在这里。' }}</p>
        <button v-if="data.cases.length" class="clear-filters" type="button" @click="statusFilter = 'all'; priorityFilter = 'all'">清除筛选</button>
      </AppCard>

      <p class="queue-footnote">展示范围：{{ data.fixtureLabel }}。队列中的标识为合成案例 ID，不代表真实学生。</p>
    </template>
  </div>
</template>

<style scoped>
.review-queue { animation: page-in 260ms ease both; }
.review-queue > .status-callout { margin-bottom: 17px; }
.queue-filters { display: flex; align-items: center; gap: 18px; margin-top: 17px; padding: 12px 15px; }
.queue-filters__label { display: inline-flex; align-items: center; gap: 8px; margin-right: auto; color: var(--color-text-primary); font-size: 12px; font-weight: 800; }.queue-filters__label svg { color: var(--color-primary); }
.queue-select { display: inline-flex; align-items: center; gap: 7px; color: var(--color-text-muted); font-size: 11px; font-weight: 700; }.queue-select select { min-height: 38px; padding: 0 28px 0 10px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; font-size: 12px; }
.queue-filters__count { color: var(--color-text-muted); font-family: var(--font-mono); font-size: 10px; white-space: nowrap; }
.queue-table { margin-top: 16px; }
.queue-table__head, .queue-row { display: grid; grid-template-columns: minmax(230px, 1.2fr) minmax(230px, 1.1fr) minmax(105px, 0.55fr) minmax(135px, 0.7fr) 22px; align-items: center; gap: 17px; padding: 12px 17px; }.queue-table__head { color: var(--color-text-muted); background: var(--color-surface-muted); font-size: 11px; font-weight: 800; }.queue-row { min-height: 78px; border-top: 1px solid var(--color-border); transition: background-color var(--motion-fast) ease; }.queue-row:hover { background: var(--color-surface-soft); }
.queue-row__identity { display: flex; align-items: center; gap: 10px; min-width: 0; }.queue-row__icon { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; flex: 0 0 34px; border-radius: 8px; color: var(--color-attention); background: var(--color-attention-wash); }.queue-row__identity > span:last-child { display: grid; gap: 3px; min-width: 0; }.queue-row strong { overflow: hidden; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.queue-row small { color: var(--color-text-muted); font-size: 10px; }.queue-row__subline { display: block; max-width: 250px; margin-top: 5px; overflow: hidden; color: var(--color-text-secondary) !important; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }.queue-row__priority { color: var(--color-text-secondary); font-size: 12px; font-weight: 700; }.queue-row__priority--high { color: var(--color-attention); }.queue-row__time { color: var(--color-text-secondary); font-size: 11px; }.queue-row__arrow { color: var(--color-text-muted); }
.queue-empty { display: grid; justify-items: center; padding: 52px 20px; text-align: center; color: var(--color-text-muted); }.queue-empty strong { margin-top: 13px; color: var(--color-text-primary); font-size: 14px; }.queue-empty p { margin: 7px 0 15px; color: var(--color-text-secondary); font-size: 12px; }.clear-filters { border: 0; color: var(--color-primary); background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; }.clear-filters:hover { text-decoration: underline; text-underline-offset: 3px; }.queue-footnote { margin: 13px 0 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
.inline-retry { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; font-size: 12px; font-weight: 700; }.inline-retry:hover { border-color: var(--color-primary); color: var(--color-primary); }
.queue-loading { padding-top: 12px; }.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }.skeleton--small { width: 140px; height: 14px; }.skeleton--title { width: 260px; height: 34px; margin-top: 17px; }.skeleton--table { height: 230px; margin-top: 32px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } } @keyframes shimmer { to { transform: translateX(100%); } }
@media (max-width: 840px) { .queue-filters { flex-wrap: wrap; gap: 11px; }.queue-filters__label { flex: 1 0 100%; }.queue-filters__count { margin-left: auto; }.queue-table { overflow: visible; }.queue-table__head { display: none; }.queue-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 13px; padding: 15px; }.queue-row > div:nth-child(2) { grid-column: 1 / -1; grid-row: 2; }.queue-row__priority { grid-column: 2; grid-row: 1; justify-self: end; }.queue-row__time { grid-column: 1; grid-row: 3; }.queue-row__arrow { grid-column: 2; grid-row: 3; justify-self: end; }.queue-row__subline { max-width: 100%; white-space: normal; } }
</style>
