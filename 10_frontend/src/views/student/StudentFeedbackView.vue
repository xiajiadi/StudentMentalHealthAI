<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, FileCheck2, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { useSessionStore } from '@/stores/session'
import { frontendApi } from '@/services/mock-api'
import { schoolFeedback, type StudentSchoolFeedback } from '@/services/school-feedback'
import StudentResearchFeedback from '@/components/school/StudentResearchFeedback.vue'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { AssessmentListEntry, ReportSummary } from '@/api/client'

type FeedbackMeta = { label: string; tone: 'neutral' | 'blue' | 'teal' | 'amber' | 'critical'; description: string; canOpen: boolean }

const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<AssessmentListEntry[]>([])
const reports = ref<ReportSummary[]>([])
const schoolFeedbackState = ref<'loading' | 'ready' | 'error'>('loading')
const schoolFeedbackRows = ref<StudentSchoolFeedback[]>([])
const schoolFeedbackError = ref('')
const session = useSessionStore()
const errorMessage = ref('')
const loadMoreError = ref('')
const assessmentPageSize = 30
const nextAssessmentOffset = ref(0)
const assessmentRequestGeneration = ref(0)
const schoolFeedbackGeneration = ref(0)
const isLoadingMoreAssessments = ref(false)
const hasMoreAssessments = ref(false)

const reportsForAssessment = (assessmentId: string) => reports.value.filter((report) => report.assessment_id === assessmentId)
const assessmentsWithoutReport = computed(() => assessments.value.filter((item) => item.status === 'completed' && reportsForAssessment(item.assessment_id).length === 0))

const listCompletedAssessmentEntries = async (skip: number) => {
  const params = { limit: assessmentPageSize, skip, status: 'completed' as const }
  if (frontendApi.listAssessmentEntries) return (await frontendApi.listAssessmentEntries(params)).data
  const rows = (await frontendApi.listAssessments(params)).data
  return rows.filter((assessment) => assessment.status === 'completed').map((assessment) => ({
    assessment_id: assessment.assessment_id,
    status: assessment.status,
    items_answered: assessment.response_summary.items_answered,
    started_at: assessment.timestamps.started_at,
    completed_at: assessment.timestamps.completed_at,
  }))
}

const formatDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const loadSchoolFeedback = async () => {
  const generation = ++schoolFeedbackGeneration.value
  schoolFeedbackState.value = 'loading'
  schoolFeedbackRows.value = []
  schoolFeedbackError.value = ''
  try {
    const result = await schoolFeedback.listStudent()
    if (generation !== schoolFeedbackGeneration.value) return
    schoolFeedbackRows.value = result.items
    schoolFeedbackState.value = 'ready'
  } catch (error) {
    if (generation !== schoolFeedbackGeneration.value) return
    schoolFeedbackRows.value = []
    schoolFeedbackState.value = 'error'
    schoolFeedbackError.value = userFacingApiError(error, '已发布反馈暂时无法加载。')
  }
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
  const generation = ++assessmentRequestGeneration.value
  state.value = 'loading'
  errorMessage.value = ''
  loadMoreError.value = ''
  nextAssessmentOffset.value = 0
  hasMoreAssessments.value = false
  isLoadingMoreAssessments.value = false
  assessments.value = []
  try {
    const [assessmentRows, reportResponse] = await Promise.all([
      listCompletedAssessmentEntries(0),
      frontendApi.listReports(),
    ])
    if (generation !== assessmentRequestGeneration.value) return
    assessments.value = assessmentRows
    nextAssessmentOffset.value = assessmentRows.length
    hasMoreAssessments.value = assessmentRows.length === assessmentPageSize
    reports.value = reportResponse.data.items
    state.value = 'ready'
  } catch (error) {
    if (generation !== assessmentRequestGeneration.value) return
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '测评反馈暂时无法加载，请稍后重试。')
  }
}

const loadMoreAssessments = async () => {
  if (isLoadingMoreAssessments.value || !hasMoreAssessments.value || state.value !== 'ready') return
  const generation = assessmentRequestGeneration.value
  isLoadingMoreAssessments.value = true
  loadMoreError.value = ''
  try {
    const rows = await listCompletedAssessmentEntries(nextAssessmentOffset.value)
    if (generation !== assessmentRequestGeneration.value) return
    const existingIds = new Set(assessments.value.map((item) => item.assessment_id))
    assessments.value = [...assessments.value, ...rows.filter((item) => !existingIds.has(item.assessment_id))]
    nextAssessmentOffset.value += rows.length
    hasMoreAssessments.value = rows.length === assessmentPageSize
  } catch (error) {
    if (generation !== assessmentRequestGeneration.value) return
    const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code) : ''
    loadMoreError.value = userFacingApiError({ code }, '暂时无法加载更多已完成测评，请重试。')
  } finally {
    if (generation === assessmentRequestGeneration.value) isLoadingMoreAssessments.value = false
  }
}

watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    schoolFeedbackRows.value = []
    schoolFeedbackError.value = ''
    if (next[0] === 'student') void loadSchoolFeedback()
    else {
      schoolFeedbackGeneration.value += 1
      schoolFeedbackState.value = 'ready'
    }
  },
)

onBeforeUnmount(() => {
  schoolFeedbackGeneration.value += 1
})

onMounted(() => {
  void load()
  void loadSchoolFeedback()
})
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

    <section class="feedback-section published-feedback" aria-labelledby="published-feedback-title">
      <header class="feedback-section__heading">
        <div><span class="section-label">单独发布 · 合成演示</span><h2 id="published-feedback-title">已发布的学生反馈</h2></div>
        <AppButton variant="quiet" size="sm" :disabled="schoolFeedbackState === 'loading'" aria-label="刷新已发布反馈" @click="loadSchoolFeedback">
          <RotateCcw :size="15" aria-hidden="true" />刷新
        </AppButton>
      </header>
      <p v-if="schoolFeedbackState === 'loading'" class="feedback-publication-state" role="status" aria-busy="true">正在读取已发布反馈…</p>
      <AppStatusCallout v-else-if="schoolFeedbackState === 'error'" tone="critical" title="已发布反馈暂时无法加载" :body="schoolFeedbackError">
        <AppButton variant="secondary" size="sm" @click="loadSchoolFeedback">重新加载</AppButton>
      </AppStatusCallout>
      <AppCard v-else-if="!schoolFeedbackRows.length" class="feedback-empty">
        <span class="feedback-empty__icon" aria-hidden="true"><FileCheck2 :size="20" /></span>
        <div><strong>目前没有单独发布的反馈</strong><p>完成测评或复核决定本身不会显示反馈正文；只有专业人员明确发布的内容才会出现在这里。</p></div>
      </AppCard>
      <AppCard v-for="item in schoolFeedbackRows" v-else :key="item.feedback_ref" class="published-feedback__row">
        <div class="published-feedback__heading"><h3>{{ item.title }}</h3><AppBadge tone="teal" dot>合成演示 · L3</AppBadge></div>
        <p class="published-feedback__body">{{ item.body }}</p>
        <p class="published-feedback__time">发布于 {{ formatDate(item.published_at) }}</p>
      </AppCard>
    </section>

    <StudentResearchFeedback />

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
        <span>{{ hasMoreAssessments ? `已显示 ${assessmentsWithoutReport.length} 项` : `${assessmentsWithoutReport.length} 项` }}</span>
      </header>
      <AppCard v-for="assessment in assessmentsWithoutReport" :key="assessment.assessment_id" class="feedback-row">
        <span class="feedback-row__icon feedback-row__icon--completed" aria-hidden="true"><FileCheck2 :size="19" /></span>
        <div class="feedback-row__copy">
          <strong>已完成的合成测评</strong>
          <span>{{ formatDate(assessment.completed_at) }}</span>
          <small>这项测评尚未提供可查看的测量报告。保存状态可在“我的记录”中查看。</small>
        </div>
        <AppBadge tone="neutral" dot>暂无测量报告</AppBadge>
      </AppCard>
    </section>

    <section v-if="state === 'ready' && hasMoreAssessments" class="assessment-load-more" aria-label="更多已完成测评">
      <p>已加载 {{ assessments.length }} 项已完成测评记录。</p>
      <AppButton variant="secondary" :disabled="isLoadingMoreAssessments" @click="loadMoreAssessments">{{ isLoadingMoreAssessments ? '正在加载…' : '加载更多测评记录' }} <ArrowRight :size="15" aria-hidden="true" /></AppButton>
      <p v-if="loadMoreError" role="alert">{{ loadMoreError }}</p>
    </section>

    <footer class="feedback-footer">
      <RouterLink to="/student/history">查看我的记录 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
    </footer>
  </div>
</template>

<style scoped>
.feedback-section { margin-top: 34px; }
.published-feedback__row { display: grid; gap: 9px; margin-top: 10px; padding: 16px 18px; }
.published-feedback__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.published-feedback__heading h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.published-feedback__body { margin: 0; color: var(--color-text-primary); font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.published-feedback__time, .feedback-publication-state { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.55; }
.published-feedback > .status-callout { margin-top: 10px; }
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
  .published-feedback__heading { align-items: flex-start; flex-direction: column; }
}
</style>
