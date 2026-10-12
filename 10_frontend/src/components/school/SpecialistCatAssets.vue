<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Archive, CircleAlert, FilePlus2, History, RotateCcw, Save, ShieldCheck, X } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { useSessionStore } from '@/stores/session'
import {
  latestCatAssetVersion,
  newCatAssetIdempotencyKey,
  schoolCatAssets,
  type CatAssetItemDocument,
  type CatBankDetail,
  type CatBankDocument,
  type CatBankMetadata,
  type CatBankVersion,
  type CatConfigDocument,
  type CatPlanDetail,
  type CatPlanMetadata,
  type CatPlanVersion,
  type CatSavedPlanSimulation,
  type CatSavedSimulationBatch,
} from '@/services/school-cat-assets'
import {
  newCatActivationIdempotencyKey,
  schoolCatActivations,
  type CatActivationMetadata,
} from '@/services/school-cat-activations'

type Tab = 'banks' | 'plans'
type State = 'loading' | 'ready' | 'forbidden' | 'unavailable'
type PendingIntent = { label: string; retry: () => Promise<void>; scope: string }
type ActivationIntent = {
  label: string
  planVersionRef: string
  key: string
  scope: string
  run: () => Promise<CatActivationMetadata>
}

const props = withDefaults(defineProps<{ active?: boolean }>(), { active: true })
const session = useSessionStore()
const tab = ref<Tab>('banks')
const state = ref<State>('loading')
const error = ref('')
const banks = ref<CatBankMetadata[]>([])
const plans = ref<CatPlanMetadata[]>([])
const availableBankVersions = ref<Array<{ bank: CatBankMetadata; version: CatBankDetail['versions'][number] }>>([])
const templateBank = ref<CatBankDocument | null>(null)
const templateConfig = ref<CatConfigDocument | null>(null)
const bankDetail = ref<CatBankDetail | null>(null)
const planDetail = ref<CatPlanDetail | null>(null)
const selectedBankVersion = ref<CatBankVersion | null>(null)
const selectedPlanVersion = ref<CatPlanVersion | null>(null)
const simulationBankVersion = ref<CatBankVersion | null>(null)
const simulationBatch = ref<CatSavedSimulationBatch>(100)
const simulationResult = ref<CatSavedPlanSimulation | null>(null)
const comparisonBaseline = ref<CatSavedPlanSimulation | null>(null)
const simulationState = ref<'idle' | 'running' | 'complete' | 'busy' | 'error' | 'blocked'>('idle')
const simulationError = ref('')
const bankDraft = ref<CatBankDocument | null>(null)
const configDraft = ref<CatConfigDocument | null>(null)
const bankName = ref('')
const planName = ref('')
const bankVersionRef = ref('')
const selectedBankRef = ref('')
const busy = ref(false)
const pendingIntent = ref<PendingIntent | null>(null)
const activationHistory = ref<CatActivationMetadata[]>([])
const activationHasMore = ref(false)
const activationSkip = ref(0)
const activationState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const activationError = ref('')
const activationNotice = ref('')
const pendingActivationIntent = ref<ActivationIntent | null>(null)
const activationBusy = ref(false)
const activationConflict = ref(false)
const conflictRefresh = ref<null | (() => Promise<void>)>(null)
const notice = ref('')
let sequence = 0
let simulationSequence = 0
let activationSequence = 0
let activationMutationSequence = 0
let disposed = false
let activated = false

const scopeKey = () => [session.user?.userId ?? '', session.role ?? '', session.user?.activeContext?.role ?? '', session.user?.activeContext?.schoolRef ?? ''].join('|')
const hasRole = () => session.role === 'psychological_specialist'
  && (!session.user?.activeContext || session.user.activeContext.role === 'psychological_specialist')
const active = computed(() => props.active !== false)
const resources = computed(() => tab.value === 'banks' ? banks.value : plans.value)
const selectedBankDocument = computed(() => selectedBankVersion.value?.bank_document ?? null)
const activeActivation = computed(() => activationHistory.value.find((item) => item.status === 'ACTIVE') ?? null)
const inputLocked = computed(() => state.value === 'loading' || busy.value || Boolean(pendingIntent.value)
  || Boolean(pendingActivationIntent.value) || activationBusy.value || simulationState.value === 'running')
const canCreateActivation = computed(() => activationState.value === 'ready'
  && !activationHasMore.value && !activeActivation.value && !inputLocked.value)
const simulationLocked = computed(() => inputLocked.value)
const canRunSavedSimulation = computed(() => Boolean(selectedPlanVersion.value && simulationBankVersion.value)
  && simulationState.value !== 'running' && simulationState.value !== 'blocked' && !inputLocked.value)
const mutationBlocked = computed(() => inputLocked.value || Boolean(conflictRefresh.value))
const canSaveBank = computed(() => Boolean(bankDraft.value && bankName.value.trim() && !mutationBlocked.value))
const canSavePlan = computed(() => Boolean(configDraft.value && planName.value.trim() && bankVersionRef.value && selectedBankDocument.value && !mutationBlocked.value))
const bankVersionLabel = (reference: string) => {
  const found = availableBankVersions.value.find((entry) => entry.version.version_ref === reference)
  return found ? `${found.bank.display_name} v${found.version.version_number}` : '本校历史题库版本'
}
const simulationBankLabel = computed(() => {
  const version = simulationBankVersion.value
  if (!version) return ''
  return `${bankVersionLabel(version.version_ref)}（v${version.version_number}）`
})
const simulationComparisonText = computed(() => {
  if (!simulationResult.value || !comparisonBaseline.value
    || !sameSimulationBasis(simulationResult.value, comparisonBaseline.value)) return ''
  return sameSimulationOutput(simulationResult.value, comparisonBaseline.value)
    ? '本次与上次运行的汇总结果相同。'
    : '本次与上次运行的汇总结果不同。'
})
const stoppingReasonLabel = (reason: string) => ({
  SE_THRESHOLD_REACHED: '达到停止阈值',
  MAX_ITEMS_REACHED: '达到最多题数',
  ITEM_BANK_EXHAUSTED: '题库题目已用尽',
  MANUAL_TERMINATION: '手动结束',
  ERROR: '运行错误',
  NOT_STOPPED: '未停止',
}[reason] ?? '其他')

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const errorCode = (value: unknown) => value && typeof value === 'object' && 'code' in value ? String(value.code).toUpperCase() : ''
const isForbidden = (value: unknown) => ['403', 'HTTP_403', 'FORBIDDEN', 'UNAUTHORIZED', '401', 'HTTP_401', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(errorCode(value))
const isConflict = (value: unknown) => ['409', 'HTTP_409', 'CONFLICT', 'CAT_ASSET_CONFLICT', 'IDEMPOTENCY_CONFLICT'].includes(errorCode(value))

function clearActivationHistory() {
  activationSequence += 1
  activationMutationSequence += 1
  activationHistory.value = []
  activationHasMore.value = false
  activationSkip.value = 0
  activationState.value = 'idle'
  activationError.value = ''
  activationNotice.value = ''
  pendingActivationIntent.value = null
  activationBusy.value = false
  activationConflict.value = false
}

function clearSavedSimulation(clearSelection: boolean) {
  simulationSequence += 1
  simulationResult.value = null
  comparisonBaseline.value = null
  simulationError.value = ''
  simulationState.value = 'idle'
  if (clearSelection) {
    simulationBatch.value = 100
    selectedPlanVersion.value = null
    simulationBankVersion.value = null
    clearActivationHistory()
  }
}

async function loadActivationHistory(reset = true) {
  const planVersionRef = selectedPlanVersion.value?.version_ref
  if (!planVersionRef || !hasRole()) return
  const token = ++activationSequence
  const scope = scopeKey()
  const skip = reset ? 0 : activationSkip.value
  if (reset) {
    activationHistory.value = []
    activationHasMore.value = false
    activationSkip.value = 0
  }
  activationState.value = 'loading'
  activationError.value = ''
  try {
    const page = await schoolCatActivations.list({ skip, limit: 30, planVersionRef })
    if (disposed || token !== activationSequence || scope !== scopeKey() || !hasRole()
      || selectedPlanVersion.value?.version_ref !== planVersionRef) return
    const items = reset ? [] : activationHistory.value
    const byRef = new Map(items.map((item) => [item.activation_ref, item]))
    for (const item of page.items) byRef.set(item.activation_ref, item)
    activationHistory.value = [...byRef.values()]
    activationSkip.value = skip + page.items.length
    activationHasMore.value = page.has_more
    activationState.value = 'ready'
  } catch (cause) {
    if (disposed || token !== activationSequence || scope !== scopeKey()
      || selectedPlanVersion.value?.version_ref !== planVersionRef) return
    if (isForbidden(cause)) {
      clearPrivate()
      state.value = 'forbidden'
      error.value = '访问权限已变化，已清除本页资产与启用记录。'
      return
    }
    activationState.value = 'error'
    activationError.value = '无法读取这个方案版本的启用记录。请重新读取后再操作。'
  }
}

function beginActivationMutation(intent: ActivationIntent) {
  activationMutationSequence += 1
  pendingActivationIntent.value = intent
  activationConflict.value = false
  activationError.value = ''
  void runActivationMutation()
}

async function runActivationMutation() {
  const intent = pendingActivationIntent.value
  if (!intent || activationBusy.value || intent.scope !== scopeKey() || !hasRole()) return
  const token = activationMutationSequence
  activationBusy.value = true
  activationError.value = ''
  try {
    const result = await intent.run()
    if (disposed || intent.scope !== scopeKey() || !hasRole()
      || selectedPlanVersion.value?.version_ref !== intent.planVersionRef) return
    pendingActivationIntent.value = null
    activationConflict.value = false
    activationNotice.value = result.status === 'ACTIVE'
      ? '该合成方案版本已启用，可供管理员为新任务选择。'
      : '该启用记录已撤销，不再用于新任务。'
    await loadActivationHistory(true)
  } catch (cause) {
    if (disposed || intent.scope !== scopeKey()
      || selectedPlanVersion.value?.version_ref !== intent.planVersionRef) return
    if (isForbidden(cause)) {
      clearPrivate()
      state.value = 'forbidden'
      error.value = '访问权限已变化，已清除本页资产与启用记录。'
    } else if (isConflict(cause) || ['WORKFLOW_CONFLICT', 'CAT_ASSET_CONFLICT'].includes(errorCode(cause))) {
      pendingActivationIntent.value = null
      activationConflict.value = true
      activationError.value = '启用状态已变化。请重新读取记录后再决定下一步。'
    } else if (['422', 'HTTP_422', 'VALIDATION_FAILED', 'API_VALIDATION_FAILED'].includes(errorCode(cause))) {
      pendingActivationIntent.value = null
      activationError.value = '请求未通过校验。请刷新启用记录后重试。'
    } else {
      activationError.value = '请求结果尚未确认。可使用同一请求重试；系统不会自动再次发送。'
    }
  } finally {
    if (!disposed && token === activationMutationSequence && intent.scope === scopeKey()) {
      activationBusy.value = false
    }
  }
}

function enableSelectedVersion() {
  const planVersionRef = selectedPlanVersion.value?.version_ref
  if (!planVersionRef || !canCreateActivation.value || !hasRole()) return
  try {
    const key = newCatActivationIdempotencyKey()
    beginActivationMutation({
      label: '启用合成方案版本', planVersionRef, key, scope: scopeKey(),
      run: () => schoolCatActivations.create(planVersionRef, key),
    })
  } catch {
    activationError.value = '当前浏览器无法安全建立请求，请更新浏览器后重试。'
  }
}

function revokeActivation(item: CatActivationMetadata) {
  if (item.status !== 'ACTIVE' || inputLocked.value || !hasRole()) return
  try {
    const key = newCatActivationIdempotencyKey()
    beginActivationMutation({
      label: '撤销方案版本启用', planVersionRef: item.plan_version_ref, key, scope: scopeKey(),
      run: () => schoolCatActivations.revoke(item.activation_ref, item.revision, key),
    })
  } catch {
    activationError.value = '当前浏览器无法安全建立请求，请更新浏览器后重试。'
  }
}

function retryActivationSameRequest() {
  if (!pendingActivationIntent.value || pendingActivationIntent.value.scope !== scopeKey()) return
  void runActivationMutation()
}

function clearPrivate() {
  banks.value = []; plans.value = []; availableBankVersions.value = []; templateBank.value = null; templateConfig.value = null
  bankDetail.value = null; planDetail.value = null; selectedBankVersion.value = null; selectedPlanVersion.value = null
  bankDraft.value = null; configDraft.value = null; bankName.value = ''; planName.value = ''
  bankVersionRef.value = ''; selectedBankRef.value = ''; pendingIntent.value = null; conflictRefresh.value = null
  error.value = ''; notice.value = ''; busy.value = false
  clearSavedSimulation(true)
}

function clearSelection() {
  bankDetail.value = null; planDetail.value = null; selectedBankVersion.value = null; selectedPlanVersion.value = null
  bankDraft.value = null; configDraft.value = null; bankName.value = ''; planName.value = ''; bankVersionRef.value = ''
  error.value = ''; notice.value = ''; pendingIntent.value = null; conflictRefresh.value = null
  clearSavedSimulation(true)
}

async function loadWorkspace() {
  const token = ++sequence
  const scope = scopeKey()
  clearPrivate()
  state.value = 'loading'
  if (!hasRole()) { state.value = 'forbidden'; return }
  try {
    const [template, bankPage, planPage] = await Promise.all([
      schoolCatAssets.getTemplate(), schoolCatAssets.listBanks(), schoolCatAssets.listPlans(),
    ])
    if (disposed || token !== sequence || scope !== scopeKey() || !hasRole()) return
    templateBank.value = template.bank_document
    templateConfig.value = template.config_document
    banks.value = bankPage.items
    plans.value = planPage.items
    const details = await Promise.all(bankPage.items.filter((bank) => bank.status === 'ACTIVE').map(async (bank) => {
      try { return { bank, detail: await schoolCatAssets.getBank(bank.bank_ref) } } catch { return null }
    }))
    if (disposed || token !== sequence || scope !== scopeKey() || !hasRole()) return
    availableBankVersions.value = details.flatMap((result) => result ? result.detail.versions.map((version) => ({ bank: result.bank, version })) : [])
    state.value = 'ready'
  } catch (cause) {
    if (disposed || token !== sequence || scope !== scopeKey()) return
    clearPrivate()
    state.value = isForbidden(cause) ? 'forbidden' : 'unavailable'
    error.value = isForbidden(cause) ? '当前账号或学校上下文无权读取资产内容。' : '题库与方案暂不可用，请重新读取。'
  }
}

function activate() {
  if (!active.value || activated) return
  activated = true
  void loadWorkspace()
}

function startNewBank() {
  if (!templateBank.value || busy.value) return
  clearSelection()
  tab.value = 'banks'
  bankName.value = '新的合成题库'
  bankDraft.value = copy(templateBank.value)
}

function startNewPlan() {
  if (!templateConfig.value || busy.value) return
  clearSelection()
  tab.value = 'plans'
  planName.value = '新的合成方案'
  configDraft.value = copy(templateConfig.value)
  selectedBankRef.value = ''
}

async function selectBank(item: CatBankMetadata) {
  const token = ++sequence
  const scope = scopeKey()
  clearSelection()
  state.value = 'loading'
  try {
    const detail = await schoolCatAssets.getBank(item.bank_ref)
    if (disposed || token !== sequence || scope !== scopeKey()) return
    bankDetail.value = detail
    bankName.value = detail.display_name
    const latest = latestCatAssetVersion(detail.versions)
    if (latest) {
      const version = await schoolCatAssets.getBankVersion(latest.version_ref)
      if (disposed || token !== sequence || scope !== scopeKey()) return
      selectedBankVersion.value = version
      bankDraft.value = copy(version.bank_document)
      bankVersionRef.value = version.version_ref
    }
    state.value = 'ready'
  } catch (cause) { handleLoadFailure(cause, token, scope) }
}

async function selectPlan(item: CatPlanMetadata) {
  const token = ++sequence
  const scope = scopeKey()
  clearSelection()
  state.value = 'loading'
  try {
    const detail = await schoolCatAssets.getPlan(item.plan_ref)
    if (disposed || token !== sequence || scope !== scopeKey()) return
    planDetail.value = detail
    planName.value = detail.display_name
    const latest = latestCatAssetVersion(detail.versions)
    if (latest) {
      const planVersion = await schoolCatAssets.getPlanVersion(latest.version_ref)
      if (disposed || token !== sequence || scope !== scopeKey()) return
      bankVersionRef.value = planVersion.bank_version_ref
      const exact = availableBankVersions.value.find((entry) => entry.version.version_ref === planVersion.bank_version_ref)
      if (!exact) throw new Error('linked bank version unavailable')
      selectedBankRef.value = exact.bank.bank_ref
      const bankVersion = await schoolCatAssets.getBankVersion(planVersion.bank_version_ref)
      if (disposed || token !== sequence || scope !== scopeKey()) return
      selectedBankVersion.value = bankVersion
      configDraft.value = copy(planVersion.config_document)
    }
    state.value = 'ready'
  } catch (cause) { handleLoadFailure(cause, token, scope) }
}

function handleLoadFailure(cause: unknown, token: number, scope: string) {
  if (disposed || token !== sequence || scope !== scopeKey()) return
  clearSelection()
  error.value = isForbidden(cause) ? '当前账号或学校上下文无权读取资产内容。' : '所选资产暂不可用，请重新读取。'
  state.value = isForbidden(cause) ? 'forbidden' : 'unavailable'
}

async function chooseBankVersion(reference: string) {
  bankVersionRef.value = reference
  selectedBankVersion.value = null
  const token = ++sequence
  const scope = scopeKey()
  try {
    const version = await schoolCatAssets.getBankVersion(reference)
    if (disposed || token !== sequence || scope !== scopeKey()) return
    selectedBankVersion.value = version
    selectedBankRef.value = availableBankVersions.value.find((entry) => entry.version.version_ref === reference)?.bank.bank_ref ?? ''
  } catch (cause) { handleLoadFailure(cause, token, scope) }
}

function addItem() {
  const document = bankDraft.value
  if (!document || document.items.length >= 100) return
  const item: CatAssetItemDocument = copy(document.items[document.items.length - 1]!)
  item.item_id = `ITEM_demo_${crypto.randomUUID()}`
  item.stem = ''
  document.items.push(item)
}

function removeItem(index: number) { bankDraft.value?.items.splice(index, 1) }

function updateOption(item: CatAssetItemDocument, index: number, value: string) {
  const previous = item.response_options[index]
  if (previous === undefined || previous === value) return
  const score = item.scoring[previous]
  const options = [...item.response_options]
  options[index] = value
  item.response_options = options
  delete item.scoring[previous]
  if (value.trim()) item.scoring[value] = score ?? index
}

function captureMutation(label: string, run: () => Promise<void>, conflictRefreshAction?: () => Promise<void>) {
  clearSavedSimulation(true)
  const scope = scopeKey()
  pendingIntent.value = { label, retry: run, scope }
  conflictRefresh.value = conflictRefreshAction ?? null
  void runMutation(run, scope)
}

async function runMutation(run: () => Promise<void>, scope = scopeKey()) {
  if (busy.value || !hasRole()) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await run()
    if (disposed || scope !== scopeKey() || !hasRole()) return
    pendingIntent.value = null; conflictRefresh.value = null
    notice.value = '保存完成，服务端已生成新的版本。'
    try { await reloadLists() } catch { notice.value = '保存已完成；列表暂未刷新，请重新读取后确认最新状态。' }
  } catch (cause) {
    if (disposed || scope !== scopeKey()) return
    if (isForbidden(cause)) {
      clearPrivate(); state.value = 'forbidden'; error.value = '访问权限已变化，已清除本页资产内容。'
    } else if (isConflict(cause)) {
      pendingIntent.value = null
      error.value = '资产已被其他操作更新。保留当前编辑内容；刷新版本信息后可继续保存。'
    } else if (['422', 'HTTP_422', 'VALIDATION_FAILED', 'API_VALIDATION_FAILED'].includes(errorCode(cause))) {
      pendingIntent.value = null; conflictRefresh.value = null
      error.value = '内容未通过结构校验。请检查题干、选项计分、递增阈值、题数范围和题库版本绑定。'
    } else {
      error.value = '保存结果尚未确认。可使用同一请求再次尝试，避免重复创建版本。'
    }
  } finally { if (!disposed && scope === scopeKey()) busy.value = false }
}

async function reloadLists() {
  const token = sequence
  const scope = scopeKey()
  const [bankPage, planPage] = await Promise.all([schoolCatAssets.listBanks(), schoolCatAssets.listPlans()])
  if (disposed || token !== sequence || scope !== scopeKey() || !hasRole()) return
  const details = await Promise.all(bankPage.items.filter((bank) => bank.status === 'ACTIVE').map(async (bank) => {
    try { return { bank, detail: await schoolCatAssets.getBank(bank.bank_ref) } } catch { return null }
  }))
  if (disposed || token !== sequence || scope !== scopeKey() || !hasRole()) return
  banks.value = bankPage.items
  plans.value = planPage.items
  availableBankVersions.value = details.flatMap((result) => result ? result.detail.versions.map((version) => ({ bank: result.bank, version })) : [])
}

function saveBank() {
  if (!bankDraft.value || !bankName.value.trim() || busy.value) return
  const document = copy(bankDraft.value)
  const name = bankName.value
  if (bankDetail.value) {
    const detail = bankDetail.value
    const action = async () => {
      bankDetail.value = await schoolCatAssets.createBankVersion(detail.bank_ref, detail.revision, document, idempotencyKey)
      bankDraft.value = copy(document)
    }
    const idempotencyKey = newCatAssetIdempotencyKey()
    captureMutation('保存题库新版本', action, async () => {
      const fresh = await schoolCatAssets.getBank(detail.bank_ref)
      bankDetail.value = fresh
    })
  } else {
    const idempotencyKey = newCatAssetIdempotencyKey()
    captureMutation('创建题库', async () => {
      const created = await schoolCatAssets.createBank(name, document, idempotencyKey)
      bankDetail.value = created
      bankDraft.value = copy(document)
      bankName.value = created.display_name
    })
  }
}

function savePlan() {
  if (!configDraft.value || !planName.value.trim() || !selectedBankVersion.value || !selectedBankDocument.value || busy.value) return
  const config = copy(configDraft.value)
  const name = planName.value
  const ref = bankVersionRef.value
  const bankDoc = copy(selectedBankDocument.value)
  if (planDetail.value) {
    const detail = planDetail.value
    const idempotencyKey = newCatAssetIdempotencyKey()
    captureMutation('保存方案新版本', async () => {
      planDetail.value = await schoolCatAssets.createPlanVersion(detail.plan_ref, detail.revision, ref, bankDoc, config, idempotencyKey)
    }, async () => { planDetail.value = await schoolCatAssets.getPlan(detail.plan_ref) })
  } else {
    const idempotencyKey = newCatAssetIdempotencyKey()
    captureMutation('创建方案', async () => {
      const created = await schoolCatAssets.createPlan(name, ref, bankDoc, config, idempotencyKey)
      planDetail.value = created
      planName.value = created.display_name
      configDraft.value = copy(config)
    })
  }
}

function renameOrArchive(archive: boolean) {
  if (busy.value) return
  if (tab.value === 'banks' && bankDetail.value) {
    const detail = bankDetail.value
    const changes = archive ? { status: 'ARCHIVED' as const } : { display_name: bankName.value }
    const idempotencyKey = newCatAssetIdempotencyKey()
    captureMutation(archive ? '归档题库' : '重命名题库', async () => {
      bankDetail.value = await schoolCatAssets.updateBank(detail.bank_ref, detail.revision, changes, idempotencyKey)
      bankName.value = bankDetail.value.display_name
    }, async () => { bankDetail.value = await schoolCatAssets.getBank(detail.bank_ref) })
  } else if (planDetail.value) {
    const detail = planDetail.value
    const changes = archive ? { status: 'ARCHIVED' as const } : { display_name: planName.value }
    const idempotencyKey = newCatAssetIdempotencyKey()
    captureMutation(archive ? '归档方案' : '重命名方案', async () => {
      planDetail.value = await schoolCatAssets.updatePlan(detail.plan_ref, detail.revision, changes, idempotencyKey)
      planName.value = planDetail.value.display_name
    }, async () => { planDetail.value = await schoolCatAssets.getPlan(detail.plan_ref) })
  }
}

async function refreshConflict() {
  if (busy.value || !conflictRefresh.value) return
  busy.value = true
  try {
    await conflictRefresh.value()
    pendingIntent.value = null; conflictRefresh.value = null
    error.value = ''; notice.value = '版本信息已更新，编辑内容仍保留。再次保存将创建新的请求。'
  } catch (cause) {
    if (isForbidden(cause)) { clearPrivate(); state.value = 'forbidden'; error.value = '访问权限已变化，已清除本页资产内容。' }
    else error.value = '无法刷新版本信息，请稍后重试。'
  } finally { busy.value = false }
}

function retrySameRequest() {
  const intent = pendingIntent.value
  if (!intent || intent.scope !== scopeKey()) return
  void runMutation(intent.retry, intent.scope)
}

async function inspectBankVersion(reference: string) {
  const token = ++sequence; const scope = scopeKey()
  try {
    const version = await schoolCatAssets.getBankVersion(reference)
    if (!disposed && token === sequence && scope === scopeKey()) selectedBankVersion.value = version
  } catch (cause) { handleLoadFailure(cause, token, scope) }
}

async function inspectPlanVersion(reference: string) {
  clearSavedSimulation(true)
  const token = ++sequence; const scope = scopeKey()
  try {
    const version = await schoolCatAssets.getPlanVersion(reference)
    if (disposed || token !== sequence || scope !== scopeKey() || !hasRole()) return
    const bank = await schoolCatAssets.getBankVersion(version.bank_version_ref)
    if (disposed || token !== sequence || scope !== scopeKey() || !hasRole()) return
    selectedPlanVersion.value = version
    simulationBankVersion.value = bank
    await loadActivationHistory(true)
  } catch (cause) { handleLoadFailure(cause, token, scope) }
}

function changeSimulationBatch(value: string) {
  const batch = Number(value)
  if (batch !== 100 && batch !== 1000) return
  if (simulationBatch.value === batch) return
  clearSavedSimulation(false)
  simulationBatch.value = batch
}

function sameSimulationBasis(left: CatSavedPlanSimulation, right: CatSavedPlanSimulation) {
  return left.plan_version_ref === right.plan_version_ref
    && left.bank_version_ref === right.bank_version_ref
    && left.n_examinees === right.n_examinees
    && left.seed === right.seed
}

function sameSimulationOutput(left: CatSavedPlanSimulation, right: CatSavedPlanSimulation) {
  const metricKeys = Object.keys(left.metrics) as Array<keyof CatSavedPlanSimulation['metrics']>
  const sameMetrics = metricKeys.every((key) => left.metrics[key] === right.metrics[key])
  const leftStops = Object.entries(left.stopping_reason_distribution).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
  const rightStops = Object.entries(right.stopping_reason_distribution).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
  return sameMetrics && JSON.stringify(leftStops) === JSON.stringify(rightStops)
}

async function runSavedSimulation() {
  const planVersion = selectedPlanVersion.value
  const bankVersion = simulationBankVersion.value
  if (!planVersion || !bankVersion || !canRunSavedSimulation.value) return

  const token = ++simulationSequence
  const scope = scopeKey()
  const batch = simulationBatch.value
  const previous = simulationResult.value
  const baseline = previous && previous.plan_version_ref === planVersion.version_ref
    && previous.bank_version_ref === bankVersion.version_ref
    && previous.n_examinees === batch
    && previous.seed === planVersion.config_document.seed ? previous : null
  comparisonBaseline.value = null
  simulationResult.value = null
  simulationError.value = ''
  simulationState.value = 'running'
  try {
    const result = await schoolCatAssets.simulateSavedPlanVersion(
      planVersion.version_ref,
      planVersion.bank_version_ref,
      bankVersion.bank_document,
      planVersion.config_document,
      batch,
    )
    if (disposed || token !== simulationSequence || scope !== scopeKey() || !hasRole()
      || selectedPlanVersion.value?.version_ref !== planVersion.version_ref
      || simulationBankVersion.value?.version_ref !== bankVersion.version_ref
      || simulationBatch.value !== batch) return
    simulationResult.value = result
    comparisonBaseline.value = baseline && sameSimulationBasis(baseline, result) ? baseline : null
    simulationState.value = 'complete'
  } catch (cause) {
    if (disposed || token !== simulationSequence || scope !== scopeKey()) return
    if (isForbidden(cause)) {
      clearPrivate(); state.value = 'forbidden'; error.value = '访问权限已变化，已清除本页资产与模拟结果。'
      simulationState.value = 'blocked'
      return
    }
    const code = errorCode(cause)
    const detail = cause && typeof cause === 'object' && 'message' in cause ? String(cause.message) : ''
    if ((isConflict(cause) || code === 'WORKFLOW_CONFLICT') && detail.includes('synthetic_cat_simulation_busy')) {
      simulationState.value = 'busy'
      simulationError.value = '已有工程模拟正在运行。本次没有排队，请稍后手动重试。'
    } else if (['404', 'HTTP_404', 'RESOURCE_NOT_FOUND', '409', 'HTTP_409', 'WORKFLOW_CONFLICT'].includes(code)) {
      simulationState.value = 'blocked'
      simulationError.value = '此保存版本或关联题库目前不可运行，请刷新方案并选择有效版本。'
    } else {
      simulationState.value = 'error'
      simulationError.value = '本次结果尚未确认。请检查连接状态后手动重新运行。'
    }
  }
}

function changeTab(next: Tab) {
  if (inputLocked.value || tab.value === next) return
  sequence += 1
  clearSelection()
  tab.value = next
}

watch(bankDraft, () => clearSavedSimulation(false), { deep: true })
watch(configDraft, () => clearSavedSimulation(false), { deep: true })

function refresh() { void loadWorkspace() }
watch(scopeKey, (next, previous) => {
  if (next === previous) return
  sequence += 1; clearPrivate()
  state.value = hasRole() ? 'loading' : 'forbidden'
  if (hasRole() && active.value) void loadWorkspace()
})
watch(active, (value) => { if (value) activate() })
onMounted(activate)
onBeforeUnmount(() => { disposed = true; sequence += 1; clearPrivate() })
</script>

<template>
  <section class="asset-workspace" aria-label="合成题库与 CAT 方案资产管理">
    <AppStatusCallout tone="attention" title="仅供工程验证" body="这里保存的是合成题库与CAT配置版本。结构校验不代表心理测量学有效性，也不会启用测评、生成个人结论或发布报告。" />
    <nav class="asset-tabs" aria-label="资产类型">
      <button type="button" :disabled="inputLocked" :aria-pressed="tab === 'banks'" @click="changeTab('banks')">题库</button>
      <button type="button" :disabled="inputLocked" :aria-pressed="tab === 'plans'" @click="changeTab('plans')">CAT 方案</button>
    </nav>
    <div v-if="state === 'loading'" class="asset-state" role="status" aria-busy="true"><RotateCcw class="asset-spin" :size="16" /> 正在读取本校资产…</div>
    <div v-else-if="state === 'forbidden'" class="asset-state asset-state--error" role="alert"><ShieldCheck :size="18" /><div><strong>无法读取资产</strong><p>{{ error || '请切换到本校心理专业账号。' }}</p></div></div>
    <div v-else-if="state === 'unavailable'" class="asset-state asset-state--error" role="alert"><CircleAlert :size="18" /><div><strong>资产暂不可用</strong><p>{{ error }}</p></div><button class="asset-button asset-button--quiet" type="button" @click="refresh">重新读取</button></div>
    <div v-else class="asset-layout">
      <AppCard class="asset-list">
        <header class="asset-heading"><div><p class="asset-kicker">{{ tab === 'banks' ? 'ITEM BANKS' : 'CAT PLANS' }}</p><h2>{{ tab === 'banks' ? '题库' : 'CAT 方案' }}</h2></div><button class="asset-button asset-button--quiet" type="button" :disabled="inputLocked" @click="tab === 'banks' ? startNewBank() : startNewPlan()"><FilePlus2 :size="15" />新建</button></header>
        <p class="asset-help">列表只显示名称、状态和修订号，不包含题目正文或配置参数。</p>
        <ul v-if="resources.length" class="asset-list__items">
          <li v-for="resource in resources" :key="'bank_ref' in resource ? resource.bank_ref : resource.plan_ref">
            <button type="button" class="asset-row" :disabled="inputLocked" :aria-current="(tab === 'banks' ? bankDetail?.bank_ref === ('bank_ref' in resource ? resource.bank_ref : '') : planDetail?.plan_ref === ('plan_ref' in resource ? resource.plan_ref : '')) ? 'true' : undefined" @click="tab === 'banks' ? selectBank(resource as CatBankMetadata) : selectPlan(resource as CatPlanMetadata)">
              <span class="asset-row__main"><strong>{{ resource.display_name }}</strong><small>修订 {{ resource.revision }} · {{ resource.status === 'ACTIVE' ? '有效' : '已归档' }}</small></span><span class="asset-row__chevron">›</span>
            </button>
          </li>
        </ul>
        <p v-else class="asset-empty">还没有{{ tab === 'banks' ? '题库' : '方案' }}。可以从合成模板开始创建。</p>
      </AppCard>

      <AppCard class="asset-editor">
        <template v-if="tab === 'banks' && bankDraft">
          <header class="asset-heading"><div><p class="asset-kicker">{{ bankDetail ? `修订 ${bankDetail.revision}` : 'NEW SYNTHETIC BANK' }}</p><h2>{{ bankDetail ? '编辑题库版本' : '新建题库' }}</h2></div><button class="asset-icon" type="button" aria-label="清除编辑内容" :disabled="inputLocked" @click="clearSelection"><X :size="16" /></button></header>
          <label class="asset-field">题库名称<input v-model="bankName" maxlength="120" :disabled="inputLocked"></label>
          <div class="asset-subheading"><div><h3>题目内容</h3><p>每次保存会生成不可覆盖的新版本。当前题型采用单维GRM结构。</p></div><button class="asset-button asset-button--quiet" type="button" :disabled="inputLocked || bankDraft.items.length >= 100" @click="addItem"><FilePlus2 :size="14" />添加题目</button></div>
          <div class="asset-items">
            <article v-for="(item, index) in bankDraft.items" :key="item.item_id" class="asset-item">
              <header><strong>题目 {{ index + 1 }}</strong><button class="asset-remove" type="button" aria-label="删除题目" :disabled="inputLocked || bankDraft.items.length <= 1" @click="removeItem(index)"><X :size="14" /></button></header>
              <label class="asset-field">题干<textarea v-model="item.stem" rows="2" maxlength="5000" :disabled="inputLocked" /></label>
              <div class="asset-options"><div v-for="(option, optionIndex) in item.response_options" :key="optionIndex" class="asset-option"><label class="asset-field">选项 {{ optionIndex + 1 }}<input :value="option" maxlength="120" :disabled="inputLocked" @input="updateOption(item, optionIndex, ($event.target as HTMLInputElement).value)"></label><label class="asset-field asset-score">计分<input v-model.number="item.scoring[item.response_options[optionIndex]!]" type="number" min="0" :disabled="inputLocked"></label></div></div>
              <div class="asset-params"><label class="asset-field">GRM 区分参数 a<input v-model.number="item.parameters.a" type="number" min="0.000001" step="0.01" :disabled="inputLocked"></label><label v-for="(threshold, thresholdIndex) in item.parameters.thresholds" :key="thresholdIndex" class="asset-field">阈值 {{ thresholdIndex + 1 }}<input v-model.number="item.parameters.thresholds[thresholdIndex]" type="number" step="0.1" :disabled="inputLocked"></label></div>
            </article>
          </div>
          <footer class="asset-actions"><button class="asset-button asset-button--primary" type="button" :disabled="!canSaveBank" @click="saveBank"><Save :size="15" />{{ busy ? '保存中…' : bankDetail ? '保存新版本' : '创建题库' }}</button><button v-if="bankDetail" class="asset-button asset-button--quiet" type="button" :disabled="mutationBlocked" @click="renameOrArchive(false)">保存名称</button><button v-if="bankDetail && bankDetail.status === 'ACTIVE'" class="asset-button asset-button--danger" type="button" :disabled="mutationBlocked" @click="renameOrArchive(true)"><Archive :size="14" />归档</button></footer>
          <section v-if="bankDetail" class="asset-history"><h3><History :size="15" />版本历史</h3><button v-for="version in bankDetail.versions" :key="version.version_ref" type="button" class="asset-history__row" @click="inspectBankVersion(version.version_ref)"><span>版本 {{ version.version_number }} · {{ version.item_count }} 道题</span><time>{{ new Date(version.created_at).toLocaleString('zh-CN') }}</time></button><p v-if="selectedBankVersion" class="asset-history__selected">正在查看 v{{ selectedBankVersion.version_number }} 的题库文档。</p></section>
        </template>

        <template v-else-if="tab === 'plans' && configDraft">
          <header class="asset-heading"><div><p class="asset-kicker">{{ planDetail ? `修订 ${planDetail.revision}` : 'NEW ENGINEERING PLAN' }}</p><h2>{{ planDetail ? '编辑 CAT 方案版本' : '新建 CAT 方案' }}</h2></div><button class="asset-icon" type="button" aria-label="清除编辑内容" :disabled="busy" @click="clearSelection"><X :size="16" /></button></header>
          <label class="asset-field">方案名称<input v-model="planName" maxlength="120" :disabled="inputLocked"></label>
          <label class="asset-field">绑定的题库<select :value="bankVersionRef" :disabled="inputLocked" @change="chooseBankVersion(($event.target as HTMLSelectElement).value)"><option value="">选择本校有效题库版本</option><optgroup v-for="bank in banks.filter((entry) => entry.status === 'ACTIVE')" :key="bank.bank_ref" :label="bank.display_name"><option v-for="entry in availableBankVersions.filter((candidate) => candidate.bank.bank_ref === bank.bank_ref)" :key="entry.version.version_ref" :value="entry.version.version_ref">版本 {{ entry.version.version_number }} · {{ entry.version.item_count }} 道</option></optgroup></select><small v-if="selectedBankVersion">固定绑定：{{ selectedBankVersion.version_number }} · {{ selectedBankDocument?.items.length }} 道合成题</small></label>
          <p v-if="!selectedBankVersion" class="asset-inline-note">请先选择题库版本。可在左侧打开题库并查看版本，再回到这里选择。</p>
          <div class="asset-config-grid">
            <label class="asset-field">估计方法<select v-model="configDraft.estimator" :disabled="inputLocked"><option value="EAP">EAP</option><option value="BM">BM</option></select></label>
            <label class="asset-field">最少题数<input v-model.number="configDraft.min_items" type="number" min="1" max="100" :disabled="inputLocked"></label>
            <label class="asset-field">最多题数<input v-model.number="configDraft.max_items" type="number" min="1" max="100" :disabled="inputLocked"></label>
            <label class="asset-field">标准误停止阈值<input v-model.number="configDraft.se_threshold" type="number" min="0.000001" step="0.01" :disabled="inputLocked"></label>
            <label class="asset-field">初始估计值<input v-model.number="configDraft.initial_theta" type="number" step="0.1" :disabled="inputLocked"></label>
            <label class="asset-field">先验均值<input v-model.number="configDraft.prior_mean" type="number" step="0.1" :disabled="inputLocked"></label>
            <label class="asset-field">先验标准差<input v-model.number="configDraft.prior_sd" type="number" min="0.000001" step="0.1" :disabled="inputLocked"></label>
            <label class="asset-field">随机种子<input v-model.number="configDraft.seed" type="number" min="0" step="1" :disabled="inputLocked"></label>
            <label class="asset-field">优化区间下限<input v-model.number="configDraft.optimization_interval[0]" type="number" step="0.1" :disabled="inputLocked"></label>
            <label class="asset-field">优化区间上限<input v-model.number="configDraft.optimization_interval[1]" type="number" step="0.1" :disabled="inputLocked"></label>
          </div>
          <p class="asset-inline-note">题型GRM、选题MFI、暴露控制和内容平衡按当前工程实现固定。配置只用于合成工程验证。</p>
          <footer class="asset-actions"><button class="asset-button asset-button--primary" type="button" :disabled="!canSavePlan" @click="savePlan"><Save :size="15" />{{ busy ? '保存中…' : planDetail ? '保存方案新版本' : '创建方案' }}</button><button v-if="planDetail" class="asset-button asset-button--quiet" type="button" :disabled="mutationBlocked" @click="renameOrArchive(false)">保存名称</button><button v-if="planDetail && planDetail.status === 'ACTIVE'" class="asset-button asset-button--danger" type="button" :disabled="mutationBlocked" @click="renameOrArchive(true)"><Archive :size="14" />归档</button></footer>
          <section v-if="planDetail" class="asset-history"><h3><History :size="15" />方案版本历史</h3><button v-for="version in planDetail.versions" :key="version.version_ref" type="button" class="asset-history__row" :aria-pressed="selectedPlanVersion?.version_ref === version.version_ref" @click="inspectPlanVersion(version.version_ref)"><span>版本 {{ version.version_number }} · {{ selectedPlanVersion?.version_ref === version.version_ref ? bankVersionLabel(selectedPlanVersion.bank_version_ref) : '查看固定题库版本' }}</span><time>{{ new Date(version.created_at).toLocaleString('zh-CN') }}</time></button><p v-if="selectedPlanVersion" class="asset-history__selected">已选择 {{ planDetail.display_name }} v{{ selectedPlanVersion.version_number }}：绑定 {{ simulationBankLabel }}。</p></section>
          <section v-if="selectedPlanVersion" class="asset-activation" aria-label="合成方案版本启用记录">
            <header><div><h3>用于新任务</h3><p>{{ planDetail?.display_name }} v{{ selectedPlanVersion.version_number }} · {{ simulationBankLabel }}</p></div></header>
            <p class="asset-inline-note">启用仅允许管理员将这个固定版本用于新的合成任务，不代表心理测量学审核或结果发布批准。</p>
            <p v-if="activationState === 'loading'" class="asset-activation__state" role="status" aria-busy="true">正在读取该版本的启用记录…</p>
            <p v-else-if="activationState === 'idle'" class="asset-activation__state">选择方案历史版本后读取启用记录。</p>
            <p v-if="activationNotice" class="asset-activation__success" role="status">{{ activationNotice }}</p>
            <p v-if="activationError" class="asset-activation__error" role="alert">{{ activationError }}</p>
            <div v-if="activationHistory.length" class="asset-activation__list">
              <article v-for="item in activationHistory" :key="item.activation_ref" class="asset-activation__row">
                <div><strong>{{ item.status === 'ACTIVE' ? '当前启用' : '已撤销' }}</strong><span>{{ item.plan_name }} v{{ item.plan_version_number }} · {{ item.bank_name }} v{{ item.bank_version_number }}</span><time>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</time></div>
                <button v-if="item.status === 'ACTIVE'" class="asset-button asset-button--danger" type="button" :disabled="inputLocked" :aria-label="`撤销 ${item.plan_name} v${item.plan_version_number} 的启用`" @click="revokeActivation(item)">{{ activationBusy ? '处理中…' : '撤销启用' }}</button>
              </article>
            </div>
            <div v-if="activationState === 'ready' && !activeActivation && activationHasMore" class="asset-activation__state">请先读取完整历史记录，确认当前启用状态。</div>
            <div v-if="activationState === 'ready' && !activeActivation && !activationHasMore" class="asset-activation__actions">
              <button class="asset-button asset-button--primary" type="button" :disabled="!canCreateActivation" @click="enableSelectedVersion">{{ activationBusy ? '处理中…' : '启用此版本' }}</button>
              <span>管理员之后可在发布新任务时选择此版本。</span>
            </div>
            <div class="asset-activation__actions">
              <button v-if="activationHasMore || activationState === 'error' || activationConflict" class="asset-button asset-button--quiet" type="button" :disabled="activationBusy" @click="loadActivationHistory(activationConflict || activationState === 'error')">{{ activationState === 'loading' ? '读取中…' : activationConflict ? '重新读取并核对' : activationHasMore ? '读取更多记录' : '重新读取' }}</button>
              <button v-if="pendingActivationIntent" class="asset-button asset-button--quiet" type="button" :disabled="activationBusy" @click="retryActivationSameRequest">{{ activationBusy ? '正在重试…' : '使用同一请求重试' }}</button>
            </div>
          </section>
          <section v-if="planDetail" class="asset-simulation" aria-label="已保存 CAT 方案版本的合成工程模拟">
            <header><div><h3>运行已保存版本</h3><p>从上方历史中选择一个版本后，再运行对应的合成工程模拟。</p></div><ShieldCheck :size="17" /></header>
            <p class="asset-inline-note">模拟只读取已保存的方案和题库版本；未保存的当前表单配置不会用于模拟。</p>
            <p v-if="!selectedPlanVersion" class="asset-inline-note">请先选择方案历史版本。</p>
            <template v-else>
              <div class="asset-simulation__binding"><strong>{{ planDetail.display_name }} v{{ selectedPlanVersion.version_number }}</strong><span>题库：{{ simulationBankLabel }}</span><span>配置：{{ selectedPlanVersion.config_document.config_version }} · 种子 {{ selectedPlanVersion.config_document.seed }}</span></div>
              <label class="asset-field asset-simulation__batch">合成样本量<select :value="simulationBatch" :disabled="simulationLocked" @change="changeSimulationBatch(($event.target as HTMLSelectElement).value)"><option :value="100">100</option><option :value="1000">1000</option></select></label>
              <button class="asset-button asset-button--primary" type="button" :disabled="!canRunSavedSimulation" @click="runSavedSimulation">{{ simulationState === 'running' ? '运行中…' : simulationState === 'busy' ? '稍后手动重试' : simulationState === 'error' ? '手动重新运行' : simulationResult ? '再次运行并比较' : '运行已保存版本' }}</button>
              <p v-if="simulationState === 'running'" class="asset-simulation__pending" role="status" aria-busy="true">运行中，较大批次可能需要几分钟。</p>
              <p v-else-if="simulationError" class="asset-simulation__error" role="alert">{{ simulationError }}</p>
              <div v-if="simulationResult" class="asset-simulation__result" role="status">
                <strong>本次汇总 · {{ simulationResult.n_examinees }} 个合成样本</strong>
                <dl><div><dt>偏差</dt><dd>{{ simulationResult.metrics.bias.toFixed(3) }}</dd></div><div><dt>均方根误差</dt><dd>{{ simulationResult.metrics.rmse.toFixed(3) }}</dd></div><div><dt>平均绝对误差</dt><dd>{{ simulationResult.metrics.mae.toFixed(3) }}</dd></div><div><dt>平均题数</dt><dd>{{ simulationResult.metrics.mean_test_length.toFixed(2) }}</dd></div><div><dt>中位题数</dt><dd>{{ simulationResult.metrics.median_test_length.toFixed(2) }}</dd></div><div><dt>平均标准误</dt><dd>{{ simulationResult.metrics.mean_se.toFixed(3) }}</dd></div></dl>
                <p>停止原因计数：<span v-for="(count, reason, index) in simulationResult.stopping_reason_distribution" :key="reason">{{ index ? ' · ' : '' }}{{ stoppingReasonLabel(reason) }} {{ count }}</span></p>
                <p v-if="simulationComparisonText" class="asset-simulation__comparison">{{ simulationComparisonText }}仅在方案版本、题库版本、样本量和种子一致时比较。</p>
              </div>
            </template>
          </section>
        </template>
        <div v-else class="asset-placeholder"><span><ShieldCheck :size="19" /></span><strong>选择或新建{{ tab === 'banks' ? '题库' : 'CAT 方案' }}</strong><p>内容只在当前本校专业账号会话中读取。</p></div>
        <div v-if="error" class="asset-feedback asset-feedback--error" role="alert"><CircleAlert :size="15" /><span>{{ error }}</span><button v-if="pendingIntent" type="button" :disabled="busy" @click="retrySameRequest">使用同一请求重试</button><button v-if="conflictRefresh" type="button" :disabled="busy" @click="refreshConflict">刷新版本信息</button></div>
        <p v-if="notice" class="asset-feedback asset-feedback--success" role="status"><ShieldCheck :size="15" />{{ notice }}</p>
      </AppCard>
    </div>
  </section>
</template>

<style scoped>
.asset-workspace{display:grid;gap:14px;color:var(--color-text-primary)}.asset-tabs{display:flex;gap:7px;padding:4px;border:1px solid #e3ece7;border-radius:11px;background:#f5f9f6;width:max-content}.asset-tabs button{min-height:34px;padding:7px 14px;border:0;border-radius:8px;background:transparent;color:#63766c;font:inherit;font-size:11px;font-weight:700;cursor:pointer}.asset-tabs button[aria-pressed=true]{background:#fff;color:#357c6b;box-shadow:0 1px 3px #203c3014}.asset-layout{display:grid;grid-template-columns:minmax(235px,.7fr) minmax(0,1.6fr);gap:13px;align-items:start}.asset-list,.asset-editor{min-width:0;padding:17px}.asset-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-bottom:12px;border-bottom:1px solid #e8efeb}.asset-heading h2{margin:3px 0 0;font-size:16px;letter-spacing:-.02em}.asset-kicker{margin:0;color:#548275;font-size:9px;font-weight:800;letter-spacing:.08em}.asset-help{margin:12px 0;color:var(--color-text-muted);font-size:10px;line-height:1.6}.asset-list__items{display:grid;gap:6px;margin:0;padding:0;list-style:none}.asset-row{display:flex;width:100%;align-items:center;justify-content:space-between;gap:9px;padding:11px;border:1px solid #e7eee9;border-radius:9px;background:#fff;text-align:left;cursor:pointer}.asset-row[aria-current=true]{border-color:#83ad9b;background:#f0f7f3}.asset-row__main{display:grid;gap:4px;min-width:0}.asset-row strong{overflow:hidden;color:#40574d;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.asset-row small{color:#788a81;font-size:9px}.asset-row__chevron{color:#8ba096;font-size:19px}.asset-empty,.asset-placeholder{padding:25px 12px;color:var(--color-text-muted);font-size:11px;line-height:1.6;text-align:center}.asset-placeholder{display:grid;justify-items:center;gap:7px;min-height:190px;align-content:center}.asset-placeholder span{color:#478675}.asset-placeholder strong{color:#496158;font-size:12px}.asset-placeholder p{margin:0}.asset-button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:35px;padding:8px 11px;border:1px solid transparent;border-radius:8px;font:inherit;font-size:10px;font-weight:750;cursor:pointer}.asset-button:disabled,.asset-icon:disabled{opacity:.5;cursor:not-allowed}.asset-button--quiet{border-color:#dce8e3;background:#fff;color:#4c6c61}.asset-button--primary{background:#357c6b;color:#fff}.asset-button--primary:hover:not(:disabled){background:#286b5a}.asset-button--danger{border-color:#eddfd7;background:#fffaf7;color:#955e45}.asset-icon,.asset-remove{display:grid;width:31px;height:31px;place-items:center;border:1px solid #e1eae5;border-radius:8px;background:#fff;color:#63796f;cursor:pointer}.asset-field{display:grid;gap:5px;min-width:0;color:#52685e;font-size:10px;font-weight:700}.asset-field input,.asset-field textarea,.asset-field select{width:100%;min-width:0;padding:9px 10px;border:1px solid #dfe9e3;border-radius:8px;background:#fff;color:#344b41;font:inherit;font-size:11px;font-weight:500;outline:none}.asset-field input:focus,.asset-field textarea:focus,.asset-field select:focus{border-color:#74a692;box-shadow:0 0 0 3px #438e7b1c}.asset-field input:disabled,.asset-field textarea:disabled,.asset-field select:disabled{background:#f5f8f6;color:#819087}.asset-field textarea{resize:vertical;line-height:1.6}.asset-field small{color:#7a8b82;font-size:9px;font-weight:500}.asset-editor>.asset-field{margin:13px 0}.asset-subheading{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:18px 0 10px}.asset-subheading h3,.asset-history h3{display:flex;align-items:center;gap:6px;margin:0;color:#405b50;font-size:12px}.asset-subheading p{margin:4px 0 0;color:#7a8a82;font-size:9px;line-height:1.5}.asset-items{display:grid;gap:9px}.asset-item{display:grid;gap:10px;padding:12px;border:1px solid #e5ece8;border-radius:10px;background:#fbfdfb}.asset-item>header{display:flex;align-items:center;justify-content:space-between;color:#4d695d;font-size:10px}.asset-remove{width:26px;height:26px}.asset-options{display:grid;gap:6px}.asset-option{display:grid;grid-template-columns:minmax(0,1fr) 95px;gap:8px}.asset-params{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.asset-score input{text-align:right}.asset-config-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}.asset-inline-note{margin:10px 0;padding:10px 11px;border-left:3px solid #88aa99;border-radius:0 7px 7px 0;background:#f3f8f5;color:#64786e;font-size:10px;line-height:1.6}.asset-actions{display:flex;flex-wrap:wrap;gap:7px;margin:15px 0;padding-top:12px;border-top:1px solid #e9efeb}.asset-history{display:grid;gap:7px;margin-top:18px;padding-top:13px;border-top:1px solid #e9efeb}.asset-history h3{margin-bottom:2px}.asset-history__row{display:flex;justify-content:space-between;gap:10px;padding:8px 9px;border:1px solid #e7eee9;border-radius:7px;background:#fff;color:#4c6258;text-align:left;font:inherit;font-size:9px;cursor:pointer}.asset-history__row time{color:#85938c;white-space:nowrap}.asset-history__selected{margin:2px 0;color:#71857a;font-size:9px}.asset-feedback{display:flex;align-items:center;gap:8px;margin-top:12px;padding:10px;border-radius:8px;font-size:10px;line-height:1.5}.asset-feedback--error{border:1px solid #efdfd4;background:#fff9f4;color:#805e4b}.asset-feedback--success{border:1px solid #dcebe2;background:#f3f9f5;color:#4d7564}.asset-feedback button{margin-left:auto;padding:6px 8px;border:1px solid #e4d6ca;border-radius:6px;background:#fff;color:#795b48;font:inherit;font-size:9px;white-space:nowrap;cursor:pointer}.asset-state{display:flex;align-items:center;gap:9px;min-height:54px;padding:13px;border:1px solid #e3ece7;border-radius:10px;background:#f7faf8;color:#52685e;font-size:11px}.asset-state--error{align-items:flex-start;border-color:#e9e2d5;background:#fcfaf5;color:#716348}.asset-state p{margin:3px 0 0;font-size:10px;line-height:1.5}.asset-state .asset-button{margin-left:auto}.asset-spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.asset-activation{display:grid;gap:9px;margin-top:14px;padding:14px;border:1px solid #e3eae6;border-radius:10px;background:#fafcfb}.asset-activation>header h3{margin:0;color:#405b50;font-size:12px}.asset-activation>header p,.asset-activation__state,.asset-activation__actions span{margin:4px 0 0;color:#788980;font-size:9px;line-height:1.5}.asset-activation__list{display:grid;gap:7px}.asset-activation__row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px;border:1px solid #e7eee9;border-radius:8px;background:#fff}.asset-activation__row>div{display:grid;gap:3px}.asset-activation__row strong{color:#486a5d;font-size:10px}.asset-activation__row span,.asset-activation__row time{color:#788980;font-size:9px}.asset-activation__actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.asset-activation__success,.asset-activation__error{margin:0;font-size:10px;line-height:1.5}.asset-activation__success{color:#39715a}.asset-activation__error{color:#805e4b}
.asset-simulation{display:grid;gap:10px;margin-top:16px;padding:14px;border:1px solid #dfeae4;border-radius:10px;background:#f8fbf9}.asset-simulation>header{display:flex;align-items:center;justify-content:space-between;color:#43816f}.asset-simulation h3{margin:0;color:#405b50;font-size:12px}.asset-simulation>header p{margin:4px 0 0;color:#788980;font-size:9px;line-height:1.5}.asset-simulation__binding{display:grid;gap:4px;padding:9px 10px;border-radius:7px;background:#fff;color:#63766c;font-size:9px}.asset-simulation__binding strong{color:#3d5e50;font-size:10px}.asset-simulation__batch{max-width:200px}.asset-simulation__pending,.asset-simulation__error{margin:0;color:#6e7e75;font-size:10px;line-height:1.5}.asset-simulation__error{color:#805e4b}.asset-simulation__result{display:grid;gap:9px;padding:11px;border:1px solid #dcebe2;border-radius:8px;background:#fff;color:#52685e;font-size:9px}.asset-simulation__result>strong{color:#3f6e5a;font-size:10px}.asset-simulation__result dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin:0}.asset-simulation__result dl div{padding:7px;border-radius:6px;background:#f5f8f6}.asset-simulation__result dt{color:#788980}.asset-simulation__result dd{margin:4px 0 0;color:#3b584a;font-size:11px;font-weight:750}.asset-simulation__result p{margin:0;line-height:1.5}.asset-simulation__comparison{color:#43816f!important}
@media(max-width:820px){.asset-layout{grid-template-columns:1fr}.asset-list__items{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.asset-list,.asset-editor{padding:13px}.asset-list__items{grid-template-columns:1fr}.asset-params{grid-template-columns:repeat(2,minmax(0,1fr))}.asset-option{grid-template-columns:minmax(0,1fr) 76px}.asset-history__row{align-items:flex-start;flex-direction:column}.asset-feedback{flex-wrap:wrap}.asset-feedback button{margin-left:0}}
@media(prefers-reduced-motion:reduce){.asset-spin{animation:none}}
</style>
