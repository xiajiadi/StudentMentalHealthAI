<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Activity, Check, CircleHelp, RefreshCw, Search, Server, X, ChevronDown } from '@lucide/vue'
import type { DependencyStatusDto } from '@/api/generated/types.gen'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import { DependencyHealthReadError, readDependencyHealth, type DependencyHealthReadErrorKind } from '@/views/admin/health'

type PageState = 'loading' | 'ready' | 'refreshing' | 'error'
type HealthCategory = 'normal' | 'attention' | 'unknown' | 'unconfigured'
type StatusFilter = 'all' | 'normal' | 'attention' | 'other'
type BadgeTone = 'neutral' | 'blue' | 'teal' | 'amber'
type HealthRow = DependencyStatusDto & {
  key: string
  name: string
  category: HealthCategory
  label: string
  tone: BadgeTone
  summary: string
}
type Snapshot = { dependencies: Record<string, DependencyStatusDto>; fetchedAt: Date }

const dependencyNames: Record<string, string> = {
  cat: 'CAT 测评',
  rag: 'RAG 检索',
  llm_runtime: 'LLM 运行时',
  safety: '安全校验',
  post_assessment_worker: '测后处理',
  research_education_worker: '研究教育任务',
  research_programme_worker: '研究项目任务',
  research_general_education_draft_worker: '通用教育草稿',
}

const integrationNames: Record<string, string> = {
  REAL_HTTP: 'HTTP 服务',
  LOCAL_OUTBOX: '本地队列',
  RESEARCH_OUTBOX: '研究队列',
  RESEARCH_STAFF_PROGRAMME_OUTBOX: '项目队列',
  RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX: '草稿队列',
}

const statusFilters: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'normal', label: '正常' },
  { value: 'attention', label: '需关注' },
  { value: 'other', label: '其他' },
]

const pageState = ref<PageState>('loading')
const requestInFlight = ref(false)
const snapshot = ref<Snapshot | null>(null)
const failureKind = ref<DependencyHealthReadErrorKind>('request')
const searchQuery = ref('')
const statusFilter = ref<StatusFilter>('all')
const selectedKey = ref('')
const statusFilterContainer = ref<HTMLElement | null>(null)
const statusFilterButtons = new Map<StatusFilter, HTMLButtonElement>()
const statusFilterIndicator = ref({ x: 0, y: 0, width: 0, height: 0, visible: false })
const statusFilterIndicatorStyle = computed(() => ({
  width: `${statusFilterIndicator.value.width}px`,
  height: `${statusFilterIndicator.value.height}px`,
  transform: `translate(${statusFilterIndicator.value.x}px, ${statusFilterIndicator.value.y}px)`,
  opacity: statusFilterIndicator.value.visible ? '1' : '0',
}))
let requestSequence = 0

const setStatusFilterButton = (value: StatusFilter, element: unknown) => {
  if (element instanceof HTMLButtonElement) statusFilterButtons.set(value, element)
  else statusFilterButtons.delete(value)
}

const updateStatusFilterIndicator = async () => {
  await nextTick()
  const container = statusFilterContainer.value
  const button = statusFilterButtons.get(statusFilter.value)
  if (!container || !button) {
    statusFilterIndicator.value = { ...statusFilterIndicator.value, visible: false }
    return
  }

  const containerRect = container.getBoundingClientRect()
  const buttonRect = button.getBoundingClientRect()
  statusFilterIndicator.value = {
    x: buttonRect.left - containerRect.left,
    y: buttonRect.top - containerRect.top,
    width: buttonRect.width,
    height: buttonRect.height,
    visible: true,
  }
}

function describeStatus(rawStatus: string): Pick<HealthRow, 'category' | 'label' | 'tone' | 'summary'> {
  const status = rawStatus.trim().toUpperCase()
  if (status === 'READY' || status === 'AVAILABLE') {
    return { category: 'normal', label: '正常', tone: 'teal', summary: '服务端返回正常状态。' }
  }
  if (status === 'UNAVAILABLE') {
    return { category: 'attention', label: '需关注', tone: 'amber', summary: '服务端报告此依赖当前不可用。' }
  }
  if (status === 'DEFERRED') {
    return { category: 'unconfigured', label: '未配置', tone: 'blue', summary: '服务端将此依赖标记为未配置。' }
  }
  if (status === 'DISABLED') {
    return { category: 'unconfigured', label: '已关闭', tone: 'neutral', summary: '服务端将此依赖标记为已关闭。' }
  }
  if (status === 'STARTING') {
    return { category: 'unknown', label: '启动中', tone: 'neutral', summary: '服务端报告此依赖正在启动。' }
  }
  return {
    category: 'unknown',
    label: '未知',
    tone: 'neutral',
    summary: status ? `服务端返回未识别状态“${rawStatus}”。` : '服务端未返回状态码。',
  }
}

function integrationName(integration: string) {
  return integration ? integrationNames[integration] ?? integration : '未返回'
}

const rows = computed<HealthRow[]>(() => Object.entries(snapshot.value?.dependencies ?? {}).map(([key, value]) => ({
  key,
  name: dependencyNames[key] ?? key.replaceAll('_', ' '),
  status: value.status,
  integration: value.integration,
  ...describeStatus(value.status),
})))

const counts = computed(() => rows.value.reduce((total, row) => {
  total[row.category] += 1
  return total
}, { normal: 0, attention: 0, unknown: 0, unconfigured: 0 }))

const additionalCount = computed(() => counts.value.unknown + counts.value.unconfigured)
const summaryMetrics = computed(() => [
  { label: '受检依赖', value: snapshot.value ? String(rows.value.length) : '—' },
  { label: '正常', value: snapshot.value ? String(counts.value.normal) : '—' },
  { label: '需关注', value: snapshot.value ? String(counts.value.attention) : '—' },
  { label: '未确认 / 未配置', value: snapshot.value ? String(additionalCount.value) : '—' },
])

const distribution = computed(() => {
  const total = rows.value.length
  if (!total) return []
  return [
    { key: 'normal', label: '正常', count: counts.value.normal },
    { key: 'attention', label: '需关注', count: counts.value.attention },
    { key: 'unknown', label: '未知', count: counts.value.unknown },
    { key: 'unconfigured', label: '未配置', count: counts.value.unconfigured },
  ].filter((segment) => segment.count > 0).map((segment) => ({
    ...segment,
    width: `${(segment.count / total) * 100}%`,
  }))
})

const distributionDescription = computed(() => rows.value.length
  ? distribution.value.map((segment) => `${segment.label} ${segment.count}`).join('，')
  : '健康端点未返回依赖条目')

const filterCount = (filter: StatusFilter) => {
  if (filter === 'all') return rows.value.length
  if (filter === 'normal') return counts.value.normal
  if (filter === 'attention') return counts.value.attention
  return additionalCount.value
}

const filteredRows = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return rows.value.filter((row) => {
    const matchesSearch = !query || `${row.name} ${row.key} ${row.integration} ${row.status}`.toLocaleLowerCase().includes(query)
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'normal' && row.category === 'normal')
      || (statusFilter.value === 'attention' && row.category === 'attention')
      || (statusFilter.value === 'other' && (row.category === 'unknown' || row.category === 'unconfigured'))
    return matchesSearch && matchesStatus
  })
})

watch(filteredRows, (visibleRows) => {
  if (!visibleRows.some((row) => row.key === selectedKey.value)) {
    selectedKey.value = visibleRows[0]?.key ?? ''
  }
}, { immediate: true })
watch(statusFilter, () => void updateStatusFilterIndicator(), { flush: 'post' })
watch(pageState, (state) => {
  if (state === 'ready') void updateStatusFilterIndicator()
}, { flush: 'post' })

const selectedRow = computed(() => filteredRows.value.find((row) => row.key === selectedKey.value) ?? null)
const busy = computed(() => requestInFlight.value || pageState.value === 'loading' || pageState.value === 'refreshing')
const localTime = computed(() => snapshot.value
  ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(snapshot.value.fetchedAt)
  : '')
const snapshotMessage = computed(() => {
  if (pageState.value === 'error') return '无法获取当前状态'
  if (pageState.value === 'loading') return '正在读取最新检查结果'
  if (pageState.value === 'refreshing') return '正在刷新，下面显示上次成功快照'
  return '已获取最新检查结果'
})
const snapshotTime = computed(() => !snapshot.value ? '' : pageState.value === 'refreshing'
  ? `上次成功快照 · 本地获取于 ${localTime.value}`
  : `本地获取于 ${localTime.value}`)

const failureCopy = computed(() => {
  if (failureKind.value === 'unauthorized') return { title: '登录状态已失效', body: '重新登录后再查看依赖状态。' }
  if (failureKind.value === 'forbidden') return { title: '当前账号无权读取系统状态', body: '请联系管理员确认账号权限。' }
  if (failureKind.value === 'invalid-response') return { title: '健康端点返回的数据无法识别', body: '响应缺少依赖状态或接入信息，请稍后重试。' }
  return { title: '无法获取当前状态', body: '健康端点暂时无法访问，请稍后重试。' }
})

async function refreshHealth() {
  if (requestInFlight.value) return
  requestInFlight.value = true
  const currentRequest = ++requestSequence
  pageState.value = snapshot.value ? 'refreshing' : 'loading'
  failureKind.value = 'request'
  try {
    const dependencies = await readDependencyHealth()
    if (currentRequest !== requestSequence) return
    snapshot.value = { dependencies, fetchedAt: new Date() }
    pageState.value = 'ready'
  } catch (error) {
    if (currentRequest !== requestSequence) return
    snapshot.value = null
    selectedKey.value = ''
    failureKind.value = error instanceof DependencyHealthReadError ? error.kind : 'request'
    pageState.value = 'error'
  } finally {
    if (currentRequest === requestSequence) requestInFlight.value = false
  }
}

onMounted(() => {
  void refreshHealth()
  window.addEventListener('resize', updateStatusFilterIndicator)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateStatusFilterIndicator)
  requestSequence += 1
})
</script>

<template>
  <section class="system-health" aria-label="系统状态">
    <div class="system-health__snapshot" :class="`system-health__snapshot--${pageState}`" role="status" aria-live="polite">
      <span class="system-health__snapshot-icon" aria-hidden="true">
        <RefreshCw v-if="busy" :size="16" />
        <CircleHelp v-else-if="pageState === 'error'" :size="16" />
        <Check v-else :size="16" />
      </span>
      <div class="system-health__snapshot-copy">
        <strong>{{ snapshotMessage }}</strong>
        <span v-if="snapshotTime">{{ snapshotTime }}</span>
      </div>
      <AppBadge tone="neutral" dot>只读诊断</AppBadge>
    </div>

    <AppCard class="system-health__summary">
      <dl aria-label="当前依赖状态概况">
        <div v-for="metric in summaryMetrics" :key="metric.label">
          <dt>{{ metric.label }}</dt>
          <dd>{{ metric.value }}</dd>
        </div>
      </dl>
    </AppCard>

    <AppCard v-if="pageState === 'loading'" class="system-health__state" role="status" aria-busy="true">
      <RefreshCw class="system-health__state-icon system-health__state-icon--spin" :size="19" aria-hidden="true" />
      <div><strong>正在读取依赖状态</strong><p>正在获取当前检查结果。</p></div>
    </AppCard>

    <AppCard v-else-if="pageState === 'error'" class="system-health__state system-health__state--error" role="alert">
      <CircleHelp class="system-health__state-icon" :size="20" aria-hidden="true" />
      <div class="system-health__state-copy"><strong>{{ failureCopy.title }}</strong><p>{{ failureCopy.body }}</p></div>
      <AppButton variant="secondary" size="sm" @click="refreshHealth">重试</AppButton>
    </AppCard>

    <AppCard v-else class="system-health__workbench" flush>
      <header class="system-health__workbench-heading">
        <div class="system-health__workbench-title">
          <span class="system-health__workbench-icon"><Server :size="18" aria-hidden="true" /></span>
          <div><h2>依赖服务</h2><p>查看各检查项的状态和接入信息</p></div>
        </div>
        <AppBadge tone="blue" dot>只读状态</AppBadge>
      </header>

      <div class="system-health__workbench-content">
        <section class="system-health__distribution" aria-label="当前状态分布">
          <div class="system-health__distribution-heading"><strong>当前状态分布</strong><span>{{ rows.length }} 项</span></div>
          <div class="system-health__bar" role="img" :aria-label="distributionDescription">
            <span
              v-for="segment in distribution"
              :key="segment.key"
              class="system-health__bar-segment"
              :class="`system-health__bar-segment--${segment.key}`"
              :style="{ width: segment.width }"
              aria-hidden="true"
            ></span>
            <span v-if="!rows.length" class="system-health__bar-empty" aria-hidden="true"></span>
          </div>
          <div v-if="rows.length" class="system-health__legend" aria-hidden="true">
            <span><i class="system-health__legend-dot system-health__legend-dot--normal"></i>正常 {{ counts.normal }}</span>
            <span><i class="system-health__legend-dot system-health__legend-dot--attention"></i>需关注 {{ counts.attention }}</span>
            <span><i class="system-health__legend-dot system-health__legend-dot--unknown"></i>未知 {{ counts.unknown }}</span>
            <span><i class="system-health__legend-dot system-health__legend-dot--unconfigured"></i>未配置 {{ counts.unconfigured }}</span>
          </div>
          <p v-else class="system-health__distribution-empty">健康端点已响应，但没有返回依赖条目。</p>
        </section>

        <div class="system-health__toolbar">
          <label class="system-health__search">
            <Search :size="16" aria-hidden="true" />
            <input v-model="searchQuery" type="text" autocomplete="off" aria-label="搜索服务名称" placeholder="搜索服务名称…">
            <button v-if="searchQuery" type="button" aria-label="清空服务搜索" @click="searchQuery = ''"><X :size="15" aria-hidden="true" /></button>
          </label>
          <div ref="statusFilterContainer" class="system-health__filters" role="group" aria-label="按状态筛选">
            <span class="system-health__filters-indicator" :style="statusFilterIndicatorStyle" aria-hidden="true"></span>
            <button
              v-for="filter in statusFilters"
              :key="filter.value"
              :ref="(element) => setStatusFilterButton(filter.value, element)"
              type="button"
              :aria-pressed="statusFilter === filter.value"
              :class="{ 'system-health__filter--active': statusFilter === filter.value }"
              @click="statusFilter = filter.value"
            >{{ filter.label }} <span>{{ filterCount(filter.value) }}</span></button>
          </div>
        </div>

        <div class="system-health__body">
          <section class="system-health__directory" aria-label="依赖服务目录">
            <header class="system-health__directory-heading"><h3>服务目录</h3><span>{{ filteredRows.length }} / {{ rows.length }}</span></header>
            <ul v-if="filteredRows.length" class="system-health__list" tabindex="0" aria-label="服务目录，可使用鼠标滚轮或方向键浏览">
              <li v-for="row in filteredRows" :key="row.key">
                <button
                  type="button"
                  class="system-health__service"
                  :class="{ 'system-health__service--selected': selectedKey === row.key }"
                  :aria-pressed="selectedKey === row.key"
                  @click="selectedKey = row.key"
                >
                  <span class="system-health__service-icon"><Activity :size="17" aria-hidden="true" /></span>
                  <span class="system-health__service-copy"><strong>{{ row.name }}</strong><span>{{ row.summary }}</span></span>
                  <AppBadge :tone="row.tone" dot>{{ row.label }}</AppBadge>
                </button>
              </li>
            </ul>
            <div v-else class="system-health__empty" role="status">
              <CircleHelp :size="19" aria-hidden="true" />
              <strong>{{ rows.length ? '没有匹配的服务' : '没有可显示的依赖' }}</strong>
              <span>{{ rows.length ? '调整搜索或状态筛选。' : '健康端点当前未返回依赖条目。' }}</span>
              <button v-if="rows.length" type="button" @click="searchQuery = ''; statusFilter = 'all'">清除筛选</button>
            </div>
          </section>

          <section class="system-health__detail" aria-label="服务详情" aria-live="polite">
            <template v-if="selectedRow">
              <header class="system-health__detail-heading">
                <span class="system-health__detail-icon"><Activity :size="19" aria-hidden="true" /></span>
                <div><span>服务详情</span><h3>{{ selectedRow.name }}</h3></div>
                <AppBadge :tone="selectedRow.tone" dot>{{ selectedRow.label }}</AppBadge>
              </header>

              <dl class="system-health__facts">
                <div><dt>服务标识</dt><dd><code>{{ selectedRow.key }}</code></dd></div>
                <div>
                  <dt>接入方式</dt>
                  <dd>{{ integrationName(selectedRow.integration) }}</dd>
                  <small v-if="integrationName(selectedRow.integration) !== selectedRow.integration && selectedRow.integration">{{ selectedRow.integration }}</small>
                </div>
                <div><dt>状态码</dt><dd><code>{{ selectedRow.status || '未返回' }}</code></dd></div>
                <div><dt>数据来源</dt><dd><code>GET /health/dependencies</code></dd></div>
              </dl>

              <section class="system-health__check-summary" aria-labelledby="system-health-check-title">
                <h4 id="system-health-check-title">检查摘要</h4>
                <p>{{ selectedRow.summary }}</p>
              </section>

              <details class="system-health__limits">
                <summary><span>检查范围与限制</span><ChevronDown :size="16" aria-hidden="true" /></summary>
                <p>本页只描述健康端点当前返回的依赖信息。状态正常不代表全部业务功能可用，也不代表心理学审核、测量学验证或生产就绪。</p>
              </details>
            </template>
            <div v-else class="system-health__detail-empty" role="status">
              <Server :size="22" aria-hidden="true" />
              <strong>{{ rows.length ? (filteredRows.length ? '选择一项依赖' : '没有匹配的服务') : '暂无服务详情' }}</strong>
              <span>{{ rows.length ? (filteredRows.length ? '查看服务端返回的状态和接入信息。' : '调整搜索或状态筛选。') : '健康端点未返回依赖条目。' }}</span>
            </div>
          </section>
        </div>
      </div>
    </AppCard>
  </section>
</template>

<style scoped>
.system-health { --health-normal: #168475; --health-attention: #b7791f; --health-unknown: #82909a; --health-unconfigured: #9cafba; display: grid; gap: 14px; min-width: 0; }
.system-health__snapshot { display: flex; min-height: 43px; align-items: center; gap: 10px; padding: 0 13px; border: 1px solid #e5ecef; border-radius: 9px; color: #536a75; background: #fff; }
.system-health__snapshot-icon { display: grid; width: 20px; height: 20px; flex: 0 0 20px; place-items: center; color: var(--color-support); }
.system-health__snapshot--loading .system-health__snapshot-icon,.system-health__snapshot--refreshing .system-health__snapshot-icon { color: var(--color-primary-active); animation: system-health-spin 900ms linear infinite; }
.system-health__snapshot--error .system-health__snapshot-icon { color: var(--color-attention); }
.system-health__snapshot-copy { display: flex; min-width: 0; flex: 1; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; }
.system-health__snapshot-copy strong { color: #425b66; font-size: 14px; font-weight: 650; }
.system-health__snapshot-copy > span { color: #87969e; font-size: 13px; }
.system-health__snapshot :deep(.app-badge),.system-health__workbench-heading :deep(.app-badge) { font-size: 14px; }
.system-health__summary { padding: 8px 17px; }
.system-health__summary dl { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); margin: 0; }
.system-health__summary dl > div { display: grid; gap: 5px; min-width: 0; padding: 6px 17px; border-left: 1px solid #edf0f2; }
.system-health__summary dl > div:first-child { padding-left: 2px; border-left: 0; }
.system-health__summary dt { color: var(--color-text-muted); font-size: 14px; }
.system-health__summary dd { margin: 0; color: #304b58; font-size: 23px; font-weight: 730; font-variant-numeric: tabular-nums; line-height: 1.15; }
.system-health__summary dl > div:nth-child(2) dd { color: var(--health-normal); }
.system-health__summary dl > div:nth-child(3) dd { color: var(--health-attention); }
.system-health__summary dl > div:nth-child(4) dd { color: #71818b; }
.system-health__state { display: flex; min-height: 105px; align-items: center; gap: 13px; padding: 19px 21px; }
.system-health__state-icon { flex: 0 0 auto; color: var(--color-primary-active); }
.system-health__state-icon--spin { animation: system-health-spin 900ms linear infinite; }
.system-health__state--error .system-health__state-icon { color: var(--color-attention); }
.system-health__state-copy { min-width: 0; flex: 1; }
.system-health__state strong { color: #344d59; font-size: 16px; font-weight: 700; }
.system-health__state p { margin: 5px 0 0; color: var(--color-text-muted); font-size: 15px; line-height: 1.55; }
.system-health__state :deep(.app-button) { font-size: 15px; }
.system-health__workbench { min-width: 0; }
.system-health__workbench-heading { display: flex; min-height: 72px; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 19px; border-bottom: 1px solid #e9eef1; }
.system-health__workbench-title { display: flex; min-width: 0; align-items: center; gap: 11px; }
.system-health__workbench-icon,.system-health__detail-icon { display: grid; width: 37px; height: 37px; flex: 0 0 37px; place-items: center; border-radius: 11px; color: #008eb5; background: #eaf7fa; }
.system-health__workbench-title h2 { margin: 0; color: #2c4654; font-size: 17px; font-weight: 720; }
.system-health__workbench-title p { margin: 4px 0 0; color: #81909a; font-size: 14px; }
.system-health__workbench-content { padding: 15px 18px 17px; }
.system-health__distribution { display: grid; gap: 8px; }
.system-health__distribution-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.system-health__distribution-heading strong { color: #445d68; font-size: 14px; font-weight: 690; }
.system-health__distribution-heading span { color: #87969d; font-size: 13px; }
.system-health__bar { display: flex; height: 8px; overflow: hidden; border-radius: 99px; background: #eff2f4; }
.system-health__bar-segment { display: block; min-width: 2px; transition: width 180ms ease; }
.system-health__bar-segment--normal { background: var(--health-normal); }
.system-health__bar-segment--attention { background: #d39a3c; }
.system-health__bar-segment--unknown { background: var(--health-unknown); }
.system-health__bar-segment--unconfigured { background: var(--health-unconfigured); }
.system-health__bar-empty { width: 100%; background: #e8edf0; }
.system-health__legend { display: flex; flex-wrap: wrap; gap: 6px 16px; color: #74858d; font-size: 13px; }
.system-health__legend > span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.system-health__legend-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.system-health__legend-dot--normal { color: var(--health-normal); }.system-health__legend-dot--attention { color: #d39a3c; }.system-health__legend-dot--unknown { color: var(--health-unknown); }.system-health__legend-dot--unconfigured { color: var(--health-unconfigured); }
.system-health__distribution-empty { margin: 0; color: #84929a; font-size: 13px; }
.system-health__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 16px 0 13px; }
.system-health__search { display: flex; width: min(360px,100%); min-width: 190px; height: 38px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #dfe7eb; border-radius: 8px; color: #81939c; background: #fff; transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.system-health__search:focus-within { border-color: #75bfce; box-shadow: 0 0 0 3px rgb(0 177 226 / 10%); }
.system-health__search input { width: 100%; min-width: 0; height: 34px; padding: 0; border: 0; outline: none; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 15px; }
.system-health__search input::placeholder { color: #96a2a8; }
.system-health__search input:focus-visible { outline: none; }
.system-health__search button { display: grid; width: 24px; height: 24px; flex: 0 0 24px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: #788a93; background: transparent; cursor: pointer; }
.system-health__search button:hover { color: #344f5b; background: #f0f5f6; }
.system-health__filters { position: relative; display: grid; width: min(360px,100%); max-width: 100%; grid-template-columns: repeat(4,minmax(0,1fr)); align-items: center; padding: 4px; border-radius: 9px; background: #fafbfd; box-shadow: inset 0 0 0 1px #eceef1; isolation: isolate; }
.system-health__filters-indicator { position: absolute; z-index: 0; top: 0; left: 0; border-radius: 7px; background: #00addf; box-shadow: 0 2px 6px rgb(0 136 178 / 20%); pointer-events: none; transition: transform 360ms cubic-bezier(.2,.8,.2,1), width 360ms cubic-bezier(.2,.8,.2,1), height 220ms ease, opacity var(--motion-fast); }
.system-health__filters button { position: relative; z-index: 1; display: inline-flex; min-width: 0; min-height: 36px; align-items: center; justify-content: center; gap: 5px; padding: 0 8px; border: 0; border-radius: 7px; color: #596574; background: transparent; font: inherit; font-size: 13px; font-weight: 600; white-space: nowrap; cursor: pointer; transition: color var(--motion-fast) ease; }
.system-health__filters button span { color: #8b989e; font-size: 12px; font-variant-numeric: tabular-nums; }
.system-health__filters button:hover:not(.system-health__filter--active) { color: #263b4c; }
.system-health__filters button.system-health__filter--active { color: #fff; background: transparent; }
.system-health__filters button.system-health__filter--active span { color: rgb(255 255 255 / 84%); }
.system-health__filters button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.system-health__body { display: grid; grid-template-columns: minmax(0,1.06fr) minmax(0,.94fr); min-width: 0; min-height: 355px; border: 1px solid #e8eef1; border-radius: 11px; }
.system-health__directory { display: flex; min-width: 0; flex-direction: column; padding: 14px 14px 12px; border-right: 1px solid #e8eef1; }
.system-health__directory-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 7px; padding: 0 2px; }
.system-health__directory-heading h3 { margin: 0; color: #415a65; font-size: 15px; font-weight: 700; }
.system-health__directory-heading span { color: #87959c; font-size: 13px; font-variant-numeric: tabular-nums; }
.system-health__list { display: grid; min-height: 0; align-content: start; gap: 7px; max-height: 460px; overflow-y: auto; overscroll-behavior-y: contain; scroll-behavior: smooth; scroll-snap-type: y proximity; margin: 0; padding: 2px 3px 2px 0; list-style: none; scrollbar-width: none; }
.system-health__list::-webkit-scrollbar { display: none; }
.system-health__list:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; border-radius: 9px; }
.system-health__list li { min-width: 0; scroll-snap-align: start; scroll-margin-block: 3px; }
.system-health__service { position: relative; display: grid; width: 100%; grid-template-columns: 34px minmax(0,1fr) auto; align-items: center; gap: 9px; min-width: 0; min-height: 62px; padding: 9px 9px 9px 11px; border: 1px solid transparent; border-radius: 9px; color: inherit; background: transparent; text-align: left; cursor: pointer; transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.system-health__service::before { position: absolute; top: 11px; bottom: 11px; left: 0; width: 2px; border-radius: 2px; background: transparent; content: ''; }
.system-health__service:hover { background: #f7fafb; }
.system-health__service--selected { border-color: #d6ebf0; background: #f1fafb; }
.system-health__service--selected::before { background: var(--color-primary); }
.system-health__service-icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 9px; color: #6e8791; background: #f0f4f6; }
.system-health__service--selected .system-health__service-icon { color: #0789a8; background: #e1f3f7; }
.system-health__service-copy { display: grid; min-width: 0; gap: 4px; }
.system-health__service-copy strong { overflow: hidden; color: #314b58; font-size: 15px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.system-health__service-copy > span { overflow: hidden; color: #809099; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.system-health__service :deep(.app-badge) { min-height: 25px; padding-inline: 7px; font-size: 12px; }
.system-health__service :deep(.app-badge__dot) { width: 5px; height: 5px; }
.system-health__empty { display: grid; justify-items: center; align-content: center; gap: 7px; flex: 1; min-height: 170px; padding: 18px; color: #82929a; text-align: center; }
.system-health__empty > svg { color: #8da0a8; }
.system-health__empty strong { color: #4b626d; font-size: 15px; font-weight: 680; }
.system-health__empty > span { font-size: 13px; line-height: 1.5; }
.system-health__empty > button { margin-top: 2px; padding: 4px 6px; border: 0; color: #187d96; background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.system-health__detail { display: flex; min-width: 0; flex-direction: column; gap: 16px; padding: 18px; }
.system-health__detail-heading { display: flex; min-width: 0; align-items: center; gap: 10px; }
.system-health__detail-icon { width: 36px; height: 36px; flex-basis: 36px; }
.system-health__detail-heading > div { display: grid; min-width: 0; flex: 1; gap: 3px; }
.system-health__detail-heading > div > span { color: #87969d; font-size: 12px; }
.system-health__detail-heading h3 { overflow: hidden; margin: 0; color: #2c4654; font-size: 17px; font-weight: 720; text-overflow: ellipsis; white-space: nowrap; }
.system-health__detail-heading :deep(.app-badge) { min-height: 26px; padding-inline: 8px; font-size: 12px; }
.system-health__facts { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 1px; overflow: hidden; margin: 0; border: 1px solid #e8eef1; border-radius: 9px; background: #e8eef1; }
.system-health__facts > div { display: grid; align-content: start; gap: 5px; min-width: 0; min-height: 67px; padding: 10px 11px; background: #fff; }
.system-health__facts dt { color: #84939b; font-size: 12px; }
.system-health__facts dd { overflow-wrap: anywhere; margin: 0; color: #3d5662; font-size: 14px; font-weight: 620; line-height: 1.45; }
.system-health__facts dd code { color: #526b76; font-size: 12px; }
.system-health__facts small { overflow-wrap: anywhere; color: #8b989e; font-family: var(--font-mono); font-size: 11px; }
.system-health__check-summary { display: grid; gap: 8px; }
.system-health__check-summary h4 { margin: 0; color: #435b66; font-size: 14px; font-weight: 700; }
.system-health__check-summary p { margin: 0; padding: 13px 14px; border: 1px solid #ebf0f2; border-radius: 9px; color: #5e737d; background: #f7f9fa; font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.system-health__limits { border-top: 1px solid #edf0f2; color: #7d8d95; }
.system-health__limits summary { display: flex; min-height: 40px; align-items: center; justify-content: space-between; gap: 10px; color: #637982; font-size: 13px; font-weight: 650; cursor: pointer; list-style: none; }
.system-health__limits summary::-webkit-details-marker { display: none; }
.system-health__limits summary > svg { flex: 0 0 auto; color: #84969e; transition: transform var(--motion-fast) ease; }
.system-health__limits[open] summary > svg { transform: rotate(180deg); }
.system-health__limits p { margin: 0; padding: 0 1px 12px; color: #819098; font-size: 13px; line-height: 1.6; }
.system-health__detail-empty { display: grid; flex: 1; align-content: center; justify-items: center; gap: 8px; min-height: 260px; color: #88979e; text-align: center; }
.system-health__detail-empty > svg { color: #8ba0a8; }
.system-health__detail-empty strong { color: #4d6671; font-size: 15px; font-weight: 690; }
.system-health__detail-empty span { font-size: 13px; line-height: 1.5; }
@keyframes system-health-spin { to { transform: rotate(360deg); } }
@media (max-width: 1000px) {
  .system-health__toolbar { align-items: stretch; flex-direction: column; }
  .system-health__search { width: 100%; }
  .system-health__filters { align-self: flex-start; }
}
@media (max-width: 760px) {
  .system-health__summary { padding: 9px 12px; }
  .system-health__summary dl { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px 0; }
  .system-health__summary dl > div { padding: 5px 12px; }
  .system-health__summary dl > div:first-child { padding-left: 12px; border-left: 1px solid #edf0f2; }
  .system-health__summary dl > div:nth-child(odd) { padding-left: 0; border-left: 0; }
  .system-health__summary dd { font-size: 21px; }
  .system-health__workbench-heading { min-height: 66px; padding: 12px 14px; }
  .system-health__workbench-content { padding: 13px 12px; }
  .system-health__body { grid-template-columns: minmax(0,1fr); }
  .system-health__directory { border-right: 0; border-bottom: 1px solid #e8eef1; }
  .system-health__list { max-height: none; overflow: visible; scroll-snap-type: none; }
  .system-health__detail { min-height: 300px; padding: 15px; }
}
@media (max-width: 480px) {
  .system-health__snapshot { align-items: flex-start; padding-block: 9px; }
  .system-health__snapshot-copy { gap: 3px; flex-direction: column; }
  .system-health__summary dl > div { padding-inline: 9px; }
  .system-health__summary dl > div:first-child { padding-left: 9px; }
  .system-health__service { grid-template-columns: 30px minmax(0,1fr) auto; gap: 7px; padding-inline: 8px; }
  .system-health__service-icon { width: 29px; height: 29px; }
  .system-health__service-copy strong { font-size: 14px; }
  .system-health__service-copy > span { font-size: 12px; }
  .system-health__service :deep(.app-badge) { min-height: 23px; padding-inline: 6px; font-size: 11px; }
  .system-health__filters button { padding-inline: 4px; }
  .system-health__facts { grid-template-columns: minmax(0,1fr); }
  .system-health__facts > div { min-height: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .system-health__snapshot--loading .system-health__snapshot-icon,.system-health__snapshot--refreshing .system-health__snapshot-icon,.system-health__state-icon--spin { animation: none; }
  .system-health__bar-segment,.system-health__service,.system-health__filters-indicator,.system-health__filters button,.system-health__search,.system-health__limits summary > svg { transition: none; }
  .system-health__list { scroll-behavior: auto; scroll-snap-type: none; }
}
</style>
