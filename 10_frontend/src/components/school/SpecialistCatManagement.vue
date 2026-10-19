<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Activity, Beaker, CircleAlert, RotateCcw, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import SpecialistCatAssets from '@/components/school/SpecialistCatAssets.vue'
import { useSessionStore } from '@/stores/session'
import {
  schoolCatManagement,
  type CatSimulationSampleSize,
  type SchoolCatCatalog,
  type SchoolCatSimulation,
} from '@/services/school-cat-management'

type CatalogState = 'loading' | 'ready' | 'forbidden' | 'unavailable'
type SimulationState = 'idle' | 'running' | 'complete' | 'busy' | 'error'

const session = useSessionStore()
const catalog = ref<SchoolCatCatalog | null>(null)
const catalogState = ref<CatalogState>('loading')
const simulationState = ref<SimulationState>('idle')
const simulation = ref<SchoolCatSimulation | null>(null)
const comparisonCandidate = ref<SchoolCatSimulation | null>(null)
const comparisonText = ref('')
const errorText = ref('')
const sampleSize = ref<CatSimulationSampleSize>(100)
const activePanel = ref<'simulation' | 'assets'>('simulation')

let catalogSequence = 0
let simulationSequence = 0
let disposed = false

const sessionScope = () => [
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
].join('|')

const allowedRole = () => session.role === 'psychological_specialist'
  && (!session.user?.activeContext || session.user.activeContext.role === 'psychological_specialist')
const canRun = computed(() => catalogState.value === 'ready' && Boolean(catalog.value) && !['running'].includes(simulationState.value))
const runLabel = computed(() => simulation.value ? '再次运行并对照' : '运行工程模拟')
const hasRepeatabilityComparison = computed(() => Boolean(simulation.value && comparisonCandidate.value))

const stopLabels: Record<keyof NonNullable<SchoolCatSimulation['stopping_reason_distribution']>, string> = {
  SE_THRESHOLD_REACHED: '达到标准误停止条件',
  MAX_ITEMS_REACHED: '达到题数上限',
  ITEM_BANK_EXHAUSTED: '可用题目已用完',
  MANUAL_TERMINATION: '手动停止',
  ERROR: '运行错误',
  NOT_STOPPED: '未触发停止条件',
}

const stoppingRows = computed(() => {
  const distribution = simulation.value?.stopping_reason_distribution
  if (!distribution) return []
  const largest = Math.max(1, ...Object.values(distribution))
  return Object.entries(distribution).map(([reason, count]) => ({
    reason,
    label: stopLabels[reason as keyof typeof stopLabels] ?? '其他停止原因',
    count: count ?? 0,
    width: `${Math.max(2, ((count ?? 0) / largest) * 100)}%`,
  }))
})

const catalogMessage = computed(() => catalogState.value === 'forbidden'
  ? '当前账号或学校上下文无权查看这份配置。请切换到本校心理专业账号后重新进入。'
  : '当前题库或配置暂不可用，本页不会填入示例数据。请手动重新读取，或稍后再试。')

const simulationMessage = computed(() => simulationState.value === 'busy'
  ? '已有工程模拟正在运行。本次请求没有排队，可稍后手动发起一次新运行。'
  : '本次模拟没有返回可用结果。请确认当前配置后，再手动运行一次。')

const formatNumber = (value: number, digits = 3) => new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: digits,
  minimumFractionDigits: 0,
}).format(value)

const statusLabel = (status: SchoolCatCatalog['item_bank']['status']) => ({
  draft: '草稿', calibrating: '校准中', validated: '结构已校验', published: '已发布', deprecated: '已停用',
}[status])

const aggregatesMatch = (first: SchoolCatSimulation, second: SchoolCatSimulation) => {
  const firstMetrics = Object.entries(first.metrics).sort(([a], [b]) => a.localeCompare(b))
  const secondMetrics = Object.entries(second.metrics).sort(([a], [b]) => a.localeCompare(b))
  const firstReasons = Object.entries(first.stopping_reason_distribution).sort(([a], [b]) => a.localeCompare(b))
  const secondReasons = Object.entries(second.stopping_reason_distribution).sort(([a], [b]) => a.localeCompare(b))
  return JSON.stringify(firstMetrics) === JSON.stringify(secondMetrics)
    && JSON.stringify(firstReasons) === JSON.stringify(secondReasons)
}

function classifyError(error: unknown): 'forbidden' | 'busy' | 'unavailable' {
  const code = error && typeof error === 'object' && 'code' in error
    ? String(error.code).toUpperCase()
    : ''
  if ([
    'FORBIDDEN', '403', 'HTTP_403', 'CSRF_FAILED', 'RESOURCE_NOT_FOUND',
    'AUTH_INVALID_CREDENTIALS', 'AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED',
    'UNAUTHORIZED', '401', 'HTTP_401',
  ].includes(code)) {
    return 'forbidden'
  }
  if ([
    '409', 'HTTP_409', 'CONFLICT', 'WORKFLOW_CONFLICT', 'CAT_SIMULATION_BUSY',
    'SYNTHETIC_CAT_SIMULATION_BUSY', 'SIMULATION_BUSY',
  ].includes(code)) {
    return 'busy'
  }
  return 'unavailable'
}

function clearWorkspaceState() {
  catalog.value = null
  simulation.value = null
  comparisonCandidate.value = null
  comparisonText.value = ''
  errorText.value = ''
  simulationState.value = 'idle'
  sampleSize.value = 100
}

function invalidateRequests() {
  catalogSequence += 1
  simulationSequence += 1
}

function failCatalog(kind: 'forbidden' | 'unavailable') {
  clearWorkspaceState()
  catalogState.value = kind
}

async function loadCatalog() {
  const sequence = ++catalogSequence
  simulationSequence += 1
  clearWorkspaceState()
  catalogState.value = 'loading'
  if (!allowedRole()) {
    failCatalog('forbidden')
    return
  }
  const scope = sessionScope()
  try {
    const result = await schoolCatManagement.getCatalog()
    if (disposed || sequence !== catalogSequence || scope !== sessionScope() || !allowedRole()) return
    catalog.value = result
    sampleSize.value = result.simulation.sample_sizes[0]
    catalogState.value = 'ready'
  } catch (error) {
    if (disposed || sequence !== catalogSequence || scope !== sessionScope()) return
    failCatalog(classifyError(error))
  }
}

function changeSampleSize(value: CatSimulationSampleSize) {
  if (sampleSize.value === value) return
  sampleSize.value = value
  simulation.value = null
  comparisonCandidate.value = null
  comparisonText.value = ''
  errorText.value = ''
  simulationState.value = 'idle'
}

async function runSimulation() {
  const currentCatalog = catalog.value
  if (!currentCatalog || !canRun.value || !allowedRole()) return
  const sequence = ++simulationSequence
  const scope = sessionScope()
  const prior = simulation.value?.n_examinees === sampleSize.value ? simulation.value : null
  simulation.value = null
  comparisonCandidate.value = null
  comparisonText.value = ''
  errorText.value = ''
  simulationState.value = 'running'
  try {
    const result = await schoolCatManagement.runSimulation(currentCatalog, sampleSize.value)
    if (disposed || sequence !== simulationSequence || scope !== sessionScope() || !allowedRole()) return
    simulation.value = result
    comparisonCandidate.value = prior
    if (prior) {
      const identical = aggregatesMatch(prior, result)
      comparisonText.value = identical
        ? '本次与上一轮同样本量运行的聚合结果一致。'
        : '本次聚合结果与上一轮存在差异，请以本次服务端返回为准。'
    }
    simulationState.value = 'complete'
  } catch (error) {
    if (disposed || sequence !== simulationSequence || scope !== sessionScope()) return
    simulation.value = null
    comparisonCandidate.value = null
    comparisonText.value = ''
    const kind = classifyError(error)
    simulationState.value = kind === 'busy' ? 'busy' : 'error'
    if (kind === 'forbidden') failCatalog('forbidden')
  }
}

function refreshCatalog() {
  void loadCatalog()
}

watch(sessionScope, (nextScope, previousScope) => {
  if (nextScope === previousScope) return
  invalidateRequests()
  clearWorkspaceState()
  if (allowedRole()) {
    void loadCatalog()
  } else {
    catalogState.value = 'forbidden'
  }
}, { flush: 'sync' })

onMounted(() => { void loadCatalog() })
onBeforeUnmount(() => {
  disposed = true
  invalidateRequests()
  clearWorkspaceState()
})
</script>

<template>
  <section class="cat-management" aria-label="CAT 方案与工程模拟">
    <nav class="cat-management__tabs" aria-label="CAT管理功能">
      <button type="button" :aria-pressed="activePanel === 'simulation'" @click="activePanel = 'simulation'">工程模拟</button>
      <button type="button" :aria-pressed="activePanel === 'assets'" @click="activePanel = 'assets'">题库与方案</button>
    </nav>
    <SpecialistCatAssets v-if="activePanel === 'assets'" />
    <div v-show="activePanel === 'simulation'">
      <AppStatusCallout tone="attention" title="工程模拟不代表心理学结论" body="这里只读取当前合成题库与配置。心理学解释已关闭；模拟结果尚待独立心理学验证，不用于个人判断或报告发布。" />

      <div v-if="catalogState === 'loading'" class="cat-state" role="status" aria-busy="true">
        <span class="cat-state__mark"><RotateCcw :size="17" aria-hidden="true" /></span>
        <span>正在读取当前题库和配置…</span>
      </div>
      <div v-else-if="catalogState === 'forbidden'" class="cat-state cat-state--restricted" role="alert">
        <span class="cat-state__mark"><ShieldCheck :size="18" aria-hidden="true" /></span>
        <div><strong>无法查看CAT配置</strong><p>{{ catalogMessage }}</p></div>
      </div>
      <div v-else-if="catalogState === 'unavailable'" class="cat-state cat-state--unavailable" role="alert">
        <span class="cat-state__mark"><CircleAlert :size="18" aria-hidden="true" /></span>
        <div><strong>题库信息暂不可用</strong><p>{{ catalogMessage }}</p></div>
        <button class="cat-button cat-button--quiet" type="button" @click="refreshCatalog">重新读取</button>
      </div>

      <div v-else-if="catalog" class="cat-workbench">
        <AppCard class="cat-catalog">
          <header class="cat-panel-heading">
            <span class="cat-panel-heading__icon"><Activity :size="18" aria-hidden="true" /></span>
            <div><p class="cat-overline">当前运行资产</p><h2>题库与配置</h2></div>
            <button class="cat-icon-button" type="button" aria-label="重新读取题库配置" :disabled="simulationState === 'running'" @click="refreshCatalog">
              <RotateCcw :size="16" aria-hidden="true" />
            </button>
          </header>
          <dl class="cat-facts">
            <div><dt>题库版本</dt><dd>{{ catalog.item_bank.version }}</dd></div>
            <div><dt>结构检查</dt><dd><span class="cat-badge">通过</span></dd></div>
            <div><dt>题目数量</dt><dd>{{ catalog.item_bank.item_count }} 道</dd></div>
            <div><dt>维度数量</dt><dd>{{ catalog.item_bank.dimension_count }} 个</dd></div>
            <div><dt>题库状态</dt><dd>{{ statusLabel(catalog.item_bank.status) }}</dd></div>
          </dl>
          <div class="cat-config-block">
            <div class="cat-config-block__heading"><span>测评配置</span><span>{{ catalog.config.config_version }}</span></div>
            <dl class="cat-config-grid">
              <div><dt>估计方法</dt><dd>{{ catalog.config.estimator }}</dd></div>
              <div><dt>选题方法</dt><dd>{{ catalog.config.selection_method }}</dd></div>
              <div><dt>题数范围</dt><dd>{{ catalog.config.min_items }}–{{ catalog.config.max_items }}</dd></div>
              <div><dt>模型</dt><dd>{{ catalog.config.model }}</dd></div>
            </dl>
          </div>
          <p class="cat-readonly-note">配置来自当前服务端，只读展示。本页不会编辑或启用题库。</p>
        </AppCard>

        <AppCard class="cat-run-panel">
          <header class="cat-panel-heading cat-panel-heading--run">
            <span class="cat-panel-heading__icon cat-panel-heading__icon--run"><Beaker :size="18" aria-hidden="true" /></span>
            <div><p class="cat-overline">固定配置，合成数据</p><h2>运行工程模拟</h2></div>
          </header>
          <p class="cat-run-intro">选择样本量后手动开始一次运行。相同条件可再次运行并比较聚合结果。</p>
          <fieldset class="cat-sample-picker" :disabled="simulationState === 'running'">
            <legend>模拟样本量</legend>
            <label v-for="size in catalog.simulation.sample_sizes" :key="size" class="cat-sample-option" :class="{ 'cat-sample-option--active': sampleSize === size }">
              <input type="radio" name="cat-sample-size" :value="size" :checked="sampleSize === size" @change="changeSampleSize(size)">
              <span><strong>{{ size.toLocaleString('zh-CN') }}</strong><small>合成模拟样本</small></span>
            </label>
          </fieldset>
          <button class="cat-button cat-button--primary" type="button" :disabled="!canRun" @click="runSimulation">
            <RotateCcw v-if="simulationState === 'running'" :size="16" class="cat-spin" aria-hidden="true" />
            <Beaker v-else :size="16" aria-hidden="true" />
            {{ simulationState === 'running' ? '模拟运行中…' : runLabel }}
          </button>
          <p class="cat-run-footnote"><ShieldCheck :size="14" aria-hidden="true" />不写入测评会话、报告或业务记录；再次运行需手动发起</p>
        </AppCard>
      </div>

      <div v-if="simulationState === 'running'" class="cat-progress" role="status" aria-live="polite" aria-busy="true">
        <span class="cat-progress__spinner" aria-hidden="true"><RotateCcw :size="15" /></span><span>运行中，较大批次可能需要数分钟。当前样本量 {{ sampleSize.toLocaleString('zh-CN') }}。</span>
      </div>
      <div v-else-if="simulationState === 'busy' || simulationState === 'error'" class="cat-state cat-state--unavailable" role="alert">
        <span class="cat-state__mark"><CircleAlert :size="18" aria-hidden="true" /></span>
        <div><strong>{{ simulationState === 'busy' ? '模拟服务正忙' : '本次模拟未完成' }}</strong><p>{{ simulationMessage }}</p></div>
      </div>

      <section v-if="simulation" class="cat-results" aria-labelledby="cat-results-title" aria-live="polite">
        <header class="cat-results__heading">
          <div><p class="cat-overline">服务端返回，聚合值</p><h2 id="cat-results-title">模拟结果</h2><p>样本量 {{ simulation.n_examinees.toLocaleString('zh-CN') }}，题库 {{ simulation.item_bank_version }}，配置 {{ simulation.config_version }}</p></div>
          <span class="cat-result-chip"><ShieldCheck :size="14" aria-hidden="true" />仅供工程验证</span>
        </header>
        <p v-if="hasRepeatabilityComparison" class="cat-comparison" role="status">{{ comparisonText }}</p>
        <div class="cat-metrics" aria-label="聚合指标">
          <div><dt>偏差 Bias</dt><dd>{{ formatNumber(simulation.metrics.bias) }}</dd></div>
          <div><dt>均方根误差 RMSE</dt><dd>{{ formatNumber(simulation.metrics.rmse) }}</dd></div>
          <div><dt>平均绝对误差 MAE</dt><dd>{{ formatNumber(simulation.metrics.mae) }}</dd></div>
          <div><dt>平均题数</dt><dd>{{ formatNumber(simulation.metrics.mean_test_length, 2) }}</dd></div>
          <div><dt>中位题数</dt><dd>{{ formatNumber(simulation.metrics.median_test_length, 2) }}</dd></div>
          <div><dt>平均标准误</dt><dd>{{ formatNumber(simulation.metrics.mean_se) }}</dd></div>
        </div>
        <div class="cat-stopping">
          <h3>停止原因汇总</h3>
          <ul>
            <li v-for="row in stoppingRows" :key="row.reason">
              <span>{{ row.label }}</span><span class="cat-stopping__bar"><i :style="{ width: row.width }" /></span><strong>{{ row.count }}</strong>
            </li>
          </ul>
        </div>
        <p class="cat-result-boundary">结果采用当前配置中的固定随机种子；这些指标不验证量表、模型或心理学解释的有效性。</p>
      </section>

      <p v-else-if="catalogState === 'ready' && simulationState === 'idle'" class="cat-empty">
        运行后，这里会显示接口返回的聚合指标与停止原因汇总。
      </p>
    </div>
  </section>
</template>

<style scoped>
.cat-management { display: grid; gap: 15px; color: var(--color-text-primary); }
.cat-management__tabs { display: flex; gap: 7px; width: max-content; padding: 4px; border: 1px solid #e3ece7; border-radius: 11px; background: #f5f9f6; }
.cat-management__tabs button { min-height: 34px; padding: 7px 14px; border: 0; border-radius: 8px; background: transparent; color: #63766c; font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }
.cat-management__tabs button[aria-pressed="true"] { background: #fff; color: #357c6b; box-shadow: 0 1px 3px #203c3014; }
.cat-workbench { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(280px, .92fr); align-items: start; gap: 14px; }
.cat-catalog,.cat-run-panel { min-width: 0; padding: 19px; }
.cat-panel-heading { display: flex; align-items: center; gap: 11px; padding-bottom: 15px; border-bottom: 1px solid #e8efeb; }
.cat-panel-heading__icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 11px; color: #397d70; background: #eaf4ef; }
.cat-panel-heading__icon--run { color: #1b7894; background: #eaf4f6; }
.cat-panel-heading h2,.cat-results__heading h2 { margin: 3px 0 0; color: var(--color-text-primary); font-size: 16px; letter-spacing: -.02em; }
.cat-overline { margin: 0; color: #548275; font-size: 10px; font-weight: 750; }
.cat-icon-button { display: inline-grid; width: 34px; height: 34px; margin-left: auto; place-items: center; border: 1px solid #dce8e2; border-radius: 9px; color: #527269; background: #fff; cursor: pointer; }
.cat-icon-button:hover:not(:disabled) { border-color: #9bbcaf; background: #f5f9f7; }
.cat-icon-button:disabled { opacity: .5; cursor: not-allowed; }
.cat-icon-button:focus-visible,.cat-button:focus-visible,.cat-sample-option:focus-within { outline: 3px solid rgb(58 127 111 / 23%); outline-offset: 2px; }
.cat-facts { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); margin: 0; padding: 5px 0 15px; }
.cat-facts > div { display: grid; gap: 5px; min-height: 57px; padding: 12px 8px 8px 0; border-bottom: 1px solid #eef2ef; }
.cat-facts dt,.cat-config-grid dt,.cat-metrics dt { color: var(--color-text-muted); font-size: 10px; }
.cat-facts dd,.cat-config-grid dd { margin: 0; color: #344b44; font-size: 12px; font-weight: 700; overflow-wrap: anywhere; }
.cat-badge { display: inline-flex; padding: 3px 7px; border-radius: 999px; color: #397363; background: #eaf4ef; font-size: 9px; font-weight: 750; }
.cat-config-block { padding-top: 3px; }
.cat-config-block__heading { display: flex; justify-content: space-between; gap: 10px; color: #52695f; font-size: 11px; font-weight: 750; }
.cat-config-block__heading span:last-child { color: #72857c; font-size: 10px; font-weight: 600; }
.cat-config-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; margin: 12px 0 0; }
.cat-config-grid > div { display: grid; gap: 4px; }
.cat-config-grid dd { font-size: 11px; }
.cat-readonly-note { margin: 15px 0 0; padding-top: 11px; border-top: 1px solid #edf2ef; color: var(--color-text-muted); font-size: 10px; line-height: 1.6; }
.cat-panel-heading--run { border-bottom: 0; padding-bottom: 7px; }
.cat-run-intro { max-width: 420px; margin: 7px 0 16px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
.cat-sample-picker { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; margin: 0 0 15px; padding: 0; border: 0; }
.cat-sample-picker legend { grid-column: 1 / -1; margin-bottom: 8px; color: #52695f; font-size: 11px; font-weight: 750; }
.cat-sample-picker:disabled { opacity: .68; }
.cat-sample-option { display: flex; align-items: center; gap: 9px; min-height: 61px; padding: 10px; border: 1px solid #e0eae5; border-radius: 10px; color: #42584f; background: #fff; cursor: pointer; }
.cat-sample-option--active { border-color: #78a996; background: #f0f7f3; box-shadow: inset 3px 0 #438e7b; }
.cat-sample-option input { accent-color: #438e7b; }
.cat-sample-option span { display: grid; gap: 3px; }
.cat-sample-option strong { font-size: 14px; }
.cat-sample-option small { color: var(--color-text-muted); font-size: 9px; }
.cat-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 39px; padding: 9px 13px; border: 1px solid transparent; border-radius: 9px; font: inherit; font-size: 11px; font-weight: 750; cursor: pointer; }
.cat-button--primary { width: 100%; color: #fff; background: #357c6b; }
.cat-button--primary:hover:not(:disabled) { background: #286b5a; }
.cat-button--quiet { flex: 0 0 auto; color: #4c6c61; border-color: #dce8e3; background: #fff; }
.cat-button:disabled { opacity: .5; cursor: not-allowed; }
.cat-run-footnote { display: flex; align-items: center; gap: 6px; margin: 12px 0 0; color: var(--color-text-muted); font-size: 10px; }
.cat-run-footnote svg { color: #4e8877; }
.cat-state { display: flex; align-items: center; gap: 11px; min-height: 72px; padding: 15px 17px; border: 1px solid #e3ece7; border-radius: 13px; color: #52665e; background: #f8fbf9; font-size: 12px; }
.cat-state__mark { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border-radius: 10px; color: #4a8172; background: #eaf4ef; }
.cat-state--restricted,.cat-state--unavailable { align-items: flex-start; border-color: #e8e1d2; color: #6b5c43; background: #fcfaf5; }
.cat-state--restricted .cat-state__mark,.cat-state--unavailable .cat-state__mark { color: #9b742f; background: #f6f0df; }
.cat-state strong { display: block; color: #4d594e; font-size: 12px; }
.cat-state p { margin: 4px 0 0; color: inherit; font-size: 11px; line-height: 1.65; }
.cat-state .cat-button { margin-left: auto; }
.cat-progress { display: flex; align-items: center; gap: 10px; min-height: 47px; padding: 12px 15px; border: 1px solid #dce9e3; border-radius: 10px; color: #4a6c60; background: #f5faf7; font-size: 11px; line-height: 1.6; }
.cat-progress__spinner { display: inline-grid; flex: 0 0 auto; color: #4f8b78; animation: cat-spin 1.1s linear infinite; }
.cat-results { display: grid; gap: 14px; padding: 20px; border: 1px solid #dce9e3; border-radius: 14px; background: #f9fbfa; }
.cat-results__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid #e5ede8; }
.cat-results__heading h2 { margin-bottom: 4px; }.cat-results__heading p:last-child { margin: 0; color: var(--color-text-secondary); font-size: 10px; line-height: 1.6; }
.cat-result-chip { display: inline-flex; align-items: center; gap: 5px; flex: 0 0 auto; padding: 6px 9px; border-radius: 999px; color: #397363; background: #eaf4ef; font-size: 9px; font-weight: 750; }
.cat-comparison { margin: 0; padding: 9px 11px; border-left: 3px solid #5b9684; color: #4e6d62; background: #eff6f2; font-size: 11px; line-height: 1.6; }
.cat-metrics { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 1px; overflow: hidden; border: 1px solid #e7eeea; border-radius: 10px; background: #e7eeea; }
.cat-metrics > div { display: grid; gap: 6px; min-height: 70px; padding: 12px 13px; background: #fff; }
.cat-metrics dd { margin: 0; color: #335c4e; font-size: 18px; font-variant-numeric: tabular-nums; font-weight: 700; letter-spacing: -.03em; }
.cat-stopping h3 { margin: 0 0 9px; color: #445d53; font-size: 11px; }
.cat-stopping ul { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.cat-stopping li { display: grid; grid-template-columns: minmax(145px, .8fr) minmax(60px,1fr) 30px; align-items: center; gap: 9px; color: #5e7067; font-size: 10px; }
.cat-stopping li strong { color: #425b50; font-variant-numeric: tabular-nums; text-align: right; }
.cat-stopping__bar { height: 6px; overflow: hidden; border-radius: 99px; background: #e8efeb; }
.cat-stopping__bar i { display: block; height: 100%; border-radius: inherit; background: #75a995; }
.cat-result-boundary { margin: 0; padding-top: 10px; border-top: 1px solid #e7eeea; color: var(--color-text-muted); font-size: 10px; line-height: 1.6; }
.cat-empty { margin: 0; padding: 13px 3px 4px; color: var(--color-text-muted); font-size: 11px; }
.cat-spin { animation: cat-spin 1.1s linear infinite; }
@keyframes cat-spin { to { transform: rotate(360deg); } }
@media (max-width: 820px) { .cat-workbench { grid-template-columns: 1fr; } }
@media (max-width: 560px) {
  .cat-catalog,.cat-run-panel,.cat-results { padding: 15px; }
  .cat-facts,.cat-config-grid { grid-template-columns: 1fr 1fr; }
  .cat-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .cat-results__heading { align-items: flex-start; flex-direction: column; }
  .cat-stopping li { grid-template-columns: minmax(105px,.9fr) minmax(35px,1fr) 25px; gap: 6px; }
  .cat-state--unavailable { flex-wrap: wrap; }
  .cat-state .cat-button { margin-left: 45px; }
}
@media (prefers-reduced-motion: reduce) {
  .cat-spin,.cat-progress__spinner { animation: none; }
}
</style>
