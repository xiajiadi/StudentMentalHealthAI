<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import { RadioGroupIndicator, RadioGroupItem, RadioGroupRoot } from 'reka-ui'
import AppButton from '@/components/app/AppButton.vue'
import AppProgress from '@/components/app/AppProgress.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentAssignedTasks from '@/components/school/StudentAssignedTasks.vue'
import { frontendApi } from '@/services/mock-api'
import { useAssessmentStore } from '@/stores/assessment'
import { useSessionStore } from '@/stores/session'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const assessment = useAssessmentStore()
const session = useSessionStore()
const selectedResponse = ref('')
const pageState = ref<'loading' | 'ready' | 'error' | 'assigned'>('loading')
const isSubmitting = ref(false)
const isCompleting = ref(false)
const errorMessage = ref('')

const question = computed(() => assessment.question)
const canComplete = computed(() => assessment.canComplete && assessment.answeredCount > 0)
const progressLabel = computed(() => `已记录 ${assessment.answeredCount} 项`)
const progressMaximum = computed(() => Math.max(
  question.value === null && assessment.canComplete
    ? assessment.answeredCount
    : assessment.maxItems ?? assessment.answeredCount + 1,
  1,
))
const progressValue = computed(() => Math.min(assessment.answeredCount, progressMaximum.value))

const load = async () => {
  pageState.value = 'loading'
  errorMessage.value = ''
  try {
    const routeAssessmentId = typeof route.params.id === 'string' ? route.params.id : undefined
    const existing = routeAssessmentId
      ? undefined
      : (await (frontendApi.listAssessmentEntries
          ? frontendApi.listAssessmentEntries({ status: 'in_progress', limit: 1 })
          : frontendApi.listAssessments({ status: 'in_progress', limit: 1 })))
        .data.find((item) => item.status === 'in_progress')
    if (!routeAssessmentId && !existing && session.user?.activeContext) {
      assessment.reset()
      pageState.value = 'assigned'
      return
    }
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

let pendingSubmission: Promise<boolean> | null = null

const saveSelectedResponse = () => {
  if (pendingSubmission) return pendingSubmission

  const currentQuestion = question.value
  const assessmentId = assessment.assessmentId
  const responseValue = selectedResponse.value
  if (!currentQuestion || !assessmentId || !responseValue) return Promise.resolve(true)

  isSubmitting.value = true
  errorMessage.value = ''
  pendingSubmission = (async () => {
    try {
      const response = await frontendApi.submitAssessmentResponse(assessmentId, currentQuestion.item_id, responseValue)
      assessment.update({
        question: response.data.question,
        currentIndex: response.data.current_index,
        answeredCount: response.data.answered_count,
        canComplete: response.data.can_complete,
      })
      selectedResponse.value = ''
      return true
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '答案暂时没有保存，请重试。'
      return false
    } finally {
      isSubmitting.value = false
    }
  })().finally(() => {
    pendingSubmission = null
  })

  return pendingSubmission
}

const submitResponse = async () => {
  if (!selectedResponse.value || !question.value || !assessment.assessmentId) return
  await saveSelectedResponse()
}

const complete = async () => {
  if (!assessment.assessmentId || !canComplete.value) return
  isCompleting.value = true
  errorMessage.value = ''
  try {
    if (!(await saveSelectedResponse()) || !canComplete.value) return
    const response = await frontendApi.completeAssessment(assessment.assessmentId)
    assessment.reset()
    await router.push(`/student/assessment/${encodeURIComponent(response.data.assessment_id)}/result`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测评完成状态没有保存，请稍后重试。'
  } finally {
    isCompleting.value = false
  }
}

onMounted(load)
onBeforeRouteLeave(saveSelectedResponse)
</script>

<template>
  <div class="assessment-page">
    <div v-if="pageState === 'loading'" class="assessment-loading" aria-busy="true" aria-label="正在准备测评">
      <div class="skeleton skeleton--question"></div>
      <div class="skeleton skeleton--option"></div>
      <div class="skeleton skeleton--option"></div>
      <div class="skeleton skeleton--option"></div>
    </div>

    <AppStatusCallout v-else-if="pageState === 'error'" tone="critical" title="测评会话暂时不可用" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新准备</AppButton>
    </AppStatusCallout>

    <section v-else-if="pageState === 'assigned'" class="assessment-assigned" aria-label="选择学校测评任务">
      <h1>选择学校测评任务</h1>
      <p>请选择当前开放的任务。已开始的测评可从本人记录中继续。</p>
      <StudentAssignedTasks />
    </section>

    <template v-else-if="pageState === 'ready' && question">
      <AppProgress :value="progressValue" :max="progressMaximum" :label="progressLabel" />

      <section class="question-card" aria-labelledby="question-title">
        <div class="question-card__top">
          <span class="question-card__number">{{ String(assessment.currentIndex + 1).padStart(2, '0') }}</span>
        </div>
        <h1 id="question-title">{{ question.prompt }}</h1>

        <RadioGroupRoot v-model="selectedResponse" class="answer-list" :aria-label="question.prompt" :disabled="isSubmitting || isCompleting">
          <label v-for="option in question.options" :key="option.value" class="answer-option" :class="{ 'answer-option--selected': selectedResponse === option.value }">
            <RadioGroupItem :id="`answer-${option.value}`" class="answer-option__radio" :value="option.value">
              <RadioGroupIndicator class="answer-option__indicator" />
            </RadioGroupItem>
            <span class="answer-option__label">{{ option.label }}</span>
          </label>
        </RadioGroupRoot>

        <AppStatusCallout v-if="errorMessage" tone="critical" title="这一步没有完成" :body="errorMessage">
          <AppButton variant="secondary" size="sm" @click="submitResponse">重试</AppButton>
        </AppStatusCallout>

        <div class="question-card__footer">
          <AppButton v-if="canComplete" variant="secondary" :disabled="isSubmitting || isCompleting" :loading="isCompleting" aria-label="完成测评" @click="complete">
            完成
          </AppButton>
          <AppButton :disabled="!selectedResponse || isSubmitting || isCompleting" :loading="isSubmitting" @click="submitResponse">
            下一题
          </AppButton>
        </div>
      </section>
    </template>

    <template v-else-if="pageState === 'ready' && canComplete">
      <AppProgress :value="progressValue" :max="progressMaximum" :label="progressLabel" />

      <section class="question-card assessment-complete-card" aria-labelledby="assessment-complete-title">
        <h1 id="assessment-complete-title">测评可结束</h1>
        <AppStatusCallout v-if="errorMessage" tone="critical" title="这一步没有完成" :body="errorMessage">
          <AppButton variant="secondary" size="sm" @click="complete">重试</AppButton>
        </AppStatusCallout>
        <div class="question-card__footer">
          <AppButton :loading="isCompleting" @click="complete">
            完成 <ArrowRight :size="16" aria-hidden="true" />
          </AppButton>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.assessment-page { width: 100%; animation: page-in 180ms ease both; }
.assessment-page :deep(.progress-wrap) { gap: clamp(5px, 0.8svh, 7px); }
.assessment-page :deep(.progress-wrap__label) { justify-content: flex-start; font-size: 12px; }
.assessment-page :deep(.progress-wrap__label strong) { display: none; }
.assessment-page :deep(.progress) { height: 5px; }
.question-card { margin-top: clamp(8px, 1.5svh, 14px); padding: clamp(16px, 2.4svh, 24px) clamp(18px, 2vw, 28px); border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); box-shadow: var(--shadow-raised); }
.question-card__top { display: flex; align-items: center; }
.question-card__number { color: var(--color-primary); font-family: var(--font-sans); font-size: 12px; font-variant-numeric: tabular-nums; font-weight: 700; }
.question-card h1 { max-width: none; margin: clamp(8px, 1.4svh, 13px) 0 clamp(10px, 1.8svh, 16px); color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(20px, calc(0.9vw + 0.8svh + 14px), 26px); letter-spacing: -0.025em; line-height: 1.35; }
.assessment-complete-card h1 { margin: 0 0 8px; }
.answer-list { display: grid; gap: clamp(6px, 0.9svh, 9px); margin-top: 0; }
.answer-option { display: flex; align-items: center; gap: 11px; min-height: clamp(38px, 5.8svh, 50px); padding: clamp(6px, 0.9svh, 10px) 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.answer-option:hover { border-color: rgb(37 99 235 / 45%); background: var(--color-surface-soft); }
.answer-option--selected { border-color: var(--color-primary); background: var(--color-info-wash); box-shadow: 0 0 0 2px rgb(37 99 235 / 10%); }
.answer-option__radio { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; flex: 0 0 18px; border: 1.5px solid var(--color-border-strong); border-radius: 50%; background: var(--color-surface); cursor: pointer; }
.answer-option__radio[data-state="checked"] { border-color: var(--color-primary); }
.answer-option__radio:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.answer-option__indicator { width: 9px; height: 9px; border-radius: 50%; background: var(--color-primary); }
.answer-option__label { font-size: 14px; font-weight: 600; line-height: 1.35; }
.question-card .status-callout { margin-top: 14px; }
.question-card__footer { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: clamp(10px, 1.6svh, 16px); padding-top: clamp(9px, 1.4svh, 14px); border-top: 1px solid var(--color-border); }
.assessment-loading { display: grid; gap: 9px; padding-top: 8px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }
.skeleton--question { width: 90%; height: 72px; margin-top: 8px; }
.skeleton--option { width: 100%; height: 46px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@keyframes shimmer { to { transform: translateX(100%); } }

@media (max-width: 600px) {
  .question-card { padding: 16px; }
  .question-card h1 { margin-top: 8px; font-size: 21px; }
  .answer-list { gap: 7px; }
  .question-card__footer { margin-top: 12px; }
}

@media (max-height: 640px) {
  .question-card { padding-block: 14px; }
  .question-card h1 { margin-block: 7px 9px; }
  .answer-option { min-height: 36px; padding-block: 5px; }
  .answer-list { gap: 5px; }
  .question-card__footer { margin-top: 8px; padding-top: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .assessment-page { animation: none; }
  .answer-option { transition: none; }
}
</style>
