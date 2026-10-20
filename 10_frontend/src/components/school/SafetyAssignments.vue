<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Clock3, Search, ShieldCheck, X } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { useSessionStore } from '@/stores/session'
import {
  newConversationSafetyIdempotencyKey,
  schoolConversationSafety,
  type SafetyClass,
  type SafetySpecialist,
  type UnassignedSafetyCase,
} from '@/services/school-conversation-safety'

/* global HTMLSelectElement */

type LoadState = 'loading' | 'ready' | 'error'
type Operation = { row: UnassignedSafetyCase; classRef: string; specialistUserId: string; key: string }

const session = useSessionStore()
const scopeKey = computed(() => [
  session.user?.userId ?? '', session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '', session.user?.activeContext?.role ?? '',
].join('|'))
const authorized = computed(() => session.role === 'school_admin' && session.user?.activeContext?.role === 'school_admin')
const emit = defineEmits<{
  'summary-change': [summary: { state: LoadState; total: number | null }]
}>()

const cases = ref<UnassignedSafetyCase[]>([])
const specialists = ref<SafetySpecialist[]>([])
const classes = ref<SafetyClass[]>([])
const state = ref<LoadState>('loading')
const errorMessage = ref('')
const notice = ref('')
const searchQuery = ref('')
const selectedClasses = ref<Record<string, string>>({})
const selectedCaseRef = ref('')
const specialistUserId = ref('')
const busy = ref(false)
const offset = ref(0)
const total = ref(0)
const assignTarget = ref<UnassignedSafetyCase | null>(null)
const failedOperation = ref<Operation | null>(null)
const operationError = ref('')
const assignmentBlocked = ref(false)
let generation = 0
let mounted = true

const pageSize = 20
const classLabel = (item: SafetyClass) => item.display_name?.trim() || `班级 · ${item.class_ref.slice(-6)}`
const specialistLabel = (person: SafetySpecialist) => person.display_name?.trim() || `心理老师 · ${person.user_id.slice(-6)}`
const caseClassValue = (row: UnassignedSafetyCase) => {
  const chosen = selectedClasses.value[row.case_ref]
  if (chosen && classes.value.some((item) => item.class_ref === chosen)) return chosen
  if (row.class_ref && classes.value.some((item) => item.class_ref === row.class_ref)) return row.class_ref
  return ''
}
const currentClassLabel = (row: UnassignedSafetyCase) => {
  const ref = caseClassValue(row)
  return classes.value.find((item) => item.class_ref === ref)
    ? classLabel(classes.value.find((item) => item.class_ref === ref)!)
    : row.class_ref ? '原关联班级当前不可用' : '尚未关联班级'
}
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pageNumber = computed(() => Math.floor(offset.value / pageSize) + 1)
const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(() => offset.value + cases.value.length < total.value)
const visibleCases = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return cases.value
  return cases.value.filter((row) => `${row.case_ref} ${currentClassLabel(row)} 待分配`.toLocaleLowerCase().includes(query))
})
const selectedCase = computed(() => visibleCases.value.find((row) => row.case_ref === selectedCaseRef.value)
  ?? visibleCases.value[0]
  ?? null)
const canConfirmAssignment = computed(() => Boolean(
  authorized.value && assignTarget.value && specialistUserId.value && caseClassValue(assignTarget.value)
  && state.value === 'ready' && !busy.value && !failedOperation.value && !assignmentBlocked.value,
))

watch(visibleCases, (rows) => {
  if (!rows.some((row) => row.case_ref === selectedCaseRef.value)) selectedCaseRef.value = rows[0]?.case_ref ?? ''
}, { immediate: true })

function emitSummary(nextState: LoadState, nextTotal: number | null) {
  emit('summary-change', { state: nextState, total: nextTotal })
}

function clearScopeData() {
  ++generation
  busy.value = false
  cases.value = []
  specialists.value = []
  classes.value = []
  selectedClasses.value = {}
  selectedCaseRef.value = ''
  specialistUserId.value = ''
  offset.value = 0
  total.value = 0
  assignTarget.value = null
  failedOperation.value = null
  operationError.value = ''
  assignmentBlocked.value = false
  notice.value = ''
}

const safeOperationError = (error: unknown) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  return {
    retryable: Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable),
    conflict: code === 'WORKFLOW_CONFLICT' || code === 'IDEMPOTENCY_CONFLICT',
    accessLost: code === 'FORBIDDEN' || code === 'RESOURCE_NOT_FOUND'
      || code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED',
  }
}

async function load(nextOffset = offset.value, preserveNotice = false, fallbackPrevious = true) {
  const current = ++generation
  errorMessage.value = ''
  operationError.value = ''
  if (!preserveNotice) notice.value = ''
  if (!authorized.value) {
    clearScopeData()
    state.value = 'error'
    errorMessage.value = '当前账号没有学校安全事项管理权限。'
    emitSummary('error', null)
    return
  }
  state.value = 'loading'
  emitSummary('loading', null)
  cases.value = []
  specialists.value = []
  classes.value = []
  try {
    const [page, specialistRows, classRows] = await Promise.all([
      schoolConversationSafety.listUnassigned(nextOffset, pageSize),
      schoolConversationSafety.listSpecialists(),
      schoolConversationSafety.listActiveClasses(),
    ])
    if (!mounted || current !== generation) return
    if (!page.items.length && nextOffset > 0 && nextOffset >= page.total && fallbackPrevious) {
      await load(Math.max(0, nextOffset - pageSize), preserveNotice, false)
      return
    }
    cases.value = page.items
    specialists.value = specialistRows
    classes.value = classRows
    offset.value = nextOffset
    total.value = page.total
    selectedClasses.value = Object.fromEntries(page.items.flatMap((row) =>
      row.class_ref && classRows.some((item) => item.class_ref === row.class_ref) ? [[row.case_ref, row.class_ref]] : [],
    ))
    state.value = 'ready'
    emitSummary('ready', page.total)
  } catch (error) {
    if (!mounted || current !== generation) return
    clearScopeData()
    state.value = 'error'
    const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
    errorMessage.value = code === 'FORBIDDEN' ? '当前账号无权查看安全事项分配队列。'
      : code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED' ? '登录状态已失效，请重新登录。'
        : '安全事项或授权对象暂时无法读取。'
    emitSummary('error', null)
  }
}

function openAssignment(row: UnassignedSafetyCase) {
  if (!authorized.value || state.value !== 'ready' || busy.value || !classes.value.length || !specialists.value.length) return
  operationError.value = ''
  assignmentBlocked.value = false
  if (row.class_ref && classes.value.some((item) => item.class_ref === row.class_ref)) {
    selectedClasses.value = { ...selectedClasses.value, [row.case_ref]: row.class_ref }
  }
  assignTarget.value = row
}

function setAssignmentOpen(open: boolean) {
  if ((busy.value || failedOperation.value) && !open) return
  if (open) return
  assignTarget.value = null
  operationError.value = ''
  assignmentBlocked.value = false
}

function setAssignmentClass(event: Event) {
  const target = event.target
  if (!(target instanceof HTMLSelectElement) || !assignTarget.value) return
  selectedClasses.value = { ...selectedClasses.value, [assignTarget.value.case_ref]: target.value }
  failedOperation.value = null
  operationError.value = ''
}

async function execute(operation: Operation) {
  if (!authorized.value || busy.value) return
  const scope = scopeKey.value
  const current = generation
  busy.value = true
  operationError.value = ''
  notice.value = ''
  try {
    await schoolConversationSafety.assign(operation.row, operation.classRef, operation.specialistUserId, operation.key)
    if (!mounted || scope !== scopeKey.value || current !== generation) return
    failedOperation.value = null
    assignTarget.value = null
    const pageOffset = offset.value
    await load(pageOffset, true)
    if (mounted && scope === scopeKey.value) notice.value = '分配已由服务端确认。'
  } catch (error) {
    if (!mounted || scope !== scopeKey.value || current !== generation) return
    const classified = safeOperationError(error)
    if (classified.conflict) {
      failedOperation.value = null
      assignmentBlocked.value = true
      await load(offset.value, true)
      operationError.value = '事项状态已变化；请核对最新队列后再继续。'
    } else if (classified.accessLost) {
      clearScopeData()
      state.value = 'error'
      errorMessage.value = '当前学校权限已变化，页面数据已清除。'
      emitSummary('error', null)
    } else {
      failedOperation.value = classified.retryable ? operation : null
      operationError.value = classified.retryable
        ? '服务端尚未确认分配结果；可使用相同请求安全重试。'
        : '分配未完成，请核对当前权限和事项状态后重试。'
    }
  } finally {
    if (scope === scopeKey.value) busy.value = false
  }
}

function confirmAssignment() {
  const row = assignTarget.value
  const classRef = row ? caseClassValue(row) : ''
  if (!row || !canConfirmAssignment.value || !classRef) return
  try {
    void execute({ row, classRef, specialistUserId: specialistUserId.value, key: newConversationSafetyIdempotencyKey() })
  } catch {
    operationError.value = '当前浏览器无法安全建立请求标识，请更新浏览器后重试。'
  }
}

function retryAssignment() {
  if (failedOperation.value && !busy.value) void execute(failedOperation.value)
}

function previousPage() {
  if (!hasPrevious.value || busy.value || state.value === 'loading') return
  void load(Math.max(0, offset.value - pageSize))
}
function nextPage() {
  if (!hasNext.value || busy.value || state.value === 'loading') return
  void load(offset.value + pageSize)
}
function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未知' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}
function refresh() {
  if (busy.value || assignTarget.value) return Promise.resolve()
  return load(offset.value)
}

watch(specialistUserId, () => { failedOperation.value = null; operationError.value = '' })
watch(scopeKey, () => {
  clearScopeData()
  state.value = 'loading'
  if (authorized.value) void load()
  else {
    state.value = 'error'
    errorMessage.value = '当前账号没有学校安全事项管理权限。'
    emitSummary('error', null)
  }
})
onMounted(() => { void load() })
onBeforeUnmount(() => { mounted = false; clearScopeData() })

defineExpose({ refresh })
</script>

<template>
  <section class="safety-assignments" aria-label="事项分配" :aria-busy="state === 'loading'">
    <label class="safety-assignments__search">
      <span class="sr-only">搜索待分配事项</span>
      <Search :size="16" aria-hidden="true" />
      <input v-model="searchQuery" type="search" autocomplete="off" placeholder="搜索事项编号或班级">
      <button v-if="searchQuery" type="button" aria-label="清空搜索" @click="searchQuery = ''"><X :size="15" aria-hidden="true" /></button>
    </label>
    <p class="safety-assignments__scope">仅筛选当前服务端页；本校待分配队列由服务端分页。已分配事项由授权专业人员查看。</p>

    <AppStatusCallout v-if="errorMessage" tone="critical" title="分配队列不可用" :body="errorMessage" role="alert" />
    <AppStatusCallout v-if="notice" tone="info" title="服务端已确认" :body="notice" role="status" />

    <div class="safety-assignments__layout">
      <AppCard class="safety-assignments__list-panel">
        <header class="safety-assignments__list-heading">
          <div><h2><ShieldCheck :size="17" aria-hidden="true" />待分配事项</h2><span>{{ state === 'ready' ? `共 ${total} 项` : '—' }}</span></div>
          <span v-if="state === 'ready'">第 {{ pageNumber }} / {{ pageCount }} 页</span>
        </header>
        <div v-if="state === 'loading'" class="safety-assignments__state" role="status" aria-live="polite" aria-busy="true">正在读取待分配事项和可选对象…</div>
        <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="无法读取事项" :body="errorMessage || '请刷新后重试。'" role="alert" />
        <div v-else-if="!visibleCases.length" class="safety-assignments__state" role="status">
          <strong>{{ cases.length ? '本页没有匹配事项' : '当前没有可分配事项' }}</strong>
          <span>{{ cases.length ? '调整搜索内容或切换服务端页。' : '服务端当前待分配队列为空。' }}</span>
        </div>
        <ul v-else class="safety-assignments__list" aria-label="当前页待分配安全事项">
          <li v-for="row in visibleCases" :key="row.case_ref">
            <button type="button" class="safety-assignments__item" :class="{ 'safety-assignments__item--selected': selectedCase?.case_ref === row.case_ref }" :aria-pressed="selectedCase?.case_ref === row.case_ref" @click="selectedCaseRef = row.case_ref">
              <span class="safety-assignments__item-main"><strong>事项 · {{ row.case_ref.slice(-6) }}</strong><span class="safety-assignments__status">待分配</span></span>
              <span class="safety-assignments__item-meta">{{ currentClassLabel(row) }} · 更新于 {{ formatTime(row.updated_at) }}</span>
            </button>
          </li>
        </ul>
        <nav v-if="state === 'ready'" class="safety-assignments__paging" aria-label="待分配事项分页">
          <span>{{ visibleCases.length }} 条显示</span>
          <div><button type="button" :disabled="!hasPrevious || busy || state === 'loading'" @click="previousPage"><ChevronLeft :size="15" aria-hidden="true" />上一页</button><button type="button" :disabled="!hasNext || busy || state === 'loading'" @click="nextPage">下一页<ChevronRight :size="15" aria-hidden="true" /></button></div>
        </nav>
      </AppCard>

      <AppCard class="safety-assignments__detail" aria-label="待分配事项详情">
        <template v-if="selectedCase">
          <header><span>事项详情</span><h3>事项 · {{ selectedCase.case_ref.slice(-6) }}</h3><code>{{ selectedCase.case_ref }}</code></header>
          <dl>
            <div><dt>流程状态</dt><dd><span class="safety-assignments__status">待分配</span></dd></div>
            <div><dt>所属班级</dt><dd>{{ currentClassLabel(selectedCase) }}</dd></div>
            <div><dt>创建时间</dt><dd>{{ formatTime(selectedCase.created_at) }}</dd></div>
            <div><dt>更新时间</dt><dd>{{ formatTime(selectedCase.updated_at) }}</dd></div>
            <div><dt>当前分配</dt><dd>尚未指派</dd></div>
          </dl>
          <p class="safety-assignments__privacy">此处仅显示事项编号和流程元数据，不展示学生身份、触发原因或对话内容。</p>
          <AppStatusCallout v-if="state === 'ready' && (!classes.length || !specialists.length)" tone="attention" title="暂不能指派" :body="!classes.length ? '当前没有可用班级。' : '当前没有可分配的授权心理老师。'" role="status" />
          <AppButton variant="primary" :disabled="!authorized || state !== 'ready' || busy || !classes.length || !specialists.length" @click="openAssignment(selectedCase)">指派专业人员</AppButton>
        </template>
        <div v-else class="safety-assignments__detail-empty"><strong>{{ state === 'loading' ? '正在同步队列' : '选择一项待分配事项' }}</strong><span>分配信息会在服务端确认后刷新。</span></div>
      </AppCard>
    </div>

    <AppDialog :open="Boolean(assignTarget)" title="指派专业人员" description="选择班级和本校授权心理老师，提交后由服务端确认。" @update:open="setAssignmentOpen">
      <div class="safety-assignments__dialog">
        <p class="safety-assignments__dialog-ref">事项 · {{ assignTarget?.case_ref.slice(-6) }}</p>
        <label for="safety-assignment-class">班级</label>
        <select id="safety-assignment-class" :value="assignTarget ? caseClassValue(assignTarget) : ''" :disabled="busy || Boolean(failedOperation) || assignmentBlocked" @change="setAssignmentClass">
          <option value="">选择班级</option>
          <option v-for="item in classes" :key="item.class_ref" :value="item.class_ref">{{ classLabel(item) }}</option>
        </select>
        <label for="safety-assignment-specialist">专业人员</label>
        <select id="safety-assignment-specialist" v-model="specialistUserId" :disabled="busy || Boolean(failedOperation) || assignmentBlocked || !specialists.length">
          <option value="">选择授权心理老师</option>
          <option v-for="person in specialists" :key="person.user_id" :value="person.user_id">{{ specialistLabel(person) }}</option>
        </select>
        <AppStatusCallout v-if="operationError" tone="critical" title="分配未完成" :body="operationError" role="alert" />
        <AppButton v-if="failedOperation" variant="secondary" :disabled="busy" :loading="busy" @click="retryAssignment">使用相同请求安全重试</AppButton>
        <div class="safety-assignments__dialog-actions">
          <AppButton variant="secondary" :disabled="busy || Boolean(failedOperation)" @click="setAssignmentOpen(false)">取消</AppButton>
          <AppButton variant="primary" :disabled="!canConfirmAssignment" :loading="busy" @click="confirmAssignment">确认指派</AppButton>
        </div>
      </div>
    </AppDialog>
  </section>
</template>

<style scoped>
.safety-assignments { display: grid; gap: 8px; min-width: 0; }
.safety-assignments__search { display: flex; min-width: 0; min-height: 40px; align-items: center; gap: 8px; padding: 0 11px; border: 1px solid var(--color-border); border-radius: 9px; color: #82939b; background: #fff; }
.safety-assignments__search:focus-within { border-color: #78c4d4; box-shadow: 0 0 0 3px rgb(0 177 226 / 9%); }
.safety-assignments__search input { width: 100%; min-width: 0; height: 36px; padding: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 13px; }
.safety-assignments__search input::placeholder { color: #94a1a9; }
.safety-assignments__search button { display: grid; width: 25px; height: 25px; flex: 0 0 25px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: #7d8e98; background: transparent; cursor: pointer; }
.safety-assignments__scope { margin: 0 2px 3px; color: var(--color-text-muted); font-size: 11px; line-height: 1.5; }
.safety-assignments__layout { display: grid; grid-template-columns: minmax(0,1.05fr) minmax(300px,.95fr); align-items: stretch; gap: 12px; min-width: 0; }
.safety-assignments__list-panel { display: flex; min-width: 0; flex-direction: column; overflow: hidden; padding: 0; }
.safety-assignments__list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 58px; padding: 12px 16px; border-bottom: 1px solid #edf1f3; color: #83939b; font-size: 11px; }
.safety-assignments__list-heading > div { display: flex; align-items: center; gap: 10px; }
.safety-assignments__list-heading h2 { display: inline-flex; align-items: center; gap: 7px; margin: 0; color: #2d4857; font-size: 15px; font-weight: 700; }
.safety-assignments__list-heading h2 svg { color: var(--color-primary-active); }
.safety-assignments__list { display: grid; gap: 7px; margin: 0; padding: 12px; list-style: none; }
.safety-assignments__item { display: grid; gap: 6px; width: 100%; min-width: 0; padding: 12px; border: 1px solid #e7edf0; border-radius: 9px; color: inherit; background: #fff; text-align: left; cursor: pointer; transition: border-color 150ms ease, background-color 150ms ease, box-shadow 150ms ease; }
.safety-assignments__item:hover { border-color: #b9dce4; background: #fbfeff; }
.safety-assignments__item:focus-visible { outline: 2px solid #4cb5cc; outline-offset: 2px; }
.safety-assignments__item--selected { border-color: #8acbda; background: #f1fafc; box-shadow: inset 3px 0 #3aaec6; }
.safety-assignments__item-main { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; }
.safety-assignments__item-main > strong { overflow: hidden; color: #3c5664; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.safety-assignments__item-meta { overflow: hidden; color: #82939a; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.safety-assignments__status { display: inline-flex; align-items: center; padding: 4px 8px; border-radius: 999px; color: #93671e; background: #f8f2e6; font-size: 10px; font-weight: 700; white-space: nowrap; }
.safety-assignments__state { display: grid; min-height: 240px; align-content: center; justify-items: center; gap: 7px; padding: 22px; color: #728690; text-align: center; }
.safety-assignments__state strong { color: #435e6c; font-size: 14px; }
.safety-assignments__state span { font-size: 12px; line-height: 1.5; }
.safety-assignments__paging { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: auto; padding: 11px 14px; border-top: 1px solid #edf1f3; color: #81919a; font-size: 11px; }
.safety-assignments__paging > div { display: flex; gap: 6px; }
.safety-assignments__paging button { display: inline-flex; min-height: 31px; align-items: center; gap: 4px; padding: 0 8px; border: 1px solid var(--color-border); border-radius: 7px; color: #536b77; background: #fff; font: inherit; font-size: 11px; cursor: pointer; }
.safety-assignments__paging button:disabled { opacity: .48; cursor: default; }
.safety-assignments__detail { display: flex; min-width: 0; flex-direction: column; padding: 18px; }
.safety-assignments__detail > header { display: grid; gap: 6px; padding-bottom: 14px; border-bottom: 1px solid #edf1f3; }
.safety-assignments__detail > header > span { color: #75909b; font-size: 11px; }
.safety-assignments__detail h3 { overflow-wrap: anywhere; margin: 0; color: #2e4a58; font-size: 17px; }
.safety-assignments__detail code { color: #91a0a7; font-family: var(--font-mono); font-size: 10px; }
.safety-assignments__detail dl { display: grid; margin: 8px 0 0; }
.safety-assignments__detail dl > div { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; padding: 11px 0; border-bottom: 1px solid #f0f3f5; }
.safety-assignments__detail dt { color: #83939b; font-size: 11px; }
.safety-assignments__detail dd { margin: 0; color: #415c69; font-size: 12px; font-weight: 620; text-align: right; overflow-wrap: anywhere; }
.safety-assignments__privacy { margin: 14px 0; padding-top: 12px; border-top: 1px solid #edf1f3; color: #83939a; font-size: 11px; line-height: 1.55; }
.safety-assignments__detail > :deep(.app-button) { align-self: flex-start; }
.safety-assignments__detail-empty { display: grid; min-height: 230px; align-content: center; justify-items: center; gap: 7px; color: #81919a; text-align: center; }
.safety-assignments__detail-empty strong { color: #435e6c; font-size: 14px; }
.safety-assignments__detail-empty span { font-size: 12px; line-height: 1.5; }
.safety-assignments__dialog { display: grid; gap: 9px; }
.safety-assignments__dialog-ref { margin: 0 0 3px; color: #526b77; font-family: var(--font-mono); font-size: 12px; }
.safety-assignments__dialog label { margin-top: 3px; color: #536c78; font-size: 12px; font-weight: 650; }
.safety-assignments__dialog select { width: 100%; min-height: 40px; padding: 8px 10px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 13px; }
.safety-assignments__dialog select:focus-visible { outline: 2px solid #38a4bf; outline-offset: 1px; }
.safety-assignments__dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 9px; padding-top: 13px; border-top: 1px solid #edf1f3; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 900px) { .safety-assignments__layout { grid-template-columns: minmax(0,1fr); }.safety-assignments__detail { min-height: 260px; } }
@media (max-width: 660px) { .safety-assignments__list-heading { padding-inline: 12px; }.safety-assignments__list { padding: 10px; }.safety-assignments__detail { padding: 15px; } }
@media (prefers-reduced-motion: reduce) { .safety-assignments__item { transition: none; } }
</style>
