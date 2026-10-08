<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowRight, CheckCircle2, ClipboardList, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import type { Assessment } from '@/types/contracts'
import type { ReportSummary } from '@/api/client'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<Assessment[]>([])
const reports = ref<ReportSummary[]>([])
const errorMessage = ref('')
const historyError = ref('')
const resetCopyState = ref<'idle' | 'copied' | 'error'>('idle')

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const assessmentResponse = await frontendApi.listAssessments()
    assessments.value = assessmentResponse.data
    try {
      reports.value = (await frontendApi.listReports()).data.items
      historyError.value = ''
    } catch (error) {
      reports.value = []
      historyError.value = error instanceof Error ? error.message : '报告历史暂时无法加载。'
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
const copyResetCommand = async () => {
  try {
    await window.navigator.clipboard.writeText('.\\reset-demo.ps1')
    resetCopyState.value = 'copied'
  } catch {
    resetCopyState.value = 'error'
  }
}

onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student student-home">
    <div v-if="state === 'loading'" class="student-loading" aria-busy="true" aria-label="正在加载学生首页"><div class="skeleton skeleton--short"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--body"></div></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="学生空间暂时无法加载" :body="errorMessage"><AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton></AppStatusCallout>
    <template v-else>
      <AppPageHeader eyebrow="学生空间" :title="route.path === '/student/history' ? '历史记录' : '合成演示工作区'" intro="从测评、结果到教育支持对话，当前流程仅使用演示数据。" fixture-label="SYNTHETIC · DEMO · 非诊断" />
      <AppStatusCallout tone="info" title="使用范围" body="这里展示工程演示流程，不提供心理诊断或治疗建议。页面中的记录由当前登录账号权限控制。" />

      <section class="student-section" aria-labelledby="assessment-list-title">
        <div class="student-section__heading"><div><span class="section-label">测评</span><h2 id="assessment-list-title">大学新生适应测评</h2></div><AppBadge tone="blue" dot>合成项目</AppBadge></div>
        <p class="student-section__copy">每次显示一道项目。提交后由服务端保存回答并返回下一步状态。</p>
        <AppCard v-if="assessments.some((item) => item.status === 'in_progress')" class="student-list-card">
          <div><strong>有一项测评尚未完成</strong><span>可以从已保存的当前项目继续。</span></div>
          <AppButton @click="continueOrStart(assessments.find((item) => item.status === 'in_progress'))">继续测评 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
        </AppCard>
        <AppCard v-else class="student-list-card">
          <div><strong>开始一项合成测评</strong><span>教育用途的演示流程，不代表已验证的心理量表。</span></div>
          <AppButton @click="continueOrStart()">开始测评 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
        </AppCard>
      </section>

      <section class="student-section" aria-labelledby="assessment-history-title">
        <div class="student-section__heading"><div><span class="section-label">历史</span><h2 id="assessment-history-title">测评记录</h2></div></div>
        <p v-if="assessments.length === 0" class="student-empty-copy">还没有测评记录。开始后，记录会由服务端保存。</p>
        <AppCard v-for="item in assessments" :key="item.assessment_id" class="student-history-row">
          <CheckCircle2 :size="18" aria-hidden="true" />
          <div><strong>{{ item.status === 'completed' ? '已完成的合成测评' : '进行中的合成测评' }}</strong><span>{{ item.assessment_id }} · {{ item.response_summary.items_answered }} 项已记录</span></div>
          <AppButton v-if="item.status === 'completed'" variant="secondary" size="sm" @click="openResult(item.assessment_id)">查看结果</AppButton>
          <AppButton v-else variant="secondary" size="sm" @click="continueOrStart(item)">继续</AppButton>
        </AppCard>
      </section>

      <section class="student-section" aria-labelledby="report-history-title">
        <div class="student-section__heading"><div><span class="section-label">支持</span><h2 id="report-history-title">对话与报告</h2></div></div>
        <AppStatusCallout v-if="historyError" tone="info" title="报告历史暂时无法加载" :body="historyError" />
        <p v-if="reports.length === 0" class="student-empty-copy">还没有支持对话或报告。完成测评后可以从结果页进入支持对话。</p>
        <AppCard v-for="report in reports" :key="report.report_id" class="student-history-row">
          <ClipboardList :size="18" aria-hidden="true" />
          <div><strong>教育支持记录</strong><span>{{ report.report_id }} · {{ report.created_at || '时间未提供' }} · {{ report.citation_count }} 条来源</span></div>
          <AppButton variant="secondary" size="sm" @click="openSupportHistory(report.report_id)">查看记录</AppButton>
        </AppCard>
      </section>

      <section class="student-section student-reset" aria-labelledby="demo-reset-title">
        <div><span class="section-label">演示维护</span><h2 id="demo-reset-title">重置演示数据</h2><p>为避免浏览器端越权清理数据，重置由本地演示运行器执行。</p></div>
        <div class="student-reset__command"><code>.\reset-demo.ps1</code><AppButton variant="secondary" size="sm" @click="copyResetCommand">{{ resetCopyState === 'copied' ? '已复制' : '复制命令' }}</AppButton></div>
        <p class="student-reset__hint">请在项目根目录的 PowerShell 中运行此命令。前端不会显示清理成功，直到服务端确认完成。</p>
        <p v-if="resetCopyState === 'error'" class="student-reset__hint" role="status">复制失败，请手动选择上面的命令。</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.student-section { margin-top: 34px; }
.student-section__heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 8px; }
.student-section__heading h2, .student-reset h2 { margin: 6px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 21px; }
.student-section__copy, .student-empty-copy { color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.student-list-card, .student-history-row { display: flex; align-items: center; gap: 14px; padding: 17px; }
.student-list-card > div, .student-history-row > div { display: grid; flex: 1; gap: 4px; min-width: 0; }
.student-list-card strong, .student-history-row strong { color: var(--color-text-primary); font-size: 14px; }
.student-list-card span, .student-history-row span { color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.student-history-row > svg { color: var(--color-support); flex: 0 0 auto; }
.student-reset { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 3px 18px; padding: 18px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.student-reset p { margin: 7px 0 0; color: var(--color-text-secondary); font-size: 12px; }
.student-reset code { padding: 9px 12px; border-radius: 6px; color: var(--color-text-primary); background: var(--color-surface-raised); font-size: 13px; }
.student-reset__command { display: flex; align-items: center; gap: 10px; }
.student-reset .student-reset__hint { grid-column: 1 / -1; color: var(--color-text-muted); }
.student-home { animation: page-in 260ms ease both; }
.section-label { color: var(--color-text-muted); font-size: 11px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.student-home__lead { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.65fr); gap: 16px; }
.student-home__state, .student-home__next { padding: 25px; }
.student-home__state { position: relative; overflow: hidden; border-color: rgb(37 99 235 / 16%); background: var(--color-surface); }
.student-home__state::before { position: absolute; top: 0; bottom: 0; left: 0; width: 4px; content: ""; background: var(--color-primary); }
.student-home__state-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.student-home__state h2 { max-width: 500px; margin: 10px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(22px, 3vw, 30px); letter-spacing: -0.04em; line-height: 1.35; }
.student-home__state p { max-width: 560px; margin: 14px 0 27px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.8; }
.student-home__state-icon { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.student-home__state-meta { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding-top: 14px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 12px; }
.student-home__state-meta strong { color: var(--color-support); }
.student-home__state-meta a { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-weight: 700; }
.student-home__state-meta a:hover { text-decoration: underline; text-underline-offset: 3px; }
.student-home__next { display: flex; flex-direction: column; justify-content: space-between; border-color: rgb(15 118 110 / 16%); background: var(--color-support-wash); }
.student-home__next-label { display: flex; justify-content: space-between; color: var(--color-support); font-size: 11px; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
.student-home__index { font-family: var(--font-mono); opacity: 0.66; }
.student-home__next h2 { margin: 36px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 21px; line-height: 1.45; }
.student-home__next p { margin: 9px 0 25px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.student-home__support { margin-top: 45px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
.section-heading__rule { display: block; width: 100px; height: 1px; margin-bottom: 5px; background: var(--color-border-strong); }
.support-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.support-item { display: flex; align-items: flex-start; gap: 12px; min-height: 104px; padding: 17px; transition: border-color var(--motion-fast) ease, transform var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.support-item:hover { border-color: rgb(37 99 235 / 30%); box-shadow: var(--shadow-raised); transform: translateY(-2px); }
.support-item__icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 7px; color: var(--color-primary); background: var(--color-info-wash); }
.support-item h3 { margin: 1px 0 4px; color: var(--color-text-primary); font-size: 13px; font-weight: 800; }
.support-item p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.support-item__arrow { align-self: center; margin-left: auto; color: var(--color-text-muted); }
.student-home > .status-callout { margin-top: 27px; }
.student-home__recent { margin-top: 39px; }
.text-link { display: inline-flex; align-items: center; gap: 5px; border: 0; color: var(--color-primary); background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; }
.text-link:hover { text-decoration: underline; text-underline-offset: 3px; }
.recent-row { display: flex; align-items: center; gap: 13px; padding: 15px 17px; }
.recent-row__icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.recent-row__copy { display: grid; flex: 1; gap: 3px; min-width: 0; }
.recent-row__copy strong { overflow: hidden; color: var(--color-text-primary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.recent-row__copy span { overflow: hidden; color: var(--color-text-muted); font-family: var(--font-mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.student-empty { display: grid; justify-items: center; padding: 55px 24px; text-align: center; }
.student-empty__mark { display: inline-flex; align-items: center; justify-content: center; width: 52px; height: 52px; border: 1px solid rgb(37 99 235 / 18%); border-radius: 12px; color: var(--color-primary); background: var(--color-info-wash); }
.student-empty h2 { margin: 18px 0 7px; font-family: var(--font-display); font-size: 22px; }
.student-empty p { max-width: 400px; margin: 0 0 22px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.student-loading { padding-top: 18px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }
.skeleton--short { width: 110px; height: 13px; }
.skeleton--title { width: min(480px, 70%); height: 35px; margin-top: 17px; }
.skeleton--body { width: min(620px, 90%); height: 16px; margin-top: 13px; }
.student-loading__grid { display: grid; grid-template-columns: 1.35fr 0.65fr; gap: 16px; margin-top: 32px; }
.skeleton--panel { height: 210px; }

@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { to { transform: translateX(100%); } }

@media (max-width: 760px) {
  .student-list-card, .student-history-row { align-items: flex-start; flex-wrap: wrap; }
  .student-reset { grid-template-columns: 1fr; }
  .student-reset .student-reset__hint { grid-column: auto; }
  .student-home__lead, .student-loading__grid { grid-template-columns: 1fr; }
  .support-grid { grid-template-columns: 1fr; }
  .student-home__state, .student-home__next { padding: 20px; }
  .student-home__next h2 { margin-top: 24px; }
}

@media (max-width: 480px) {
  .student-home__state-meta { display: grid; justify-content: stretch; gap: 9px; }
  .recent-row { align-items: flex-start; }
  .recent-row .app-badge { align-self: center; }
}
</style>
