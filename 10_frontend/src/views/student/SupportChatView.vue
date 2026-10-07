<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, ArrowUp, BookOpen, ShieldAlert } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import type { ReportSummary, SupportResult } from '@/api/client'
import { useRoute, useRouter } from 'vue-router'

interface ChatEntry {
  question: string
  result: SupportResult
}

const route = useRoute()
const router = useRouter()
const assessmentId = computed(() => typeof route.query.assessment === 'string' ? route.query.assessment : '')
const draft = ref('')
const entries = ref<ChatEntry[]>([])
const reports = ref<ReportSummary[]>([])
const busy = ref(false)
const loadingHistory = ref(true)
const errorMessage = ref('')

const loadHistory = async () => {
  loadingHistory.value = true
  try {
    reports.value = (await frontendApi.listReports(assessmentId.value || undefined)).data.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '历史记录暂时无法加载。'
  } finally {
    loadingHistory.value = false
  }
}

const send = async () => {
  if (!assessmentId.value || !draft.value.trim() || busy.value) return
  const question = draft.value.trim()
  busy.value = true
  errorMessage.value = ''
  try {
    const result = (await frontendApi.createSupport(assessmentId.value, question)).data
    entries.value.push({ question, result })
    draft.value = ''
    await loadHistory()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '支持请求未完成，请稍后重试。'
  } finally {
    busy.value = false
  }
}

const openReport = (reportId: string) => void router.push(`/student/reports/${encodeURIComponent(reportId)}`)
const citations = (result: SupportResult) => result.citations.filter((item) => typeof item === 'object' && item !== null)
const hasCrisis = (result: SupportResult) => result.safety_action === 'CRISIS_ROUTE'
const isAbstain = (result: SupportResult) => !result.content && !hasCrisis(result)
const isReviewBlocked = (result: SupportResult) => Boolean(result.content)
  && (!result.normal_generation || !['generated', 'approved'].includes(result.status))
onMounted(loadHistory)
</script>

<template>
  <div class="content-wrap content-wrap--student support-chat">
    <AppPageHeader eyebrow="AI 支持" title="教育支持对话" intro="向本地演示服务提交问题。回答、状态和来源以服务端返回为准。" fixture-label="合成演示 · 非诊断">
      <template #actions><AppBadge tone="blue" dot>仅教育用途</AppBadge></template>
    </AppPageHeader>
    <AppStatusCallout tone="info" title="对话边界" body="系统不能诊断或提供治疗建议。高风险流程会由后端安全规则阻断普通生成；本页面不会自动联系家长或教师。" />

    <AppStatusCallout v-if="!assessmentId" tone="critical" title="还没有关联的测评" body="请从已完成测评的结果页进入支持对话。">
      <AppButton variant="secondary" size="sm" @click="router.push('/student/home')"><ArrowLeft :size="15" aria-hidden="true" />返回学生空间</AppButton>
    </AppStatusCallout>
    <template v-else>
      <section class="support-chat__thread" aria-label="支持对话记录" aria-live="polite">
        <AppCard v-if="entries.length === 0" class="support-chat__welcome">
          <span><BookOpen :size="18" aria-hidden="true" /></span>
          <div><strong>从一个具体的小问题开始</strong><p>例如：我想把这周的学习安排拆成更容易开始的几步。</p></div>
        </AppCard>

        <article v-for="(entry, index) in entries" :key="`${entry.result.report_id}-${index}`" class="support-turn">
          <div class="support-turn__question"><span>你</span><p>{{ entry.question }}</p></div>
          <AppCard class="support-turn__answer">
            <div v-if="hasCrisis(entry.result)" class="support-turn__state support-turn__state--blocked">
              <ShieldAlert :size="19" aria-hidden="true" /><div><strong>已进入安全流程</strong><p>后端返回 CRISIS_ROUTE；普通检索和生成未用于回答。请按照已审核的本地支持流程处理。</p></div>
            </div>
            <div v-else-if="isReviewBlocked(entry.result)" class="support-turn__state support-turn__state--blocked">
              <ShieldAlert :size="19" aria-hidden="true" /><div><strong>内容暂未开放</strong><p>服务端返回了需要确认的状态。页面不会展示待审核内容。</p></div>
            </div>
            <div v-else-if="isAbstain(entry.result)" class="support-turn__state">
              <ShieldAlert :size="19" aria-hidden="true" /><div><strong>目前没有可用的演示资料</strong><p>服务端没有返回可展示的回答。你可以换一种问法，或查看已有支持记录。</p></div>
            </div>
            <template v-else-if="entry.result.content">
              <span class="support-turn__label">服务端回答</span>
              <p v-if="entry.result.content?.summary" class="support-turn__summary">{{ entry.result.content.summary }}</p>
              <ul v-if="Array.isArray(entry.result.content?.suggestions) && entry.result.content.suggestions.length">
                <li v-for="(suggestion, suggestionIndex) in entry.result.content.suggestions" :key="suggestionIndex">{{ suggestion.text }}</li>
              </ul>
              <p v-if="entry.result.content?.disclaimer" class="support-turn__disclaimer">{{ entry.result.content.disclaimer }}</p>
            </template>
            <div v-if="citations(entry.result).length" class="support-turn__citations" aria-label="回答引用">
              <strong>来源</strong>
              <a v-for="citation in citations(entry.result)" :key="String(citation.citation_id || citation.chunk_id)" :href="typeof citation.locator === 'string' && citation.locator.startsWith('https://') ? citation.locator : undefined" :target="typeof citation.locator === 'string' && citation.locator.startsWith('https://') ? '_blank' : undefined" :rel="typeof citation.locator === 'string' && citation.locator.startsWith('https://') ? 'noreferrer' : undefined">
                {{ citation.title || citation.document_id || citation.chunk_id || '演示资料来源' }}<span v-if="citation.locator"> · {{ citation.locator }}</span>
              </a>
            </div>
            <footer class="support-turn__saved"><span>记录已返回</span><button type="button" @click="openReport(entry.result.report_id)">查看保存的报告</button></footer>
          </AppCard>
        </article>
      </section>

      <form class="support-chat__composer" @submit.prevent="send">
        <label for="support-message">你的问题</label>
        <textarea id="support-message" v-model="draft" rows="3" :disabled="busy" maxlength="2000" placeholder="写下你想整理的具体问题"></textarea>
        <div class="support-chat__composer-footer"><span>提交后会由后端安全检查并保存报告。</span><AppButton type="submit" :disabled="!draft.trim() || busy || !assessmentId" :loading="busy">发送 <ArrowUp :size="16" aria-hidden="true" /></AppButton></div>
      </form>
      <AppStatusCallout v-if="errorMessage" tone="critical" title="请求或历史记录未能加载" :body="errorMessage" />

      <section class="support-chat__history" aria-labelledby="support-history-title">
        <div class="support-chat__history-head"><div><span class="section-label">已保存</span><h2 id="support-history-title">报告与对话历史</h2></div><span v-if="loadingHistory" role="status">正在加载…</span></div>
        <p v-if="!loadingHistory && reports.length === 0" class="support-chat__empty">当前测评还没有已保存的支持报告。</p>
        <AppCard v-for="report in reports" :key="report.report_id" class="support-chat__history-row">
          <div><strong>{{ report.safety_action === 'CRISIS_ROUTE' ? '安全流程记录' : '教育支持报告' }}</strong><span>{{ report.report_id }} · {{ report.created_at || '时间未提供' }} · {{ report.citation_count }} 条来源</span></div>
          <AppButton variant="secondary" size="sm" @click="openReport(report.report_id)">打开记录</AppButton>
        </AppCard>
      </section>
    </template>
  </div>
</template>

<style scoped>
.support-chat__thread { display: grid; gap: 16px; margin: 22px 0; }
.support-chat__welcome, .support-turn__answer { padding: 18px; }
.support-chat__welcome { display: flex; gap: 12px; }
.support-chat__welcome > span { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 36px; border-radius: 9px; color: var(--color-primary); background: var(--color-info-wash); }
.support-chat__welcome strong, .support-turn__state strong { color: var(--color-text-primary); font-size: 14px; }
.support-chat__welcome p, .support-turn__state p { margin: 6px 0 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.support-turn { display: grid; gap: 10px; }
.support-turn__question { justify-self: end; max-width: min(85%, 620px); padding: 12px 15px; border-radius: 12px 12px 3px 12px; color: white; background: var(--color-primary); }
.support-turn__question span { font-size: 10px; opacity: .8; }
.support-turn__question p { margin: 4px 0 0; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.support-turn__label, .support-turn__citations > strong { color: var(--color-text-muted); font-size: 11px; font-weight: 800; }
.support-turn__summary { color: var(--color-text-primary); font-size: 14px; line-height: 1.75; white-space: pre-wrap; }
.support-turn__answer ul { padding-left: 21px; color: var(--color-text-primary); font-size: 13px; line-height: 1.8; }
.support-turn__disclaimer { color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
.support-turn__state { display: flex; gap: 11px; color: var(--color-text-secondary); }
.support-turn__state > svg { flex: 0 0 auto; color: var(--color-primary); }
.support-turn__state--blocked > svg { color: var(--color-critical); }
.support-turn__citations { display: grid; gap: 7px; padding-top: 13px; border-top: 1px solid var(--color-border); }
.support-turn__citations a { color: var(--color-primary); font-size: 12px; overflow-wrap: anywhere; }
.support-turn__citations a span { color: var(--color-text-muted); }
.support-turn__saved { display: flex; justify-content: space-between; gap: 12px; margin-top: 13px; color: var(--color-text-muted); font-size: 11px; }
.support-turn__saved button { border: 0; color: var(--color-primary); background: transparent; cursor: pointer; font: inherit; font-weight: 700; }
.support-chat__composer { display: grid; gap: 9px; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.support-chat__composer label { color: var(--color-text-primary); font-size: 13px; font-weight: 700; }
.support-chat__composer textarea { width: 100%; resize: vertical; padding: 11px; border: 1px solid var(--color-border-strong); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); font: inherit; line-height: 1.6; }
.support-chat__composer textarea:focus-visible { outline: 3px solid rgb(37 99 235 / 28%); outline-offset: 1px; }
.support-chat__composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.support-chat__composer-footer > span, .support-chat__history-head > span { color: var(--color-text-muted); font-size: 11px; }
.support-chat__history { display: grid; gap: 10px; margin-top: 34px; }
.support-chat__history-head { display: flex; align-items: end; justify-content: space-between; }
.support-chat__history-head h2 { margin: 6px 0 0; font-family: var(--font-display); font-size: 20px; }
.support-chat__empty { color: var(--color-text-muted); font-size: 13px; }
.support-chat__history-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; }
.support-chat__history-row > div { display: grid; gap: 4px; min-width: 0; }
.support-chat__history-row strong { font-size: 13px; }
.support-chat__history-row span { color: var(--color-text-secondary); font-size: 11px; overflow-wrap: anywhere; }
@media (max-width: 520px) { .support-chat__history-row { align-items: flex-start; flex-direction: column; } .support-chat__composer-footer { align-items: flex-start; flex-direction: column; } .support-turn__question { max-width: 96%; } }
</style>
