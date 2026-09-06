<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft } from '@lucide/vue'
import { Check } from '@lucide/vue'
import { FileCheck2 } from '@lucide/vue'
import { Info } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import { ShieldAlert } from '@lucide/vue'
import { X } from '@lucide/vue'
import EvidenceItem from '@/components/evidence/EvidenceItem.vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import AppTextarea from '@/components/app/AppTextarea.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { ReviewDetailViewModel, ReviewWorkflowStatus } from '@/types/view-models'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const data = ref<ReviewDetailViewModel | null>(null)
const errorMessage = ref('')
const note = ref('')
const isSubmitting = ref(false)
const actionDialog = ref<'approved' | 'rejected' | null>(null)
const actionError = ref('')

const caseId = computed(() => typeof route.params.id === 'string' ? route.params.id : 'REVIEW_demo_001')
const statusLabel = (status: ReviewWorkflowStatus) => ({ PENDING: '待处理', IN_REVIEW: '复核中', APPROVED: '已通过', REJECTED: '已退回' }[status])
const actionTitle = computed(() => actionDialog.value === 'approved' ? '确认通过这条复核记录？' : '确认退回这条复核记录？')
const actionBody = computed(() => actionDialog.value === 'approved' ? '确认后，记录会进入后续授权流程；原始测评、引用和模型版本不会被修改。' : '确认后，该记录不会进入后续发布流程；原始测评、引用和模型版本不会被修改。')
const actionDialogOpen = computed({
  get: () => actionDialog.value !== null,
  set: (open: boolean) => {
    if (!open) actionDialog.value = null
  },
})

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const response = await frontendApi.getReviewDetail(caseId.value)
    data.value = response.data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '复核详情暂时无法加载。'
  }
}

const openAction = (action: 'approved' | 'rejected') => {
  actionError.value = ''
  actionDialog.value = action
}

const submitAction = async () => {
  if (!data.value || !actionDialog.value) return
  isSubmitting.value = true
  actionError.value = ''
  try {
    const response = await frontendApi.submitReview(data.value.case.report_id, { decision: actionDialog.value, note: note.value.trim() })
    data.value.case = response.data
    data.value.allowedActions = []
    data.value.timeline = data.value.timeline.map((item) => item.label === '审核结果'
      ? { ...item, detail: response.data.status === 'APPROVED' ? '复核已通过' : '复核已退回', time: '刚刚', tone: 'done' as const }
      : item)
    actionDialog.value = null
  } catch (error) {
    actionError.value = error instanceof MockApiError ? error.message : '审核动作没有完成，请重试。'
  } finally {
    isSubmitting.value = false
  }
}

const goBack = () => void router.push('/reviewer/queue')

onMounted(load)
</script>

<template>
  <div class="content-wrap review-detail">
    <div v-if="state === 'loading'" class="detail-loading" aria-busy="true" aria-label="正在加载复核详情"><div class="skeleton skeleton--small"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--panel"></div></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="复核详情暂时无法加载" :body="errorMessage"><AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton></AppStatusCallout>
    <template v-else-if="data">
      <AppPageHeader eyebrow="安全复核 / 详情" :title="data.case.review_case_id" intro="在授权摘要范围内完成一次可追溯的人工确认。" :fixture-label="data.fixtureLabel">
        <template #actions><AppButton variant="quiet" size="sm" @click="goBack"><ArrowLeft :size="15" aria-hidden="true" />返回队列</AppButton></template>
      </AppPageHeader>

      <AppStatusCallout tone="critical" title="普通生成已暂停，等待人工复核" :body="data.case.summary">
        <div class="detail-safety-meta"><span><ShieldAlert :size="15" aria-hidden="true" />安全流程状态：{{ statusLabel(data.case.status) }}</span><span>普通生成不是当前下一步</span></div>
      </AppStatusCallout>

      <section class="case-detail-grid">
        <div class="case-detail-main">
          <AppCard class="detail-panel" raised>
            <div class="detail-panel__heading"><div><span class="section-label">案例摘要</span><h2 class="section-title">当前授权范围</h2></div><AppBadge tone="amber" dot>{{ data.case.priority === 'NORMAL' ? '常规' : '需要确认' }}</AppBadge></div>
            <p class="detail-panel__summary">{{ data.case.safeContext }}</p>
            <dl class="detail-facts">
              <div><dt>匿名主体</dt><dd>{{ data.case.subject_id }}</dd></div>
              <div><dt>报告标识</dt><dd>{{ data.case.report_id }}</dd></div>
              <div><dt>安全决策</dt><dd>{{ data.case.decision_id }}</dd></div>
              <div><dt>追踪标识</dt><dd>{{ data.case.trace_id }}</dd></div>
              <div><dt>披露策略</dt><dd>{{ data.case.disclosure_policy }}</dd></div>
            </dl>
          </AppCard>

          <AppCard class="detail-panel">
            <div class="detail-panel__heading"><div><span class="section-label">测评上下文</span><h2 class="section-title">只展示最小摘要</h2></div><Info :size="18" class="detail-panel__info" aria-hidden="true" /></div>
            <div class="assessment-summary">
              <div><span>测评标识</span><strong>{{ data.safeAssessment.assessmentId }}</strong></div>
              <div><span>完成状态</span><strong>{{ data.safeAssessment.completion }}</strong></div>
              <div><span>维度说明</span><strong>{{ data.safeAssessment.dimensionNote }}</strong></div>
              <div><span>数据边界</span><strong>{{ data.safeAssessment.dataBoundary }}</strong></div>
            </div>
          </AppCard>

          <AppCard class="detail-panel">
            <div class="detail-panel__heading"><div><span class="section-label">依据</span><h2 class="section-title">与该流程相关的已审核片段</h2></div><FileCheck2 :size="18" class="detail-panel__info" aria-hidden="true" /></div>
            <div class="detail-evidence"><EvidenceItem v-for="citation in data.evidence" :key="citation.citation_id" :citation="citation" /></div>
          </AppCard>
        </div>

        <aside class="case-detail-side">
          <AppCard class="timeline-panel">
            <div class="detail-panel__heading"><div><span class="section-label">时间线</span><h2 class="section-title">流程记录</h2></div></div>
            <ol class="timeline">
              <li v-for="item in data.timeline" :key="item.label" :class="`timeline__item timeline__item--${item.tone}`"><span class="timeline__dot" aria-hidden="true"><Check v-if="item.tone === 'done'" :size="11" /><span v-else></span></span><div><strong>{{ item.label }}</strong><p>{{ item.detail }}</p><time>{{ item.time }}</time></div></li>
            </ol>
          </AppCard>

          <AppCard class="action-panel" :class="{ 'action-panel--resolved': !data.allowedActions.length }">
            <span class="section-label">人工动作</span>
            <h2 class="section-title">{{ data.allowedActions.length ? '完成本次确认' : '本次复核已完成' }}</h2>
            <p>{{ data.allowedActions.length ? '请根据当前授权摘要记录一个明确决定。' : '状态已经写入演示 API；页面不会修改原始测评或模型版本。' }}</p>
            <AppTextarea v-if="data.allowedActions.length" id="review-note" v-model="note" label="复核备注（可选）" placeholder="记录本次决定的简短理由" :rows="4" hint="不要填写姓名、联系方式或原始回答。" />
            <div v-if="data.allowedActions.length" class="action-panel__buttons">
              <AppButton variant="secondary" block @click="openAction('rejected')"><X :size="16" aria-hidden="true" />退回</AppButton>
              <AppButton block @click="openAction('approved')"><Check :size="16" aria-hidden="true" />通过</AppButton>
            </div>
            <div v-else class="resolved-state"><Check :size="17" aria-hidden="true" />{{ statusLabel(data.case.status) }}</div>
          </AppCard>
        </aside>
      </section>

      <AppDialog v-if="actionDialog" v-model:open="actionDialogOpen" :title="actionTitle" :description="actionBody">
        <p v-if="actionError" class="action-error" role="alert">{{ actionError }}</p>
        <div class="confirm-actions"><AppButton variant="quiet" @click="actionDialog = null">返回</AppButton><AppButton :variant="actionDialog === 'rejected' ? 'danger' : 'primary'" :loading="isSubmitting" @click="submitAction">确认{{ actionDialog === 'approved' ? '通过' : '退回' }}</AppButton></div>
      </AppDialog>
    </template>
  </div>
</template>

<style scoped>
.review-detail { animation: page-in 260ms ease both; }
.review-detail > .status-callout { margin-bottom: 20px; }
.detail-safety-meta { display: flex; flex-wrap: wrap; gap: 12px 20px; margin-top: 9px; color: var(--color-critical); font-size: 11px; font-weight: 700; }.detail-safety-meta span { display: inline-flex; align-items: center; gap: 6px; }
.case-detail-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(290px, 0.36fr); align-items: start; gap: 16px; }.case-detail-main { display: grid; gap: 16px; }.case-detail-side { display: grid; gap: 16px; position: sticky; top: 20px; }
.detail-panel, .timeline-panel, .action-panel { padding: 20px; }.detail-panel__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }.detail-panel__heading .section-title { margin-top: 6px; }.detail-panel__info { color: var(--color-primary); }
.detail-panel__summary { margin: 19px 0 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.8; }.detail-facts { display: grid; gap: 0; margin: 18px 0 0; }.detail-facts div { display: flex; justify-content: space-between; gap: 15px; padding: 10px 0; border-bottom: 1px solid var(--color-border); font-size: 12px; }.detail-facts div:last-child { border-bottom: 0; }.detail-facts dt { color: var(--color-text-muted); }.detail-facts dd { max-width: 65%; margin: 0; overflow-wrap: anywhere; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 10px; text-align: right; }
.assessment-summary { display: grid; gap: 0; margin-top: 18px; }.assessment-summary div { display: grid; gap: 5px; padding: 11px 0; border-bottom: 1px solid var(--color-border); }.assessment-summary div:last-child { border-bottom: 0; }.assessment-summary span { color: var(--color-text-muted); font-size: 10px; }.assessment-summary strong { color: var(--color-text-primary); font-size: 12px; line-height: 1.6; }
.detail-evidence { margin-top: 8px; }.timeline-panel { padding-bottom: 15px; }.timeline { display: grid; gap: 0; margin: 20px 0 0; padding: 0; list-style: none; }.timeline__item { position: relative; display: flex; gap: 12px; min-height: 75px; }.timeline__item:not(:last-child)::after { position: absolute; top: 18px; bottom: -4px; left: 7px; width: 1px; content: ""; background: var(--color-border); }.timeline__dot { position: relative; z-index: 1; display: inline-flex; align-items: center; justify-content: center; width: 15px; height: 15px; flex: 0 0 15px; margin-top: 2px; border: 1px solid var(--color-border-strong); border-radius: 50%; color: var(--color-text-inverse); background: var(--color-surface); }.timeline__item--done .timeline__dot { border-color: var(--color-support); background: var(--color-support); }.timeline__item--current .timeline__dot { border-color: var(--color-attention); box-shadow: 0 0 0 3px rgb(183 121 31 / 13%); }.timeline__item--current .timeline__dot span { width: 5px; height: 5px; border-radius: 50%; background: var(--color-attention); }.timeline__item > div { display: grid; align-content: start; gap: 3px; }.timeline__item strong { color: var(--color-text-primary); font-size: 12px; }.timeline__item p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }.timeline__item time { color: var(--color-text-muted); font-family: var(--font-mono); font-size: 9px; }.timeline__item--muted strong, .timeline__item--muted p { color: var(--color-text-muted); }
.action-panel { border-color: rgb(37 99 235 / 20%); }.action-panel--resolved { border-color: rgb(15 118 110 / 20%); }.action-panel > .section-title { margin-top: 7px; }.action-panel > p { margin: 10px 0 17px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; }.action-panel__buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 16px; }.resolved-state { display: flex; align-items: center; gap: 7px; min-height: 42px; margin-top: 7px; padding: 0 11px; border-radius: 7px; color: var(--color-support); background: var(--color-support-wash); font-size: 12px; font-weight: 800; }.confirm-actions { display: flex; justify-content: flex-end; gap: 8px; }.action-error { margin: 0 0 13px; padding: 9px 11px; border: 1px solid rgb(180 35 24 / 20%); border-radius: 7px; color: var(--color-critical); background: var(--color-critical-wash); font-size: 12px; line-height: 1.55; }
.detail-loading { padding-top: 12px; }.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }.skeleton--small { width: 140px; height: 14px; }.skeleton--title { width: 300px; height: 34px; margin-top: 17px; }.skeleton--panel { height: 300px; margin-top: 32px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } } @keyframes shimmer { to { transform: translateX(100%); } }
@media (max-width: 900px) { .case-detail-grid { grid-template-columns: 1fr; }.case-detail-side { position: static; grid-template-columns: 1fr 1fr; }.action-panel { grid-column: 1 / -1; } }
@media (max-width: 620px) { .case-detail-side { grid-template-columns: 1fr; }.detail-panel, .timeline-panel, .action-panel { padding: 17px; }.action-panel { grid-column: auto; }.action-panel__buttons { grid-template-columns: 1fr; }.detail-facts dd { max-width: 58%; } }
</style>
