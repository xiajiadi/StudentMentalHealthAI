<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft, ArrowRight, BookOpen, RotateCcw, ShieldAlert } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import type { ReportSummary } from '@/api/client'
import { useRouter } from 'vue-router'

const router = useRouter()
const reports = ref<ReportSummary[]>([])
const loading = ref(true)
const errorMessage = ref('')

const loadHistory = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    reports.value = (await frontendApi.listReports()).data.items
  } catch (error) {
    reports.value = []
    errorMessage.value = error instanceof Error ? error.message : '支持记录暂时无法加载。'
  } finally {
    loading.value = false
  }
}

const openReport = (reportId: string) => void router.push(`/student/reports/${encodeURIComponent(reportId)}`)
onMounted(loadHistory)
</script>

<template>
  <div class="content-wrap content-wrap--student education-support">
    <header class="support-heading">
      <div><span class="support-kicker">学生空间 · 教育支持</span><h1>教育支持</h1><p>查看当前服务能力和已经保存、且当前账号可访问的记录。</p></div>
      <AppBadge tone="attention" dot>当前受限</AppBadge>
    </header>

    <AppCard class="support-unavailable" raised>
      <span class="support-unavailable__icon"><ShieldAlert :size="22" aria-hidden="true" /></span>
      <div class="support-unavailable__copy">
        <span class="support-kicker">功能状态 · BLOCKED</span>
        <h2>独立支持生成暂不可用</h2>
        <p>当前后端支持请求需要关联测评；常规生成路径会在 <code>CLAIM_BOUNDARY</code> 阻断。此页面不会提交消息、创建虚构的测评关联，也不会展示占位回答或来源。</p>
        <div class="support-unavailable__actions">
          <AppButton @click="router.push('/student/history')">查看我的记录 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
          <RouterLink class="support-unavailable__back" to="/student/home"><ArrowLeft :size="16" aria-hidden="true" />返回学生首页</RouterLink>
        </div>
      </div>
      <img class="support-unavailable__art" :src="'/assets/heartbridge/card-student-original.png'" alt="" aria-hidden="true">
    </AppCard>

    <section class="support-records" aria-labelledby="support-records-title">
      <div class="support-records__heading"><div><span class="support-kicker">已保存</span><h2 id="support-records-title">支持记录</h2></div><span v-if="loading" role="status">正在加载…</span></div>
      <AppStatusCallout v-if="errorMessage" tone="attention" title="支持记录暂时无法加载" :body="errorMessage">
        <AppButton variant="secondary" size="sm" :loading="loading" @click="loadHistory"><RotateCcw :size="15" aria-hidden="true" />重试</AppButton>
      </AppStatusCallout>
      <AppCard v-else-if="!loading && reports.length === 0" class="support-records__empty">
        <BookOpen :size="20" aria-hidden="true" /><div><strong>还没有可显示的支持记录</strong><p>有新的、当前账号可访问的服务端记录后，会显示在这里。</p></div>
      </AppCard>
      <AppCard v-for="report in reports" :key="report.report_id" class="support-record-row">
        <span class="support-record-row__icon"><BookOpen :size="17" aria-hidden="true" /></span>
        <div><strong>{{ report.safety_action === 'CRISIS_ROUTE' ? '安全流程记录' : '教育支持记录' }}</strong><span>{{ report.created_at || '时间未提供' }} · {{ report.citation_count }} 条来源</span></div>
        <AppButton variant="secondary" size="sm" @click="openReport(report.report_id)">查看记录 <ArrowRight :size="15" aria-hidden="true" /></AppButton>
      </AppCard>
    </section>
  </div>
</template>

<style scoped>
.education-support { padding-top: 30px; padding-bottom: 64px; }
.support-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 22px; }
.support-kicker { color: var(--color-support); font-size: 11px; font-weight: 800; letter-spacing: .1em; }
.support-heading h1 { margin: 8px 0 5px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(30px, 4vw, 40px); letter-spacing: -.04em; }
.support-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.support-unavailable { position: relative; display: flex; align-items: flex-start; gap: 16px; overflow: hidden; padding: clamp(22px, 4vw, 34px); border-color: #e5dfce; background: linear-gradient(115deg, #fcfbf7, #f9f8f2); }
.support-unavailable__icon { position: relative; z-index: 1; display: grid; place-items: center; width: 44px; height: 44px; flex: 0 0 44px; border-radius: 14px; color: #947344; background: #f3eddf; }
.support-unavailable__copy { position: relative; z-index: 1; max-width: 660px; }
.support-unavailable__copy h2 { margin: 7px 0 8px; color: #3d4843; font-family: var(--font-display); font-size: clamp(20px, 3vw, 26px); }
.support-unavailable__copy p { margin: 0; color: #5e6963; font-size: 13px; line-height: 1.8; }
.support-unavailable__copy code { padding: 2px 5px; border-radius: 4px; color: #765d35; background: #f0ecdf; font-size: 11px; }
.support-unavailable__back { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; color: var(--color-text-secondary); font-size: 13px; font-weight: 500; transition: color var(--motion-fast); }
.support-unavailable__back:hover { color: var(--color-primary); }
.support-unavailable__actions { display: flex; align-items: center; gap: 20px; margin-top: 19px; }
.support-unavailable__actions a { color: var(--color-support); font-size: 12px; font-weight: 750; }
.support-unavailable__actions a:hover { text-decoration: underline; text-underline-offset: 3px; }
.support-unavailable__art { position: absolute; right: 20px; bottom: -35px; width: 150px; opacity: .2; }
.support-records { display: grid; gap: 9px; margin-top: 38px; }
.support-records__heading { display: flex; align-items: end; justify-content: space-between; margin-bottom: 5px; }
.support-records__heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 22px; }
.support-records__heading > span { color: var(--color-text-muted); font-size: 11px; }
.support-records > .status-callout { margin-top: 4px; }
.support-records__empty { display: flex; align-items: flex-start; gap: 12px; padding: 17px; color: #947344; }
.support-records__empty > div { display: grid; gap: 4px; }
.support-records__empty strong { color: var(--color-text-primary); font-size: 13px; }
.support-records__empty p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.support-record-row { display: flex; align-items: center; gap: 12px; padding: 13px 15px; }
.support-record-row__icon { display: grid; place-items: center; width: 34px; height: 34px; flex: 0 0 34px; border-radius: 10px; color: #947344; background: #f7f1e5; }
.support-record-row > div { display: grid; min-width: 0; flex: 1; gap: 4px; }
.support-record-row strong { color: var(--color-text-primary); font-size: 12px; }
.support-record-row span:not(.support-record-row__icon) { color: var(--color-text-secondary); font-size: 10px; }
@media (max-width: 600px) {
  .education-support { padding-top: 17px; }
  .support-unavailable { gap: 11px; padding: 19px 15px; }
  .support-unavailable__icon { width: 36px; height: 36px; flex-basis: 36px; border-radius: 11px; }
  .support-unavailable__art { right: -24px; width: 112px; }
  .support-unavailable__actions { align-items: flex-start; flex-direction: column; gap: 11px; }
  .support-record-row { align-items: flex-start; flex-wrap: wrap; }
  .support-record-row > div { flex-basis: calc(100% - 48px); }
  .support-record-row .app-button { margin-left: 46px; }
}
</style>
