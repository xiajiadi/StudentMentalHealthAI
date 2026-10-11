<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft, ArrowRight, CheckCircle2, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import type { Assessment } from '@/types/contracts'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const assessment = ref<Assessment | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const errorMessage = ref('')
const assessmentId = typeof route.params.id === 'string' ? route.params.id : ''

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    assessment.value = (await frontendApi.getAssessmentResult(assessmentId)).data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '结果暂时无法加载。'
  }
}

const openSupport = () => void router.push('/student/support')
onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student assessment-result">
    <div v-if="state === 'loading'" class="skeleton skeleton--panel" aria-busy="true" aria-label="正在加载测评结果"></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="结果暂时无法加载" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
    </AppStatusCallout>
    <template v-else-if="assessment">
      <AppPageHeader eyebrow="测评结果" title="本次合成测评已完成" intro="结果由服务端返回并保存，可从学生空间查看历史记录。" fixture-label="SYNTHETIC · DEMO · 教育用途 · 非诊断">
        <template #actions><AppBadge tone="teal" dot>已保存</AppBadge></template>
      </AppPageHeader>
      <AppStatusCallout tone="info" title="如何理解此页" body="这是工程演示中的测量记录，不代表真实心理量表的有效测量，不构成心理诊断或治疗建议。页面不对测量值作心理学解释。" />
      <AppCard class="assessment-result__summary" raised>
        <div class="assessment-result__mark"><CheckCircle2 :size="21" aria-hidden="true" /></div>
        <div><span class="section-label">测量记录</span><h2>已记录 {{ assessment.response_summary.items_answered }} 项回答</h2><p>{{ assessment.assessment_id }} · {{ assessment.timestamps.completed_at || '完成时间未提供' }}</p></div>
      </AppCard>
      <AppStatusCallout tone="attention" title="独立教育支持暂不可用" body="当前后端需要测评关联，常规支持生成会在 CLAIM_BOUNDARY 阻断。此演示不会生成占位回答或引用。" />
      <section class="assessment-result__actions" aria-label="下一步">
        <AppButton @click="openSupport">查看教育支持状态 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
        <RouterLink class="assessment-result__back" to="/student/home"><ArrowLeft :size="16" aria-hidden="true" />返回学生空间</RouterLink>
      </section>
    </template>
  </div>
</template>

<style scoped>
.assessment-result__summary { display: flex; align-items: center; gap: 16px; margin-top: 22px; padding: 22px; }
.assessment-result__back { display: inline-flex; align-items: center; gap: 7px; color: var(--color-text-secondary); font-size: 13px; font-weight: 500; transition: color var(--motion-fast); }
.assessment-result__back:hover { color: var(--color-primary); }
.assessment-result__mark { display: grid; place-items: center; width: 44px; height: 44px; flex: 0 0 44px; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.assessment-result__summary h2 { margin: 6px 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 20px; }
.assessment-result__summary p { margin: 0; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.assessment-result__actions { display: flex; align-items: center; gap: 20px; margin-top: 20px; }
.assessment-result__actions a { color: var(--color-primary); font-size: 13px; font-weight: 700; }
@media (max-width: 520px) { .assessment-result__actions { align-items: stretch; flex-direction: column; } }
</style>
