<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Activity, Beaker, CircleAlert, RotateCcw, ShieldCheck } from '@lucide/vue'
import CatSimulationStopChart from '@/components/charts/CatSimulationStopChart.vue'
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
const sampleSize = ref<CatSimulationSampleSize>(100)

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
  return Object.entries(distribution).map(([reason, count]) => ({
    reason,
    label: stopLabels[reason as keyof typeof stopLabels] ?? '其他停止原因',
    count: count ?? 0,
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
  <section class="cat-management" aria-label="CAT 工程模拟">
    <div v-if="catalogState === 'loading'" class="cat-load-state" role="status" aria-busy="true">
      <span class="cat-load-state__mark cat-spin"><RotateCcw :size="17" aria-hidden="true" /></span>
      <span>正在读取当前题库和配置…</span>
    </div>
    <div v-else-if="catalogState === 'forbidden'" class="cat-load-state cat-load-state--warning" role="alert">
      <span class="cat-load-state__mark"><ShieldCheck :size="18" aria-hidden="true" /></span>
      <div><strong>无法查看 CAT 配置</strong><p>{{ catalogMessage }}</p></div>
    </div>
    <div v-else-if="catalogState === 'unavailable'" class="cat-load-state cat-load-state--warning" role="alert">
      <span class="cat-load-state__mark"><CircleAlert :size="18" aria-hidden="true" /></span>
      <div><strong>题库信息暂不可用</strong><p>{{ catalogMessage }}</p></div>
      <button class="cat-button cat-button--quiet" type="button" @click="refreshCatalog">重新读取</button>
    </div>

    <div v-else-if="catalog" class="cat-simulation-workbench">
      <aside class="cat-config" aria-labelledby="cat-config-title">
        <header class="cat-section-heading">
          <div class="cat-section-heading__main">
            <p class="cat-section-heading__index">01 / CONFIGURATION</p>
            <div class="cat-section-heading__title"><Activity :size="16" aria-hidden="true" /><h2 id="cat-config-title">模拟配置</h2></div>
          </div>
          <button class="cat-refresh" type="button" aria-label="重新读取题库配置" :disabled="simulationState === 'running'" @click="refreshCatalog"><RotateCcw :size="15" aria-hidden="true" /></button>
        </header>

        <div class="cat-bank-summary">
          <span>当前题库 <b>{{ catalog.item_bank.version }}</b></span>
          <strong>{{ catalog.item_bank.instrument_id }}</strong>
          <p>{{ catalog.item_bank.item_count }} 道题 · {{ catalog.item_bank.dimension_count }} 个维度</p>
          <span class="cat-bank-summary__status"><i />{{ statusLabel(catalog.item_bank.status) }}</span>
        </div>

        <dl class="cat-config-facts">
          <div><dt>测评方案</dt><dd>{{ catalog.config.config_version }}</dd></div>
          <div><dt>模型与估计</dt><dd>{{ catalog.config.model }} · {{ catalog.config.estimator }}</dd></div>
          <div><dt>选题方式</dt><dd>{{ catalog.config.selection_method }}</dd></div>
          <div><dt>题数范围</dt><dd>{{ catalog.config.min_items }}–{{ catalog.config.max_items }}</dd></div>
        </dl>

        <fieldset class="cat-sample-picker" :disabled="simulationState === 'running'">
          <legend>合成样本量</legend>
          <label v-for="size in catalog.simulation.sample_sizes" :key="size" class="cat-sample-option" :class="{ 'cat-sample-option--active': sampleSize === size }">
            <input type="radio" name="cat-sample-size" :value="size" :checked="sampleSize === size" @change="changeSampleSize(size)">
            <span><strong>{{ size.toLocaleString('zh-CN') }}</strong><small>合成样本</small></span>
          </label>
        </fieldset>

        <button class="cat-button cat-button--primary" type="button" :disabled="!canRun" @click="runSimulation">
          <RotateCcw v-if="simulationState === 'running'" :size="16" class="cat-spin" aria-hidden="true" />
          <Beaker v-else :size="16" aria-hidden="true" />
          {{ simulationState === 'running' ? '模拟运行中…' : runLabel }}
        </button>
        <p class="cat-config-note"><ShieldCheck :size="14" aria-hidden="true" />配置只读；运行由当前账号手动发起。</p>
      </aside>

      <section class="cat-analysis" aria-labelledby="cat-analysis-title">
        <header class="cat-section-heading">
          <div><p class="cat-section-heading__index">02 / ANALYSIS</p><h2 id="cat-analysis-title">停止原因分布</h2></div>
          <span v-if="simulation" class="cat-analysis__sample">n = {{ simulation.n_examinees.toLocaleString('zh-CN') }}</span>
        </header>

        <div v-if="simulationState === 'running'" class="cat-analysis-state" role="status" aria-live="polite" aria-busy="true">
          <span class="cat-analysis-state__spinner cat-spin"><RotateCcw :size="18" aria-hidden="true" /></span>
          <strong>正在运行模拟</strong>
          <p>当前样本量 {{ sampleSize.toLocaleString('zh-CN') }}；请求完成后显示服务端汇总。</p>
        </div>
        <div v-else-if="simulationState === 'busy' || simulationState === 'error'" class="cat-analysis-state cat-analysis-state--warning" role="alert">
          <span class="cat-analysis-state__spinner"><CircleAlert :size="18" aria-hidden="true" /></span>
          <strong>{{ simulationState === 'busy' ? '模拟服务正忙' : '本次模拟未完成' }}</strong>
          <p>{{ simulationMessage }}</p>
        </div>
        <CatSimulationStopChart v-else-if="simulation" :rows="stoppingRows" />
        <div v-else class="cat-analysis-state cat-analysis-state--empty">
          <span class="cat-analysis-state__mark"><Beaker :size="18" aria-hidden="true" /></span>
          <strong>等待运行数据</strong>
          <p>提交模拟后，此处会呈现服务端返回的停止原因和样本数。</p>
        </div>
        <p v-if="simulation" class="cat-analysis__source">{{ simulation.item_bank_version }} · {{ simulation.config_version }}</p>
      </section>

      <aside class="cat-metrics" aria-labelledby="cat-metrics-title" aria-live="polite">
        <header class="cat-section-heading">
          <div><p class="cat-section-heading__index">03 / METRICS</p><h2 id="cat-metrics-title">结果读数</h2></div>
          <span v-if="simulation" class="cat-metrics__badge"><i />已返回</span>
        </header>
        <p v-if="hasRepeatabilityComparison" class="cat-comparison" role="status">{{ comparisonText }}</p>
        <dl v-if="simulation" class="cat-metric-list">
          <div><dt>偏差 Bias</dt><dd>{{ formatNumber(simulation.metrics.bias) }}</dd></div>
          <div><dt>均方根误差 RMSE</dt><dd>{{ formatNumber(simulation.metrics.rmse) }}</dd></div>
          <div><dt>平均绝对误差 MAE</dt><dd>{{ formatNumber(simulation.metrics.mae) }}</dd></div>
          <div><dt>平均施测题数</dt><dd>{{ formatNumber(simulation.metrics.mean_test_length, 2) }}</dd></div>
          <div><dt>中位施测题数</dt><dd>{{ formatNumber(simulation.metrics.median_test_length, 2) }}</dd></div>
          <div><dt>平均标准误 SE</dt><dd>{{ formatNumber(simulation.metrics.mean_se) }}</dd></div>
        </dl>
        <div v-else class="cat-metrics-empty">
          <span>—</span>
          <p>{{ simulationState === 'running' ? '等待本次服务端响应' : '尚无本次运行结果' }}</p>
        </div>
        <p v-if="simulation" class="cat-metrics__footnote">固定种子 {{ simulation.seed }} · 数据来自本次服务端响应</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.cat-management { min-width: 0; color: var(--color-text-primary); }
.cat-simulation-workbench { display: grid; grid-template-columns: minmax(220px, .88fr) minmax(0, 1.95fr) minmax(230px, .92fr); min-width: 0; border: 1px solid #e4edf0; border-radius: 13px; background: #fff; }
.cat-config,.cat-analysis,.cat-metrics { position: relative; min-width: 0; padding: 20px 18px; }
.cat-analysis { border-inline: 1px solid #e8eef1; }
.cat-section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 9px; min-height: 42px; padding-bottom: 13px; border-bottom: 1px solid #edf2f4; }
.cat-section-heading__index { margin: 0 0 6px; color: #1687a0; font-size: 9px; font-weight: 760; letter-spacing: .12em; }
.cat-section-heading h2 { margin: 0; color: #2d4651; font-size: 15px; font-weight: 730; letter-spacing: -.02em; }
.cat-section-heading__title { display: flex; align-items: center; gap: 7px; color: #1687a0; }
.cat-section-heading__title h2 { color: #2d4651; }
.cat-refresh { display: grid; width: 29px; height: 29px; flex: 0 0 29px; place-items: center; border: 1px solid #e2eaed; border-radius: 8px; color: #647c85; background: #fff; cursor: pointer; }
.cat-refresh:hover:not(:disabled) { color: #087f9e; border-color: #b7dce5; background: #f6fbfc; }
.cat-refresh:focus-visible,.cat-button:focus-visible,.cat-sample-option:focus-within { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.cat-refresh:disabled { opacity: .5; cursor: not-allowed; }
.cat-bank-summary { position: relative; display: grid; gap: 7px; padding: 15px 0 14px; border-bottom: 1px solid #edf2f4; }
.cat-bank-summary > span:first-child { color: #72858b; font-size: 10px; }.cat-bank-summary > span:first-child b { margin-left: 4px; color: #3e5c68; font-weight: 650; }
.cat-bank-summary > strong { color: #294957; font-size: 13px; font-weight: 720; overflow-wrap: anywhere; }
.cat-bank-summary > p { margin: 0; color: #78898f; font-size: 10px; }
.cat-bank-summary__status { position: absolute; right: 0; top: 13px; display: inline-flex; align-items: center; gap: 5px; color: #548276; font-size: 9px; }
.cat-bank-summary__status i,.cat-metrics__badge i { width: 6px; height: 6px; border-radius: 50%; background: #43a58d; }
.cat-config-facts { display: grid; gap: 0; margin: 0; padding: 4px 0 10px; }
.cat-config-facts > div { display: grid; grid-template-columns: minmax(75px,.7fr) minmax(0,1fr); gap: 8px; padding: 8px 0; border-bottom: 1px solid #f0f3f5; }
.cat-config-facts dt { color: #849399; font-size: 10px; }
.cat-config-facts dd { margin: 0; color: #526a73; font-size: 10px; font-weight: 640; text-align: right; overflow-wrap: anywhere; }
.cat-sample-picker { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 7px; margin: 4px 0 14px; padding: 0; border: 0; }
.cat-sample-picker legend { grid-column: 1 / -1; margin-bottom: 6px; color: #566e77; font-size: 10px; font-weight: 700; }
.cat-sample-option { display: flex; align-items: center; gap: 7px; min-height: 49px; padding: 7px 8px; border: 1px solid #e3ebee; border-radius: 8px; color: #526a73; background: #fff; cursor: pointer; }
.cat-sample-option--active { border-color: #76bdcc; background: #f1fafc; box-shadow: inset 2px 0 #10a2c3; }
.cat-sample-option input { width: 13px; height: 13px; margin: 0; accent-color: var(--color-primary); }
.cat-sample-option span { display: grid; gap: 2px; min-width: 0; }
.cat-sample-option strong { color: #34535f; font-size: 12px; font-variant-numeric: tabular-nums; }
.cat-sample-option small { color: #87969b; font-size: 9px; }
.cat-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 39px; padding: 9px 13px; border: 1px solid transparent; border-radius: 8px; font: inherit; font-size: 11px; font-weight: 720; cursor: pointer; }
.cat-button--primary { width: 100%; color: #fff; background: var(--color-primary); }
.cat-button--primary:hover:not(:disabled) { background: var(--color-primary-active); }
.cat-button--quiet { flex: 0 0 auto; color: #42636e; border-color: #d8e5e9; background: #fff; }
.cat-button:disabled { opacity: .5; cursor: not-allowed; }
.cat-config-note { display: flex; align-items: center; gap: 6px; margin: 10px 0 0; color: #829197; font-size: 9px; line-height: 1.5; }
.cat-config-note svg { flex: 0 0 auto; color: #578c86; }
.cat-analysis .cat-section-heading { align-items: center; }
.cat-analysis .cat-section-heading__index { margin-bottom: 5px; }
.cat-analysis__sample { padding: 5px 7px; border: 1px solid #e2edf0; border-radius: 7px; color: #66808a; background: #f9fcfd; font-family: var(--font-mono); font-size: 9px; font-variant-numeric: tabular-nums; }
.cat-analysis .cat-stop-chart { margin-top: 14px; }
.cat-analysis__source { margin: -1px 0 0; padding-top: 9px; border-top: 1px solid #edf2f4; color: #87959a; font-size: 9px; text-align: right; }
.cat-analysis-state { display: flex; min-height: 260px; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 22px 12px; color: #61777f; text-align: center; }
.cat-analysis-state__mark,.cat-analysis-state__spinner { display: grid; width: 38px; height: 38px; place-items: center; border: 1px solid #d7edf1; border-radius: 12px; color: #1498b6; background: #f1fafb; }
.cat-analysis-state strong { color: #3b5964; font-size: 12px; }
.cat-analysis-state p { max-width: 270px; margin: 0; color: #819197; font-size: 10px; line-height: 1.65; }
.cat-analysis-state--warning .cat-analysis-state__spinner { color: #a47529; border-color: #eee2c8; background: #fcf8ee; }
.cat-analysis-state--warning strong { color: #735b35; }
.cat-analysis-state--empty { min-height: 310px; }
.cat-metrics__badge { display: inline-flex; align-items: center; gap: 5px; margin-top: 2px; color: #588479; font-size: 9px; }
.cat-metric-list { display: grid; margin: 4px 0 0; }
.cat-metric-list > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 43px; border-bottom: 1px solid #edf2f4; }
.cat-metric-list dt { color: #74868d; font-size: 10px; }
.cat-metric-list dd { margin: 0; color: #254b5a; font-size: 15px; font-weight: 690; font-variant-numeric: tabular-nums; letter-spacing: -.02em; }
.cat-metrics-empty { display: grid; min-height: 260px; align-content: center; justify-items: center; gap: 7px; color: #a0adb1; }
.cat-metrics-empty span { font-size: 27px; font-weight: 400; }.cat-metrics-empty p { margin: 0; color: #84949a; font-size: 10px; text-align: center; }
.cat-metrics__footnote { margin: 12px 0 0; color: #87959a; font-size: 9px; line-height: 1.5; }
.cat-comparison { margin: 9px 0 4px; padding: 8px 9px; border-left: 2px solid #7cbdac; color: #55766e; background: #f3f9f7; font-size: 9px; line-height: 1.55; }
.cat-load-state { display: flex; align-items: center; gap: 11px; min-height: 78px; padding: 18px 20px; border: 1px solid #e3ecef; border-radius: 11px; color: #526a73; background: #fff; font-size: 12px; }
.cat-load-state__mark { display: grid; width: 35px; height: 35px; flex: 0 0 35px; place-items: center; border-radius: 10px; color: #168da9; background: #eef9fb; }
.cat-load-state--warning { align-items: flex-start; border-color: #eee4d1; color: #765e39; background: #fffdf8; }.cat-load-state--warning .cat-load-state__mark { color: #a47529; background: #faf3e3; }
.cat-load-state strong { display: block; color: #455d66; font-size: 12px; }.cat-load-state p { margin: 4px 0 0; color: inherit; font-size: 11px; line-height: 1.6; }.cat-load-state .cat-button { margin-left: auto; }
.cat-spin { animation: cat-spin 1.1s linear infinite; } @keyframes cat-spin { to { transform: rotate(360deg); } }
@media (max-width: 1080px) { .cat-simulation-workbench { grid-template-columns: minmax(220px,.9fr) minmax(0,1.45fr); }.cat-analysis { border-right: 0; }.cat-metrics { grid-column: 1 / -1; border-top: 1px solid #e8eef1; }.cat-metric-list { grid-template-columns: repeat(3,minmax(0,1fr)); column-gap: 18px; }.cat-metric-list > div { min-height: 49px; }.cat-metrics-empty { min-height: 115px; } }
@media (max-width: 720px) { .cat-simulation-workbench { grid-template-columns: minmax(0,1fr); }.cat-config,.cat-analysis,.cat-metrics { padding: 17px; }.cat-analysis { border-top: 1px solid #e8eef1; border-left: 0; }.cat-analysis-state,.cat-analysis-state--empty { min-height: 215px; }.cat-metrics { grid-column: auto; border-top: 1px solid #e8eef1; }.cat-metric-list { grid-template-columns: repeat(2,minmax(0,1fr)); column-gap: 14px; } }
@media (max-width: 420px) { .cat-config,.cat-analysis,.cat-metrics { padding: 14px; }.cat-metric-list { grid-template-columns: 1fr; }.cat-analysis .cat-stop-chart { margin-inline: -4px; }.cat-load-state--warning { flex-wrap: wrap; }.cat-load-state .cat-button { margin-left: 46px; } }
@media (prefers-reduced-motion: reduce) { .cat-spin { animation: none; } }
</style>
