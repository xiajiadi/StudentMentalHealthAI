<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw, ShieldCheck } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { useSessionStore } from '@/stores/session'
import {
  newConversationSafetyIdempotencyKey,
  schoolConversationSafety,
  type AssignedSafetyCase,
  type SafetyTransitionStatus,
} from '@/services/school-conversation-safety'

type LoadState = 'loading' | 'ready' | 'error'
type FailedMutation = { label: string; key: string; run: () => Promise<AssignedSafetyCase> }
const pageSize = 20
const session = useSessionStore()
const scopeKey = computed(() => [
  session.user?.userId ?? '', session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '', session.user?.activeContext?.role ?? '',
].join('|'))
const authorized = computed(() => session.role === 'psychological_specialist'
  && session.user?.activeContext?.role === 'psychological_specialist')
const cases = ref<AssignedSafetyCase[]>([])
const selectedRef = ref('')
const selected = ref<AssignedSafetyCase | null>(null)
const listState = ref<LoadState>('loading')
const detailState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const listError = ref('')
const detailError = ref('')
const note = ref('')
const busy = ref(false)
const mutationError = ref('')
const conflict = ref(false)
const notice = ref('')
const selectedTransition = ref<SafetyTransitionStatus | ''>('')
const confirmUnresolved = ref(false)
const failedMutation = ref<FailedMutation | null>(null)
const offset = ref(0)
const total = ref(0)
let generation = 0
let detailGeneration = 0
let mounted = true

const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(() => offset.value + cases.value.length < total.value)
const pageNumber = computed(() => Math.floor(offset.value / pageSize) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const noteDirty = computed(() => selected.value && selected.value.review_note !== note.value)
const canSaveNote = computed(() => authorized.value && Boolean(selected.value && noteDirty.value)
  && note.value.trim().length > 0 && note.value.length <= 4000
  && !busy.value && !failedMutation.value && ['ASSIGNED', 'IN_REVIEW', 'ESCALATION_NEEDED'].includes(selected.value?.status ?? ''))
const availableTransitions = computed<SafetyTransitionStatus[]>(() => {
  switch (selected.value?.status) {
    case 'ASSIGNED': return ['IN_REVIEW']
    case 'IN_REVIEW': return ['REVIEWED', 'ESCALATION_NEEDED', 'CLOSED']
    case 'ESCALATION_NEEDED': return ['IN_REVIEW', 'CLOSED']
    default: return []
  }
})
const canTransition = computed(() => authorized.value && Boolean(selected.value && selectedTransition.value)
  && availableTransitions.value.includes(selectedTransition.value as SafetyTransitionStatus)
  && (selectedTransition.value === 'IN_REVIEW' || confirmUnresolved.value)
  && !busy.value && !failedMutation.value)

const actionLabel = (action: AssignedSafetyCase['action']) => action === 'CRISIS_ROUTE' ? '安全升级流程已触发' : '需要人工复核'
const statusLabel = (status: AssignedSafetyCase['status']) => ({
  ASSIGNED: '等待专业人员查看', IN_REVIEW: '专业人员处理中', REVIEWED: '流程已标记复核',
  ESCALATION_NEEDED: '仍需更多信息', CLOSED: '流程已结束 · 安全状态未解除',
}[status])
const transitionLabel = (status: SafetyTransitionStatus) => ({
  IN_REVIEW: '开始或继续复核', REVIEWED: '标记已复核',
  ESCALATION_NEEDED: '标记需要升级处理', CLOSED: '结束此复核流程',
}[status])
const formatDate = (value: string | null) => {
  if (!value) return '暂无记录'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间暂不可用' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}
const safeError = (error: unknown) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  return {
    conflict: code === 'WORKFLOW_CONFLICT' || code === 'IDEMPOTENCY_CONFLICT',
    accessLost: code === 'FORBIDDEN' || code === 'RESOURCE_NOT_FOUND'
      || code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED',
    retryable: Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable),
  }
}

function clearPrivateState() {
  ++generation
  ++detailGeneration
  busy.value = false
  cases.value = []
  selectedRef.value = ''
  selected.value = null
  note.value = ''
  selectedTransition.value = ''
  confirmUnresolved.value = false
  failedMutation.value = null
  mutationError.value = ''
  conflict.value = false
  notice.value = ''
  total.value = 0
  offset.value = 0
}

async function loadPage(nextOffset = offset.value, preferredCaseRef = '', fallbackPrevious = true) {
  clearPrivateState()
  const current = ++generation
  if (!authorized.value) {
    listState.value = 'error'
    listError.value = '当前账号没有心理专业安全事项权限。'
    return
  }
  listState.value = 'loading'
  listError.value = ''
  detailState.value = 'idle'
  try {
    const page = await schoolConversationSafety.listAssigned(nextOffset, pageSize)
    if (!mounted || current !== generation) return
    if (!page.items.length && nextOffset > 0 && nextOffset >= page.total && fallbackPrevious) {
      await loadPage(Math.max(0, nextOffset - pageSize), preferredCaseRef, false)
      return
    }
    cases.value = page.items
    total.value = page.total
    offset.value = nextOffset
    listState.value = 'ready'
    const selectedRow = page.items.find((row) => row.case_ref === preferredCaseRef) ?? page.items[0]
    if (selectedRow) await selectCase(selectedRow.case_ref)
  } catch (error) {
    if (!mounted || current !== generation) return
    clearPrivateState()
    listState.value = 'error'
    const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
    listError.value = code === 'FORBIDDEN' ? '当前账号无权读取已指派事项。'
      : code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED' ? '登录状态已失效，请重新登录。'
        : '已指派事项暂时无法读取；不会以示例记录替代。'
  }
}

async function selectCase(caseRef: string) {
  if (!authorized.value || busy.value || failedMutation.value || !cases.value.some((row) => row.case_ref === caseRef)) return
  selectedRef.value = caseRef
  selected.value = null
  note.value = ''
  selectedTransition.value = ''
  confirmUnresolved.value = false
  detailError.value = ''
  const current = ++detailGeneration
  detailState.value = 'loading'
  try {
    const value = await schoolConversationSafety.getAssignedCase(caseRef)
    if (!mounted || current !== detailGeneration || selectedRef.value !== caseRef) return
    if (!cases.value.some((row) => row.case_ref === value.case_ref)) throw new Error('SCOPE_MISMATCH')
    selected.value = value
    note.value = value.review_note ?? ''
    detailState.value = 'ready'
  } catch (error) {
    if (!mounted || current !== detailGeneration) return
    selected.value = null
    note.value = ''
    detailState.value = 'error'
    const classified = safeError(error)
    if (classified.accessLost) {
      clearPrivateState()
      listState.value = 'error'
      listError.value = '当前指派或角色权限已变化，页面缓存已清除。'
    } else detailError.value = '该事项详情暂时不可用。请刷新指派列表后重试。'
  }
}

async function execute(label: string, operationKey: string, run: () => Promise<AssignedSafetyCase>) {
  if (!authorized.value || busy.value || !selected.value) return
  const scope = scopeKey.value
  const caseRef = selected.value.case_ref
  const current = detailGeneration
  busy.value = true
  mutationError.value = ''
  conflict.value = false
  notice.value = ''
  try {
    await run()
    if (!mounted || scope !== scopeKey.value || current !== detailGeneration || selectedRef.value !== caseRef) return
    failedMutation.value = null
    await loadPage(offset.value, caseRef)
    if (!mounted || scope !== scopeKey.value) return
    notice.value = '服务端已记录流程更新；此状态不代表诊断结论或安全状态解除。'
  } catch (error) {
    if (!mounted || scope !== scopeKey.value || current !== detailGeneration) return
    const classified = safeError(error)
    if (classified.accessLost) {
      clearPrivateState()
      listState.value = 'error'
      listError.value = '当前指派或角色权限已变化，页面缓存已清除。'
    } else if (classified.conflict) {
      failedMutation.value = null
      conflict.value = true
      selected.value = null
      note.value = ''
      detailState.value = 'error'
      await loadPage(offset.value)
      if (mounted && scope === scopeKey.value) mutationError.value = '事项版本已经变化；当前页已刷新，请核对最新状态后再处理。'
    } else {
      failedMutation.value = classified.retryable ? { label, key: operationKey, run } : null
      mutationError.value = classified.retryable
        ? '服务端尚未确认操作结果；可使用同一请求安全重试。'
        : '操作未完成，请刷新并核对当前流程状态。'
    }
  } finally {
    if (scope === scopeKey.value) busy.value = false
  }
}

function saveNote() {
  const current = selected.value
  if (!current || !canSaveNote.value || note.value.length > 4000) return
  try {
    const text = note.value
    const expected = current.state_version
    const key = newConversationSafetyIdempotencyKey()
    void execute('保存备注', key, () => schoolConversationSafety.saveNote(current.case_ref, expected, text, key))
  } catch {
    mutationError.value = '当前浏览器无法安全建立请求标识，请更新浏览器后重试。'
  }
}

function transitionCase() {
  const current = selected.value
  const status = selectedTransition.value
  if (!current || !status || !canTransition.value) return
  try {
    const expected = current.state_version
    const key = newConversationSafetyIdempotencyKey()
    void execute('更新复核流程', key, () => schoolConversationSafety.transition(current.case_ref, expected, status, key))
  } catch {
    mutationError.value = '当前浏览器无法安全建立请求标识，请更新浏览器后重试。'
  }
}

function retry() {
  if (failedMutation.value && !busy.value) {
    const operation = failedMutation.value
    void execute(operation.label, operation.key, operation.run)
  }
}

watch(scopeKey, () => {
  clearPrivateState()
  listError.value = ''
  if (authorized.value) void loadPage(0)
  else {
    listState.value = 'error'
    listError.value = '当前账号没有心理专业安全事项权限。'
  }
})
watch(selectedTransition, () => { confirmUnresolved.value = false })
onMounted(() => { void loadPage(0) })
onBeforeUnmount(() => { mounted = false; clearPrivateState() })
</script>

<template>
  <AppCard class="conversation-safety" aria-labelledby="conversation-safety-title">
    <header class="conversation-safety__header">
      <div class="conversation-safety__title"><ShieldCheck :size="18" aria-hidden="true" /><div><h2 id="conversation-safety-title">对话安全复核</h2><p>仅列出当前指派给你的事项。这里只记录复核流程，不作诊断，也不解除安全提示。</p></div></div>
      <div class="conversation-safety__paging">
        <AppButton variant="quiet" size="sm" :disabled="listState === 'loading' || busy || Boolean(failedMutation)" @click="loadPage(offset)"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton>
        <AppButton variant="quiet" size="sm" :disabled="!hasPrevious || listState === 'loading' || busy || Boolean(failedMutation)" @click="loadPage(Math.max(0, offset - pageSize))">上一页</AppButton>
        <AppButton variant="quiet" size="sm" :disabled="!hasNext || listState === 'loading' || busy || Boolean(failedMutation)" @click="loadPage(offset + pageSize)">下一页</AppButton>
        <span v-if="listState === 'ready'">第 {{ pageNumber }} / {{ pageCount }} 页 · 共 {{ total }} 项</span>
      </div>
    </header>
    <AppStatusCallout tone="info" title="流程记录与专业结论不同" body="动作与原因代码仅说明安全流程进入复核，不代表诊断、风险已经解除或专业结论。若仅凭当前元数据无法判断，可记录需要更多信息；任何结束或升级标记都不会关闭学生端安全提示。" />
    <AppStatusCallout v-if="listError" tone="critical" title="复核事项暂不可用" :body="listError" role="alert"><AppButton variant="secondary" size="sm" @click="loadPage(offset)">重新加载</AppButton></AppStatusCallout>
    <p v-else-if="listState === 'loading'" class="conversation-safety__state" role="status" aria-busy="true">正在读取当前指派事项…</p>
    <p v-else-if="listState === 'ready' && !cases.length" class="conversation-safety__state">当前没有可查看的指派事项。</p>
    <div v-else-if="listState === 'ready'" class="conversation-safety__layout">
      <nav class="conversation-safety__list" aria-label="已指派安全事项">
        <button v-for="row in cases" :key="row.case_ref" type="button" :class="['conversation-safety__case', { 'conversation-safety__case--selected': row.case_ref === selectedRef }]" :disabled="busy || Boolean(failedMutation)" @click="selectCase(row.case_ref)">
          <strong>{{ row.case_ref }}</strong><span>{{ statusLabel(row.status) }}</span><small>{{ actionLabel(row.action) }}</small>
        </button>
      </nav>
      <section class="conversation-safety__detail" aria-label="安全复核事项详情">
        <p v-if="detailState === 'loading'" class="conversation-safety__state" role="status" aria-busy="true">正在读取授权的事项摘要…</p>
        <p v-else-if="detailState === 'error'" class="conversation-safety__state" role="alert">{{ detailError }}</p>
        <template v-else-if="selected && detailState === 'ready'">
          <header class="conversation-safety__detail-heading"><div><span class="conversation-safety__eyebrow">事项 {{ selected.case_ref }}</span><h3>{{ statusLabel(selected.status) }}</h3></div><span class="conversation-safety__action">{{ actionLabel(selected.action) }}</span></header>
          <dl class="conversation-safety__metadata"><div><dt>班级</dt><dd>{{ selected.class_ref }}</dd></div><div><dt>流程原因代码</dt><dd>{{ selected.reason_codes.length ? selected.reason_codes.join('、') : '未提供' }}</dd></div><div><dt>状态版本</dt><dd>{{ selected.state_version }}</dd></div><div><dt>更新时间</dt><dd>{{ formatDate(selected.updated_at) }}</dd></div><div><dt>指派时间</dt><dd>{{ formatDate(selected.assigned_at) }}</dd></div><div v-if="selected.decision_code"><dt>流程说明</dt><dd>仍需更多信息；安全提示保持有效</dd></div></dl>
          <label class="conversation-safety__note"><span>专业复核备注（仅当前授权复核人员可读）</span><textarea v-model="note" maxlength="4000" :disabled="busy || Boolean(failedMutation) || !['ASSIGNED', 'IN_REVIEW', 'ESCALATION_NEEDED'].includes(selected.status)" rows="4" placeholder="只记录完成复核所需的最少工作信息。"></textarea><small>{{ note.length }}/4000</small></label>
          <AppButton size="sm" :disabled="!canSaveNote || note.length > 4000" :loading="busy" @click="saveNote">保存备注并进入处理中</AppButton>
          <fieldset v-if="availableTransitions.length" class="conversation-safety__transitions" :disabled="busy || Boolean(failedMutation)">
            <legend>更新流程状态</legend>
            <label v-for="status in availableTransitions" :key="status" class="conversation-safety__option"><input v-model="selectedTransition" type="radio" :value="status"><span>{{ transitionLabel(status) }}</span></label>
            <label v-if="selectedTransition && selectedTransition !== 'IN_REVIEW'" class="conversation-safety__confirm"><input v-model="confirmUnresolved" type="checkbox"><span>我确认这是流程记录，信息仍可能不足；此操作不会表示安全风险已解决，也不会关闭学生端安全提示。</span></label>
            <AppButton variant="secondary" size="sm" :disabled="!canTransition" :loading="busy" @click="transitionCase">确认流程状态</AppButton>
          </fieldset>
          <p class="conversation-safety__boundary">复核视图不包含姓名、联系方式、原始聊天内容或测评回答。需要更完整信息时，应使用学校既定人工流程；此界面不会替代该流程。</p>
        </template>
      </section>
    </div>
    <AppStatusCallout v-if="conflict || mutationError" tone="critical" title="更新未确认" :body="conflict ? detailError : mutationError" role="alert" />
    <AppButton v-if="failedMutation" variant="secondary" size="sm" :disabled="busy" :loading="busy" @click="retry">使用同一请求重试</AppButton>
    <AppStatusCallout v-if="notice" tone="info" title="服务端已记录" :body="notice" role="status" />
  </AppCard>
</template>

<style scoped>
.conversation-safety { display: grid; gap: 12px; min-width: 0; margin-bottom: 14px; padding: 17px; }
.conversation-safety__header,.conversation-safety__title,.conversation-safety__paging,.conversation-safety__detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.conversation-safety__title { justify-content: flex-start; align-items: flex-start; color: #388576; }.conversation-safety__title h2 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 15px; }.conversation-safety__title p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.conversation-safety__state { margin: 0; padding: 11px; border-radius: 8px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 12px; }.conversation-safety__layout { display: grid; grid-template-columns: minmax(190px,.72fr) minmax(0,1.5fr); gap: 13px; }
.conversation-safety__list { display: grid; align-content: start; gap: 6px; }.conversation-safety__case { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--color-border); border-radius: 9px; color: var(--color-text-primary); background: #fff; text-align: left; cursor: pointer; }.conversation-safety__case--selected { border-color: #72a89a; background: #f2f8f5; }.conversation-safety__case strong { font-size: 11px; }.conversation-safety__case span,.conversation-safety__case small { color: var(--color-text-secondary); font-size: 10px; }
.conversation-safety__detail { display: grid; align-content: start; gap: 12px; min-width: 0; padding: 13px; border: 1px solid var(--color-border); border-radius: 10px; }.conversation-safety__eyebrow { color: #548074; font-size: 10px; font-weight: 750; }.conversation-safety__detail-heading h3 { margin: 4px 0 0; color: var(--color-text-primary); font-size: 15px; }.conversation-safety__action { padding: 5px 8px; border-radius: 999px; color: #815a19; background: #fbf2df; font-size: 10px; font-weight: 700; }
.conversation-safety__metadata { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; margin: 0; }.conversation-safety__metadata > div { min-width: 0; padding: 8px; border-radius: 7px; background: #f7f8f9; }.conversation-safety__metadata dt { color: var(--color-text-muted); font-size: 10px; }.conversation-safety__metadata dd { overflow-wrap: anywhere; margin: 3px 0 0; color: var(--color-text-primary); font-size: 11px; }
.conversation-safety__note { display: grid; gap: 5px; color: var(--color-text-secondary); font-size: 11px; font-weight: 650; }.conversation-safety__note textarea { width: 100%; resize: vertical; border: 1px solid var(--color-border); border-radius: 8px; padding: 9px; color: var(--color-text-primary); background: #fff; font: inherit; font-weight: 400; line-height: 1.55; }.conversation-safety__note small { justify-self: end; color: var(--color-text-muted); font-weight: 400; }
.conversation-safety__transitions { display: grid; gap: 9px; margin: 0; padding: 11px; border: 1px solid var(--color-border); border-radius: 8px; }.conversation-safety__transitions legend { padding: 0 5px; color: var(--color-text-primary); font-size: 12px; font-weight: 700; }.conversation-safety__option,.conversation-safety__confirm { display: flex; gap: 8px; align-items: flex-start; color: var(--color-text-secondary); font-size: 11px; line-height: 1.55; }.conversation-safety__confirm { padding: 8px; border-radius: 7px; color: #765616; background: #fbf5e8; }.conversation-safety__boundary { margin: 0; padding-top: 9px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 10px; line-height: 1.6; }
@media(max-width:720px) { .conversation-safety__header { align-items: flex-start; flex-wrap: wrap; }.conversation-safety__layout { grid-template-columns: 1fr; }.conversation-safety__list { grid-template-columns: 1fr; }.conversation-safety__metadata { grid-template-columns: 1fr; } }
</style>
