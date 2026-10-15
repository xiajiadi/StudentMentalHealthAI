<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import ResearchFeedbackSources from '@/components/school/ResearchFeedbackSources.vue'
import SpecialistResearchEducationInputReviews from '@/components/school/SpecialistResearchEducationInputReviews.vue'
import SpecialistResearchEducationOutputReviews from '@/components/school/SpecialistResearchEducationOutputReviews.vue'
import { newResearchFeedbackIdempotencyKey } from '@/services/school-research-feedback'
import { schoolResearchEducationCandidates, type ResearchEducationCandidateDetail, type ResearchEducationCandidateSummary } from '@/services/school-research-education-candidates'
import type { ResearchEducationGenerationJob } from '@/services/school-research-education-candidates'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const props = defineProps<{ taskRef: string; sessionRef?: string; canUseSource: boolean; disabled?: boolean }>()
const emit = defineEmits<{ source: [candidate: ResearchEducationCandidateDetail] }>()
const session = useSessionStore()
const rows = ref<ResearchEducationCandidateSummary[]>([])
const detail = ref<ResearchEducationCandidateDetail | null>(null)
const status = ref<'HELD' | 'ADOPTED' | 'DISCARDED'>('HELD')
const offset = ref(0)
const hasMore = ref(false)
const jobs = ref<ResearchEducationGenerationJob[]>([])
const jobTotal = ref(0)
const jobCounts = ref<Record<string, number>>({})
const busy = ref(false)
const errorMessage = ref('')
const notice = ref('')
const batchOffset = ref(0)
const confirmation = ref('')
const pending = ref<(() => Promise<unknown>) | null>(null)
let sequence = 0
let alive = true
const allowed = computed(() => session.user?.role === 'psychological_specialist')
const canWrite = computed(() => allowed.value && !busy.value && !props.disabled && !pending.value)
const linked = computed(() => detail.value?.status === 'ADOPTED' && detail.value.session_ref === props.sessionRef && props.canUseSource)

function clear() {
  ++sequence
  rows.value = []; detail.value = null; errorMessage.value = ''; notice.value = ''
  jobs.value = []; jobTotal.value = 0; jobCounts.value = {}
  offset.value = 0; hasMore.value = false; batchOffset.value = 0
  confirmation.value = ''; pending.value = null; busy.value = false
}
async function load(next = 0) {
  if (!allowed.value || !props.taskRef || pending.value) return
  const current = ++sequence
  busy.value = true; errorMessage.value = ''; detail.value = null; confirmation.value = ''
  try {
    const [page, jobPage] = await Promise.all([
      schoolResearchEducationCandidates.list(props.taskRef, status.value, next, 20),
      schoolResearchEducationCandidates.listJobs(props.taskRef, 0, 20),
    ])
    if (!alive || current !== sequence || !allowed.value) return
    rows.value = page.items; offset.value = page.offset; hasMore.value = page.has_more
    jobs.value = jobPage.items; jobTotal.value = jobPage.total; jobCounts.value = jobPage.status_counts
  } catch (error) {
    if (current !== sequence) return
    rows.value = []; jobs.value = []; jobTotal.value = 0; jobCounts.value = {}; errorMessage.value = userFacingApiError(error, '教育候选暂时无法加载。')
  } finally { if (current === sequence) busy.value = false }
}
function jobLabel(value: string): string {
  return ({ QUEUED: '等待生成', LEASED: '正在生成', RETRY: '等待处理', HELD: '待核对', ABSTAINED: '未生成内容', REVIEW_REQUIRED: '需人工处理', CRISIS_ROUTED: '已进入安全处理', FAILED: '生成失败', CANCELLED: '已停止' } as Record<string, string>)[value] ?? '状态待确认'
}
function jobRoundLabel(job: ResearchEducationGenerationJob): string {
  return job.generation_round === 0
    ? '原始研究任务'
    : `授权继续任务（输入复核 ${job.input_review_ref}）`
}
function jobExplanation(job: ResearchEducationGenerationJob): string | null {
  if (!['ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED'].includes(job.status)) return null
  const explanation = ({
    SAFETY_BLOCKED: '安全检查要求复核，尚未生成可用内容。',
    SOURCE_UNQUALIFIED: '资料不满足本次研究要求，未生成可用内容。',
    GENERATION_FAILED: '生成未完成，未生成可用内容。',
    UPSTREAM_TIMEOUT: '处理超时，未生成可用内容。',
    UPSTREAM_TRANSIENT: '所需服务暂不可用，未生成可用内容。',
    INTERNAL_FAILURE_OUTCOME_VALIDATION: '返回内容未通过格式检查，未生成可用内容。',
  } as Record<string, string>)[job.last_error_code ?? ''] ?? '此任务已结束，未生成可用内容。'
  return `${explanation} 刷新页面不会自动重新生成。`
}
async function open(item: ResearchEducationCandidateSummary) {
  if (!canWrite.value) return
  const current = ++sequence
  busy.value = true; detail.value = null; errorMessage.value = ''; confirmation.value = ''
  try {
    const value = await schoolResearchEducationCandidates.get(props.taskRef, item.candidate_ref)
    if (alive && current === sequence && allowed.value) detail.value = value
  } catch (error) { if (current === sequence) errorMessage.value = userFacingApiError(error, '候选详情暂不可用。') }
  finally { if (current === sequence) busy.value = false }
}
async function mutate(run: () => Promise<unknown>) {
  if (!allowed.value || busy.value || props.disabled) return
  const current = ++sequence
  busy.value = true; errorMessage.value = ''
  try {
    const result = await run()
    if (!alive || current !== sequence || !allowed.value) return
    pending.value = null; detail.value = null; confirmation.value = ''
    if (result && typeof result === 'object' && 'next_offset' in result) {
      const next = result.next_offset
      if (typeof next === 'number') batchOffset.value = next
      notice.value = '本批已提交；生成内容将进入待核对列表。点击刷新查看处理结果。'
    } else notice.value = '候选状态已更新。采纳后仍需单独修订、复核和发布反馈。'
    busy.value = false
    await load(offset.value)
  } catch (error) {
    if (current !== sequence) return
    errorMessage.value = userFacingApiError(error, '操作未完成。')
    const retryable = error && typeof error === 'object' && 'retryable' in error && error.retryable
    pending.value = retryable ? run : null
  } finally { if (current === sequence) busy.value = false }
}
function enqueue() {
  if (!canWrite.value || confirmation.value !== 'enqueue') return
  const key = newResearchFeedbackIdempotencyKey()
  const taskRef = props.taskRef; const start = batchOffset.value
  void mutate(() => schoolResearchEducationCandidates.enqueue(taskRef, 25, start, key))
}
function resolve(target: 'ADOPTED' | 'DISCARDED') {
  const row = detail.value
  if (!row || row.status !== 'HELD' || !canWrite.value || confirmation.value !== target) return
  const key = newResearchFeedbackIdempotencyKey(); const taskRef = props.taskRef
  void mutate(() => schoolResearchEducationCandidates.resolve(taskRef, row, target, key))
}
function refreshAfterOutputReview() {
  confirmation.value = ''
  if (status.value === 'HELD') void load(0)
  else status.value = 'HELD'
}
watch(() => [props.taskRef, session.user?.role, session.user?.userId, session.user?.activeContext] as const, () => { clear(); if (allowed.value) void load() }, { immediate: true })
watch(status, () => { if (!busy.value && !pending.value) void load() })
onBeforeUnmount(() => { alive = false; clear() })
</script>

<template>
  <AppCard v-if="allowed" class="education-candidates">
    <header><div><h3>AI 教育候选</h3><p>核对原始生成内容与来源中的研究限制，再修订为学生反馈。原候选会保留。</p></div><AppButton variant="quiet" size="sm" :disabled="busy || Boolean(pending)" @click="load(offset)">刷新候选</AppButton></header>
    <div class="education-candidates__controls">
      <label>查看状态 <select v-model="status" :disabled="busy || Boolean(pending)"><option value="HELD">待核对</option><option value="ADOPTED">已采纳为来源</option><option value="DISCARDED">已弃用</option></select></label>
      <label>批量起始记录 <input v-model.number="batchOffset" type="number" min="0" max="100000" step="1" :disabled="!canWrite"></label>
      <label><input v-model="confirmation" type="radio" value="enqueue" :disabled="!canWrite">确认将此任务下一批最多 25 条完成记录入队</label>
      <AppButton size="sm" :disabled="!canWrite || confirmation !== 'enqueue' || !Number.isInteger(batchOffset) || batchOffset < 0 || batchOffset > 100000" @click="enqueue">提交本批生成</AppButton>
    </div>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="jobTotal" role="status">本任务共 {{ jobTotal }} 项生成任务：<span v-for="(count,name) in jobCounts" :key="name"><template v-if="count">{{ jobLabel(String(name)) }} {{ count }} 项；</template></span></p>
    <details v-if="jobs.length"><summary>查看生成状态（最多 20 条）</summary><ul><li v-for="(job,index) in jobs" :key="job.job_ref">任务 {{ index + 1 }}：{{ jobRoundLabel(job) }} · {{ jobLabel(job.status) }} · 已尝试 {{ job.attempt_count }} 次<small v-if="jobExplanation(job)">{{ jobExplanation(job) }}</small></li></ul></details>
    <p v-if="busy" role="status" aria-busy="true">正在处理…</p>
    <AppStatusCallout v-if="errorMessage" tone="critical" title="候选操作未完成" :body="errorMessage"><AppButton v-if="pending" size="sm" :disabled="busy" @click="mutate(pending!)">使用相同请求重试</AppButton></AppStatusCallout>
    <p v-if="!busy && !rows.length && !errorMessage">当前没有此状态的候选。</p>
    <div class="education-candidates__rows"><AppButton v-for="(row,index) in rows" :key="row.candidate_ref" variant="secondary" size="sm" :disabled="!canWrite" @click="open(row)">候选 {{ offset + index + 1 }}{{ row.session_ref === sessionRef ? ' · 当前复核记录' : '' }}</AppButton></div>
    <nav v-if="offset || hasMore" aria-label="教育候选分页"><AppButton variant="quiet" size="sm" :disabled="busy || Boolean(pending) || offset === 0" @click="load(Math.max(0,offset-20))">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="busy || Boolean(pending) || !hasMore" @click="load(offset+20)">下一页</AppButton></nav>
    <section v-if="detail" class="education-candidates__original" aria-label="原始生成候选">
      <h4>原始生成内容</h4><p>{{ detail.candidate_payload.content.summary }}</p>
      <ul><li v-for="(item,index) in detail.candidate_payload.content.observations" :key="index">{{ item }}</li></ul>
      <ul><li v-for="(item,index) in detail.candidate_payload.content.suggestions" :key="index">{{ item.text }}</li></ul>
      <p>{{ detail.candidate_payload.content.disclaimer }}</p>
      <ResearchFeedbackSources :source-cards="detail.candidate_payload.source_cards" />
      <div v-if="detail.status === 'HELD'" class="education-candidates__controls"><label><input v-model="confirmation" type="radio" value="ADOPTED" :disabled="!canWrite">已核对来源，采纳为修订依据</label><AppButton size="sm" :disabled="!canWrite || confirmation !== 'ADOPTED'" @click="resolve('ADOPTED')">采纳来源</AppButton><label><input v-model="confirmation" type="radio" value="DISCARDED" :disabled="!canWrite">弃用此候选</label><AppButton variant="secondary" size="sm" :disabled="!canWrite || confirmation !== 'DISCARDED'" @click="resolve('DISCARDED')">弃用候选</AppButton></div>
      <AppButton v-if="linked" size="sm" :disabled="!canWrite" @click="emit('source',detail)">用于当前反馈修订稿</AppButton>
      <p v-else-if="detail.status === 'ADOPTED'">选择同一完成记录并完成复核后，可将此来源用于新的反馈修订稿。</p>
    </section>
  </AppCard>
  <SpecialistResearchEducationOutputReviews
    :task-ref="taskRef"
    :disabled="disabled"
    @candidate-created="refreshAfterOutputReview"
  />
  <SpecialistResearchEducationInputReviews :task-ref="taskRef" :disabled="disabled" />
</template>

<style scoped>
.education-candidates { display: grid; gap: 12px; padding: 17px; min-width: 0; }
.education-candidates header,.education-candidates__controls,.education-candidates__rows,.education-candidates nav { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.education-candidates header { justify-content: space-between; align-items: flex-start; }
.education-candidates h3,.education-candidates h4 { margin: 0; font-size: 15px; }
.education-candidates p,.education-candidates li,.education-candidates label { margin: 5px 0; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.education-candidates li small { display: block; color: var(--color-text-secondary); }
.education-candidates input[type=number] { width: 88px; }
.education-candidates select,.education-candidates input[type=number] { padding: 6px; border: 1px solid #d7e3de; border-radius: 6px; background: white; color: var(--color-text-primary); }
.education-candidates__original { display: grid; gap: 9px; border-top: 1px solid #e4ece8; padding-top: 14px; }
.education-candidates :focus-visible { outline: 2px solid #438e7b; outline-offset: 3px; }
</style>
