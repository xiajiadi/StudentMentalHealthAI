<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, CheckCircle2, RotateCcw } from '@lucide/vue'
import { RadioGroupIndicator, RadioGroupItem, RadioGroupRoot } from 'reka-ui'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppLoadingDots from '@/components/app/AppLoadingDots.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'
import type {
  ResearchAnswerInput,
  ResearchL1Session,
  ResearchSessionDiscoveryEntry,
  ResearchTaskDiscoveryEntry,
} from '@/api/client'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const sessionStore = useSessionStore()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const researchSession = ref<ResearchL1Session | null>(null)
const completedReceipt = ref<ResearchSessionDiscoveryEntry | null>(null)
const selectedOption = ref('')
const pending = ref(false)
const errorMessage = ref('')
const generation = ref(0)
const startIdempotencyKey = ref('')
const pendingAnswer = ref<{ input: ResearchAnswerInput; idempotencyKey: string } | null>(null)
let receiptLookupController: ReturnType<typeof globalThis.AbortController> | null = null

const taskRef = computed(() => typeof route.params.taskRef === 'string' ? route.params.taskRef : '')
const sessionRef = computed(() => typeof route.params.sessionRef === 'string' ? route.params.sessionRef : '')
const routeKey = computed(() => JSON.stringify([taskRef.value, sessionRef.value]))
const skipRouteLoadKey = ref('')
const contextKey = computed(() => JSON.stringify([
  sessionStore.user?.userId ?? '', sessionStore.role ?? '',
  sessionStore.user?.activeContext?.schoolRef ?? '', sessionStore.user?.activeContext?.role ?? '',
]))
const question = computed(() => researchSession.value?.question ?? null)
const complete = computed(() => researchSession.value?.status === 'COMPLETED')
const selectedRawValue = computed(() => {
  if (!question.value || !selectedOption.value) return null
  const option = question.value.response_options.find((item) => String(item.value) === selectedOption.value)
  return option?.value ?? null
})

const createIdempotencyKey = (scope: string) => {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `frontend-${scope}-${suffix}`
}

const errorText = (error: unknown, fallback: string) => {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    const code = String(error.code).toLowerCase()
    if (code === 'forbidden' || code === '403') return '当前账号暂时无法访问此研究任务。'
    if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '任务或会话已不可用，请返回任务列表刷新。'
    if (code === 'workflow_conflict' || code === 'conflict' || code === '409') return '会话状态已变化，请返回任务列表后重新进入。'
  }
  return error instanceof Error ? error.message : fallback
}

const errorCode = (error: unknown) => {
  if (typeof error === 'object' && error !== null && 'code' in error) {
    return String(error.code).toLowerCase()
  }
  return ''
}

const isConflictOrUnavailable = (error: unknown) => {
  const code = errorCode(error)
  return code === 'workflow_conflict' || code === 'conflict' || code === '409'
    || code === 'resource_not_found' || code === 'not_found' || code === '404'
}

const formatReceiptDate = (value: string | null) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const findCompletedReceipt = async (reference: string, requestGeneration: number) => {
  if (!frontendApi.listStudentResearchSessions) return false
  receiptLookupController?.abort()
  const controller = new globalThis.AbortController()
  receiptLookupController = controller
  let offset = 0
  try {
    while (offset <= 10_000) {
      const page = (await frontendApi.listStudentResearchSessions({
        limit: 30,
        offset,
        signal: controller.signal,
      })).data
      if (requestGeneration !== generation.value || controller.signal.aborted) return false
      const exact = page.items.find((item) => item.session_ref === reference)
      if (exact) {
        if (exact.status !== 'COMPLETED' || exact.research_only !== true) return false
        completedReceipt.value = exact
        researchSession.value = null
        selectedOption.value = ''
        pendingAnswer.value = null
        state.value = 'ready'
        errorMessage.value = ''
        return true
      }
      if (!page.has_more || page.next_offset === null || page.next_offset <= offset) return false
      offset = page.next_offset
    }
  } catch {
    // The signed-in discovery API is only a fallback receipt source. If it is
    // unavailable, keep the original resume error and show no inferred state.
  }
  return false
}

const findTaskSession = async (reference: string, requestGeneration: number): Promise<ResearchTaskDiscoveryEntry | null> => {
  if (!frontendApi.listStudentResearchTasks) return null
  receiptLookupController?.abort()
  const controller = new globalThis.AbortController()
  receiptLookupController = controller
  let offset = 0
  try {
    while (offset <= 10_000) {
      const page = (await frontendApi.listStudentResearchTasks({
        limit: 30,
        offset,
        signal: controller.signal,
      })).data
      if (requestGeneration !== generation.value || controller.signal.aborted) return null
      const exact = page.items.find((item) => item.task_ref === reference)
      if (exact) return exact
      if (!page.has_more || page.next_offset === null || page.next_offset <= offset) return null
      offset = page.next_offset
    }
  } catch {
    // Do not replace the start error with discovery transport details.
  }
  return null
}

const recoverExistingTaskSession = async (requestGeneration: number) => {
  const task = await findTaskSession(taskRef.value, requestGeneration)
  if (requestGeneration !== generation.value || !task?.session_ref) return false
  if (task.session_status === 'COMPLETED') {
    return await findCompletedReceipt(task.session_ref, requestGeneration)
  }
  if (task.session_status !== 'IN_PROGRESS') return false
  await enterResumeRoute(task.session_ref, requestGeneration)
  if (requestGeneration !== generation.value || sessionRef.value !== task.session_ref) return false
  await resume(requestGeneration)
  return state.value === 'ready' && Boolean(researchSession.value || completedReceipt.value)
}

const acceptSession = (value: ResearchL1Session, expectedSessionRef?: string) => {
  if (expectedSessionRef && value.session_ref !== expectedSessionRef) {
    throw new Error('研究会话标识与当前页面不一致，请返回任务列表后重新进入。')
  }
  researchSession.value = value
  selectedOption.value = ''
  pendingAnswer.value = null
  state.value = 'ready'
}

const enterResumeRoute = async (reference: string, requestGeneration: number) => {
  if (sessionRef.value === reference) return
  const destinationKey = JSON.stringify(['', reference])
  skipRouteLoadKey.value = destinationKey
  try {
    await router.replace({ name: 'student-research-session-resume', params: { sessionRef: reference } })
  } finally {
    if (skipRouteLoadKey.value === destinationKey) skipRouteLoadKey.value = ''
  }
  if (requestGeneration !== generation.value || sessionRef.value !== reference) return
}

const start = async (requestGeneration = generation.value) => {
  if (!taskRef.value || !frontendApi.startStudentResearchTask) {
    state.value = 'error'
    errorMessage.value = '当前环境没有可用的研究任务服务；不会使用模拟数据替代。'
    return
  }
  if (!startIdempotencyKey.value) startIdempotencyKey.value = createIdempotencyKey(`research-start-${taskRef.value}`)
  pending.value = true
  errorMessage.value = ''
  let started: ResearchL1Session
  try {
    const response = await frontendApi.startStudentResearchTask(taskRef.value, startIdempotencyKey.value)
    if (requestGeneration !== generation.value) return
    started = response.data
  } catch (error) {
    if (requestGeneration !== generation.value) return
    if (isConflictOrUnavailable(error)) {
      const recovered = await recoverExistingTaskSession(requestGeneration)
      if (requestGeneration !== generation.value) return
      if (recovered) {
        startIdempotencyKey.value = ''
        pending.value = false
        return
      }
    }
    state.value = 'error'
    errorMessage.value = errorText(error, '研究任务暂时无法开始。重试会沿用本次请求编号。')
    pending.value = false
    return
  }
  if (requestGeneration !== generation.value) return
  startIdempotencyKey.value = ''
  pending.value = false
  acceptSession(started)
  try {
    await enterResumeRoute(started.session_ref, requestGeneration)
    if (requestGeneration !== generation.value) return
    if (started.resume_required) await resumeAfterReplay()
  } catch {
    if (requestGeneration !== generation.value) return
    errorMessage.value = '会话已建立，但恢复地址未能更新。请返回任务列表后继续。'
  }
}

const resume = async (requestGeneration = generation.value) => {
  if (!sessionRef.value || !frontendApi.resumeStudentResearchSession) {
    state.value = 'error'
    errorMessage.value = '当前环境没有可用的研究会话服务；请连接已配置的本地服务。'
    return
  }
  pending.value = true
  errorMessage.value = ''
  try {
    // A completed historical record is a read-only receipt. Do not attempt
    // state restoration for legacy bindings that cannot accept new answers.
    if (await findCompletedReceipt(sessionRef.value, requestGeneration)) return
    if (requestGeneration !== generation.value) return
    const response = await frontendApi.resumeStudentResearchSession(sessionRef.value)
    if (requestGeneration !== generation.value) return
    acceptSession(response.data, sessionRef.value)
  } catch (error) {
    if (requestGeneration !== generation.value) return
    if (isConflictOrUnavailable(error)
      && await findCompletedReceipt(sessionRef.value, requestGeneration)) {
      return
    }
    if (requestGeneration !== generation.value) return
    state.value = 'error'
    errorMessage.value = errorText(error, '研究会话暂时无法恢复。')
  } finally {
    if (requestGeneration === generation.value) pending.value = false
  }
}

const load = () => {
  const requestGeneration = ++generation.value
  receiptLookupController?.abort()
  receiptLookupController = null
  startIdempotencyKey.value = ''
  researchSession.value = null
  completedReceipt.value = null
  selectedOption.value = ''
  pendingAnswer.value = null
  errorMessage.value = ''
  state.value = 'loading'
  if (sessionRef.value) void resume(requestGeneration)
  else void start(requestGeneration)
}

const submitAnswer = async (retry = false) => {
  const current = researchSession.value
  const currentQuestion = question.value
  if (!current || current.status !== 'IN_PROGRESS' || !currentQuestion || pending.value) return
  if (!retry && selectedRawValue.value === null) return
  if (!frontendApi.answerStudentResearchSession) {
    errorMessage.value = '当前环境没有可用的研究会话服务；答案未保存。'
    return
  }
  if (!pendingAnswer.value) {
    pendingAnswer.value = {
      input: {
        item_id: currentQuestion.item_id,
        raw_value: selectedRawValue.value as number,
        expected_state_version: current.state_version,
      },
      idempotencyKey: createIdempotencyKey(`research-answer-${current.session_ref}-${current.state_version}`),
    }
  }
  const requestGeneration = generation.value
  pending.value = true
  errorMessage.value = ''
  try {
    const response = await frontendApi.answerStudentResearchSession(
      current.session_ref,
      pendingAnswer.value.input,
      pendingAnswer.value.idempotencyKey,
    )
    if (requestGeneration !== generation.value) return
    if (response.data.session_ref !== current.session_ref
      || response.data.items_answered !== current.items_answered + 1
      || response.data.state_version <= current.state_version) {
      throw new Error('会话进度响应无法确认；请返回任务列表后重新进入。')
    }
    acceptSession(response.data, current.session_ref)
  } catch (error) {
    if (requestGeneration !== generation.value) return
    errorMessage.value = errorText(error, '答案暂时没有保存。点击重试会沿用相同请求编号。')
  } finally {
    if (requestGeneration === generation.value) pending.value = false
  }
}

const resumeAfterReplay = async () => {
  const current = researchSession.value
  if (!current?.resume_required || !frontendApi.resumeStudentResearchSession) return
  const requestGeneration = generation.value
  pending.value = true
  errorMessage.value = ''
  try {
    await enterResumeRoute(current.session_ref, requestGeneration)
    if (requestGeneration !== generation.value) return
    const response = await frontendApi.resumeStudentResearchSession(current.session_ref)
    if (requestGeneration !== generation.value) return
    acceptSession(response.data, current.session_ref)
  } catch (error) {
    if (requestGeneration !== generation.value) return
    errorMessage.value = errorText(error, '当前题目暂时无法恢复。')
  } finally {
    if (requestGeneration === generation.value) pending.value = false
  }
}

watch(routeKey, (current) => {
  if (skipRouteLoadKey.value === current) {
    skipRouteLoadKey.value = ''
    return
  }
  load()
}, { flush: 'sync' })

watch(contextKey, (current, previous) => {
  if (!previous || current === previous) return
  generation.value += 1
  receiptLookupController?.abort()
  receiptLookupController = null
  startIdempotencyKey.value = ''
  pendingAnswer.value = null
  researchSession.value = null
  selectedOption.value = ''
  pending.value = false
  state.value = 'error'
  errorMessage.value = '当前学校身份已切换；为保护会话，请返回任务列表后重新进入。'
  const destinationKey = JSON.stringify(['', ''])
  skipRouteLoadKey.value = destinationKey
  void router.replace('/student/assessments').finally(() => {
    if (skipRouteLoadKey.value === destinationKey) skipRouteLoadKey.value = ''
  })
})
onMounted(load)
onBeforeUnmount(() => {
  generation.value += 1
  receiptLookupController?.abort()
})
</script>

<template>
  <main class="research-cat content-wrap content-wrap--student" aria-labelledby="research-cat-title">
    <header class="research-cat__heading">
      <RouterLink to="/student/assessments" class="research-cat__back"><ArrowLeft :size="15" aria-hidden="true" />返回我的测评</RouterLink>
      <div><span class="research-cat__tag">仅研究演示，未获发布或运营批准</span><h1 id="research-cat-title">公开研究任务</h1></div>
    </header>

    <AppStatusCallout tone="info" title="按来源原文作答" body="题目和选项保持来源文字与原始数值；本页面不生成个人分数、解释或建议。" />

    <AppCard v-if="state === 'loading'" class="research-cat__state" aria-busy="true">正在核对研究会话或本人完成记录<AppLoadingDots /></AppCard>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="研究会话暂时不可用" :body="errorMessage">
      <AppButton variant="secondary" size="sm" :loading="pending" @click="sessionRef ? load() : start()">
        <RotateCcw :size="15" aria-hidden="true" />{{ sessionRef ? '重新读取会话' : '重试开始' }}
      </AppButton>
    </AppStatusCallout>

    <template v-else-if="completedReceipt">
      <AppCard class="research-cat__completion">
        <span class="research-cat__completion-icon"><CheckCircle2 :size="21" aria-hidden="true" /></span>
        <div><h2>研究完成记录</h2><p>本人记录显示已完成 {{ completedReceipt.items_answered }} 项<span v-if="formatReceiptDate(completedReceipt.completed_at)">，完成时间 {{ formatReceiptDate(completedReceipt.completed_at) }}</span>。此记录不包含测评分数或解释。</p></div>
      </AppCard>
      <div class="research-cat__actions"><RouterLink to="/student/assessments">返回我的测评 <ArrowRight :size="15" aria-hidden="true" /></RouterLink></div>
    </template>
    <template v-else-if="researchSession && complete">
      <AppCard class="research-cat__completion">
        <span class="research-cat__completion-icon"><CheckCircle2 :size="21" aria-hidden="true" /></span>
        <div><h2>研究会话已记录</h2><p>已记录 {{ researchSession.completion?.items_answered ?? researchSession.items_answered }} 项回答。此记录不包含个人测评分数或解释。</p></div>
      </AppCard>
      <div class="research-cat__actions"><RouterLink to="/student/assessments">返回我的测评 <ArrowRight :size="15" aria-hidden="true" /></RouterLink></div>
    </template>

    <template v-else-if="researchSession && researchSession.status === 'IN_PROGRESS' && researchSession.resume_required && !question">
      <AppStatusCallout v-if="errorMessage" tone="critical" title="当前题目尚未恢复" :body="errorMessage" />
      <AppCard class="research-cat__state"><span>会话已存在，需要重新读取当前题目。</span><AppButton :loading="pending" @click="resumeAfterReplay">恢复当前题目</AppButton></AppCard>
    </template>

    <template v-else-if="researchSession && researchSession.status === 'IN_PROGRESS' && question">
      <div class="research-cat__progress" aria-live="polite">已记录 {{ researchSession.items_answered }} 项</div>
      <section class="research-cat__question" aria-labelledby="research-question-title">
        <span class="research-cat__step">第 {{ question.step + 1 }} 题</span>
        <h2 id="research-question-title">{{ question.stem }}</h2>
        <RadioGroupRoot v-model="selectedOption" class="research-cat__options" :aria-label="question.stem" :disabled="pending || pendingAnswer !== null">
          <label
            v-for="option in question.response_options"
            :key="option.value"
            class="research-cat__option"
            :class="{ 'research-cat__option--selected': selectedOption === String(option.value) }"
          >
            <RadioGroupItem :id="`research-answer-${option.value}`" class="research-cat__radio" :value="String(option.value)">
              <RadioGroupIndicator class="research-cat__indicator" />
            </RadioGroupItem>
            <span class="research-cat__option-label">{{ option.label ?? String(option.value) }}</span>
          </label>
        </RadioGroupRoot>
        <AppStatusCallout v-if="errorMessage" tone="critical" title="答案暂未确认" :body="errorMessage">
          <AppButton variant="secondary" size="sm" :loading="pending" @click="submitAnswer(true)"><RotateCcw :size="15" aria-hidden="true" />使用相同请求重试</AppButton>
        </AppStatusCallout>
        <div class="research-cat__footer">
          <AppButton :disabled="selectedRawValue === null || pending || pendingAnswer !== null" :loading="pending" @click="submitAnswer()">
            保存并继续 <ArrowRight :size="15" aria-hidden="true" />
          </AppButton>
        </div>
      </section>
    </template>

    <AppStatusCallout v-else-if="researchSession" tone="attention" title="会话已结束" body="此会话当前不可继续。返回任务列表查看最新状态。">
      <RouterLink to="/student/assessments">返回我的测评</RouterLink>
    </AppStatusCallout>
  </main>
</template>

<style scoped>
.research-cat { display: grid; gap: 16px; padding-top: 8px; padding-bottom: 32px; }
.research-cat__heading { display: grid; gap: 14px; }
.research-cat__back { display: inline-flex; align-items: center; gap: 6px; width: fit-content; color: var(--color-text-secondary); font-size: 12px; text-decoration: none; }
.research-cat__back:focus-visible,.research-cat__actions a:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.research-cat__tag { color: #8f651d; font-size: 11px; font-weight: 700; }
.research-cat__heading h1 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(23px, 3vw, 30px); font-weight: 650; line-height: 1.25; }
.research-cat__state { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 70px; padding: 17px; color: var(--color-text-secondary); font-size: 13px; }
.research-cat__progress { color: var(--color-text-secondary); font-size: 12px; }
.research-cat__question { padding: clamp(18px, 3vw, 28px); border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); box-shadow: var(--shadow-raised); }
.research-cat__step { color: var(--color-primary); font-size: 12px; font-weight: 700; }
.research-cat__question h2 { margin: 11px 0 18px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(19px, 2.5vw, 25px); font-weight: 620; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.research-cat__options { display: grid; gap: 8px; }
.research-cat__option { display: flex; align-items: center; gap: 11px; min-height: 46px; padding: 8px 12px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; }
.research-cat__option:hover { border-color: var(--color-primary); background: var(--color-surface-soft); }
.research-cat__option--selected { border-color: var(--color-primary); background: var(--color-info-wash); }
.research-cat__radio { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; flex: 0 0 18px; border: 1.5px solid var(--color-border-strong); border-radius: 50%; background: var(--color-surface); }
.research-cat__radio:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.research-cat__radio[data-state="checked"] { border-color: var(--color-primary); }
.research-cat__indicator { width: 9px; height: 9px; border-radius: 50%; background: var(--color-primary); }
.research-cat__option-label { font-size: 14px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
.research-cat__question .status-callout { margin-top: 14px; }
.research-cat__footer { display: flex; justify-content: flex-end; margin-top: 17px; padding-top: 14px; border-top: 1px solid var(--color-border); }
.research-cat__completion { display: flex; align-items: flex-start; gap: 13px; padding: 20px; }
.research-cat__completion-icon { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 50%; color: var(--color-support); background: var(--color-support-wash); }
.research-cat__completion h2 { margin: 3px 0 6px; color: var(--color-text-primary); font-size: 17px; }
.research-cat__completion p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.research-cat__actions { display: flex; justify-content: flex-end; }
.research-cat__actions a { display: inline-flex; align-items: center; gap: 6px; color: var(--color-primary); font-size: 12px; font-weight: 700; text-decoration: none; }
@media(max-width:600px) { .research-cat__state { align-items: flex-start; flex-direction: column; }.research-cat__question { padding: 17px; } }
</style>
