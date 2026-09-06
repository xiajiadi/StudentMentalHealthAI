<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { ClipboardCheck } from '@lucide/vue'
import { FileCheck2 } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import { UsersRound } from '@lucide/vue'
import CompletionTrend from '@/components/charts/CompletionTrend.vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { TeacherOverviewViewModel } from '@/types/view-models'

const state = ref<'loading' | 'ready' | 'error'>('loading')
const data = ref<TeacherOverviewViewModel | null>(null)
const errorMessage = ref('')

const toneFor = (tone: 'blue' | 'teal' | 'amber') => tone
const summaryIcon = (tone: 'blue' | 'teal' | 'amber') => ({ blue: ClipboardCheck, teal: UsersRound, amber: FileCheck2 }[tone])
const maxCaseRows = computed(() => data.value?.attentionCases.slice(0, 3) || [])

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const response = await frontendApi.getTeacherOverview()
    data.value = response.data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '教师工作区暂时无法加载。'
  }
}

onMounted(load)
</script>

<template>
  <div class="content-wrap teacher-overview">
    <div v-if="state === 'loading'" class="teacher-loading" aria-busy="true" aria-label="正在加载教师工作区">
      <div class="skeleton skeleton--small"></div><div class="skeleton skeleton--title"></div>
      <div class="summary-skeleton"><div class="skeleton skeleton--metric"></div><div class="skeleton skeleton--metric"></div><div class="skeleton skeleton--metric"></div></div>
      <div class="skeleton skeleton--chart"></div>
    </div>

    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="教师工作区暂时无法加载" :body="errorMessage">
      <button class="inline-retry" type="button" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</button>
    </AppStatusCallout>

    <template v-else-if="data">
      <AppPageHeader eyebrow="教师工作区" title="工作概览" intro="从完成情况、支持流程和人工复核入口开始了解当前工作。" :fixture-label="data.fixtureLabel" />

      <section class="summary-grid" aria-label="工作概览摘要">
        <AppCard v-for="item in data.summary" :key="item.label" class="summary-card">
          <div class="summary-card__head"><span>{{ item.label }}</span><component :is="summaryIcon(item.tone)" :class="`summary-card__icon summary-card__icon--${toneFor(item.tone)}`" :size="17" aria-hidden="true" /></div>
          <strong>{{ item.value }}</strong>
          <p>{{ item.helper }}</p>
        </AppCard>
      </section>

      <section class="overview-grid">
        <AppCard class="chart-card" raised>
          <div class="card-heading"><div><span class="section-label">近 7 日</span><h2 class="section-title">完成与支持流程</h2></div><AppBadge tone="blue">合成趋势</AppBadge></div>
          <CompletionTrend :data="data.trend" />
        </AppCard>

        <AppCard class="workflow-card">
          <div class="card-heading"><div><span class="section-label">流程入口</span><h2 class="section-title">需要先看什么</h2></div></div>
          <div class="workflow-list">
            <RouterLink to="/teacher/students" class="workflow-link"><span class="workflow-link__num">01</span><span><strong>学生支持记录</strong><small>查看受控摘要与后续动作</small></span><ArrowRight :size="16" aria-hidden="true" /></RouterLink>
            <div class="workflow-link workflow-link--static"><span class="workflow-link__num">02</span><span><strong>安全流程</strong><small>需要人工复核的记录会在复核队列停止</small></span><AppBadge tone="amber" dot>1 条</AppBadge></div>
          </div>
          <AppStatusCallout tone="info" title="查看范围" body="当前页面只包含合成案例和授权摘要，不显示姓名、学号或原始回答。" />
        </AppCard>
      </section>

      <section class="case-section" aria-labelledby="case-title">
        <div class="section-heading"><div><span class="section-label">支持流程</span><h2 id="case-title" class="section-title">最近需要行动的记录</h2></div><RouterLink class="text-link" to="/teacher/students">查看全部 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></div>
        <AppCard class="case-table" flush>
          <div class="case-table__header"><span>案例标识</span><span>当前状态</span><span>更新时间</span><span>优先级</span><span class="sr-only">操作</span></div>
          <RouterLink v-for="item in maxCaseRows" :key="item.caseId" :to="`/teacher/students/${item.caseId}`" class="case-row">
            <span class="case-row__id">{{ item.subjectId }}<small>{{ item.caseId }}</small></span>
            <span><AppBadge :tone="item.priority === 'high' ? 'amber' : 'teal'" dot>{{ item.state }}</AppBadge></span>
            <span class="case-row__time">{{ item.updatedAt }}</span>
            <span class="case-row__priority" :class="{ 'case-row__priority--high': item.priority === 'high' }">{{ item.priority === 'high' ? '需要确认' : '常规' }}</span>
            <ArrowRight class="case-row__arrow" :size="16" aria-hidden="true" />
          </RouterLink>
        </AppCard>
      </section>
    </template>
  </div>
</template>

<style scoped>
.teacher-overview { animation: page-in 260ms ease both; }
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.summary-card { position: relative; min-height: 142px; padding: 18px; overflow: hidden; }
.summary-card::after { position: absolute; right: 0; bottom: 0; width: 62px; height: 3px; content: ""; background: var(--color-primary); opacity: 0.55; }
.summary-card:nth-child(2)::after { background: var(--color-support); }
.summary-card:nth-child(3)::after { background: var(--color-attention); }
.summary-card__head { display: flex; align-items: center; justify-content: space-between; color: var(--color-text-secondary); font-size: 12px; font-weight: 700; }
.summary-card__icon { display: inline-flex; padding: 7px; width: 31px; height: 31px; border-radius: 7px; }
.summary-card__icon--blue { color: var(--color-primary); background: var(--color-info-wash); }
.summary-card__icon--teal { color: var(--color-support); background: var(--color-support-wash); }
.summary-card__icon--amber { color: var(--color-attention); background: var(--color-attention-wash); }
.summary-card > strong { display: block; margin-top: 20px; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 27px; line-height: 1; }
.summary-card > p { margin: 8px 0 0; color: var(--color-text-muted); font-size: 11px; }
.overview-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr); gap: 16px; margin-top: 18px; }
.chart-card, .workflow-card { padding: 20px; }
.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; margin-bottom: 11px; }
.card-heading .section-title { margin-top: 6px; }
.workflow-card { display: flex; flex-direction: column; }
.workflow-list { display: grid; gap: 7px; margin-top: 5px; }
.workflow-link { display: flex; align-items: center; gap: 10px; min-height: 60px; padding: 9px 10px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.workflow-link:not(.workflow-link--static):hover { border-color: rgb(37 99 235 / 30%); background: var(--color-info-wash); }
.workflow-link__num { align-self: flex-start; color: var(--color-primary); font-family: var(--font-mono); font-size: 11px; font-weight: 700; }
.workflow-link > span:nth-child(2) { display: grid; flex: 1; gap: 3px; }
.workflow-link strong { font-size: 12px; }
.workflow-link small { color: var(--color-text-secondary); font-size: 10px; line-height: 1.5; }
.workflow-link > svg { color: var(--color-text-muted); }
.workflow-card .status-callout { margin-top: auto; }
.case-section { margin-top: 40px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 15px; margin-bottom: 13px; }
.text-link { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-size: 12px; font-weight: 700; }
.text-link:hover { text-decoration: underline; text-underline-offset: 3px; }
.case-table__header, .case-row { display: grid; grid-template-columns: minmax(175px, 1.2fr) minmax(150px, 1fr) minmax(108px, 0.7fr) minmax(80px, 0.6fr) 24px; align-items: center; gap: 15px; padding: 12px 17px; }
.case-table__header { color: var(--color-text-muted); background: var(--color-surface-muted); font-size: 11px; font-weight: 800; }
.case-row { min-height: 66px; border-top: 1px solid var(--color-border); color: var(--color-text-primary); transition: background-color var(--motion-fast) ease; }
.case-row:hover { background: var(--color-surface-soft); }
.case-row__id { display: grid; gap: 4px; font-family: var(--font-mono); font-size: 11px; font-weight: 700; }
.case-row__id small { color: var(--color-text-muted); font-size: 9px; font-weight: 500; }
.case-row__time { color: var(--color-text-secondary); font-size: 12px; }
.case-row__priority { color: var(--color-text-secondary); font-size: 12px; font-weight: 700; }
.case-row__priority--high { color: var(--color-attention); }
.case-row__arrow { color: var(--color-text-muted); }
.inline-retry { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; font-size: 12px; font-weight: 700; }
.inline-retry:hover { border-color: var(--color-primary); color: var(--color-primary); }
.teacher-loading { padding-top: 12px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }
.skeleton--small { width: 140px; height: 14px; }.skeleton--title { width: 280px; height: 34px; margin-top: 17px; }.summary-skeleton { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 30px; }.skeleton--metric { height: 142px; }.skeleton--chart { height: 300px; margin-top: 18px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { to { transform: translateX(100%); } }

@media (max-width: 860px) {
  .overview-grid { grid-template-columns: 1fr; }
  .case-table { overflow-x: auto; }
  .case-table__header, .case-row { min-width: 660px; }
}
@media (max-width: 560px) {
  .summary-grid, .summary-skeleton { grid-template-columns: 1fr; }
  .summary-card { min-height: 120px; }
  .summary-card > strong { margin-top: 14px; }
  .chart-card, .workflow-card { padding: 16px; }
}
</style>
