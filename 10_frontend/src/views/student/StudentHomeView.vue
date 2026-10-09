<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, BookOpen, CheckCircle2, ClipboardList, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import type { ReportSummary } from '@/api/client'
import type { Assessment } from '@/types/contracts'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<Assessment[]>([])
const reports = ref<ReportSummary[]>([])
const errorMessage = ref('')
const historyError = ref('')

const isHistory = computed(() => route.path === '/student/history')
const inProgress = computed(() => assessments.value.find((item) => item.status === 'in_progress'))
const completedCount = computed(() => assessments.value.filter((item) => item.status === 'completed').length)
const recentAssessment = computed(() => assessments.value[0])

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    assessments.value = (await frontendApi.listAssessments()).data
    try {
      reports.value = (await frontendApi.listReports()).data.items
      historyError.value = ''
    } catch (error) {
      reports.value = []
      historyError.value = error instanceof Error ? error.message : '支持记录暂时无法加载。'
    }
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '页面暂时无法加载，请稍后重试。'
  }
}

const continueOrStart = (assessment?: Assessment) => {
  void router.push(assessment ? `/student/assessment/${encodeURIComponent(assessment.assessment_id)}` : '/student/assessment')
}
const openResult = (assessmentId: string) => void router.push(`/student/assessment/${encodeURIComponent(assessmentId)}/result`)
const openSupportHistory = (reportId: string) => void router.push(`/student/reports/${encodeURIComponent(reportId)}`)

onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student student-space">
    <div v-if="state === 'loading'" class="student-loading" aria-busy="true" aria-label="正在加载学生空间">
      <div class="skeleton skeleton--short"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--body"></div>
    </div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="学生空间暂时无法加载" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
    </AppStatusCallout>
    <template v-else-if="!isHistory">
      <section class="student-hero" aria-labelledby="student-home-title">
        <img class="student-hero__flow" :src="'/assets/heartbridge/hero-flow-original.png'" alt="" aria-hidden="true">
        <div class="student-hero__copy">
          <span class="student-kicker">心桥 · 学生空间</span>
          <h1 id="student-home-title">给自己一点时间，<br>从一步开始。</h1>
          <p>这里可以完成一项合成测评、查看自己的记录，或了解教育支持当前的可用状态。</p>
          <div class="student-hero__actions">
            <AppButton size="lg" @click="continueOrStart(inProgress)">
              {{ inProgress ? '继续测评' : '开始测评' }} <ArrowRight :size="17" aria-hidden="true" />
            </AppButton>
            <RouterLink class="student-secondary-link" to="/student/support"><BookOpen :size="17" aria-hidden="true" />教育支持</RouterLink>
          </div>
          <div class="student-hero__note"><span class="student-hero__note-dot" aria-hidden="true"></span>演示数据 · 教育用途 · 非诊断</div>
        </div>
        <figure class="student-hero__art">
          <img :src="'/assets/heartbridge/card-student-original.png'" alt="" aria-hidden="true">
          <figcaption>按自己的节奏了解流程</figcaption>
        </figure>
      </section>

      <section class="student-overview" aria-label="我的空间概览">
        <div class="student-overview__heading"><div><span class="student-kicker">当前空间</span><h2>我的记录</h2></div><RouterLink to="/student/history">查看全部 <ArrowRight :size="15" aria-hidden="true" /></RouterLink></div>
        <div class="student-overview__grid">
          <AppCard class="overview-card">
            <span class="overview-card__icon"><ClipboardList :size="18" aria-hidden="true" /></span>
            <div><span>测评记录</span><strong>{{ assessments.length }}</strong><small>{{ inProgress ? '有一项可以继续' : '由服务端保存' }}</small></div>
          </AppCard>
          <AppCard class="overview-card">
            <span class="overview-card__icon overview-card__icon--green"><CheckCircle2 :size="18" aria-hidden="true" /></span>
            <div><span>已完成</span><strong>{{ completedCount }}</strong><small>仅显示当前账号可访问记录</small></div>
          </AppCard>
          <AppCard class="overview-card overview-card--recent">
            <span class="overview-card__icon overview-card__icon--amber"><BookOpen :size="18" aria-hidden="true" /></span>
            <div><span>一项测评记录</span><strong>{{ recentAssessment ? (recentAssessment.status === 'completed' ? '已完成' : '进行中') : '还没有记录' }}</strong><small>{{ recentAssessment?.timestamps.completed_at || recentAssessment?.timestamps.started_at || '开始测评后会显示在这里' }}</small></div>
          </AppCard>
        </div>
      </section>

      <section class="student-support-card" aria-labelledby="education-support-title">
        <div class="student-support-card__visual"><img :src="'/assets/heartbridge/card-student-original.png'" alt="" aria-hidden="true"></div>
        <div class="student-support-card__copy"><span class="student-kicker">教育支持</span><h2 id="education-support-title">了解当前支持功能</h2><p>教育支持入口保持开放。独立支持生成目前受后端流程限制，页面会说明哪些功能暂不可用。</p><RouterLink to="/student/support">查看支持状态 <ArrowRight :size="16" aria-hidden="true" /></RouterLink></div>
        <AppBadge tone="attention" dot>部分功能受限</AppBadge>
      </section>

      <AppStatusCallout tone="info" title="关于演示数据" body="本空间仅展示合成演示流程。测评记录不代表经过验证的心理测量，也不提供诊断或治疗建议。" />
    </template>
    <template v-else>
      <header class="history-heading">
        <div><span class="student-kicker">学生空间 · 我的记录</span><h1>测评与支持记录</h1><p>这里仅显示当前登录账号有权访问的记录。</p></div>
        <AppButton variant="secondary" @click="router.push('/student/home')"><ArrowRight :size="16" aria-hidden="true" />返回首页</AppButton>
      </header>
      <section class="history-section" aria-labelledby="assessment-history-title">
        <div class="history-section__heading"><div><span class="student-kicker">测评</span><h2 id="assessment-history-title">我的测评</h2></div><span>{{ assessments.length }} 条</span></div>
        <AppCard v-if="assessments.length === 0" class="history-empty"><ClipboardList :size="21" aria-hidden="true" /><div><strong>还没有测评记录</strong><p>开始测评后，保存的记录会显示在这里。</p><AppButton size="sm" @click="continueOrStart()">开始测评 <ArrowRight :size="15" aria-hidden="true" /></AppButton></div></AppCard>
        <AppCard v-for="item in assessments" :key="item.assessment_id" class="history-row">
          <span class="history-row__icon" :class="{ 'history-row__icon--complete': item.status === 'completed' }"><CheckCircle2 :size="18" aria-hidden="true" /></span>
          <div class="history-row__copy"><strong>{{ item.status === 'completed' ? '已完成的合成测评' : '进行中的合成测评' }}</strong><span>{{ item.response_summary.items_answered }} 项已记录 · {{ item.timestamps.completed_at || item.timestamps.started_at }}</span></div>
          <AppBadge :tone="item.status === 'completed' ? 'teal' : 'blue'" dot>{{ item.status === 'completed' ? '已完成' : '进行中' }}</AppBadge>
          <AppButton variant="secondary" size="sm" @click="item.status === 'completed' ? openResult(item.assessment_id) : continueOrStart(item)">{{ item.status === 'completed' ? '查看结果' : '继续测评' }} <ArrowRight :size="15" aria-hidden="true" /></AppButton>
        </AppCard>
      </section>
      <section class="history-section" aria-labelledby="report-history-title">
        <div class="history-section__heading"><div><span class="student-kicker">教育支持</span><h2 id="report-history-title">支持记录</h2></div><span>{{ reports.length }} 条</span></div>
        <AppStatusCallout v-if="historyError" tone="attention" title="支持记录暂时无法加载" :body="historyError"><AppButton variant="secondary" size="sm" @click="load">重新加载</AppButton></AppStatusCallout>
        <p v-else-if="reports.length === 0" class="history-empty-copy">还没有支持记录。独立支持生成目前受限；如果服务端已有可访问的记录，会显示在这里。</p>
        <AppCard v-for="report in reports" :key="report.report_id" class="history-row">
          <span class="history-row__icon history-row__icon--support"><BookOpen :size="18" aria-hidden="true" /></span>
          <div class="history-row__copy"><strong>{{ report.safety_action === 'CRISIS_ROUTE' ? '安全流程记录' : '教育支持记录' }}</strong><span>{{ report.created_at || '时间未提供' }} · {{ report.citation_count }} 条来源</span></div>
          <AppButton variant="secondary" size="sm" @click="openSupportHistory(report.report_id)">查看记录 <ArrowRight :size="15" aria-hidden="true" /></AppButton>
        </AppCard>
      </section>
    </template>
  </div>
</template>

<style scoped>
.student-space { padding-top: 28px; padding-bottom: 64px; }
.student-kicker { color: var(--color-support); font-size: 11px; font-weight: 800; letter-spacing: .11em; }
.student-hero { position: relative; display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(260px, .8fr); align-items: center; min-height: 370px; overflow: hidden; padding: clamp(26px, 5vw, 58px); border: 1px solid #d8e7e2; border-radius: 24px; background: linear-gradient(110deg, #f0f7f4 0%, #f6f8f5 50%, #e9f2ee 100%); }
.student-hero__flow { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .17; pointer-events: none; }
.student-hero__copy { position: relative; z-index: 1; max-width: 560px; }
.student-hero h1 { margin: 14px 0 14px; color: #233d39; font-family: var(--font-display); font-size: clamp(34px, 5vw, 55px); font-weight: 650; letter-spacing: -.045em; line-height: 1.18; }
.student-hero__copy > p { max-width: 465px; margin: 0; color: #536963; font-size: 15px; line-height: 1.85; }
.student-hero__actions { display: flex; align-items: center; gap: 22px; margin-top: 25px; }
.student-secondary-link { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; color: #315e55; font-size: 13px; font-weight: 750; }
.student-secondary-link:hover, .student-overview__heading > a:hover, .student-support-card__copy > a:hover { text-decoration: underline; text-underline-offset: 4px; }
.student-hero__note { display: flex; align-items: center; gap: 8px; margin-top: 26px; color: #667a74; font-size: 11px; }
.student-hero__note-dot { width: 7px; height: 7px; border-radius: 50%; background: #75978a; }
.student-hero__art { position: relative; z-index: 1; justify-self: center; width: min(100%, 340px); margin: 0; text-align: center; }
.student-hero__art img { display: block; width: 100%; max-height: 235px; object-fit: contain; filter: drop-shadow(0 18px 28px rgb(42 77 66 / 11%)); }
.student-hero__art figcaption { margin-top: 3px; color: #647771; font-size: 11px; }
.student-overview, .history-section { margin-top: 40px; }
.student-overview__heading, .history-section__heading { display: flex; align-items: end; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.student-overview__heading h2, .history-section__heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 23px; }
.student-overview__heading > a { display: inline-flex; align-items: center; gap: 5px; color: var(--color-support); font-size: 12px; font-weight: 750; }
.student-overview__grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.overview-card { display: flex; align-items: flex-start; gap: 13px; min-height: 122px; padding: 18px; }
.overview-card__icon, .history-row__icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 36px; border-radius: 11px; color: #456f64; background: #eaf3ef; }
.overview-card__icon--green, .history-row__icon--complete { color: #397c67; background: #e8f3ec; }
.overview-card__icon--amber { color: #947342; background: #f7f1e5; }
.overview-card > div { display: grid; min-width: 0; gap: 4px; }
.overview-card > div > span { color: var(--color-text-secondary); font-size: 11px; }
.overview-card strong { overflow: hidden; color: #2d4942; font-family: var(--font-display); font-size: 23px; text-overflow: ellipsis; white-space: nowrap; }
.overview-card small { overflow: hidden; color: var(--color-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.student-support-card { position: relative; display: grid; grid-template-columns: 92px minmax(0, 1fr) auto; align-items: center; gap: 20px; margin-top: 28px; padding: 20px 24px; border: 1px solid #e3e9e4; border-radius: var(--radius-card); background: #fbfcfa; }
.student-support-card__visual { display: grid; place-items: center; width: 86px; height: 86px; overflow: hidden; border-radius: 20px; background: #f0f5f1; }
.student-support-card__visual img { width: 100%; height: 100%; object-fit: contain; }
.student-support-card__copy h2 { margin: 5px 0 4px; color: var(--color-text-primary); font-family: var(--font-display); font-size: 18px; }
.student-support-card__copy p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; }
.student-support-card__copy > a { display: inline-flex; align-items: center; gap: 5px; margin-top: 9px; color: var(--color-support); font-size: 12px; font-weight: 750; }
.student-space > .status-callout { margin-top: 26px; }
.history-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 15px 0 8px; }
.history-heading h1 { margin: 8px 0 5px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(28px, 4vw, 38px); letter-spacing: -.035em; }
.history-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
.history-section__heading > span { color: var(--color-text-muted); font-size: 11px; }
.history-row { display: flex; align-items: center; gap: 13px; margin-top: 9px; padding: 14px 16px; }
.history-row__icon--support { color: #957344; background: #f7f1e5; }
.history-row__copy { display: grid; min-width: 0; flex: 1; gap: 4px; }
.history-row__copy strong { color: var(--color-text-primary); font-size: 13px; }
.history-row__copy span { overflow: hidden; color: var(--color-text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.history-empty { display: flex; align-items: flex-start; gap: 13px; padding: 20px; color: #54766b; }
.history-empty > div { display: grid; gap: 7px; }
.history-empty strong { color: var(--color-text-primary); font-size: 13px; }
.history-empty p, .history-empty-copy { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.history-empty-copy { padding: 12px 0; }
.history-section > .status-callout { margin-top: 9px; }
.student-loading { padding-top: 18px; }
.skeleton { border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton--short { width: 120px; height: 13px; }
.skeleton--title { width: min(480px, 70%); height: 35px; margin-top: 17px; }
.skeleton--body { width: min(620px, 90%); height: 16px; margin-top: 13px; }

@media (max-width: 760px) {
  .student-hero { grid-template-columns: 1fr; min-height: 0; padding: 30px 24px; }
  .student-hero__art { position: absolute; right: -20px; bottom: 8px; width: 36%; opacity: .58; }
  .student-hero__art figcaption { display: none; }
  .student-hero__copy { max-width: 78%; }
  .student-hero h1 { font-size: clamp(30px, 7vw, 42px); }
  .student-overview__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-card--recent { grid-column: 1 / -1; min-height: 98px; }
  .student-support-card { grid-template-columns: 68px minmax(0, 1fr); gap: 13px; padding: 16px; }
  .student-support-card__visual { width: 64px; height: 64px; }
  .student-support-card > .app-badge { grid-column: 2; justify-self: start; }
}
@media (max-width: 520px) {
  .student-space { padding-top: 15px; }
  .student-hero { border-radius: 18px; padding: 24px 18px; }
  .student-hero__copy { max-width: 100%; }
  .student-hero__copy > p { max-width: 95%; font-size: 13px; }
  .student-hero__art { right: -50px; bottom: 25px; width: 42%; opacity: .25; }
  .student-hero__actions { align-items: flex-start; flex-direction: column; gap: 8px; margin-top: 20px; }
  .student-hero__note { margin-top: 18px; }
  .student-overview__grid { grid-template-columns: 1fr; }
  .overview-card, .overview-card--recent { grid-column: auto; min-height: 88px; }
  .student-support-card { align-items: start; grid-template-columns: 50px minmax(0, 1fr); }
  .student-support-card__visual { width: 48px; height: 48px; border-radius: 14px; }
  .history-heading { align-items: flex-start; flex-direction: column; }
  .history-row { align-items: flex-start; flex-wrap: wrap; }
  .history-row__copy { flex-basis: calc(100% - 52px); }
  .history-row .app-badge { margin-left: 48px; }
  .history-row .app-button { margin-left: 48px; }
}
</style>
