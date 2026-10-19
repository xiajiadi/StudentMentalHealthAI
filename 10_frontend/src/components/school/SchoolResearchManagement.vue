<script setup lang="ts">
/* global AbortController */

import { computed, ref, watch } from 'vue'
import { BookOpenCheck, CalendarClock, RefreshCw, ShieldCheck } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import type {
  ResearchProfileCandidate,
  ResearchProfileSimulationReceipt,
  ResearchProfileVersion,
  ResearchTaskBindingOption,
  ResearchTaskPublicationReceipt,
  SchoolClass,
} from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'

const props = defineProps<{ mode: 'specialist' | 'admin' }>()
type LoadState = 'loading' | 'ready' | 'error' | 'unavailable'

const session = useSessionStore()
const scopeKey = computed(() => [
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
].join('|'))
const state = ref<LoadState>('loading')
const pending = ref('')
const errorMessage = ref('')
const notice = ref('')
const requestGeneration = ref(0)
const retryKeys = new Map<string, { fingerprint: string; key: string }>()
let activeGetController: AbortController | null = null

const abortActiveGet = () => {
  activeGetController?.abort()
  activeGetController = null
}

const newGetController = () => {
  abortActiveGet()
  const controller = new AbortController()
  activeGetController = controller
  return controller
}

const isCurrentRequest = (generation: number, scope = scopeKey.value) =>
  generation === requestGeneration.value && scope === scopeKey.value

const profiles = ref<ResearchProfileCandidate[]>([])
const selectedProfileRef = ref('')
const versionNumber = ref('')
const registeredVersions = ref<ResearchProfileVersion[]>([])
const selectedRegisteredVersionNumber = ref<number | null>(null)
const versionsState = ref<LoadState>('loading')
const versionsError = ref('')
const versionsTotal = ref(0)
const versionsNextOffset = ref<number | null>(null)
const enabledReceipt = ref<ResearchProfileSimulationReceipt | null>(null)
const selectedProfile = computed(() => profiles.value.find((item) => item.profile_ref === selectedProfileRef.value) ?? null)
const selectedRegisteredVersion = computed(() => registeredVersions.value.find(
  (item) => item.version_number === selectedRegisteredVersionNumber.value,
) ?? null)
const parsedNewVersionNumber = computed(() => /^\d+$/.test(versionNumber.value) ? Number(versionNumber.value) : null)
const canImportNewVersion = computed(() => Boolean(
  selectedProfile.value
  && versionsState.value === 'ready'
  && parsedNewVersionNumber.value !== null
  && Number.isSafeInteger(parsedNewVersionNumber.value)
  && parsedNewVersionNumber.value > 0
  && !registeredVersions.value.some((item) => item.version_number === parsedNewVersionNumber.value),
))
const canEnableSelected = computed(() => Boolean(
  selectedProfile.value
  && selectedRegisteredVersion.value?.rights_status === 'PENDING'
  && selectedRegisteredVersion.value.execution_status === 'CANDIDATE_RESEARCH_ONLY'
  && selectedRegisteredVersion.value.use_eligibility === 'RECHECK_REQUIRED'
))

const classes = ref<SchoolClass[]>([])
const bindings = ref<ResearchTaskBindingOption[]>([])
const selectedClassRef = ref('')
const selectedBindingChoice = ref('')
const opensAt = ref('')
const dueAt = ref('')
const taskRef = ref('')
const publicationReceipt = ref<ResearchTaskPublicationReceipt | null>(null)
const bindingChoiceKey = (item: ResearchTaskBindingOption) =>
  JSON.stringify([item.binding_ref, item.profile_version_number, item.profile_ref])
const selectedBinding = computed(() => bindings.value.find((item) => bindingChoiceKey(item) === selectedBindingChoice.value) ?? null)
const activeClasses = computed(() => classes.value.filter((item) => item.status === 'ACTIVE' || item.status === 'active'))

const instrumentLabel = (instrumentId: string, populationScope = '') => {
  const identity = `${instrumentId} ${populationScope}`.toUpperCase()
  if (identity.includes('PROMIS') && identity.includes('ANXIETY')) return 'PROMIS 儿童青少年焦虑，8 题研究子集'
  if (identity.includes('PROMIS') && (identity.includes('DEPRESS') || identity.includes('DEPRESSION'))) return 'PROMIS 儿童青少年抑郁症状研究资料'
  if (identity.includes('NHANES') && (identity.includes('DPQ') || identity.includes('PHQ'))) return 'NHANES 成人抑郁症状问卷（P_DPQ）'
  if (identity.includes('SAPA') && (identity.includes('EXTRAVERSION') || identity.includes('IPIP'))) return 'SAPA 外向性公开作答研究子集'
  return '公开研究资料'
}

const populationLabel = (populationScope: string | null | undefined, instrumentId = '') => {
  const identity = `${instrumentId} ${populationScope ?? ''}`.toUpperCase()
  if (identity.includes('PROMIS') && (identity.includes('8_17') || identity.includes('8–17') || identity.includes('8-17'))) {
    return '美国 8–17 岁儿童自评研究样本'
  }
  if (identity.includes('PROMIS') && identity.includes('CHILD')) return '美国儿童自评研究样本'
  if (identity.includes('NHANES') && (identity.includes('ADULT') || identity.includes('18'))) return '美国成人公开调查样本'
  if (identity.includes('SAPA')) return 'SAPA 网络自愿参与者'
  return '人群范围以来源记录为准'
}

const rightsLabel = (status: string) => ({
  PENDING: '来源权利待核验', VERIFIED: '来源权利记录显示已核验', REVOKED: '来源权利已撤销',
}[status] ?? '状态待确认')

const executionLabel = (status: string) => ({
  CANDIDATE_RESEARCH_ONLY: '待核验仿真资格',
  SIMULATION_ENABLED: '已登记限期仿真资格',
  DISABLED: '已停用',
}[status] ?? '状态待确认')

const candidateStateLabel = (status: ResearchProfileCandidate['catalog_state']) => ({
  REGISTRY_CANDIDATE: '来源候选',
  IMPORTED_CANDIDATE: '候选版本已登记',
  EXISTING_CANDIDATE: '候选版本已存在',
  IDEMPOTENT_REPLAY: '上次请求已完成',
}[status])

const publicationClassLabel = computed(() => {
  const publishedClassRef = publicationReceipt.value?.class_ref
  if (!publishedClassRef) return '已发布班级'
  return classes.value.find((item) => item.class_ref === publishedClassRef)?.display_name || '已发布班级'
})

const idempotencyKey = (prefix: string, body: unknown): string => {
  const fingerprint = JSON.stringify(body)
  const existing = retryKeys.get(prefix)
  if (existing?.fingerprint === fingerprint) return existing.key
  const uuid = globalThis.crypto?.randomUUID?.()
  if (!uuid) throw new Error('此浏览器无法生成安全的请求编号。请更新浏览器后重试。')
  const key = `${prefix}-${uuid}`
  retryKeys.set(prefix, { fingerprint, key })
  return key
}

const clearIdempotencyKey = (prefix: string) => retryKeys.delete(prefix)

const safeError = (cause: unknown, fallback: string) => {
  const code = typeof cause === 'object' && cause !== null && 'code' in cause
    ? String(cause.code).toLowerCase()
    : ''
  if (code.includes('auth_session_expired') || code.includes('auth_session_revoked')) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前账号暂时没有此项操作权限。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '所选资料或班级已不可用，请刷新目录。'
  if (code === 'workflow_conflict' || code === 'conflict' || code === '409') return '服务端状态已变化，请刷新目录后确认当前资格。'
  if (code === 'dependency_unavailable' || code === 'research_service_unavailable') return '研究服务当前未配置或不可用；没有使用演示数据代替。'
  if (code === 'csrf_failed') return '安全令牌已失效，请刷新页面后重试。'
  return fallback
}

const loadVersions = async (profileRef: string, generation: number, append = false, scope = scopeKey.value) => {
  if (props.mode !== 'specialist' || !isCurrentRequest(generation, scope)) return
  const api = frontendApi.listResearchProfileVersions
  if (!api) {
    versionsState.value = 'unavailable'
    versionsError.value = '当前运行环境未提供已登记版本目录；不会推测资料状态。'
    if (!append) registeredVersions.value = []
    return
  }
  if (!append) {
    registeredVersions.value = []
    selectedRegisteredVersionNumber.value = null
    versionsTotal.value = 0
    versionsNextOffset.value = null
    versionsError.value = ''
    versionsState.value = 'loading'
  }
  const controller = newGetController()
  versionsState.value = 'loading'
  try {
    const result = await api(profileRef, {
      limit: 30,
      offset: append ? (versionsNextOffset.value ?? registeredVersions.value.length) : 0,
      signal: controller.signal,
    })
    if (!isCurrentRequest(generation, scope) || controller.signal.aborted) return
    const incoming = result.data.items
    const knownVersions = new Set(registeredVersions.value.map((item) => item.version_number))
    registeredVersions.value = append
      ? [...registeredVersions.value, ...incoming.filter((item) => !knownVersions.has(item.version_number))]
      : incoming
    versionsTotal.value = result.data.total
    versionsNextOffset.value = result.data.next_offset
    if (!registeredVersions.value.some((item) => item.version_number === selectedRegisteredVersionNumber.value)) {
      selectedRegisteredVersionNumber.value = registeredVersions.value[0]?.version_number ?? null
    }
    versionsState.value = 'ready'
  } catch (cause) {
    if (!isCurrentRequest(generation, scope) || controller.signal.aborted) return
    versionsState.value = 'error'
    versionsError.value = safeError(cause, '暂时无法读取服务端已登记版本。')
  } finally {
    if (activeGetController === controller) activeGetController = null
  }
}

const loadMoreVersions = () => {
  if (!selectedProfile.value || versionsNextOffset.value === null || versionsState.value === 'loading') return
  void loadVersions(selectedProfile.value.profile_ref, requestGeneration.value, true)
}

const load = async () => {
  const generation = ++requestGeneration.value
  const scope = scopeKey.value
  abortActiveGet()
  pending.value = ''
  errorMessage.value = ''
  notice.value = ''

  if (props.mode === 'specialist') {
    profiles.value = []
    registeredVersions.value = []
    versionsState.value = 'loading'
    if (!frontendApi.listResearchProfileCatalog) {
      state.value = 'unavailable'
      errorMessage.value = '当前运行环境未提供研究资料目录；页面不会显示虚构候选。'
      return
    }
    state.value = 'loading'
    const controller = newGetController()
    try {
      const result = await frontendApi.listResearchProfileCatalog({ signal: controller.signal })
      if (!isCurrentRequest(generation, scope) || controller.signal.aborted) return
      const previousSelection = selectedProfileRef.value
      profiles.value = result.data
      if (!profiles.value.some((item) => item.profile_ref === selectedProfileRef.value)) {
        selectedProfileRef.value = profiles.value[0]?.profile_ref ?? ''
      }
      state.value = 'ready'
      if (selectedProfileRef.value && selectedProfileRef.value === previousSelection) {
        void loadVersions(selectedProfileRef.value, generation, false, scope)
      }
    } catch (cause) {
      if (!isCurrentRequest(generation, scope) || controller.signal.aborted) return
      state.value = 'error'
      errorMessage.value = safeError(cause, '暂时无法读取研究资料候选。')
    } finally {
      if (activeGetController === controller) activeGetController = null
    }
    return
  }

  classes.value = []
  bindings.value = []
  if (!frontendApi.listSchoolClasses || !frontendApi.listResearchTaskCatalog) {
    state.value = 'unavailable'
    errorMessage.value = '当前运行环境未提供学校研究任务服务；页面不会显示虚构班级或绑定。'
    return
  }
  state.value = 'loading'
  const controller = newGetController()
  try {
    const [classResult, bindingResult] = await Promise.all([
      frontendApi.listSchoolClasses({ signal: controller.signal }),
      frontendApi.listResearchTaskCatalog({ signal: controller.signal }),
    ])
    if (!isCurrentRequest(generation, scope) || controller.signal.aborted) return
    classes.value = classResult.data
    bindings.value = bindingResult.data
    if (!activeClasses.value.some((item) => item.class_ref === selectedClassRef.value)) {
      selectedClassRef.value = activeClasses.value[0]?.class_ref ?? ''
    }
    if (!bindings.value.some((item) => bindingChoiceKey(item) === selectedBindingChoice.value)) {
      selectedBindingChoice.value = bindings.value[0] ? bindingChoiceKey(bindings.value[0]) : ''
    }
    if (!taskRef.value) taskRef.value = newTaskRef()
    state.value = 'ready'
  } catch (cause) {
    if (!isCurrentRequest(generation, scope) || controller.signal.aborted) return
    state.value = 'error'
    errorMessage.value = safeError(cause, '暂时无法读取本校班级和可用研究绑定。')
  } finally {
    if (activeGetController === controller) activeGetController = null
  }
}

const refresh = () => { if (!pending.value) void load() }

const importSelectedProfile = async () => {
  if (!selectedProfile.value || pending.value || !frontendApi.importResearchProfile) return
  const newVersionNumber = parsedNewVersionNumber.value
  if (!canImportNewVersion.value || newVersionNumber === null) {
    errorMessage.value = '请输入尚未登记的正整数版本号；已有版本请从上方列表选择。'
    return
  }
  const generation = requestGeneration.value
  const scope = scopeKey.value
  pending.value = 'import-profile'
  errorMessage.value = ''
  notice.value = ''
  enabledReceipt.value = null
  try {
    const selectedRef = selectedProfile.value.profile_ref
    await frontendApi.importResearchProfile(
      selectedRef,
      newVersionNumber,
      idempotencyKey('research-profile-import', {
        profile_ref: selectedRef,
        version_number: newVersionNumber,
      }),
    )
    if (!isCurrentRequest(generation, scope)) return
    clearIdempotencyKey('research-profile-import')
    versionNumber.value = ''
    await loadVersions(selectedRef, generation, false, scope)
    if (!isCurrentRequest(generation, scope)) return
    notice.value = '候选版本已登记。请选择已登记版本，再核验研究仿真资格；实际使用与专业批准仍按相应范围审核。'
  } catch (cause) {
    if (!isCurrentRequest(generation, scope)) return
    errorMessage.value = safeError(cause, '候选资料导入没有完成，请核对版本号后重试。')
  } finally {
    if (generation === requestGeneration.value) pending.value = ''
  }
}

const enableSelectedProfile = async () => {
  if (!selectedProfile.value || !selectedRegisteredVersion.value || !canEnableSelected.value || pending.value || !frontendApi.enableResearchProfileSimulation) return
  const generation = requestGeneration.value
  const scope = scopeKey.value
  pending.value = 'enable-profile'
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await frontendApi.enableResearchProfileSimulation(
      selectedProfile.value.profile_ref,
      selectedRegisteredVersion.value.version_number,
      idempotencyKey('research-profile-simulation', {
        profile_ref: selectedProfile.value.profile_ref,
        version_number: selectedRegisteredVersion.value.version_number,
      }),
    )
    if (!isCurrentRequest(generation, scope)) return
    clearIdempotencyKey('research-profile-simulation')
    enabledReceipt.value = result.data
    await loadVersions(selectedProfile.value.profile_ref, generation, false, scope)
    if (!isCurrentRequest(generation, scope)) return
    notice.value = '服务端已登记限期研究仿真资格；每次实际使用仍由服务端重新核验。临床、伦理、心理测量学及正式发布审批均未获批准。'
  } catch (cause) {
    if (!isCurrentRequest(generation, scope)) return
    errorMessage.value = safeError(cause, '研究仿真资格没有启用；请刷新候选并确认服务端策略仍有效。')
  } finally {
    if (generation === requestGeneration.value) pending.value = ''
  }
}

const newTaskRef = () => {
  const uuid = globalThis.crypto?.randomUUID?.()
  return uuid ? `TASK_R_${uuid.replaceAll('-', '')}` : ''
}

const localDateTimeToIso = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

const publishTask = async () => {
  if (!selectedBinding.value || !selectedClassRef.value || pending.value || !frontendApi.publishResearchTask) return
  const opens = localDateTimeToIso(opensAt.value)
  const due = localDateTimeToIso(dueAt.value)
  if (!opens || !due || new Date(due).getTime() <= new Date(opens).getTime()) {
    errorMessage.value = '请设置有效的开放时间和晚于开放时间的截止时间。'
    return
  }
  if (!taskRef.value.trim()) taskRef.value = newTaskRef()
  if (!taskRef.value) {
    errorMessage.value = '此浏览器无法生成安全的任务编号，请更新浏览器后重试。'
    return
  }
  const generation = requestGeneration.value
  const scope = scopeKey.value
  pending.value = 'publish-task'
  errorMessage.value = ''
  notice.value = ''
  try {
    const request = {
      class_ref: selectedClassRef.value,
      task_ref: taskRef.value,
      binding_ref: selectedBinding.value.binding_ref,
      profile_version_number: selectedBinding.value.profile_version_number,
      opens_at: opens,
      due_at: due,
    }
    const result = await frontendApi.publishResearchTask(
      request,
      idempotencyKey('research-task-publish', request),
    )
    if (!isCurrentRequest(generation, scope)) return
    clearIdempotencyKey('research-task-publish')
    publicationReceipt.value = result.data
    taskRef.value = newTaskRef()
    notice.value = `研究任务已发布，共 ${result.data.published_enrollment_count} 项报名，仅用于历史公开作答回放。正式使用仍须相应专业批准。`
  } catch (cause) {
    if (!isCurrentRequest(generation, scope)) return
    errorMessage.value = safeError(cause, '研究任务没有发布；请刷新目录并核对时间窗口。')
  } finally {
    if (generation === requestGeneration.value) pending.value = ''
  }
}

watch([() => props.mode, scopeKey], () => {
  requestGeneration.value += 1
  abortActiveGet()
  retryKeys.clear()
  profiles.value = []
  classes.value = []
  bindings.value = []
  selectedProfileRef.value = ''
  selectedClassRef.value = ''
  selectedBindingChoice.value = ''
  opensAt.value = ''
  dueAt.value = ''
  versionNumber.value = ''
  registeredVersions.value = []
  selectedRegisteredVersionNumber.value = null
  versionsState.value = 'loading'
  versionsError.value = ''
  versionsTotal.value = 0
  versionsNextOffset.value = null
  taskRef.value = ''
  enabledReceipt.value = null
  publicationReceipt.value = null
  void load()
}, { immediate: true })

watch(selectedProfileRef, (profileRef) => {
  enabledReceipt.value = null
  registeredVersions.value = []
  selectedRegisteredVersionNumber.value = null
  versionsError.value = ''
  if (!profileRef || props.mode !== 'specialist') {
    versionsState.value = 'ready'
    versionsTotal.value = 0
    versionsNextOffset.value = null
    versionNumber.value = ''
    return
  }
  versionNumber.value = ''
  void loadVersions(profileRef, requestGeneration.value)
})
</script>

<template>
  <section class="research-management" :aria-label="mode === 'specialist' ? '研究资料候选管理' : '研究班级任务管理'">
    <AppStatusCallout
      tone="attention"
      title="仅限隔离研究仿真"
      body="此流程只在隔离环境中回放经服务端固定的公开历史作答。资料和任务尚未获得临床、伦理、心理测量学或正式发布批准，不可用于真实个案、诊断或学校生产决策。"
    />

    <AppCard class="research-panel">
      <div class="research-panel__heading">
        <span class="research-panel__icon"><BookOpenCheck :size="19" aria-hidden="true" /></span>
        <div>
          <span class="research-panel__eyebrow">{{ mode === 'specialist' ? 'PSYCHOLOGICAL SPECIALIST' : 'SCHOOL ADMIN' }}</span>
          <h2>{{ mode === 'specialist' ? '公开研究资料候选' : '公开研究班级任务' }}</h2>
          <p>{{ mode === 'specialist' ? '从服务端目录导入指定版本；仿真资格由服务端权利与研究策略校验。' : '仅能选择服务端列出的研究绑定和本校有效班级。' }}</p>
        </div>
        <AppButton class="research-refresh" variant="secondary" size="sm" :disabled="state === 'loading' || pending !== ''" @click="refresh">
          <RefreshCw :size="14" aria-hidden="true" />刷新目录
        </AppButton>
      </div>

      <div v-if="state === 'loading'" class="research-message" role="status">正在读取服务端目录…</div>
      <div v-else-if="state === 'unavailable' || state === 'error'" class="research-message research-message--error" role="status">
        {{ errorMessage || '服务端目录当前不可读取。' }}
      </div>

      <template v-else-if="mode === 'specialist'">
        <div class="research-form">
          <label for="research-profile">服务端资料候选</label>
          <select id="research-profile" v-model="selectedProfileRef" :disabled="pending !== '' || profiles.length === 0">
            <option value="" disabled>选择一个候选资料</option>
            <option v-for="profile in profiles" :key="profile.profile_ref" :value="profile.profile_ref">
              {{ instrumentLabel(profile.instrument_id, profile.source_population_scope ?? '') }}，{{ populationLabel(profile.source_population_scope, profile.instrument_id) }}，{{ candidateStateLabel(profile.catalog_state) }}
            </option>
          </select>
          <p v-if="selectedProfile" class="research-form__hint">
            {{ instrumentLabel(selectedProfile.instrument_id, selectedProfile.source_population_scope ?? '') }}；{{ populationLabel(selectedProfile.source_population_scope, selectedProfile.instrument_id) }}。来源状态：{{ rightsLabel(selectedRegisteredVersion?.rights_status ?? selectedProfile.rights_status) }}；{{ executionLabel(selectedRegisteredVersion?.execution_status ?? 'CANDIDATE_RESEARCH_ONLY') }}；尚未批准正式发布或运营使用。
          </p>

          <label for="research-profile-registered-version">服务端已登记版本</label>
          <select id="research-profile-registered-version" v-model.number="selectedRegisteredVersionNumber" :disabled="pending !== '' || registeredVersions.length === 0 || versionsState === 'loading'">
            <option :value="null" disabled>选择已登记版本</option>
            <option v-for="version in registeredVersions" :key="version.version_number" :value="version.version_number">
              v{{ version.version_number }}，{{ rightsLabel(version.rights_status) }}，{{ executionLabel(version.execution_status) }}
            </option>
          </select>
          <div v-if="versionsState === 'loading'" class="research-message" role="status">正在读取已登记版本…</div>
          <div v-else-if="versionsState === 'unavailable' || versionsState === 'error'" class="research-message research-message--error" role="status">
            {{ versionsError || '已登记版本目录当前不可读取。' }}
          </div>
          <p v-if="selectedRegisteredVersion" class="research-form__hint">
            {{ instrumentLabel(selectedRegisteredVersion.instrument_id, selectedRegisteredVersion.source_population_scope) }}，{{ populationLabel(selectedRegisteredVersion.source_population_scope, selectedRegisteredVersion.instrument_id) }}，{{ rightsLabel(selectedRegisteredVersion.rights_status) }}，{{ executionLabel(selectedRegisteredVersion.execution_status) }}。实际使用由服务端重新核验。
          </p>
          <AppButton v-if="versionsNextOffset !== null" variant="secondary" size="sm" :disabled="versionsState === 'loading' || pending !== ''" @click="loadMoreVersions">
            加载更多已登记版本（{{ registeredVersions.length }} / {{ versionsTotal }}）
          </AppButton>
          <div class="research-actions">
            <AppButton variant="secondary" :loading="pending === 'enable-profile'" :disabled="pending !== '' || !canEnableSelected" @click="enableSelectedProfile">
              <ShieldCheck :size="15" aria-hidden="true" />核验并登记限期仿真资格
            </AppButton>
          </div>
          <p class="research-form__hint">版本登记状态不等于当前可使用许可；每次实际使用仍由服务端核验。已启用、停用或撤销的版本不能通过此页面重新激活。</p>
        </div>

        <form class="research-form research-form--new-version" @submit.prevent="importSelectedProfile">
          <h3>登记新的候选版本</h3>
          <label for="research-profile-version">新版本号</label>
          <input id="research-profile-version" v-model="versionNumber" type="number" min="1" step="1" required :disabled="pending !== '' || !selectedProfile || versionsState !== 'ready'">
          <p class="research-form__hint">请输入未登记的正整数版本号。已登记版本请在上方选择并查看服务端状态。</p>
          <AppButton type="submit" :loading="pending === 'import-profile'" :disabled="pending !== '' || !canImportNewVersion">
            <BookOpenCheck :size="15" aria-hidden="true" />登记候选版本
          </AppButton>
        </form>
        <div v-if="state === 'ready' && profiles.length === 0" class="research-message">服务端当前没有可导入的候选资料。</div>
        <div v-if="enabledReceipt" class="research-receipt" role="status">
          <strong>服务端已登记限期仿真资格，v{{ enabledReceipt.version_number }}</strong>
          <span>有效期至 {{ new Date(enabledReceipt.policy_expires_at).toLocaleString('zh-CN') }}；实际使用仍由服务端重新核验。</span>
          <span>临床 / 伦理 / 心理测量学批准：均未授予</span>
        </div>
      </template>

      <template v-else>
        <div v-if="bindings.length === 0" class="research-message">服务端当前没有列出公开研究绑定。请先由心理老师完成候选版本核验流程。</div>
        <form v-else class="research-form" @submit.prevent="publishTask">
          <label for="research-class">本校有效班级</label>
          <select id="research-class" v-model="selectedClassRef" :disabled="pending !== '' || activeClasses.length === 0">
            <option value="" disabled>选择班级</option>
            <option v-for="item in activeClasses" :key="item.class_ref" :value="item.class_ref">
              {{ item.display_name || `班级 ${item.class_ref.slice(-6)}` }}，{{ item.active_student_count }} 名在册学生
            </option>
          </select>
          <label for="research-binding">服务端当前列出的研究绑定</label>
          <select id="research-binding" v-model="selectedBindingChoice" :disabled="pending !== ''">
            <option value="" disabled>选择绑定</option>
            <option v-for="binding in bindings" :key="bindingChoiceKey(binding)" :value="bindingChoiceKey(binding)">
              {{ instrumentLabel(binding.instrument_id, binding.source_population_scope) }}，v{{ binding.profile_version_number }}，{{ populationLabel(binding.source_population_scope, binding.instrument_id) }}
            </option>
          </select>
          <p v-if="selectedBinding" class="research-form__hint">
            {{ instrumentLabel(selectedBinding.instrument_id, selectedBinding.source_population_scope) }}，{{ populationLabel(selectedBinding.source_population_scope, selectedBinding.instrument_id) }}，已登记版本 v{{ selectedBinding.profile_version_number }}，历史公开作答研究回放，未批准正式发布。实际使用仍由服务端核验。
          </p>
          <label for="research-task-ref">系统生成的任务编号</label>
          <input id="research-task-ref" :value="taskRef" type="text" readonly aria-readonly="true" :disabled="pending !== ''">
          <p class="research-form__hint">编号由系统生成并随任务保存，无需手动填写。</p>
          <div class="research-form__grid research-form__grid--dates">
            <label for="research-opens">开放时间</label>
            <input id="research-opens" v-model="opensAt" type="datetime-local" required :disabled="pending !== ''">
            <label for="research-due">截止时间</label>
            <input id="research-due" v-model="dueAt" type="datetime-local" required :disabled="pending !== ''">
          </div>
          <p class="research-form__hint">服务端按发布时有效的班级报名建立内部样本映射；此处不显示作答记录或映射编号。</p>
          <AppButton type="submit" :loading="pending === 'publish-task'" :disabled="pending !== '' || !selectedClassRef || !selectedBinding">
            <CalendarClock :size="15" aria-hidden="true" />发布研究仿真任务
          </AppButton>
        </form>
        <div v-if="activeClasses.length === 0" class="research-message">本校没有可供选择的有效班级；没有创建或填充班级数据。</div>
        <div v-if="publicationReceipt" class="research-receipt" role="status">
          <strong>研究任务已由服务端发布</strong>
          <span>{{ publicationClassLabel }}，{{ instrumentLabel(publicationReceipt.instrument_id, publicationReceipt.source_population_scope) }}，已建立 {{ publicationReceipt.published_enrollment_count }} 条报名记录</span>
          <span>公开历史作答回放，研究仿真，未批准发布</span>
        </div>
      </template>

      <p v-if="errorMessage && state === 'ready'" class="research-message research-message--error" role="alert">{{ errorMessage }}</p>
      <p v-if="notice" class="research-message research-message--success" role="status">{{ notice }}</p>
    </AppCard>
  </section>
</template>

<style scoped>
.research-management { display: grid; gap: 13px; margin-top: 15px; }
.research-panel { display: grid; gap: 16px; padding: 20px; }
.research-panel__heading { display: flex; align-items: flex-start; gap: 12px; }
.research-panel__icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 11px; color: #388576; background: #e8f4ef; }
.research-panel__heading > div { min-width: 0; }
.research-panel__eyebrow { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.research-panel h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 16px; }
.research-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.research-refresh { margin-left: auto; }
.research-form { display: grid; gap: 9px; max-width: 760px; }
.research-form--new-version { margin-top: 8px; padding-top: 15px; border-top: 1px solid var(--color-border); }
.research-form--new-version h3 { margin: 0; color: var(--color-text-primary); font-size: 13px; }
.research-form label { color: var(--color-text-secondary); font-size: 12px; font-weight: 650; }
.research-form input,.research-form select { width: 100%; min-width: 0; min-height: 40px; padding: 8px 10px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 13px; }
.research-form input:focus-visible,.research-form select:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.research-form__grid { display: grid; grid-template-columns: minmax(140px,.5fr) minmax(140px,1fr); align-items: center; gap: 8px; }
.research-form__grid--dates { grid-template-columns: repeat(2,minmax(0,1fr)); padding: 12px; border-radius: 10px; background: #f8fafb; }
.research-form__hint { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.research-actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 3px; }
.research-message { display: flex; align-items: center; min-height: 48px; padding: 11px; border-radius: 9px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 12px; line-height: 1.55; }
.research-message--error { color: #8f651d; background: #fcf7eb; }
.research-message--success { color: #287765; background: #e8f4ef; }
.research-receipt { display: grid; gap: 4px; padding: 13px; border: 1px solid #dcebe5; border-radius: 9px; color: var(--color-text-secondary); background: #f5faf7; font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.research-receipt strong { color: var(--color-text-primary); font-size: 12px; }
@media(max-width:620px) { .research-panel { padding: 15px; }.research-panel__heading { flex-wrap: wrap; }.research-refresh { margin-left: 50px; }.research-form__grid,.research-form__grid--dates { grid-template-columns: 1fr; }.research-form__grid label { margin-top: 4px; } }
</style>
