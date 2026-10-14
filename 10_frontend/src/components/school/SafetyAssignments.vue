<script setup lang="ts">
/* global Event, HTMLSelectElement */

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw, ShieldCheck } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { useSessionStore } from '@/stores/session'
import {
  newConversationSafetyIdempotencyKey,
  schoolConversationSafety,
  type SafetyClass,
  type SafetySpecialist,
  type UnassignedSafetyCase,
} from '@/services/school-conversation-safety'

type LoadState = 'loading' | 'ready' | 'error'
type Operation = { row: UnassignedSafetyCase; classRef: string; specialistUserId: string; key: string }

const session = useSessionStore()
const scopeKey = computed(() => [
  session.user?.userId ?? '', session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '', session.user?.activeContext?.role ?? '',
].join('|'))
const authorized = computed(() => session.role === 'school_admin' && session.user?.activeContext?.role === 'school_admin')
const cases = ref<UnassignedSafetyCase[]>([])
const specialists = ref<SafetySpecialist[]>([])
const classes = ref<SafetyClass[]>([])
const state = ref<LoadState>('loading')
const errorMessage = ref('')
const notice = ref('')
const selectedClasses = ref<Record<string, string>>({})
const specialistUserId = ref('')
const busy = ref(false)
const offset = ref(0)
const total = ref(0)
const failedOperation = ref<Operation | null>(null)
const operationError = ref('')
let generation = 0
let mounted = true

const classLabel = (item: SafetyClass) => item.display_name?.trim() || `班级 ${classes.value.findIndex((row) => row.class_ref === item.class_ref) + 1}`
const caseClassValue = (row: UnassignedSafetyCase) => {
  const chosen = selectedClasses.value[row.case_ref]
  if (chosen && classes.value.some((item) => item.class_ref === chosen)) return chosen
  if (row.class_ref && classes.value.some((item) => item.class_ref === row.class_ref)) return row.class_ref
  return ''
}
const visibleSpecialists = computed(() => specialists.value)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / 20)))
const pageNumber = computed(() => Math.floor(offset.value / 20) + 1)
const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(() => offset.value + cases.value.length < total.value)
const canAssign = (row: UnassignedSafetyCase) => Boolean(
  authorized.value && !busy.value && !failedOperation.value && state.value === 'ready'
  && specialistUserId.value && caseClassValue(row),
)
const specialistLabel = (person: SafetySpecialist, index: number) =>
  person.display_name?.trim() || `心理老师 · ${person.user_id.slice(-6) || `编号 ${index + 1}`}`

function setClass(caseRef: string, event: Event) {
  const target = event.target
  if (!(target instanceof HTMLSelectElement)) return
  selectedClasses.value = { ...selectedClasses.value, [caseRef]: target.value }
}

function clearScopeData() {
  ++generation
  busy.value = false
  cases.value = []
  specialists.value = []
  classes.value = []
  selectedClasses.value = {}
  specialistUserId.value = ''
  offset.value = 0
  total.value = 0
  failedOperation.value = null
  operationError.value = ''
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
  if (!preserveNotice) notice.value = ''
  if (!authorized.value) {
    clearScopeData()
    state.value = 'error'
    errorMessage.value = '当前账号没有学校安全事项管理权限。'
    return
  }
  state.value = 'loading'
  cases.value = []
  specialists.value = []
  classes.value = []
  try {
    const [page, specialistRows, classRows] = await Promise.all([
      schoolConversationSafety.listUnassigned(nextOffset, 20),
      schoolConversationSafety.listSpecialists(),
      schoolConversationSafety.listActiveClasses(),
    ])
    if (!mounted || current !== generation) return
    if (!page.items.length && nextOffset > 0 && nextOffset >= page.total && fallbackPrevious) {
      await load(Math.max(0, nextOffset - 20), preserveNotice, false)
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
  } catch (error) {
    if (!mounted || current !== generation) return
    clearScopeData()
    state.value = 'error'
    const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
    errorMessage.value = code === 'FORBIDDEN' ? '当前账号无权查看安全事项分配队列。'
      : code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED' ? '登录状态已失效，请重新登录。'
        : '安全事项或分配对象暂时无法读取；未使用本地示例数据替代。'
  }
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
    await load(offset.value, true)
    if (mounted && scope === scopeKey.value) notice.value = '分配已由服务端确认。'
  } catch (error) {
    if (!mounted || scope !== scopeKey.value || current !== generation) return
    const classified = safeOperationError(error)
    if (classified.conflict) {
      failedOperation.value = null
      operationError.value = '事项状态已变化，请刷新队列后核对。'
      await load(offset.value)
    } else if (classified.accessLost) {
      clearScopeData()
      state.value = 'error'
      operationError.value = '当前学校权限已变化，页面数据已清除。'
    } else {
      failedOperation.value = classified.retryable ? operation : null
      operationError.value = classified.retryable
        ? '服务端尚未确认分配结果；可使用同一请求安全重试。'
        : '分配未完成，请刷新队列并核对当前权限。'
    }
  } finally {
    if (scope === scopeKey.value) busy.value = false
  }
}

function assign(row: UnassignedSafetyCase) {
  const classRef = caseClassValue(row)
  if (!canAssign(row) || !classRef) return
  try {
    void execute({ row, classRef, specialistUserId: specialistUserId.value, key: newConversationSafetyIdempotencyKey() })
  } catch {
    operationError.value = '当前浏览器无法安全建立请求标识，请更新浏览器后重试。'
  }
}

function retry() {
  if (failedOperation.value && !busy.value) void execute(failedOperation.value)
}

watch(scopeKey, () => {
  clearScopeData()
  state.value = 'loading'
  if (authorized.value) void load()
  else {
    state.value = 'error'
    errorMessage.value = '当前账号没有学校安全事项管理权限。'
  }
})
watch(specialistUserId, () => { failedOperation.value = null; operationError.value = '' })
onMounted(() => { void load() })
onBeforeUnmount(() => { mounted = false; clearScopeData() })
</script>

<template>
  <AppCard class="safety-assignments" aria-labelledby="safety-assignments-title">
    <header class="safety-assignments__header">
      <div class="safety-assignments__heading">
        <ShieldCheck :size="18" aria-hidden="true" />
        <div><h2 id="safety-assignments-title">安全事项分配</h2><p>仅显示待分配的事项编号、流程状态和班级，不展示学生身份、触发原因或对话内容。</p></div>
      </div>
      <AppButton variant="secondary" size="sm" :disabled="state === 'loading' || busy || Boolean(failedOperation)" @click="load(offset)">
        <RotateCcw :size="15" aria-hidden="true" />刷新
      </AppButton>
    </header>

    <AppStatusCallout v-if="errorMessage" tone="critical" title="分配队列不可用" :body="errorMessage" role="alert" />
    <AppStatusCallout v-if="operationError" tone="critical" title="操作未确认" :body="operationError" role="alert" />
    <AppButton v-if="failedOperation" variant="secondary" size="sm" :disabled="busy" :loading="busy" @click="retry">使用相同请求重试</AppButton>
    <AppStatusCallout v-if="notice" tone="info" title="服务端已确认" :body="notice" role="status" />

    <div v-if="state === 'loading'" class="safety-assignments__state" role="status" aria-busy="true">正在读取待分配事项和当前可选对象…</div>
    <div v-else-if="state === 'ready' && !cases.length" class="safety-assignments__state">当前没有可分配的安全事项。</div>
    <ul v-else-if="state === 'ready'" class="safety-assignments__list" aria-label="待分配安全事项">
      <li v-for="row in cases" :key="row.case_ref" class="safety-assignments__row">
        <div class="safety-assignments__case">
          <strong>{{ row.case_ref }}</strong><span>待分配</span>
          <small>状态版本 {{ row.state_version }} · 更新于 {{ new Date(row.updated_at).toLocaleString('zh-CN') }}</small>
        </div>
        <label class="safety-assignments__field">
          <span>班级</span>
          <select :value="caseClassValue(row)" :disabled="busy || Boolean(failedOperation) || !classes.length" @change="setClass(row.case_ref, $event)">
            <option value="">选择班级</option>
            <option v-for="item in classes" :key="item.class_ref" :value="item.class_ref">{{ classLabel(item) }} · {{ item.class_ref }}</option>
          </select>
        </label>
        <label class="safety-assignments__field">
          <span>心理老师</span>
          <select v-model="specialistUserId" :disabled="busy || Boolean(failedOperation) || !visibleSpecialists.length">
            <option value="">选择心理老师</option>
            <option v-for="(person, index) in visibleSpecialists" :key="person.user_id" :value="person.user_id">{{ specialistLabel(person, index) }}</option>
          </select>
        </label>
        <AppButton size="sm" :disabled="!canAssign(row)" :loading="busy" @click="assign(row)">分配</AppButton>
      </li>
    </ul>
    <div v-if="state === 'ready' && total > 20" class="safety-assignments__paging" aria-label="待分配事项分页">
      <span>第 {{ pageNumber }} / {{ pageCount }} 页 · 共 {{ total }} 项</span>
      <div><AppButton variant="quiet" size="sm" :disabled="!hasPrevious || state === 'loading' || busy || Boolean(failedOperation)" @click="load(Math.max(0, offset - 20))">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="!hasNext || state === 'loading' || busy || Boolean(failedOperation)" @click="load(offset + 20)">下一页</AppButton></div>
    </div>
    <p v-if="state === 'ready' && !classes.length" class="safety-assignments__hint">当前没有可用班级，无法分配。</p>
    <p v-if="state === 'ready' && !specialists.length" class="safety-assignments__hint">当前没有可分配的心理老师。</p>
    <p class="safety-assignments__boundary">分配只改变服务端的流程归属；本页不提供安全判断、处置结论或对学生的消息发送。</p>
  </AppCard>
</template>

<style scoped>
.safety-assignments { display: grid; gap: 12px; min-width: 0; margin-top: 14px; padding: 17px; }
.safety-assignments__header,.safety-assignments__heading,.safety-assignments__row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.safety-assignments__heading { justify-content: flex-start; align-items: flex-start; color: #388576; }
.safety-assignments__heading h2 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 15px; }
.safety-assignments__heading p,.safety-assignments__boundary { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.safety-assignments__state,.safety-assignments__hint { padding: 11px; border-radius: 8px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 12px; }
.safety-assignments__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.safety-assignments__paging { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--color-text-secondary); font-size: 11px; }.safety-assignments__paging > div { display: flex; gap: 6px; }
.safety-assignments__row { flex-wrap: wrap; padding: 11px; border: 1px solid var(--color-border); border-radius: 9px; }
.safety-assignments__case { display: grid; min-width: 130px; gap: 3px; }.safety-assignments__case strong { color: var(--color-text-primary); font-size: 12px; }.safety-assignments__case > span { color: #8a621a; font-size: 11px; font-weight: 700; }.safety-assignments__case small { color: var(--color-text-muted); font-size: 10px; }
.safety-assignments__field { display: grid; flex: 1 1 180px; gap: 4px; color: var(--color-text-secondary); font-size: 11px; font-weight: 650; }.safety-assignments__field select { min-height: 38px; width: 100%; border: 1px solid var(--color-border); border-radius: 8px; padding: 7px 9px; color: var(--color-text-primary); background: white; font: inherit; font-weight: 400; }
.safety-assignments__boundary { padding-top: 7px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 11px; }
@media(max-width:700px) { .safety-assignments__header { align-items: flex-start; }.safety-assignments__row { align-items: stretch; }.safety-assignments__case { flex: 1 1 100%; }.safety-assignments__field { flex-basis: 100%; } }
</style>
