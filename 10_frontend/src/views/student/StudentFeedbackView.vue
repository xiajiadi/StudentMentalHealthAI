<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, FileCheck2, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { ReportSummary } from '@/api/client'
import type { Assessment } from '@/types/contracts'

type FeedbackMeta = { label: string; tone: 'neutral' | 'blue' | 'teal' | 'amber' | 'critical'; description: string; canOpen: boolean }

const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<Assessment[]>([])
const reports = ref<ReportSummary[]>([])
const errorMessage = ref('')

const completedAssessments = computed(() => assessments.value.filter((item) => item.status === 'completed'))
const reportsForAssessment = (assessmentId: string) => reports.value.filter((report) => report.assessment_id === assessmentId)
const assessmentsWithoutReport = computed(() => completedAssessments.value.filter((item) => reportsForAssessment(item.assessment_id).length === 0))

const formatDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const feedbackMeta = (report: ReportSummary): FeedbackMeta => {
  const status = report.status.toLowerCase()
  if (report.safety_action === 'CRISIS_ROUTE') {
    return { label: '安全流程记录', tone: 'amber', description: '此记录由安全流程管理，普通个性化反馈不会在这里显示。', canOpen: false }
  }
  if (status === 'generated') {
    return { label: '已发布', tone: 'teal', description: '服务端已为当前账号返回可查看的反馈。', canOpen: true }
  }
  if (status === 'needs_review' || status === 'pending' || status === 'in_review') {
    return { label: '待复核', tone: 'amber', description: '人工复核完成并获准发布前，不显示反馈内容。', canOpen: false }
  }
  if (status === 'approved' || status === 'closed') {
    return { label: '已批准', tone: 'teal', description: '状态已批准；当前服务端尚未向学生端返回报告正文。', canOpen: false }
  }
  if (status === 'rejected') {
    return { label: '未获准发布', tone: 'critical', description: '这条记录没有获准发布的反馈内容。', canOpen: false }
  }
  if (status === 'safety_blocked' || status === 'blocked') {
    return { label: '暂不可发布', tone: 'amber', description: '当前流程未允许发布普通反馈。', canOpen: false }
  }
  return { label: '处理中', tone: 'neutral', description: '服务端尚未提供可展示的反馈内容。', canOpen: false }
}

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const [assessmentResponse, reportResponse] = await Promise.all([
      frontendApi.listAssessments(),
      frontendApi.listReports(),
    ])
    assessments.value = assessmentResponse.data
    reports.value = reportResponse.data.items
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '测评反馈暂时无法加载，请稍后重试。')
  }
}

onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student student-feedback">
    <AppPageHeader
      eyebrow="学生空间 · 测评反馈"
      title="测评反馈"
      intro="这里只展示服务端允许当前账号查看的反馈状态与内容。"
    />

    <AppStatusCallout
      tone="info"
      title="反馈发布由服务端权限控制"
      body="待复核、被阻断或尚未向学生端提供正文的记录只显示状态，不会在页面中生成或补写建议。"
    />

    <section class="feedback-section" aria-labelledby="reports-title">
      <header class="feedback-section__heading">
        <div><span class="section-label">本人授权范围内</span><h2 id="reports-title">反馈状态</h2></div>
        <span>{{ reports.length }} 条</span>
      </header>

      <div v-if="state === 'loading'" class="feedback-loading" aria-busy="true" aria-label="正在加载反馈状态">
        <div class="skeleton skeleton--panel"></div>
      </div>
      <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="测评反馈暂时无法加载" :body="errorMessage">
        <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
      </AppStatusCallout>
      <AppCard v-else-if="reports.length === 0" class="feedback-empty">
        <span class="feedback-empty__icon" aria-hidden="true"><FileCheck2 :size="20" /></span>
        <div>
          <strong>目前没有可显示的反馈状态</strong>
          <p>完成的测评会在服务端创建相应流程。只有获准向当前账号发布的反馈才会在这里展示。</p>
        </div>
      </AppCard>
      <AppCard v-for="report in reports" v-else :key="report.report_id" class="feedback-row">
        <span class="feedback-row__icon" aria-hidden="true"><FileCheck2 :size="19" /></span>
        <div class="feedback-row__copy">
          <strong>{{ report.safety_action === 'CRISIS_ROUTE' ? '安全流程记录' : '测评反馈' }}</strong>
          <span>{{ formatDate(report.created_at) }}</span>
          <small>{{ feedbackMeta(report).description }}</small>
        </div>
        <AppBadge :tone="feedbackMeta(report).tone" dot>{{ feedbackMeta(report).label }}</AppBadge>
        <RouterLink v-if="feedbackMeta(report).canOpen" class="feedback-row__link" :to="`/student/reports/${encodeURIComponent(report.report_id)}`">
          查看反馈 <ArrowRight :size="15" aria-hidden="true" />
        </RouterLink>
      </AppCard>
    </section>

    <section v-if="state === 'ready' && assessmentsWithoutReport.length" class="feedback-section feedback-section--completed" aria-labelledby="completed-assessments-title">
      <header class="feedback-section__heading">
        <div><span class="section-label">测评记录</span><h2 id="completed-assessments-title">已完成测评</h2></div>
        <span>{{ assessmentsWithoutReport.length }} 项</span>
      </header>
      <AppCard v-for="assessment in assessmentsWithoutReport" :key="assessment.assessment_id" class="feedback-row">
        <span class="feedback-row__icon feedback-row__icon--completed" aria-hidden="true"><FileCheck2 :size="19" /></span>
        <div class="feedback-row__copy">
          <strong>已完成的合成测评</strong>
          <span>{{ formatDate(assessment.timestamps.completed_at) }}</span>
          <small>当前没有获准发布的反馈。可在“我的记录”中查看这项测评的保存状态。</small>
        </div>
        <AppBadge tone="neutral" dot>暂无反馈</AppBadge>
      </AppCard>
    </section>

    <footer class="feedback-footer">
      <RouterLink to="/student/history">查看我的记录 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
    </footer>
  </div>
</template>

<style scoped>
.feedback-section { margin-top: 34px; }
.feedback-section__heading { display: flex; align-items: end; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.feedback-section__heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 23px; }
.feedback-section__heading > span { color: var(--color-text-muted); font-size: 12px; }
.feedback-row { display: flex; align-items: center; gap: 14px; margin-top: 10px; padding: 16px 18px; }
.feedback-row__icon, .feedback-empty__icon { display: grid; place-items: center; width: 38px; height: 38px; flex: 0 0 38px; border-radius: 12px; color: var(--color-primary); background: var(--color-info-wash); }
.feedback-row__icon--completed { color: #456f64; background: #eaf3ef; }
.feedback-row__copy { display: grid; flex: 1; min-width: 0; gap: 4px; }
.feedback-row__copy strong, .feedback-empty strong { color: var(--color-text-primary); font-size: 14px; }
.feedback-row__copy span, .feedback-row__copy small, .feedback-empty p { color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.feedback-row__copy small { color: var(--color-text-muted); }
.feedback-empty { display: flex; align-items: flex-start; gap: 14px; padding: 21px; }
.feedback-empty > div { display: grid; gap: 7px; }
.feedback-empty p { margin: 0; }
.feedback-row__link, .feedback-footer a { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-size: 12px; font-weight: 600; white-space: nowrap; }
.feedback-row__link:hover, .feedback-footer a:hover { text-decoration: underline; text-underline-offset: 3px; }
.feedback-loading { padding: 14px 0; }
.feedback-loading .skeleton { height: 112px; border-radius: var(--radius-card); background: var(--color-surface-skeleton); }
.feedback-section > .status-callout { margin-top: 10px; }
.feedback-footer { display: flex; justify-content: flex-end; margin-top: 22px; }

@media (max-width: 680px) {
  .feedback-row { align-items: flex-start; flex-wrap: wrap; }
  .feedback-row__copy { flex-basis: calc(100% - 54px); }
  .feedback-row .app-badge, .feedback-row__link { margin-left: 52px; }
}
</style>
