<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft } from '@lucide/vue'
import { ArrowRight } from '@lucide/vue'
import { BookOpen } from '@lucide/vue'
import { CheckCircle2 } from '@lucide/vue'
import { Info } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import { ShieldCheck } from '@lucide/vue'
import DimensionRadar from '@/components/charts/DimensionRadar.vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import EvidenceItem from '@/components/evidence/EvidenceItem.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { StudentReportViewModel } from '@/types/view-models'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const data = ref<StudentReportViewModel | null>(null)
const errorMessage = ref('')

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const reportId = typeof route.params.id === 'string' ? route.params.id : 'REPORT_demo_student_001'
    const response = await frontendApi.getStudentReport(reportId)
    data.value = response.data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '结果页面暂时无法打开，请稍后重试。'
  }
}

const backHome = () => void router.push('/student/home')

onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student result-page">
    <div v-if="state === 'loading'" class="result-loading" aria-busy="true" aria-label="正在加载测评结果">
      <div class="skeleton skeleton--small"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--copy"></div>
      <div class="result-loading__grid"><div class="skeleton skeleton--panel"></div><div class="skeleton skeleton--panel"></div></div>
    </div>

    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="这份结果暂时无法打开" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
    </AppStatusCallout>

    <template v-else-if="data">
      <AppPageHeader eyebrow="学生结果" title="你的支持参考" intro="先看懂这份结果，再决定是否要做一个小行动。" :fixture-label="data.fixtureLabel">
        <template #actions>
          <AppButton variant="quiet" size="sm" @click="backHome"><ArrowLeft :size="15" aria-hidden="true" />返回首页</AppButton>
        </template>
      </AppPageHeader>

      <div class="result-identity">
        <div class="result-identity__mark" aria-hidden="true"><CheckCircle2 :size="22" /></div>
        <div><strong>结构化支持参考已准备</strong><span>{{ data.report.reportId }} · {{ data.report.assessment.timestamps.completed_at || '完成时间不可用' }}</span></div>
        <AppBadge tone="teal" dot>安全流程已完成</AppBadge>
      </div>

      <section id="meaning" class="result-section result-section--meaning" aria-labelledby="meaning-title">
        <div class="result-section__heading"><span class="result-section__index">01</span><div><span class="section-label">Meaning · 意义</span><h2 id="meaning-title">{{ data.meaning.title }}</h2></div></div>
        <p class="result-section__lead">{{ data.meaning.body }}</p>
        <div class="result-section__note"><Info :size="16" aria-hidden="true" /><span>{{ data.meaning.note }}</span></div>
      </section>

      <section id="data" class="result-section" aria-labelledby="data-title">
        <div class="result-section__heading"><span class="result-section__index">02</span><div><span class="section-label">Data · 数据</span><h2 id="data-title">{{ data.data.title }}</h2></div></div>
        <p class="result-section__description">{{ data.data.body }}</p>
        <AppCard class="data-panel" raised>
          <div class="data-panel__chart"><DimensionRadar :dimensions="data.data.dimensions" /></div>
          <div class="data-panel__list" aria-label="测评结构文字摘要">
            <div v-for="dimension in data.data.dimensions" :key="dimension.key" class="data-dimension">
              <span class="data-dimension__bar" :style="{ height: `${Math.max(22, dimension.value * 0.72)}px` }" aria-hidden="true"></span>
              <div><strong>{{ dimension.label }}</strong><span>{{ dimension.helper }}</span></div>
              <b>{{ dimension.value }}</b>
            </div>
          </div>
        </AppCard>
      </section>

      <section id="action" class="result-section" aria-labelledby="action-title">
        <div class="result-section__heading"><span class="result-section__index">03</span><div><span class="section-label">Action · 行动</span><h2 id="action-title">从一个能完成的动作开始</h2></div></div>
        <p class="result-section__description">下面的建议是教育支持场景中的合成示例。选择一项就够了，不需要一次完成所有事情。</p>
        <div v-if="data.report.generation.content" class="action-list">
          <AppCard v-for="action in data.actions" :key="action.number" class="action-item">
            <span class="action-item__number">{{ action.number }}</span>
            <div><h3>{{ action.title }}</h3><p>{{ action.body }}</p></div>
            <ArrowRight :size="17" class="action-item__arrow" aria-hidden="true" />
          </AppCard>
        </div>
        <AppStatusCallout v-else tone="attention" title="支持参考尚未完整准备" body="当前只显示已确认的部分内容；完整建议需要在后端流程完成后再展示。" />
      </section>

      <section id="evidence" class="result-section" aria-labelledby="evidence-title">
        <div class="result-section__heading"><span class="result-section__index">04</span><div><span class="section-label">Evidence · 依据</span><h2 id="evidence-title">为什么会看到这些建议</h2></div></div>
        <p class="result-section__description">每条支持建议都应能回到经过审核的资料片段。以下顺序与本次结果返回的引用顺序一致。</p>
        <AppCard class="evidence-panel">
          <div v-if="data.evidence.length">
            <EvidenceItem v-for="citation in data.evidence" :key="citation.citation_id" :citation="citation" />
          </div>
          <div v-else class="evidence-empty">
            <BookOpen :size="21" aria-hidden="true" />
            <strong>依据暂时不可用</strong>
            <p>这次页面没有收到可展示的引用，不会用猜测补齐来源。你可以稍后重新打开结果。</p>
            <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新查看</AppButton>
          </div>
        </AppCard>
      </section>

      <AppStatusCallout tone="support" title="给自己的提醒" body="测评和支持参考只用于帮助你整理下一步，不构成诊断或治疗建议。如果持续困扰或出现安全风险，请按照学校已审核的支持流程寻求专业帮助。">
        <ShieldCheck :size="16" aria-hidden="true" />
      </AppStatusCallout>
    </template>
  </div>
</template>

<style scoped>
.result-page { animation: page-in 260ms ease both; }
.result-identity { display: flex; align-items: center; gap: 12px; margin-bottom: 34px; padding: 13px 15px; border: 1px solid rgb(15 118 110 / 17%); border-radius: var(--radius-card); background: var(--color-support-wash); }
.result-identity__mark { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; flex: 0 0 36px; border-radius: 50%; color: var(--color-support); background: var(--color-surface); }
.result-identity > div:nth-child(2) { display: grid; flex: 1; min-width: 0; gap: 3px; }
.result-identity strong { color: var(--color-text-primary); font-size: 13px; }
.result-identity span { overflow: hidden; color: var(--color-text-secondary); font-family: var(--font-mono); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.result-section { margin-top: 54px; }
.result-section--meaning { margin-top: 0; padding: 25px; border-left: 3px solid var(--color-primary); background: var(--color-surface); box-shadow: var(--shadow-rest); }
.result-section__heading { display: flex; align-items: flex-start; gap: 15px; }
.result-section__index { padding-top: 2px; color: var(--color-primary); font-family: var(--font-mono); font-size: 12px; font-weight: 700; }
.result-section__heading h2 { margin: 8px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 23px; letter-spacing: -0.04em; line-height: 1.4; }
.result-section__lead { max-width: 720px; margin: 18px 0 0; color: var(--color-text-primary); font-size: 15px; line-height: 1.95; }
.result-section__description { max-width: 750px; margin: 13px 0 18px 34px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.75; }
.result-section__note { display: flex; align-items: flex-start; gap: 8px; margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 11px; line-height: 1.65; }
.result-section__note svg { flex: 0 0 auto; margin-top: 1px; color: var(--color-primary); }
.data-panel { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(260px, 0.9fr); gap: 8px; padding: 19px 22px; }
.data-panel__chart { min-width: 0; }
.data-panel__list { display: grid; align-content: center; gap: 8px; padding: 5px 0 5px 16px; border-left: 1px solid var(--color-border); }
.data-dimension { display: flex; align-items: center; gap: 10px; min-height: 56px; padding: 8px 0; border-bottom: 1px solid var(--color-border); }
.data-dimension:last-child { border-bottom: 0; }
.data-dimension__bar { display: inline-block; width: 4px; flex: 0 0 4px; border-radius: 3px; background: var(--color-primary); }
.data-dimension:nth-child(2) .data-dimension__bar { background: var(--color-support); }
.data-dimension:nth-child(3) .data-dimension__bar { background: var(--color-attention); }
.data-dimension:nth-child(4) .data-dimension__bar { background: var(--color-text-secondary); }
.data-dimension div { display: grid; min-width: 0; flex: 1; gap: 3px; }
.data-dimension strong { overflow: hidden; color: var(--color-text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.data-dimension span { color: var(--color-text-muted); font-size: 10px; }
.data-dimension b { color: var(--color-text-primary); font-family: var(--font-mono); font-size: 14px; font-weight: 700; }
.action-list { display: grid; gap: 10px; }
.action-item { display: flex; align-items: center; gap: 14px; padding: 16px 17px; transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease, transform var(--motion-fast) ease; }
.action-item:hover { border-color: rgb(37 99 235 / 28%); box-shadow: var(--shadow-raised); transform: translateY(-1px); }
.action-item__number { color: var(--color-primary); font-family: var(--font-mono); font-size: 12px; font-weight: 700; }
.action-item div { flex: 1; min-width: 0; }
.action-item h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; font-weight: 800; }
.action-item p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; }
.action-item__arrow { color: var(--color-text-muted); }
.evidence-panel { padding: 6px 18px; }
.evidence-empty { display: grid; justify-items: center; padding: 40px 20px; text-align: center; color: var(--color-text-muted); }
.evidence-empty svg { color: var(--color-attention); }
.evidence-empty strong { margin-top: 13px; color: var(--color-text-primary); font-size: 14px; }
.evidence-empty p { max-width: 360px; margin: 7px 0 17px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
.result-page > .status-callout { align-items: flex-start; margin-top: 34px; }
.result-page > .status-callout :deep(svg) { order: -1; flex: 0 0 auto; margin-top: 1px; color: var(--color-support); }
.result-loading { padding-top: 12px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }
.skeleton--small { width: 150px; height: 14px; }
.skeleton--title { width: 44%; height: 34px; margin-top: 17px; }
.skeleton--copy { width: 70%; height: 18px; margin-top: 13px; }
.result-loading__grid { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 16px; margin-top: 34px; }
.skeleton--panel { height: 270px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { to { transform: translateX(100%); } }

@media (max-width: 700px) {
  .result-identity { align-items: flex-start; flex-wrap: wrap; }
  .result-identity .app-badge { margin-left: 48px; }
  .result-section--meaning { padding: 20px 17px; }
  .result-section { margin-top: 43px; }
  .result-section__description { margin-left: 0; }
  .data-panel, .result-loading__grid { grid-template-columns: 1fr; }
  .data-panel { padding: 15px 16px; }
  .data-panel__list { padding: 14px 0 0; border-top: 1px solid var(--color-border); border-left: 0; }
}
</style>
