<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft } from '@lucide/vue'
import { ArrowRight } from '@lucide/vue'
import { CircleCheck } from '@lucide/vue'
import { Info } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { TeacherOverviewViewModel } from '@/types/view-models'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const data = ref<TeacherOverviewViewModel | null>(null)
const errorMessage = ref('')

const caseId = computed(() => typeof route.params.id === 'string' ? route.params.id : 'CASE_demo_review_001')
const currentCase = computed(() => data.value?.attentionCases.find((item) => item.caseId === caseId.value) || data.value?.attentionCases[0] || null)
const requiresReview = computed(() => currentCase.value?.priority === 'high')

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const response = await frontendApi.getTeacherOverview()
    data.value = response.data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '学生摘要暂时无法加载。'
  }
}

const goBack = () => void router.push('/teacher/students')

onMounted(load)
</script>

<template>
  <div class="content-wrap teacher-detail">
    <div v-if="state === 'loading'" class="detail-loading" aria-busy="true" aria-label="正在加载学生摘要"><div class="skeleton skeleton--small"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--panel"></div></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="学生摘要暂时无法加载" :body="errorMessage"><AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton></AppStatusCallout>
    <template v-else-if="data && currentCase">
      <AppPageHeader eyebrow="教师工作区 / 学生支持" :title="currentCase.subjectId" intro="当前页面仅展示经授权的匿名摘要，便于安排下一步支持。" :fixture-label="data.fixtureLabel">
        <template #actions><AppButton variant="quiet" size="sm" @click="goBack"><ArrowLeft :size="15" aria-hidden="true" />返回记录</AppButton></template>
      </AppPageHeader>

      <AppStatusCallout v-if="requiresReview" tone="attention" title="普通生成已暂停，等待人工复核" body="安全流程要求先完成复核。此页面不会提供继续生成个性化内容的入口。">
        <span class="review-boundary"><Info :size="15" aria-hidden="true" />复核动作由安全复核角色完成</span>
      </AppStatusCallout>
      <AppStatusCallout v-else tone="support" title="支持性沟通可以先从这里开始" body="这是一条合成流程记录。请围绕学生当前希望解决的事情，先约定一个可回看的小步骤。" />

      <section class="detail-grid" aria-label="学生摘要">
        <AppCard class="detail-card" raised>
          <div class="detail-card__heading"><div><span class="section-label">摘要</span><h2 class="section-title">当前记录</h2></div><AppBadge :tone="requiresReview ? 'amber' : 'teal'" dot>{{ currentCase.state }}</AppBadge></div>
          <dl class="detail-facts">
            <div><dt>案例标识</dt><dd>{{ currentCase.caseId }}</dd></div>
            <div><dt>匿名主体</dt><dd>{{ currentCase.subjectId }}</dd></div>
            <div><dt>最近更新</dt><dd>{{ currentCase.updatedAt }}</dd></div>
            <div><dt>数据范围</dt><dd>授权摘要</dd></div>
          </dl>
        </AppCard>

        <AppCard class="detail-card">
          <div class="detail-card__heading"><div><span class="section-label">测评结构</span><h2 class="section-title">只看结构，不下结论</h2></div><CircleCheck :size="19" class="detail-card__icon" aria-hidden="true" /></div>
          <p class="detail-card__body">本轮使用合成测评结构。页面不展示 theta、SE、原始回答或未经确认的心理学解释。</p>
          <div class="detail-bars" aria-label="合成结构示意">
            <div><span>维度 A · 合成占位</span><i style="width: 58%"></i></div>
            <div><span>维度 B · 合成占位</span><i style="width: 66%"></i></div>
          </div>
        </AppCard>
      </section>

      <AppCard class="detail-next">
        <div><span class="section-label">下一步</span><h2 class="section-title">保持流程可回看</h2><p>把支持动作、回看时间与实际结果记录在授权系统中。页面本身不会修改测评结果。</p></div>
        <AppButton variant="secondary" @click="goBack">返回支持记录 <ArrowRight :size="16" aria-hidden="true" /></AppButton>
      </AppCard>
    </template>
  </div>
</template>

<style scoped>
.teacher-detail { animation: page-in 260ms ease both; }
.teacher-detail > .status-callout { margin-bottom: 20px; }
.review-boundary { display: inline-flex; align-items: center; gap: 6px; margin-top: 8px; color: var(--color-attention); font-size: 12px; font-weight: 700; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 20px; }
.detail-card { min-height: 236px; padding: 20px; }
.detail-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }
.detail-card__heading .section-title { margin-top: 6px; }
.detail-card__icon { color: var(--color-support); }
.detail-facts { display: grid; gap: 0; margin: 21px 0 0; }
.detail-facts div { display: flex; justify-content: space-between; gap: 15px; padding: 11px 0; border-bottom: 1px solid var(--color-border); font-size: 12px; }
.detail-facts div:last-child { border-bottom: 0; }
.detail-facts dt { color: var(--color-text-muted); }.detail-facts dd { margin: 0; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 10px; text-align: right; }
.detail-card__body { margin: 20px 0 19px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.75; }
.detail-bars { display: grid; gap: 13px; }.detail-bars div { display: grid; gap: 5px; }.detail-bars span { color: var(--color-text-secondary); font-size: 11px; }.detail-bars i { display: block; height: 7px; border-radius: 99px; background: var(--color-primary); }.detail-bars div:nth-child(2) i { background: var(--color-support); }
.detail-next { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 16px; padding: 20px; }.detail-next p { max-width: 610px; margin: 8px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
.detail-loading { padding-top: 12px; }.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }.skeleton--small { width: 140px; height: 14px; }.skeleton--title { width: 300px; height: 34px; margin-top: 17px; }.skeleton--panel { height: 235px; margin-top: 32px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } } @keyframes shimmer { to { transform: translateX(100%); } }
@media (max-width: 680px) { .detail-grid { grid-template-columns: 1fr; }.detail-next { align-items: flex-start; flex-direction: column; }.detail-next .app-button { width: 100%; } }
</style>
