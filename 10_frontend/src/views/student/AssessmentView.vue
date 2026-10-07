<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { CircleHelp } from '@lucide/vue'
import { Pause } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import { RadioGroupIndicator, RadioGroupItem, RadioGroupRoot } from 'reka-ui'
import AppButton from '@/components/app/AppButton.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppProgress from '@/components/app/AppProgress.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import { useAssessmentStore } from '@/stores/assessment'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const assessment = useAssessmentStore()
const selectedResponse = ref('')
const pageState = ref<'loading' | 'ready' | 'error'>('loading')
const isSubmitting = ref(false)
const isCompleting = ref(false)
const errorMessage = ref('')
const isPauseDialogOpen = ref(false)

const question = computed(() => assessment.question)
const canComplete = computed(() => assessment.canComplete && assessment.answeredCount > 0)
const progressLabel = computed(() => `已记录 ${assessment.answeredCount} 项`)
const actionLabel = computed(() => canComplete.value ? '完成并查看结构' : '保存并继续')

const load = async () => {
  pageState.value = 'loading'
  errorMessage.value = ''
  try {
    const routeAssessmentId = typeof route.params.id === 'string' ? route.params.id : undefined
    const existing = routeAssessmentId
      ? undefined
      : (await frontendApi.listAssessments()).data.find((item) => item.status === 'in_progress')
    const response = await frontendApi.startAssessment(routeAssessmentId || existing?.assessment_id)
    assessment.start({
      assessmentId: response.data.assessment_id,
      subjectId: response.data.subject_id,
      question: response.data.question,
      currentIndex: response.data.current_index,
      answeredCount: response.data.answered_count,
      canComplete: response.data.can_complete,
      maxItems: response.data.max_items,
    })
    pageState.value = 'ready'
  } catch (error) {
    pageState.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '测评会话没有准备好，请重试。'
  }
}

const submitResponse = async () => {
  if (!question.value || !assessment.assessmentId || !selectedResponse.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    const response = await frontendApi.submitAssessmentResponse(assessment.assessmentId, question.value.item_id, selectedResponse.value)
    assessment.update({
      question: response.data.question,
      currentIndex: response.data.current_index,
      answeredCount: response.data.answered_count,
      canComplete: response.data.can_complete,
    })
    selectedResponse.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '答案暂时没有保存，请重试。'
  } finally {
    isSubmitting.value = false
  }
}

const complete = async () => {
  if (!assessment.assessmentId || !canComplete.value) return
  isCompleting.value = true
  errorMessage.value = ''
  try {
    const response = await frontendApi.completeAssessment(assessment.assessmentId)
    assessment.reset()
    await router.push(`/student/assessment/${encodeURIComponent(response.data.assessment_id)}/result`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测评完成状态没有保存，请稍后重试。'
  } finally {
    isCompleting.value = false
  }
}

const primaryAction = () => canComplete.value ? complete() : submitResponse()
const leave = () => {
  isPauseDialogOpen.value = false
  assessment.reset()
  void router.push('/student/home')
}

onMounted(load)
</script>

<template>
  <div class="assessment-page">
    <div v-if="pageState === 'loading'" class="assessment-loading" aria-busy="true" aria-label="正在准备测评">
      <div class="skeleton skeleton--meta"></div>
      <div class="skeleton skeleton--question"></div>
      <div class="skeleton skeleton--option"></div>
      <div class="skeleton skeleton--option"></div>
      <div class="skeleton skeleton--option"></div>
    </div>

    <AppStatusCallout v-else-if="pageState === 'error'" tone="critical" title="测评会话暂时不可用" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新准备</AppButton>
    </AppStatusCallout>

    <template v-else-if="pageState === 'ready' && question">
      <div class="assessment-meta">
        <div>
          <span class="assessment-meta__eyebrow">专注模式</span>
          <p>第 {{ assessment.currentIndex + 1 }} 题 · 测评进行中</p>
        </div>
        <span class="assessment-meta__boundary">不计算或展示内部测量参数</span>
      </div>

      <AppProgress :value="assessment.answeredCount" :max="assessment.maxItems || 8" :label="progressLabel" :value-label="`${assessment.answeredCount} 项`" />

      <section class="question-card" aria-labelledby="question-title">
        <div class="question-card__top">
          <span class="question-card__number">{{ String(assessment.currentIndex + 1).padStart(2, '0') }}</span>
          <span class="question-card__hint"><CircleHelp :size="15" aria-hidden="true" />按自己的感受选择即可</span>
        </div>
        <h1 id="question-title">{{ question.prompt }}</h1>
        <p class="question-card__note">这是一个合成流程示例。选择后请点击下方按钮保存，不会自动提交。</p>

        <RadioGroupRoot v-model="selectedResponse" class="answer-list" :aria-label="question.prompt">
          <label v-for="option in question.options" :key="option.value" class="answer-option" :class="{ 'answer-option--selected': selectedResponse === option.value }">
            <RadioGroupItem :id="`answer-${option.value}`" class="answer-option__radio" :value="option.value">
              <RadioGroupIndicator class="answer-option__indicator" />
            </RadioGroupItem>
            <span class="answer-option__label">{{ option.label }}</span>
          </label>
        </RadioGroupRoot>

        <AppStatusCallout v-if="errorMessage" tone="critical" title="这一步没有完成" :body="errorMessage">
          <AppButton variant="secondary" size="sm" @click="primaryAction">重试</AppButton>
        </AppStatusCallout>

        <div v-if="canComplete" class="completion-note" role="status">
          <span class="completion-note__line" aria-hidden="true"></span>
          <p>系统已返回可以结束流程的状态。你也可以继续回答，完成按钮会保留在这里。</p>
        </div>

        <div class="question-card__footer">
          <button class="assessment-back" type="button" :disabled="isSubmitting || isCompleting" @click="isPauseDialogOpen = true">
            <Pause :size="16" aria-hidden="true" />暂停并离开
          </button>
          <div class="question-card__actions">
            <AppButton :disabled="!canComplete && !selectedResponse" :loading="isSubmitting || isCompleting" @click="primaryAction">
              {{ actionLabel }} <ArrowRight :size="16" aria-hidden="true" />
            </AppButton>
          </div>
        </div>
      </section>
    </template>

    <template v-else-if="pageState === 'ready' && canComplete">
      <div class="assessment-meta">
        <div>
          <span class="assessment-meta__eyebrow">专注模式</span>
          <p>测评项目已完成</p>
        </div>
        <span class="assessment-meta__boundary">不计算或展示内部测量参数</span>
      </div>

      <AppProgress :value="assessment.answeredCount" :max="assessment.maxItems || assessment.answeredCount" :label="progressLabel" :value-label="`${assessment.answeredCount} 项`" />

      <section class="question-card assessment-complete-card" aria-labelledby="assessment-complete-title">
        <span class="assessment-meta__eyebrow">可以进入下一步</span>
        <h1 id="assessment-complete-title">本次合成测评已经可以结束</h1>
        <p class="question-card__note">系统已返回完整的测评状态。完成后，后端会按安全流程生成教育支持参考。</p>
        <AppStatusCallout v-if="errorMessage" tone="critical" title="这一步没有完成" :body="errorMessage">
          <AppButton variant="secondary" size="sm" @click="complete">重试</AppButton>
        </AppStatusCallout>
        <div class="question-card__footer">
          <button class="assessment-back" type="button" :disabled="isCompleting" @click="isPauseDialogOpen = true">
            <Pause :size="16" aria-hidden="true" />暂停并离开
          </button>
          <div class="question-card__actions">
            <AppButton :loading="isCompleting" @click="complete">
              完成并查看结构 <ArrowRight :size="16" aria-hidden="true" />
            </AppButton>
          </div>
        </div>
      </section>
    </template>

    <AppDialog v-model:open="isPauseDialogOpen" title="要离开这次测评吗？" description="已保存的合成流程会被清除；真实部署时，保存与恢复规则由后端提供。">
      <div class="pause-dialog__actions">
        <AppButton variant="secondary" @click="isPauseDialogOpen = false">继续测评</AppButton>
        <AppButton variant="danger" @click="leave">离开测评</AppButton>
      </div>
    </AppDialog>
  </div>
</template>

<style scoped>
.assessment-page { animation: page-in 260ms ease both; }
.assessment-meta { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 19px; }
.assessment-meta__eyebrow { color: var(--color-primary); font-size: 11px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
.assessment-meta p { margin: 7px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 19px; font-weight: 700; }
.assessment-meta__boundary { color: var(--color-text-muted); font-size: 11px; }
.question-card { margin-top: 30px; padding: clamp(22px, 5vw, 42px); border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); box-shadow: var(--shadow-raised); }
.question-card__top { display: flex; align-items: center; justify-content: space-between; gap: 15px; }
.question-card__number { color: var(--color-primary); font-family: var(--font-mono); font-size: 13px; font-weight: 700; }
.question-card__hint { display: inline-flex; align-items: center; gap: 6px; color: var(--color-text-muted); font-size: 12px; }
.question-card h1 { max-width: 590px; margin: 32px 0 11px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(23px, 3vw, 31px); letter-spacing: -0.04em; line-height: 1.5; }
.question-card__note { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.answer-list { display: grid; gap: 10px; margin-top: 28px; }
.answer-option { display: flex; align-items: center; gap: 13px; min-height: 58px; padding: 0 15px; border: 1px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.answer-option:hover { border-color: rgb(37 99 235 / 45%); background: var(--color-surface-soft); }
.answer-option--selected { border-color: var(--color-primary); background: var(--color-info-wash); box-shadow: 0 0 0 2px rgb(37 99 235 / 10%); }
.answer-option__radio { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; flex: 0 0 20px; border: 1.5px solid var(--color-border-strong); border-radius: 50%; background: var(--color-surface); cursor: pointer; }
.answer-option__radio[data-state="checked"] { border-color: var(--color-primary); }
.answer-option__indicator { width: 10px; height: 10px; border-radius: 50%; background: var(--color-primary); }
.answer-option__label { font-size: 14px; font-weight: 600; }
.question-card .status-callout { margin-top: 18px; }
.completion-note { display: flex; align-items: center; gap: 10px; margin-top: 22px; padding-top: 15px; border-top: 1px solid var(--color-border); }
.completion-note__line { width: 24px; height: 2px; background: var(--color-support); }
.completion-note p { margin: 0; color: var(--color-support); font-size: 12px; line-height: 1.6; }
.question-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 15px; margin-top: 30px; padding-top: 18px; border-top: 1px solid var(--color-border); }
.assessment-back { display: inline-flex; align-items: center; gap: 7px; min-height: 44px; border: 0; color: var(--color-text-secondary); background: transparent; cursor: pointer; font-size: 12px; font-weight: 700; }
.assessment-back:hover { color: var(--color-primary); }
.assessment-back:disabled { cursor: not-allowed; opacity: 0.5; }
.question-card__actions { display: flex; align-items: center; gap: 10px; }
.pause-dialog__actions { display: flex; justify-content: flex-end; gap: 9px; }
.assessment-loading { display: grid; gap: 15px; padding-top: 20px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }
.skeleton--meta { width: 180px; height: 20px; }
.skeleton--question { width: 90%; height: 120px; margin-top: 25px; }
.skeleton--option { width: 100%; height: 58px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { to { transform: translateX(100%); } }

@media (max-width: 600px) {
  .assessment-meta { display: block; }
  .assessment-meta__boundary { display: block; margin-top: 9px; }
  .question-card { padding: 21px 17px; }
  .question-card h1 { margin-top: 25px; font-size: 22px; }
  .question-card__footer { display: grid; gap: 12px; }
  .question-card__actions { justify-content: flex-end; }
  .assessment-back { justify-self: start; }
}
</style>
