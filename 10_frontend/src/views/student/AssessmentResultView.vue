<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { CheckCircle2, RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentRecordDetailLayout from '@/components/student/StudentRecordDetailLayout.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt } from '@/data/student-feature-cards'
import { frontendApi } from '@/services/mock-api'
import type { Assessment } from '@/types/contracts'
import { useRoute } from 'vue-router'

const route = useRoute()
const assessment = ref<Assessment | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const errorMessage = ref('')
const isWho5 = computed(() => assessment.value?.instrument.instrument_id === 'WHO5_2024_EN')
const resultTitle = computed(() => isWho5.value ? 'WHO-5 测评已完成' : '本次合成测评已完成')
const resultSummary = computed(() => isWho5.value ? '五项答题记录已保存。' : '结果由服务端返回并保存，可从成长记录中查看。')

const formatDate = (value: string | null) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

let requestGeneration = 0

const load = async () => {
  const generation = ++requestGeneration
  const assessmentId = typeof route.params.id === 'string' ? route.params.id : ''
  state.value = 'loading'
  assessment.value = null
  errorMessage.value = ''
  try {
    const result = await frontendApi.getAssessmentResult(assessmentId)
    if (generation !== requestGeneration) return
    assessment.value = result.data
    state.value = 'ready'
  } catch (error) {
    if (generation !== requestGeneration) return
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '结果暂时无法加载。'
  }
}

watch(() => route.params.id, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { requestGeneration += 1 })
</script>

<template>
  <div class="content-wrap content-wrap--student assessment-result">
    <WorkspaceBreadcrumb v-if="state !== 'ready'" current="测评结果" :parent="{ label: '我的记录', to: '/student/history' }" />
    <div v-if="state === 'loading'" class="assessment-result__loading" aria-busy="true" aria-label="正在加载测评结果"></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="结果暂时无法加载" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
    </AppStatusCallout>
    <StudentRecordDetailLayout
      v-else-if="assessment"
      current="测评结果"
      :parent="{ label: '我的记录', to: '/student/history' }"
      eyebrow="ASSESSMENT RECORD"
      :title="resultTitle"
      :summary="resultSummary"
      :image="studentPageArt.assessments"
      :metadata="[{ label: '完成时间', value: formatDate(assessment.timestamps.completed_at) }]"
      :badges="[isWho5 ? 'WHO-5 英文原版（2024）' : '合成演示，教育用途']"
      :table-of-contents="[{ id: 'assessment-summary', label: '测评记录' }, { id: 'assessment-notes', label: '记录说明' }]"
    >
      <section id="assessment-summary" class="assessment-result__section" aria-labelledby="assessment-summary-title">
        <div class="assessment-result__section-heading"><span>RECORD</span><h2 id="assessment-summary-title">测评记录</h2></div>
        <AppCard class="assessment-result__summary" raised>
          <div class="assessment-result__mark"><CheckCircle2 :size="21" aria-hidden="true" /></div>
          <div><span class="section-label">已保存的答题记录</span><h3>已记录 {{ assessment.response_summary.items_answered }} 项回答</h3><p>{{ assessment.assessment_id }}</p></div>
        </AppCard>
      </section>
      <section id="assessment-notes" class="assessment-result__section" aria-labelledby="assessment-notes-title">
        <div class="assessment-result__section-heading"><span>NOTES</span><h2 id="assessment-notes-title">记录说明</h2></div>
        <AppStatusCallout v-if="!isWho5" tone="info" title="如何理解此页" body="这是工程演示中的测量记录，不代表真实心理量表的有效测量，不构成心理诊断或治疗建议。页面不对测量值作心理学解释。" />
        <p v-if="isWho5" class="assessment-result__source">来源：World Health Organization, WHO-5 (2024), CC BY-NC-SA 3.0 IGO</p>
        <AppStatusCallout v-else tone="attention" title="独立教育支持暂不可用" body="当前后端需要测评关联，常规支持生成会在 CLAIM_BOUNDARY 阻断。此演示不会生成占位回答或引用。" />
      </section>
    </StudentRecordDetailLayout>
  </div>
</template>

<style scoped>
.assessment-result { padding-top: 0; }
.assessment-result__section { display: grid; gap: 12px; scroll-margin-top: 86px; }
.assessment-result__section-heading > span { color: #6f8490; font-size: 10px; font-weight: 700; letter-spacing: .1em; }
.assessment-result__section-heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 21px; }
.assessment-result__summary { display: flex; align-items: center; gap: 16px; padding: 22px; }
.assessment-result__mark { display: grid; place-items: center; width: 44px; height: 44px; flex: 0 0 44px; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.assessment-result__summary h3 { margin: 6px 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 18px; }
.assessment-result__summary p { margin: 0; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.assessment-result__source { margin: 0; color: var(--color-text-muted); font-size: 12px; line-height: 1.65; }
.assessment-result__loading { position: relative; min-height: min(380px, calc(100svh - 210px)); overflow: hidden; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface-skeleton); }
.assessment-result__loading::after { position: absolute; inset: 0; content: ""; background: linear-gradient(100deg, transparent, rgb(255 255 255 / 66%), transparent); transform: translateX(-100%); animation: assessment-result-shimmer 1.35s ease-in-out infinite; }
@keyframes assessment-result-shimmer { to { transform: translateX(100%); } }
</style>
