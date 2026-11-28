<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppSelect from '@/components/app/AppSelect.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { roleHomes } from '@/components/shell/navigation'
import { studentEducationArticles } from '@/services/student-education'
import { readSchoolFeedbackContent } from '@/services/school-feedback-content'
import { useSessionStore } from '@/stores/session'
import {
  schoolSupport, supportActionStates, supportCaseStates, supportCategories, supportError,
  supportPageSize, supportRequestKey, type SupportAction, type SupportCase, type TeacherReferral,
} from '@/services/school-support'

const { audience, initialReferral, preparePlan, openLatestPlan } = defineProps<{
  audience: 'student' | 'teacher' | 'specialist'
  initialReferral?: TeacherReferral
  preparePlan?: boolean
  openLatestPlan?: boolean
}>()
const session = useSessionStore()
const router = useRouter()
const titles = { student: '向学校求助', teacher: '班级支持', specialist: '学生支持' }
const workspace = {
  student: { label: '学生空间', to: roleHomes.student },
  teacher: { label: '教师工作区', to: roleHomes.teacher },
  specialist: { label: '心理老师工作区', to: roleHomes.psychological_specialist },
}[audience]
const cases = ref<Awaited<ReturnType<typeof schoolSupport.cases>> | null>(null)
const actions = ref<Awaited<ReturnType<typeof schoolSupport.actions>> | null>(null)
const students = ref<Awaited<ReturnType<typeof schoolSupport.students>>>([])
const assignees = ref<Awaited<ReturnType<typeof schoolSupport.assignees>>>([])
const current = ref<SupportCase | null>(null)
const selected = ref('')
const offset = ref(0)
const actionOffset = ref(0)
const loading = ref(false)
const detailLoading = ref(false)
const busy = ref(false)
const failure = ref('')
const notice = ref('')
const readError = ref('')
const detailError = ref('')
const assigneeError = ref('')
const studentKey = ref('')
const category = ref<keyof typeof supportCategories>(
  audience === 'teacher' && initialReferral ? initialReferral.category_code : 'LEARNING_SUPPORT',
)
const content = ref(audience === 'teacher' ? initialReferral?.observation ?? '' : '')
const plan = ref('')
const planEvidence = ref<Awaited<ReturnType<typeof schoolSupport.planEvidence>>>()
const evidenceLoading = ref(false)
const evidenceError = ref('')
const includeEvidence = ref(false)
const feedbackText = computed(() => planEvidence.value && readSchoolFeedbackContent(planEvidence.value.body))
const planTopic = ref('')
const planArticle = computed(() => studentEducationArticles.find((article) => article.id === planTopic.value))
const planResources = [
  { value: '', label: '暂不选资料' },
  ...studentEducationArticles.map((article) => ({ value: article.id, label: article.title })),
]
const recipient = ref('')
const instructions = ref('')
const due = ref('')
const closeConfirmed = ref(false)
const feedback = ref<Record<string, string>>({})
const retry = ref<(() => void) | null>(null)
const locked = computed(() => loading.value || detailLoading.value || busy.value || Boolean(retry.value))
const planningOnly = computed(() => audience === 'specialist' && Boolean(openLatestPlan))
const student = computed(() => students.value.find((entry) => JSON.stringify([entry.classRef, entry.studentRef]) === studentKey.value))
const studentOptions = computed(() => students.value.map((entry) => ({
  value: JSON.stringify([entry.classRef, entry.studentRef]),
  label: `${entry.name} · ${entry.classRef}`,
})))
const categoryOptions = Object.entries(supportCategories).map(([value, label]) => ({ value, label }))
const recipientOptions = computed(() => [
  { value: 'STUDENT', label: '学生本人' },
  ...assignees.value.map((entry) => ({ value: entry.userId, label: entry.name })),
])
const dateFormatter = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
const dueDate = computed(() => new Date(due.value))
const mayAssign = computed(() => audience === 'specialist' && ['PLANNED', 'FOLLOWING'].includes(current.value?.status ?? ''))
const canClose = computed(() => current.value?.actions.every((item) => ['ACCEPTED', 'CANCELLED'].includes(item.status)))
const recipientValid = computed(() => recipient.value === 'STUDENT' || assignees.value.some((entry) => entry.userId === recipient.value))
let live = true
let detailRequest = 0

function checkSession(cause: unknown) {
  const code = cause && typeof cause === 'object' && 'code' in cause ? String(cause.code).toLowerCase() : ''
  if (live && ['auth_session_expired', 'auth_session_revoked'].includes(code)) {
    session.signOut()
    void router.replace('/login')
  }
}

async function load(selectLatest = false) {
  loading.value = true
  readError.value = ''
  const results = await Promise.allSettled([
    schoolSupport.cases(offset.value, planningOnly.value),
    audience === 'specialist' ? Promise.resolve(null) : schoolSupport.actions(actionOffset.value),
    audience === 'teacher' ? schoolSupport.students() : Promise.resolve([]),
  ] as const)
  if (!live) return
  const [casePage, actionPage, directory] = results
  cases.value = casePage.status === 'fulfilled' ? casePage.value : null
  actions.value = actionPage.status === 'fulfilled' ? actionPage.value : null
  students.value = directory.status === 'fulfilled' ? directory.value : []
  for (const result of results) {
    if (result.status === 'rejected') {
      checkSession(result.reason)
      readError.value = supportError(result.reason)
    }
  }
  loading.value = false
  const latest = cases.value?.items[0]
  if (selectLatest && planningOnly.value && latest) await openCase(latest.caseRef)
}

async function openCase(ref: string) {
  const request = ++detailRequest
  selected.value = ref
  current.value = null
  detailError.value = ''
  assigneeError.value = ''
  assignees.value = []
  detailLoading.value = Boolean(ref)
  closeConfirmed.value = false
  planEvidence.value = undefined
  evidenceLoading.value = false
  evidenceError.value = ''
  includeEvidence.value = false
  if (!ref) return
  try {
    const item = await schoolSupport.detail(ref)
    if (!live || request !== detailRequest) return
    current.value = item
    if (audience === 'specialist' && ['PLANNED', 'FOLLOWING'].includes(item.status)) {
      try {
        const rows = await schoolSupport.assignees(ref)
        if (live && request === detailRequest) assignees.value = rows
      } catch (cause) {
        if (live && request === detailRequest) {
          checkSession(cause)
          assigneeError.value = supportError(cause)
        }
      }
    }
  } catch (cause) {
    if (live && request === detailRequest) {
      checkSession(cause)
      detailError.value = supportError(cause)
    }
  } finally {
    if (live && request === detailRequest) detailLoading.value = false
  }
}

function selectCase(ref: string) {
  plan.value = ''
  planTopic.value = ''
  recipient.value = ''
  instructions.value = ''
  due.value = ''
  void openCase(ref)
}

async function loadPlanEvidence() {
  const item = current.value
  if (!item || item.status !== 'TRIAGED' || locked.value || evidenceLoading.value) return
  const request = detailRequest
  evidenceLoading.value = true
  evidenceError.value = ''
  includeEvidence.value = false
  planEvidence.value = undefined
  try {
    const result = await schoolSupport.planEvidence(item.caseRef)
    if (live && request === detailRequest) planEvidence.value = result
  } catch (cause) {
    if (live && request === detailRequest) {
      checkSession(cause)
      evidenceError.value = supportError(cause)
    }
  } finally {
    if (live && request === detailRequest) evidenceLoading.value = false
  }
}

function draftSupportPlan() {
  const item = current.value
  if (!item || audience !== 'specialist' || item.status !== 'TRIAGED' || plan.value.trim() || locked.value || evidenceLoading.value) return
  const source = item.source === 'STUDENT_REQUEST' ? '学生主动求助' : '教师转介'
  const facts = `已核对事实\n${source} · ${supportCategories[item.category]} · ${supportCaseStates[item.status]}。记录更新于 ${dateFormatter.format(new Date(item.updatedAt))}`
  const reviewed = includeEvidence.value ? planEvidence.value : null
  const evidence = reviewed
    ? `已核对的测评反馈\n《${reviewed.title}》第 ${reviewed.revision} 版，发布于 ${dateFormatter.format(new Date(reviewed.publishedAt))}\n请结合反馈和学生当前情况，由心理教师确认哪些建议适用于本次请求`
    : ''
  const evidenceGap = reviewed
    ? '本次草案尚未核对获批风险规则'
    : '当前草案未引用授权的测评反馈。若需结合测评，请先核对获授权的正式复核记录'
  const unknowns = [
    '待向学生核实',
    '先确认请求描述是否仍适用、学生希望获得哪类支持，以及希望由谁联系',
    evidenceGap,
  ].join('\n')
  const decisions = '待心理教师确认\n记录学生同意的支持事项、负责人、下一次联系时间和复核方式'
  const article = planArticle.value
  const references = article ? `可供沟通参考的通用科普\n${article.title}\n${article.source}\n${article.url}` : ''
  plan.value = [facts, evidence, unknowns, decisions, references].filter(Boolean).join('\n\n')
}

type Operation = (key: string) => Promise<unknown>
async function execute(operation: Operation, key: string, onSuccess?: () => void) {
  busy.value = true
  failure.value = ''
  notice.value = ''
  try {
    await operation(key)
    if (!live) return
    retry.value = null
    onSuccess?.()
    notice.value = '已保存。'
  } catch (cause) {
    if (!live) return
    checkSession(cause)
    failure.value = supportError(cause)
    retry.value = cause && typeof cause === 'object' && 'retryable' in cause && cause.retryable === true
      ? () => void execute(operation, key, onSuccess) : null
  } finally {
    if (live) {
      await Promise.all([load(), openCase(selected.value)])
      busy.value = false
    }
  }
}

function submit(operation: Operation, onSuccess?: () => void) {
  if (locked.value) return
  try {
    void execute(operation, supportRequestKey(), onSuccess)
  } catch {
    failure.value = '当前浏览器无法建立安全请求。'
  }
}

function transition(status: 'TRIAGED' | 'PLANNED' | 'REVIEW' | 'CLOSED') {
  const item = current.value
  if (item) submit((key) => schoolSupport.transition(item, status, key, status === 'PLANNED' ? plan.value.trim() : undefined))
}

function assign() {
  const item = current.value
  if (!item || !recipientValid.value || !instructions.value.trim() || !Number.isFinite(dueDate.value.getTime())) return
  const input = { instructions: instructions.value.trim(), dueAt: dueDate.value.toISOString(), teacher: recipient.value === 'STUDENT' ? undefined : recipient.value }
  submit((key) => schoolSupport.assign(item, input, key), () => { instructions.value = ''; due.value = '' })
}

function submitFeedback(action: SupportAction) {
  const note = feedback.value[action.actionRef]?.trim()
  if (!note) return
  submit((key) => schoolSupport.feedback(action, 'SUBMITTED', key, note), () => { delete feedback.value[action.actionRef] })
}

function isActionOpen(action: SupportAction) {
  return action.status === 'PENDING' || action.status === 'RETURNED'
}

onMounted(() => void load(true))
onScopeDispose(() => { live = false })
</script>

<template>
  <section class="school-support content-wrap">
    <WorkspaceBreadcrumb :current="titles[audience]" :home-label="workspace.label" :home-to="workspace.to" />
    <h1 class="sr-only">{{ titles[audience] }}</h1>
    <p v-if="notice" role="status">{{ notice }}</p>
    <AppStatusCallout v-if="failure" tone="attention" title="操作未完成" :body="failure">
      <AppButton v-if="retry" variant="secondary" :disabled="busy" @click="retry?.()">使用同一请求重试</AppButton>
    </AppStatusCallout>
    <AppStatusCallout v-if="readError" tone="attention" title="部分记录无法读取" :body="readError">
      <AppButton variant="secondary" :disabled="locked" @click="load(!selected && offset === 0)">重新加载</AppButton>
    </AppStatusCallout>
    <AppCard v-if="audience !== 'specialist'">
      <form class="school-support__panel" @submit.prevent="submit((key) => schoolSupport.create(category, content.trim(), key, student), () => { content = '' })">
        <h2>{{ audience === 'teacher' ? '提交支持转介' : '提交求助请求' }}</h2>
        <p v-if="audience === 'teacher' && initialReferral">请选择学生，核对并编辑观察记录，再提交请求</p>
        <div v-if="audience === 'teacher'" class="school-support__field">
          <label for="support-student">选择学生</label>
          <AppSelect id="support-student" v-model="studentKey" :options="studentOptions" :disabled="locked || !studentOptions.length"
            :placeholder="loading || studentOptions.length ? '请选择授权班级的学生' : '没有可选择的学生'" />
        </div>
        <div class="school-support__field">
          <label for="support-category">支持事项</label>
          <AppSelect id="support-category" v-model="category" :options="categoryOptions" :disabled="locked" />
        </div>
        <label>{{ audience === 'teacher' ? '观察记录' : '你希望学校提供什么支持？' }}
          <textarea v-model="content" maxlength="4000" rows="4" :disabled="locked" required></textarea>
        </label>
        <AppButton type="submit" :disabled="locked || !content.trim() || (audience === 'teacher' && !student)">提交支持请求</AppButton>
      </form>
    </AppCard>
    <AppCard>
      <section class="school-support__panel">
        <h2>{{ planningOnly ? '我已受理的请求' : '支持请求' }}</h2>
        <p v-if="audience === 'specialist' && preparePlan && !planningOnly">选择一条授权请求。受理后可根据该请求准备可编辑的草案</p>
        <p v-if="loading" role="status">正在读取支持请求。</p>
        <ul v-else-if="cases?.items.length">
          <li v-for="item in cases.items" :key="item.caseRef">
            <AppButton variant="quiet" :disabled="locked" :aria-pressed="selected === item.caseRef" @click="selectCase(item.caseRef)">
              {{ supportCategories[item.category] }} · {{ supportCaseStates[item.status] }} · {{ item.caseRef.slice(-8) }}
            </AppButton>
          </li>
        </ul>
        <p v-else-if="cases">{{ planningOnly && !offset ? '当前没有已受理且待制定计划的请求' : '当前页没有支持请求' }}</p>
        <div v-if="offset || (cases?.total ?? 0) > supportPageSize" class="school-support__actions">
          <AppButton variant="secondary" :disabled="locked || !offset" @click="offset -= supportPageSize; selectCase(''); load()">上一页支持请求</AppButton>
          <AppButton variant="secondary" :disabled="locked || offset + supportPageSize >= (cases?.total ?? 0)" @click="offset += supportPageSize; selectCase(''); load()">下一页支持请求</AppButton>
        </div>
      </section>
    </AppCard>
    <p v-if="detailLoading" role="status">正在读取请求详情。</p>
    <AppStatusCallout v-else-if="detailError" tone="attention" title="无法读取请求详情" :body="detailError">
      <AppButton variant="secondary" :disabled="locked" @click="openCase(selected)">重新加载详情</AppButton>
    </AppStatusCallout>
    <AppCard v-else-if="current">
      <section class="school-support__panel">
        <h2>{{ supportCategories[current.category] }} · {{ supportCaseStates[current.status] }}</h2>
        <p v-if="current.content" class="school-support__body">{{ current.content }}</p>
        <template v-if="audience === 'specialist'">
          <p v-if="current.plan" class="school-support__body">{{ current.plan }}</p>
          <AppButton v-if="current.status === 'SUBMITTED'" :disabled="locked" @click="transition('TRIAGED')">受理请求</AppButton>
          <template v-if="current.status === 'TRIAGED'">
            <div v-if="preparePlan" class="school-support__panel">
              <h3>准备支持计划草案</h3>
              <div class="school-support__field">
                <AppButton variant="secondary" :disabled="locked || evidenceLoading || Boolean(plan.trim())" @click="loadPlanEvidence">核对已发布测评反馈</AppButton>
                <p v-if="evidenceLoading" role="status">正在核对授权的测评反馈</p>
                <AppStatusCallout v-else-if="evidenceError" tone="attention" title="未能读取测评反馈" :body="evidenceError" />
                <p v-else-if="planEvidence === null" role="status">在这条请求和你当前的测评指派范围内，没有可引用的已发布反馈</p>
                <section v-else-if="planEvidence && feedbackText" class="school-support__panel" aria-label="已发布测评反馈">
                  <h4>{{ planEvidence.title }}</h4>
                  <p>第 {{ planEvidence.revision }} 版 · {{ dateFormatter.format(new Date(planEvidence.publishedAt)) }}</p>
                  <p class="school-support__body">{{ feedbackText.body }}</p>
                  <template v-if="feedbackText.nextSteps">
                    <h4>老师建议的下一步</h4>
                    <p class="school-support__body">{{ feedbackText.nextSteps }}</p>
                  </template>
                  <label class="school-support__actions"><input v-model="includeEvidence" type="checkbox" :disabled="locked || Boolean(plan.trim())"> 将这份反馈列为计划依据</label>
                </section>
              </div>
              <div class="school-support__field">
                <label for="support-plan-topic">供沟通参考的科普资料</label>
                <AppSelect id="support-plan-topic" v-model="planTopic" :options="planResources" placeholder="选择资料" :disabled="locked || Boolean(plan.trim())" />
              </div>
              <a v-if="planArticle" :href="planArticle.url" target="_blank" rel="noopener noreferrer">{{ planArticle.source }}</a>
              <AppButton variant="secondary" :disabled="locked || evidenceLoading || Boolean(plan.trim())" @click="draftSupportPlan">生成可编辑草案</AppButton>
            </div>
            <label>专业支持计划<textarea v-model="plan" maxlength="4000" :disabled="locked"></textarea></label>
            <AppButton :disabled="locked || !plan.trim()" @click="transition('PLANNED')">保存计划</AppButton>
          </template>
          <form v-if="mayAssign" class="school-support__panel" @submit.prevent="assign">
            <h3>分派跟进任务</h3>
            <AppStatusCallout v-if="assigneeError" tone="attention" title="无法读取授权教师" :body="assigneeError">
              <AppButton variant="secondary" :disabled="locked" @click="openCase(selected)">重新加载</AppButton>
            </AppStatusCallout>
            <div class="school-support__field">
              <label for="support-recipient">接收人</label>
              <AppSelect id="support-recipient" v-model="recipient" :options="recipientOptions" placeholder="请选择接收人" :disabled="locked" />
            </div>
            <label>任务说明<textarea v-model="instructions" maxlength="4000" :disabled="locked" required></textarea></label>
            <label>截止时间<input v-model="due" type="datetime-local" :disabled="locked" required></label>
            <AppButton type="submit" :disabled="locked || !recipientValid || !instructions.trim() || !due">分派任务</AppButton>
          </form>
          <section v-for="action in current.actions" :key="action.actionRef" class="school-support__panel">
            <h3>{{ supportActionStates[action.status] }} · {{ action.actionRef.slice(-8) }}</h3>
            <p v-if="action.instructions" class="school-support__body">{{ action.instructions }}</p>
            <p v-if="action.feedback" class="school-support__body">{{ action.feedback }}</p>
            <div v-if="isActionOpen(action) || action.status === 'SUBMITTED'" class="school-support__actions">
              <template v-if="action.status === 'SUBMITTED'">
                <AppButton :disabled="locked" @click="submit((key) => schoolSupport.feedback(action, 'ACCEPTED', key))">确认反馈</AppButton>
                <AppButton variant="secondary" :disabled="locked" @click="submit((key) => schoolSupport.feedback(action, 'RETURNED', key))">退回补充</AppButton>
              </template>
              <AppButton variant="secondary" :disabled="locked" @click="submit((key) => schoolSupport.feedback(action, 'CANCELLED', key))">取消任务</AppButton>
            </div>
          </section>
          <AppButton v-if="current.status === 'FOLLOWING'" variant="secondary" :disabled="locked" @click="transition('REVIEW')">进入复核</AppButton>
          <template v-if="current.status === 'REVIEW'">
            <p v-if="!canClose">请先确认或取消尚未结束的跟进任务。</p>
            <label v-else class="school-support__actions"><input v-model="closeConfirmed" type="checkbox" :disabled="locked"> 确认结束此支持请求</label>
            <AppButton variant="secondary" :disabled="locked || !canClose || !closeConfirmed" @click="transition('CLOSED')">结案</AppButton>
          </template>
        </template>
      </section>
    </AppCard>
    <AppCard v-if="audience !== 'specialist'">
      <section class="school-support__panel">
        <h2>交给我的跟进任务</h2>
        <p v-if="loading" role="status">正在读取跟进任务。</p>
        <p v-else-if="actions && !actions.items.length">当前页没有跟进任务。</p>
        <section v-for="action in actions?.items ?? []" :key="action.actionRef" class="school-support__panel">
          <h3>{{ supportActionStates[action.status] }} · {{ action.actionRef.slice(-8) }}</h3>
          <p v-if="action.dueAt">截止 {{ dateFormatter.format(new Date(action.dueAt)) }}</p>
          <p v-if="action.instructions" class="school-support__body">{{ action.instructions }}</p>
          <p v-if="action.feedback" class="school-support__body">{{ action.feedback }}</p>
          <form v-if="isActionOpen(action)" class="school-support__panel" @submit.prevent="submitFeedback(action)">
            <label>执行反馈<textarea v-model="feedback[action.actionRef]" maxlength="4000" :disabled="locked" required></textarea></label>
            <AppButton type="submit" :disabled="locked || !feedback[action.actionRef]?.trim()">提交跟进反馈</AppButton>
          </form>
        </section>
        <div v-if="actionOffset || (actions?.total ?? 0) > supportPageSize" class="school-support__actions">
          <AppButton variant="secondary" :disabled="locked || !actionOffset" @click="actionOffset -= supportPageSize; load()">上一页跟进任务</AppButton>
          <AppButton variant="secondary" :disabled="locked || actionOffset + supportPageSize >= (actions?.total ?? 0)" @click="actionOffset += supportPageSize; load()">下一页跟进任务</AppButton>
        </div>
      </section>
    </AppCard>
  </section>
</template>

<style scoped>
.school-support, .school-support__panel { display: grid; gap: 16px; }
.school-support { padding-block: 24px 48px; }
.school-support h1, .school-support h2, .school-support h3, .school-support p { margin: 0; }
.school-support header p { margin-top: 6px; color: var(--color-text-secondary); }
.school-support__panel { padding: 18px 20px; }
.school-support__panel .school-support__panel { padding: 16px 0 0; border-top: 1px solid var(--color-border); }
.school-support h1, .school-support h2, .school-support h3 { font-family: var(--font-display); font-weight: 650; }
.school-support h1 { font-size: 26px; }
.school-support h2 { font-size: 18px; }
.school-support h3 { font-size: 15px; }
.school-support__panel label, .school-support__field { display: grid; gap: 7px; }
.school-support__field { width: min(100%, 42rem); }
.school-support__panel label { color: var(--color-text-primary); font-size: 13px; font-weight: 700; }
.school-support__panel textarea, .school-support input:not([type="checkbox"]) {
  width: min(100%, 42rem);
  padding: 10px 13px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  background: var(--color-surface);
  font-family: inherit;
  font-size: 14px;
  font-weight: 400;
}
.school-support__panel textarea:focus, .school-support input:not([type="checkbox"]):focus {
  border-color: var(--color-primary);
  outline: 2px solid color-mix(in srgb, var(--color-primary) 26%, transparent);
  outline-offset: 1px;
}
.school-support__panel > button { justify-self: start; }
.school-support__panel ul { display: grid; gap: 6px; padding-inline-start: 20px; }
.school-support__actions, .school-support__panel label.school-support__actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.school-support__body { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
