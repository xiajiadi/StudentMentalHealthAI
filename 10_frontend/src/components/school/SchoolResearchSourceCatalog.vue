<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  BookOpen,
  BookOpenCheck,
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  ExternalLink,
  FileText,
  Library,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from '@lucide/vue'
import {
  SelectContent as RightsSelectContent,
  SelectItem as RightsSelectItem,
  SelectItemIndicator as RightsSelectItemIndicator,
  SelectItemText as RightsSelectItemText,
  SelectPortal as RightsSelectPortal,
  SelectRoot as RightsSelectRoot,
  SelectTrigger as RightsSelectTrigger,
  SelectValue as RightsSelectValue,
  SelectViewport as RightsSelectViewport,
  TabsContent,
  TabsIndicator,
  TabsList,
  TabsRoot,
  TabsTrigger,
} from 'reka-ui'
import AppButton from '@/components/app/AppButton.vue'
import type {
  ResearchSourceCatalogPage,
  ResearchSourceDetail,
  ResearchSourceSummary,
} from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'

type CatalogState = 'loading' | 'ready' | 'error' | 'forbidden' | 'unavailable'
type DetailState = 'loading' | 'ready' | 'error' | 'forbidden' | 'unavailable'
type SourceLayer = ResearchSourceSummary['layers'][number]
type TopicFilter = 'all' | SourceLayer
type RightsFilter = 'all' | ResearchSourceSummary['rights_status']
type SortMode = 'catalog' | 'title'
type InspectorTab = 'archive' | 'rights' | 'verification'

const session = useSessionStore()
const scopeKey = computed(() => [
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
].join('|'))

const state = ref<CatalogState>('loading')
const page = ref<ResearchSourceCatalogPage | null>(null)
const selectedSourceRef = ref('')
const detail = ref<ResearchSourceDetail | null>(null)
const detailState = ref<DetailState>('loading')
const errorMessage = ref('')
const searchQuery = ref('')
const topicFilter = ref<TopicFilter>('all')
const rightsFilter = ref<RightsFilter>('all')
const sortMode = ref<SortMode>('catalog')
const inspectorTab = ref<InspectorTab>('archive')
const copyMessage = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const requestGeneration = ref(0)
const detailGeneration = ref(0)
let catalogController: AbortController | null = null
let detailController: AbortController | null = null

const layerLabels: Record<SourceLayer, string> = {
  policy: '政策',
  theory: '理论',
  intervention: '干预',
}

const topicOptions: Array<{ value: TopicFilter; label: string }> = [
  { value: 'all', label: '全部资料' },
  { value: 'policy', label: '政策' },
  { value: 'theory', label: '理论' },
  { value: 'intervention', label: '干预' },
]

const rightsOptions: Array<{ value: RightsFilter; label: string }> = [
  { value: 'all', label: '全部权利状态' },
  { value: 'VERIFIED_WITH_CONDITIONS', label: '有条件的权利记录' },
  { value: 'PENDING', label: '待核验' },
]

const sortOptions: Array<{ value: SortMode; label: string }> = [
  { value: 'catalog', label: '目录顺序' },
  { value: 'title', label: '按标题排序' },
]

const layerLabel = (layer: SourceLayer) => layerLabels[layer]
const topicIcon = (topic: TopicFilter) => {
  if (topic === 'all') return Library
  if (topic === 'policy') return ShieldCheck
  if (topic === 'theory') return BookOpen
  return BookOpenCheck
}

function safeWebUrl(value: string | null | undefined): string | null {
  if (!value) return null
  try {
    const parsed = new URL(value)
    if ((parsed.protocol !== 'https:' && parsed.protocol !== 'http:') || parsed.username || parsed.password) return null
    return parsed.href
  } catch {
    return null
  }
}

function sourceHost(value: string | null | undefined): string {
  const safeUrl = safeWebUrl(value)
  if (!safeUrl) return ''
  try {
    return new URL(safeUrl).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

const rightsLabel = (status: ResearchSourceSummary['rights_status']) =>
  status === 'VERIFIED_WITH_CONDITIONS' ? '有条件的权利记录' : '待核验'

const rightsTone = (status: ResearchSourceSummary['rights_status']) =>
  status === 'PENDING' ? 'pending' : 'conditional'

function requestFailureState(error: unknown): Exclude<CatalogState, 'loading' | 'ready'> {
  if (typeof error !== 'object' || error === null || !('code' in error)) return 'error'
  const codeValue = (error as { code?: unknown }).code
  const code = typeof codeValue === 'string' ? codeValue.toUpperCase() : ''
  if (code === 'FORBIDDEN' || code === 'AUTH_FORBIDDEN') return 'forbidden'
  if (code === 'RESEARCH_SERVICE_UNAVAILABLE') return 'unavailable'
  return 'error'
}

const loadedItemCount = computed(() => page.value?.items.length ?? 0)
const selectedPageItem = computed(() =>
  page.value?.items.find((item) => item.source_ref === selectedSourceRef.value) ?? null,
)

const visibleItems = computed(() => {
  if (!page.value || state.value !== 'ready') return []

  const keyword = searchQuery.value.trim().toLocaleLowerCase()
  const matching = page.value.items.filter((item) => {
    if (topicFilter.value !== 'all' && !item.layers.includes(topicFilter.value)) return false
    if (rightsFilter.value !== 'all' && item.rights_status !== rightsFilter.value) return false
    if (!keyword) return true

    const haystack = [
      item.title,
      item.organization,
      item.source_ref,
      item.publication_date,
      sourceHost(item.canonical_url),
      ...item.layers.map(layerLabel),
    ].join(' ').toLocaleLowerCase()
    return haystack.includes(keyword)
  })

  if (sortMode.value === 'title') {
    return [...matching].sort((left, right) => left.title.localeCompare(right.title, 'zh-CN'))
  }
  return matching
})

const pageRangeLabel = computed(() => {
  if (!page.value || page.value.total === 0 || page.value.items.length === 0) return '0 条'
  const first = page.value.offset + 1
  const last = Math.min(page.value.total, page.value.offset + page.value.items.length)
  return first + '–' + last + ' / ' + page.value.total
})

function topicCount(topic: TopicFilter): number {
  if (!page.value) return 0
  if (topic === 'all') return page.value.items.length
  return page.value.items.filter((item) => item.layers.includes(topic)).length
}

function abortRequests() {
  catalogController?.abort()
  detailController?.abort()
  catalogController = null
  detailController = null
}

async function loadCatalog(offset = 0) {
  const generation = ++requestGeneration.value
  detailGeneration.value += 1
  catalogController?.abort()
  detailController?.abort()
  detail.value = null
  selectedSourceRef.value = ''
  copyMessage.value = ''
  detailState.value = 'loading'
  errorMessage.value = ''

  if (!frontendApi.listResearchSourceCatalog) {
    page.value = null
    state.value = 'unavailable'
    errorMessage.value = '当前运行环境没有可读取的已校验来源目录。'
    return
  }

  const scope = scopeKey.value
  catalogController = new AbortController()
  state.value = 'loading'
  try {
    const result = await frontendApi.listResearchSourceCatalog({
      limit: 20,
      offset,
      signal: catalogController.signal,
    })
    if (generation !== requestGeneration.value || scope !== scopeKey.value) return
    page.value = result.data
    state.value = 'ready'
  } catch (error) {
    if (catalogController?.signal.aborted || generation !== requestGeneration.value || scope !== scopeKey.value) return
    page.value = null
    state.value = requestFailureState(error)
    errorMessage.value = state.value === 'forbidden'
      ? '当前账号无权访问此来源目录。'
      : state.value === 'unavailable'
        ? '当前运行环境没有可读取的已校验来源目录。'
        : '来源目录暂时无法读取；未显示未经验证的资料。'
  } finally {
    if (generation === requestGeneration.value) catalogController = null
  }
}

async function openDetail(item: ResearchSourceSummary) {
  if (selectedSourceRef.value === item.source_ref && (detailState.value === 'loading' || detailState.value === 'ready')) return

  const generation = ++detailGeneration.value
  const scope = scopeKey.value
  detailController?.abort()
  selectedSourceRef.value = item.source_ref
  detail.value = null
  copyMessage.value = ''
  detailState.value = 'loading'

  if (!frontendApi.getResearchSource) {
    detailState.value = 'unavailable'
    return
  }

  detailController = new AbortController()
  try {
    const result = await frontendApi.getResearchSource(item.source_ref, { signal: detailController.signal })
    if (generation !== detailGeneration.value || scope !== scopeKey.value) return
    if (result.data.source_ref !== item.source_ref) throw new Error('source detail mismatch')
    detail.value = result.data
    detailState.value = 'ready'
  } catch (error) {
    if (detailController?.signal.aborted || generation !== detailGeneration.value || scope !== scopeKey.value) return
    detail.value = null
    detailState.value = requestFailureState(error)
  } finally {
    if (generation === detailGeneration.value) detailController = null
  }
}

watch(visibleItems, (items) => {
  if (selectedSourceRef.value && items.some((item) => item.source_ref === selectedSourceRef.value)) return

  detailController?.abort()
  detailController = null
  detailGeneration.value += 1
  selectedSourceRef.value = ''
  detail.value = null
  copyMessage.value = ''

  if (items[0] && state.value === 'ready') {
    void openDetail(items[0])
  } else {
    detailState.value = state.value === 'ready' ? 'ready' : 'loading'
  }
}, { flush: 'post' })

function nextPage() {
  if (page.value?.has_more) void loadCatalog(page.value.offset + page.value.limit)
}

function previousPage() {
  if (page.value && page.value.offset > 0) {
    void loadCatalog(Math.max(0, page.value.offset - page.value.limit))
  }
}

function setTopic(value: TopicFilter) {
  topicFilter.value = value
}

function setRightsFilter(value: unknown) {
  if (typeof value !== 'string') return
  if (rightsOptions.some((option) => option.value === value)) rightsFilter.value = value as RightsFilter
}

function setSortMode(value: unknown) {
  if (typeof value !== 'string') return
  if (sortOptions.some((option) => option.value === value)) sortMode.value = value as SortMode
}

function setInspectorTab(value: unknown) {
  if (value === 'archive' || value === 'rights' || value === 'verification') {
    inspectorTab.value = value
  }
}

async function clearSearch() {
  searchQuery.value = ''
  await nextTick()
  searchInput.value?.focus()
}

async function clearFilters() {
  searchQuery.value = ''
  topicFilter.value = 'all'
  rightsFilter.value = 'all'
  sortMode.value = 'catalog'
  await nextTick()
  searchInput.value?.focus()
}

async function copyValue(value: string, label: string) {
  if (!value) return
  if (!navigator.clipboard?.writeText) {
    copyMessage.value = '此浏览器不支持复制；可手动选择编号。'
    return
  }
  try {
    await navigator.clipboard.writeText(value)
    copyMessage.value = '已复制' + label
  } catch {
    copyMessage.value = '复制失败；可手动选择编号。'
  }
}

const canonicalUrl = computed(() => safeWebUrl(detail.value?.canonical_url))
const licenseUrl = computed(() => safeWebUrl(detail.value?.license_url))
const rightsEvidenceUrl = computed(() => safeWebUrl(detail.value?.rights_evidence_url))

watch(scopeKey, () => {
  requestGeneration.value += 1
  detailGeneration.value += 1
  abortRequests()
  page.value = null
  detail.value = null
  selectedSourceRef.value = ''
  state.value = 'loading'
  void loadCatalog(0)
}, { immediate: true })

onBeforeUnmount(() => {
  requestGeneration.value += 1
  detailGeneration.value += 1
  abortRequests()
})
</script>

<template>
  <section class="source-catalog" aria-labelledby="source-catalog-title">
    <section class="source-catalog__banner" aria-label="研究资料档案馆">
      <div class="source-catalog__banner-copy">
        <div class="source-catalog__banner-meta">
          <span class="source-catalog__eyebrow">RESEARCH ARCHIVE</span>
          <span class="source-catalog__readonly"><ShieldCheck :size="14" aria-hidden="true" />只读目录</span>
        </div>
        <h1 id="source-catalog-title">追溯每一份资料</h1>
        <p>整理研究档案。</p>
      </div>
      <div class="source-catalog__books" aria-hidden="true">
        <span class="source-catalog__book source-catalog__book--mint"></span>
        <span class="source-catalog__book source-catalog__book--blue"></span>
        <span class="source-catalog__book source-catalog__book--violet"></span>
        <span class="source-catalog__book source-catalog__book--sand"></span>
        <span class="source-catalog__book source-catalog__book--teal"></span>
      </div>
    </section>

    <section class="source-workbench" aria-label="研究资料工作台">
      <div class="source-workbench__toolbar" role="search" aria-label="检索与筛选">
        <label class="source-workbench__search" for="source-archive-search">
          <Search :size="17" aria-hidden="true" />
          <span class="sr-only">检索标题、主题或来源</span>
          <input
            id="source-archive-search"
            ref="searchInput"
            v-model="searchQuery"
            type="search"
            placeholder="检索标题、主题或来源…"
            aria-describedby="source-search-scope"
          />
          <button v-if="searchQuery" type="button" class="source-workbench__clear" aria-label="清除检索" @click="clearSearch">
            <X :size="15" aria-hidden="true" />
          </button>
        </label>

        <label class="sr-only" for="source-rights-filter">按权利状态筛选</label>
        <RightsSelectRoot :model-value="rightsFilter" @update:model-value="setRightsFilter">
          <RightsSelectTrigger id="source-rights-filter" class="source-workbench__select" aria-label="按权利状态筛选">
            <RightsSelectValue placeholder="全部权利状态" />
            <ChevronDown :size="15" aria-hidden="true" />
          </RightsSelectTrigger>
          <RightsSelectPortal>
            <RightsSelectContent class="source-workbench__select-content" position="popper" :side-offset="6" align="end">
              <RightsSelectViewport class="source-workbench__select-viewport">
                <RightsSelectItem v-for="option in rightsOptions" :key="option.value" :value="option.value" class="source-workbench__select-item">
                  <RightsSelectItemText>{{ option.label }}</RightsSelectItemText>
                  <RightsSelectItemIndicator class="source-workbench__select-indicator"><Check :size="15" aria-hidden="true" /></RightsSelectItemIndicator>
                </RightsSelectItem>
              </RightsSelectViewport>
            </RightsSelectContent>
          </RightsSelectPortal>
        </RightsSelectRoot>

        <label class="sr-only" for="source-sort-order">资料排序方式</label>
        <RightsSelectRoot :model-value="sortMode" @update:model-value="setSortMode">
          <RightsSelectTrigger id="source-sort-order" class="source-workbench__select" aria-label="资料排序方式">
            <RightsSelectValue placeholder="目录顺序" />
            <ChevronDown :size="15" aria-hidden="true" />
          </RightsSelectTrigger>
          <RightsSelectPortal>
            <RightsSelectContent class="source-workbench__select-content" position="popper" :side-offset="6" align="end">
              <RightsSelectViewport class="source-workbench__select-viewport">
                <RightsSelectItem v-for="option in sortOptions" :key="option.value" :value="option.value" class="source-workbench__select-item">
                  <RightsSelectItemText>{{ option.label }}</RightsSelectItemText>
                  <RightsSelectItemIndicator class="source-workbench__select-indicator"><Check :size="15" aria-hidden="true" /></RightsSelectItemIndicator>
                </RightsSelectItem>
              </RightsSelectViewport>
            </RightsSelectContent>
          </RightsSelectPortal>
        </RightsSelectRoot>

        <span id="source-search-scope" class="sr-only">检索、权利筛选和排序仅作用于已加载的服务端分页结果。</span>
      </div>

      <aside class="source-topics" aria-labelledby="source-topics-title">
        <div class="source-topics__heading">
          <p id="source-topics-title">TOPICS / 主题目录</p>
          <span>本页</span>
        </div>
        <nav class="source-topics__list" aria-label="按来源层级筛选">
          <button
            v-for="topic in topicOptions"
            :key="topic.value"
            type="button"
            class="source-topics__item"
            :class="{ 'source-topics__item--active': topicFilter === topic.value }"
            :aria-pressed="topicFilter === topic.value"
            @click="setTopic(topic.value)"
          >
            <component :is="topicIcon(topic.value)" :size="16" aria-hidden="true" />
            <span>{{ topic.label }}</span>
            <span class="source-topics__count">{{ topicCount(topic.value) }}</span>
          </button>
        </nav>
      </aside>

      <section class="source-index" aria-labelledby="source-index-title">
        <header class="source-index__heading">
          <div>
            <h2 id="source-index-title">资料索引</h2>
            <p v-if="state === 'ready'">
              <strong>{{ visibleItems.length }}</strong> 项匹配
              <span>· 本页 {{ loadedItemCount }} 项</span>
            </p>
            <p v-else>服务端分页目录</p>
          </div>
          <div class="source-index__actions">
            <span v-if="page" class="source-index__total">目录 {{ page.total }} 项</span>
            <AppButton variant="quiet" size="sm" :disabled="state === 'loading'" :loading="state === 'loading'" @click="loadCatalog(page?.offset ?? 0)">
              <RefreshCw :size="15" aria-hidden="true" />刷新目录
            </AppButton>
          </div>
        </header>

        <div v-if="state === 'loading'" class="source-index__state" role="status" aria-busy="true">
          <span class="source-index__state-icon"><BookOpenCheck :size="20" aria-hidden="true" /></span>
          <strong>正在读取来源目录</strong>
          <span>只展示服务端返回的来源元数据。</span>
        </div>
        <div v-else-if="state === 'forbidden'" class="source-index__state source-index__state--blocked" role="status">
          <span class="source-index__state-icon"><CircleAlert :size="20" aria-hidden="true" /></span>
          <strong>无权访问来源目录</strong>
          <span>{{ errorMessage }}</span>
        </div>
        <div v-else-if="state === 'error' || state === 'unavailable'" class="source-index__state source-index__state--error" role="status">
          <span class="source-index__state-icon"><CircleAlert :size="20" aria-hidden="true" /></span>
          <strong>{{ state === 'unavailable' ? '来源目录尚未提供' : '来源目录读取失败' }}</strong>
          <span>{{ errorMessage }}</span>
          <AppButton variant="secondary" size="sm" @click="loadCatalog(0)">重新读取</AppButton>
        </div>
        <div v-else-if="page && page.total === 0" class="source-index__state">
          <span class="source-index__state-icon"><BookOpen :size="20" aria-hidden="true" /></span>
          <strong>当前目录没有可显示的资料</strong>
          <span>服务端目录为空；没有使用演示条目填充。</span>
        </div>
        <div v-else-if="page && !page.items.length" class="source-index__state source-index__state--error" role="status">
          <span class="source-index__state-icon"><CircleAlert :size="20" aria-hidden="true" /></span>
          <strong>当前页没有返回资料</strong>
          <span>目录共 {{ page.total }} 项，可返回上一页或重新读取当前页。</span>
          <AppButton v-if="page.offset > 0" variant="secondary" size="sm" @click="previousPage">返回上一页</AppButton>
          <AppButton variant="quiet" size="sm" @click="loadCatalog(page.offset)">重新读取</AppButton>
        </div>
        <div v-else-if="!visibleItems.length" class="source-index__state source-index__state--filtered">
          <span class="source-index__state-icon"><Search :size="20" aria-hidden="true" /></span>
          <strong>当前页没有匹配的资料</strong>
          <span>已按当前页 {{ loadedItemCount }} 项筛选；可调整检索或筛选条件。</span>
          <AppButton variant="quiet" size="sm" @click="clearFilters">清除筛选</AppButton>
        </div>
        <ol v-else class="source-index__rows" tabindex="0" aria-label="当前页资料列表">
          <li v-for="item in visibleItems" :key="item.source_ref" class="source-record">
            <button
              type="button"
              class="source-record__button"
              :class="{ 'source-record__button--active': selectedSourceRef === item.source_ref }"
              :aria-pressed="selectedSourceRef === item.source_ref"
              @click="openDetail(item)"
            >
              <span class="source-record__icon"><FileText :size="17" aria-hidden="true" /></span>
              <span class="source-record__body">
                <span class="source-record__title">{{ item.title }}</span>
                <span class="source-record__meta">
                  <span>{{ item.organization }}</span>
                  <span aria-hidden="true">/</span>
                  <span>{{ item.publication_date }}</span>
                  <span v-if="sourceHost(item.canonical_url)" aria-hidden="true">/</span>
                  <span v-if="sourceHost(item.canonical_url)">{{ sourceHost(item.canonical_url) }}</span>
                </span>
                <span class="source-record__layers">
                  {{ item.layers.length ? item.layers.map(layerLabel).join('、') : '主题未提供' }}
                </span>
              </span>
              <span class="source-record__rights" :class="'source-record__rights--' + rightsTone(item.rights_status)">
                {{ rightsLabel(item.rights_status) }}
              </span>
            </button>
          </li>
        </ol>

        <footer v-if="page && state === 'ready'" class="source-index__pagination">
          <span>{{ pageRangeLabel }}<small v-if="page.total"> · 服务端分页</small></span>
          <div>
            <AppButton variant="quiet" size="sm" :disabled="state === 'loading' || page.offset === 0" @click="previousPage">上一页</AppButton>
            <AppButton variant="quiet" size="sm" :disabled="state === 'loading' || !page.has_more" @click="nextPage">下一页</AppButton>
          </div>
        </footer>
      </section>

      <aside class="source-inspector" aria-label="来源档案检查器">
        <div class="source-inspector__topline">
          <span>SOURCE RECORD</span>
          <code>{{ selectedSourceRef || '未选择' }}</code>
        </div>

        <div v-if="state === 'loading'" class="source-inspector__empty" role="status" aria-busy="true">
          <span class="source-inspector__empty-icon"><BookOpenCheck :size="20" aria-hidden="true" /></span>
          <strong>正在载入来源档案</strong>
          <span>等待服务端目录返回。</span>
        </div>
        <div v-else-if="state === 'forbidden'" class="source-inspector__empty source-inspector__empty--error" role="status">
          <span class="source-inspector__empty-icon"><CircleAlert :size="20" aria-hidden="true" /></span>
          <strong>当前账号无权查看来源档案</strong>
          <span>来源详情不会在权限不足时显示。</span>
        </div>
        <div v-else-if="state === 'error' || state === 'unavailable'" class="source-inspector__empty" role="status">
          <span class="source-inspector__empty-icon"><BookOpen :size="20" aria-hidden="true" /></span>
          <strong>来源档案不可用</strong>
          <span>{{ errorMessage }}</span>
        </div>
        <div v-else-if="page && page.total === 0" class="source-inspector__empty">
          <span class="source-inspector__empty-icon"><BookOpen :size="20" aria-hidden="true" /></span>
          <strong>没有可检查的来源</strong>
          <span>目录返回 0 项记录。</span>
        </div>
        <div v-else-if="!selectedSourceRef && !visibleItems.length" class="source-inspector__empty">
          <span class="source-inspector__empty-icon"><Search :size="20" aria-hidden="true" /></span>
          <strong>没有匹配的来源</strong>
          <span>清除当前页筛选后可继续浏览。</span>
        </div>
        <div v-else-if="detailState === 'loading'" class="source-inspector__empty" role="status" aria-busy="true">
          <span class="source-inspector__paper" aria-hidden="true"><i></i><i></i><Search :size="17" /></span>
          <strong>{{ selectedPageItem?.title || '正在读取来源详情' }}</strong>
          <span>只显示服务端返回的来源元数据。</span>
        </div>
        <div v-else-if="detailState === 'forbidden'" class="source-inspector__empty source-inspector__empty--error" role="status">
          <span class="source-inspector__empty-icon"><CircleAlert :size="20" aria-hidden="true" /></span>
          <strong>无权读取此来源详情</strong>
          <span>当前账号可查看的来源范围由服务端控制。</span>
        </div>
        <div v-else-if="detailState === 'unavailable' || detailState === 'error' || !detail" class="source-inspector__empty" role="status">
          <span class="source-inspector__empty-icon"><BookOpen :size="20" aria-hidden="true" /></span>
          <strong>详情暂时无法读取</strong>
          <span>未展示未验证内容。可以重新选择该资料重试。</span>
        </div>
        <template v-else>
          <div class="source-inspector__record">
            <div class="source-inspector__summary">
              <div class="source-inspector__paper" aria-hidden="true">
                <i></i><i></i>
                <Search :size="17" />
              </div>
              <div class="source-inspector__identity">
                <span>{{ detail.layers.length ? detail.layers.map(layerLabel).join(' / ') : '资料来源' }}</span>
                <h2>{{ detail.title }}</h2>
                <p>{{ detail.organization }} <span aria-hidden="true">/</span> {{ detail.publication_date }}</p>
              </div>
            </div>

            <TabsRoot
              :model-value="inspectorTab"
              class="source-inspector__tabs"
              activation-mode="automatic"
              @update:model-value="setInspectorTab"
            >
              <TabsList class="source-inspector__tab-list" aria-label="来源档案信息">
                <TabsIndicator class="source-inspector__tab-indicator" aria-hidden="true" />
                <TabsTrigger class="source-inspector__tab" value="archive">档案</TabsTrigger>
                <TabsTrigger class="source-inspector__tab" value="rights">权利与来源</TabsTrigger>
                <TabsTrigger class="source-inspector__tab" value="verification">校验记录</TabsTrigger>
              </TabsList>

              <TabsContent class="source-inspector__tab-panel" value="archive">
                <div class="source-inspector__fields">
                  <div><span>来源层级</span><strong>{{ detail.layers.length ? detail.layers.map(layerLabel).join('、') : '未提供' }}</strong></div>
                  <div><span>出版日期</span><strong>{{ detail.publication_date || '未提供' }}</strong></div>
                  <div><span>来源单位</span><strong>{{ detail.organization || '未提供' }}</strong></div>
                  <div><span>来源语言</span><strong>{{ detail.source_language || '未提供' }}</strong></div>
                  <div class="source-inspector__field-wide"><span>研究范围</span><strong>{{ detail.source_population_scope || '未提供' }}</strong></div>
                  <div class="source-inspector__field-wide"><span>配置研究通道</span><strong>{{ page?.consumer_age_min }}–{{ page?.consumer_age_max }} 岁；不代表原始研究样本年龄</strong></div>
                  <div class="source-inspector__field-wide"><span>来源引用</span><code>{{ detail.source_ref }}</code></div>
                </div>
                <section class="source-inspector__abstract" aria-label="档案说明">
                  <h3>档案说明</h3>
                  <p>暂无摘要。当前目录提供来源元数据，不包含文献正文。</p>
                </section>
              </TabsContent>

              <TabsContent class="source-inspector__tab-panel" value="rights">
                <dl class="source-inspector__rights-list">
                  <div><dt>权利记录</dt><dd><span class="source-record__rights" :class="'source-record__rights--' + rightsTone(detail.rights_status)">{{ rightsLabel(detail.rights_status) }}</span></dd></div>
                  <div><dt>许可信息</dt><dd>{{ detail.license || '未提供' }}</dd></div>
                  <div><dt>使用范围</dt><dd>{{ detail.rights_scope_note || '未提供' }}</dd></div>
                  <div><dt>归属信息</dt><dd>{{ detail.attribution || '未提供' }}</dd></div>
                  <div><dt>当前包检索标记</dt><dd>{{ detail.retrieval_eligible ? '是' : '否' }}；不代表权利或专业批准</dd></div>
                </dl>
                <div class="source-inspector__source-links">
                  <a v-if="canonicalUrl" :href="canonicalUrl" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">
                    <span>查看来源</span><small>{{ sourceHost(canonicalUrl) }}</small><ExternalLink :size="14" aria-hidden="true" />
                  </a>
                  <a v-if="licenseUrl" :href="licenseUrl" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">
                    <span>查看许可说明</span><small>{{ sourceHost(licenseUrl) }}</small><ExternalLink :size="14" aria-hidden="true" />
                  </a>
                  <a v-if="rightsEvidenceUrl" :href="rightsEvidenceUrl" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">
                    <span>查看权利证据</span><small>{{ sourceHost(rightsEvidenceUrl) }}</small><ExternalLink :size="14" aria-hidden="true" />
                  </a>
                  <p v-if="!canonicalUrl && !licenseUrl && !rightsEvidenceUrl">没有可打开的 HTTP 或 HTTPS 来源链接。</p>
                </div>
                <p class="source-inspector__boundary">
                  来源包的工程审核状态不等于版权许可、伦理批准、心理专业审核或临床审核。
                </p>
              </TabsContent>

              <TabsContent class="source-inspector__tab-panel" value="verification">
                <ol class="source-inspector__trace">
                  <li>
                    <span class="source-inspector__trace-mark"><FileText :size="14" aria-hidden="true" /></span>
                    <div>
                      <strong>来源记录</strong>
                      <dl>
                        <div><dt>来源引用</dt><dd><code>{{ detail.source_ref }}</code></dd></div>
                        <div><dt>来源包</dt><dd><code>{{ page?.source_package_ref || '未提供' }}</code></dd></div>
                        <div><dt>研究项目</dt><dd><code>{{ page?.study_ref || '未提供' }}</code></dd></div>
                      </dl>
                    </div>
                  </li>
                  <li>
                    <span class="source-inspector__trace-mark"><ShieldCheck :size="14" aria-hidden="true" /></span>
                    <div>
                      <strong>包内工程审核元数据</strong>
                      <dl>
                        <div><dt>审核层级</dt><dd>{{ detail.review.reviewer_kind }}</dd></div>
                        <div><dt>审核状态</dt><dd><code>{{ detail.review.review_status }}</code></dd></div>
                        <div><dt>包状态</dt><dd><code>{{ detail.review.package_status }}</code></dd></div>
                        <div><dt>专业 / 伦理 / 临床 / 测量学批准</dt><dd>均未授予</dd></div>
                        <div><dt>正式发布 / 生产使用</dt><dd>未批准</dd></div>
                      </dl>
                    </div>
                  </li>
                  <li>
                    <span class="source-inspector__trace-mark"><Check :size="14" aria-hidden="true" /></span>
                    <div>
                      <strong>文件校验字段</strong>
                      <dl>
                        <div class="source-inspector__hash-row">
                          <dt>Manifest SHA-256</dt>
                          <dd><code>{{ page?.manifest_sha256 || '未提供' }}</code><button v-if="page?.manifest_sha256" type="button" aria-label="复制 Manifest SHA-256" @click="copyValue(page.manifest_sha256, 'Manifest SHA-256')"><Copy :size="13" aria-hidden="true" /></button></dd>
                        </div>
                        <div class="source-inspector__hash-row">
                          <dt>权利证据 SHA-256</dt>
                          <dd><code>{{ detail.rights_evidence_sha256 || '未提供' }}</code><button v-if="detail.rights_evidence_sha256" type="button" aria-label="复制权利证据 SHA-256" @click="copyValue(detail.rights_evidence_sha256, '权利证据 SHA-256')"><Copy :size="13" aria-hidden="true" /></button></dd>
                        </div>
                        <div class="source-inspector__hash-row">
                          <dt>来源快照 SHA-256</dt>
                          <dd><code>{{ detail.source_capture_sha256 || '未提供' }}</code><button v-if="detail.source_capture_sha256" type="button" aria-label="复制来源快照 SHA-256" @click="copyValue(detail.source_capture_sha256, '来源快照 SHA-256')"><Copy :size="13" aria-hidden="true" /></button></dd>
                        </div>
                      </dl>
                    </div>
                  </li>
                </ol>
                <p class="source-inspector__boundary">
                  哈希值仅作为接口返回的校验字段；不证明来源可信、许可有效或审核已完成。
                </p>
              </TabsContent>
            </TabsRoot>

            <footer class="source-inspector__footer">
              <AppButton variant="quiet" size="sm" :disabled="!selectedSourceRef" @click="copyValue(selectedSourceRef, '来源编号')">
                <Copy :size="14" aria-hidden="true" />复制编号
              </AppButton>
              <span role="status" aria-live="polite">{{ copyMessage }}</span>
            </footer>
          </div>
        </template>
      </aside>
    </section>
  </section>
</template>

<style scoped>
.source-catalog { display: grid; min-width: 0; gap: 14px; }
.source-catalog__readonly { display: inline-flex; min-height: 30px; align-items: center; gap: 6px; padding: 0 9px; border: 1px solid #d8e9ed; border-radius: 999px; color: #47727e; background: #f7fbfc; font-size: 11px; font-weight: 650; white-space: nowrap; }
.source-catalog__readonly svg { color: var(--color-primary-active); }

.source-catalog__banner { position: relative; display: flex; min-height: 128px; align-items: center; justify-content: space-between; gap: 20px; overflow: hidden; padding: 19px 28px; border: 1px solid #e1edf0; border-radius: var(--radius-card); background: linear-gradient(104deg, #fff 0%, #f8fbfc 62%, #f0f8fa 100%); }
.source-catalog__banner-copy { position: relative; z-index: 1; min-width: 0; }
.source-catalog__banner-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.source-catalog__eyebrow { color: #43869a; font-size: 10px; font-weight: 800; letter-spacing: .11em; }
.source-catalog__banner h1 { margin: 6px 0 4px; color: #284453; font-size: 19px; font-weight: 720; line-height: 1.35; }
.source-catalog__banner p { margin: 0; color: #758892; font-size: 12px; line-height: 1.5; }
.source-catalog__books { position: relative; display: flex; min-width: 190px; height: 106px; align-items: flex-end; justify-content: center; gap: 7px; padding: 0 13px 10px; }
.source-catalog__books::after { position: absolute; right: 0; bottom: 8px; left: 0; height: 1px; background: #bfd0d5; box-shadow: 0 3px 7px rgb(74 100 110 / 10%); content: ''; }
.source-catalog__book { position: relative; z-index: 1; display: block; width: 27px; height: 78px; flex: 0 0 27px; border: 1px solid rgb(71 104 116 / 12%); border-radius: 4px 4px 2px 2px; box-shadow: inset 4px 0 rgb(255 255 255 / 60%), 0 5px 11px rgb(47 80 92 / 9%); transform: rotate(var(--book-tilt, 0deg)); transform-origin: bottom center; transition: transform 220ms ease, box-shadow 220ms ease; }
.source-catalog__book::before { position: absolute; top: 13px; right: 7px; left: 7px; height: 2px; background: rgb(255 255 255 / 76%); box-shadow: 0 7px rgb(255 255 255 / 60%), 0 25px rgb(255 255 255 / 48%); content: ''; }
.source-catalog__book--mint { height: 71px; background: #dcefeb; --book-tilt: -3deg; }
.source-catalog__book--blue { height: 88px; background: #dcebf1; --book-tilt: 2deg; }
.source-catalog__book--violet { height: 79px; background: #e9e5f2; --book-tilt: -1deg; }
.source-catalog__book--sand { height: 96px; background: #f0eadc; --book-tilt: 3deg; }
.source-catalog__book--teal { height: 76px; background: #d9ecea; --book-tilt: -2deg; }
.source-catalog__banner:hover .source-catalog__book { box-shadow: inset 4px 0 rgb(255 255 255 / 60%), 0 8px 14px rgb(47 80 92 / 12%); transform: translateY(-3px) rotate(0); }

.source-workbench { display: grid; min-width: 0; grid-template-columns: minmax(148px, 176px) minmax(0, 1fr) minmax(320px, 380px); grid-template-rows: auto minmax(510px, 1fr); overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); box-shadow: var(--shadow-rest); }
.source-workbench__toolbar { display: grid; grid-column: 1 / -1; grid-row: 1; grid-template-columns: minmax(220px, 1fr) minmax(170px, 210px) minmax(145px, 175px); align-items: center; gap: 10px; padding: 14px 16px 8px; }
.source-workbench__search { display: flex; min-width: 0; min-height: 42px; align-items: center; gap: 9px; padding: 0 11px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: #7a8a94; background: var(--color-surface); transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.source-workbench__search:hover { border-color: #b6cbd2; }
.source-workbench__search:focus-within { border-color: var(--color-primary); background: #fff; box-shadow: 0 0 0 3px rgb(0 177 226 / 10%); }
.source-workbench__search > svg { flex: 0 0 auto; }
.source-workbench__search input { width: 100%; min-width: 0; height: 40px; padding: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 13px; }
.source-workbench__search input::placeholder { color: #8b99a1; opacity: 1; }
.source-workbench__search input::-webkit-search-cancel-button { display: none; }
.source-workbench__clear { display: grid; width: 26px; height: 26px; flex: 0 0 26px; place-items: center; border: 0; border-radius: 50%; color: #72838d; background: transparent; cursor: pointer; }
.source-workbench__clear:hover { color: var(--color-text-primary); background: #eef4f6; }
.source-catalog .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; clip-path: inset(50%); }

:global(.source-workbench__select-content) { z-index: 150; width: var(--reka-select-trigger-width, 100%); min-width: min(var(--reka-select-trigger-width, 100%), calc(100vw - 32px)); max-width: calc(100vw - 32px); overflow: hidden; border: 1px solid #dce8ed; border-radius: 10px; background: #fff; box-shadow: 0 14px 32px rgb(34 67 83 / 14%); }
:global(body > [data-reka-popper-content-wrapper]:has(.source-workbench__select-content)) { z-index: 160 !important; }
:global(.source-workbench__select-viewport) { max-height: min(240px, calc(100vh - 150px)); overflow-y: auto; padding: 5px; overscroll-behavior: contain; }
.source-workbench__select { display: flex; width: 100%; min-width: 0; min-height: 42px; align-items: center; justify-content: space-between; gap: 9px; padding: 0 11px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-secondary); background: #fff; font: inherit; font-size: 12px; text-align: left; cursor: pointer; transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.source-workbench__select:hover { border-color: #b6cbd2; }
.source-workbench__select:focus-visible,.source-workbench__select[data-state='open'] { border-color: var(--color-primary); outline: none; box-shadow: 0 0 0 3px rgb(0 177 226 / 10%); }
.source-workbench__select > svg { flex: 0 0 auto; color: #71848f; transition: transform 140ms ease; }
.source-workbench__select[data-state='open'] > svg { transform: rotate(180deg); }
:global(.source-workbench__select-item) { position: relative; display: flex; min-height: 38px; align-items: center; justify-content: space-between; gap: 12px; padding: 7px 10px; border-radius: 7px; color: #425a66; outline: none; font-size: 12px; cursor: pointer; }
:global(.source-workbench__select-item[data-highlighted]) { color: #155e74; background: #eef8fa; }
:global(.source-workbench__select-item[data-disabled]) { opacity: .45; cursor: not-allowed; }
:global(.source-workbench__select-indicator) { display: flex; color: var(--color-primary-active); }

.source-topics { min-width: 0; grid-column: 1; grid-row: 2; padding: 18px 11px 16px 15px; border-right: 1px solid #e8edf0; }
.source-topics__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 5px; padding: 0 7px 10px; }
.source-topics__heading p { margin: 0; color: #6e8290; font-size: 10px; font-weight: 750; letter-spacing: .04em; }
.source-topics__heading > span { color: #9ba8ae; font-size: 10px; }
.source-topics__list { display: grid; gap: 3px; }
.source-topics__item { display: grid; width: 100%; min-height: 39px; grid-template-columns: 18px minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 0 8px; border: 1px solid transparent; border-radius: 8px; color: var(--color-text-secondary); background: transparent; font: inherit; font-size: 12px; text-align: left; cursor: pointer; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.source-topics__item > svg { color: #78909a; }
.source-topics__item:hover { background: #f7fafb; }
.source-topics__item--active { border-color: #d8edf1; color: #087e9d; background: #eff9fb; font-weight: 700; }
.source-topics__item--active > svg { color: var(--color-primary-active); }
.source-topics__count { color: #94a2a9; font-size: 10px; font-variant-numeric: tabular-nums; }
.source-topics__item--active .source-topics__count { color: #4c8a99; }
.source-index { display: flex; min-width: 0; min-height: 0; grid-column: 2; grid-row: 2; flex-direction: column; border-right: 1px solid #e8edf0; }
.source-index__heading { display: flex; min-height: 72px; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px 12px; }
.source-index__heading h2 { margin: 0; color: var(--color-text-primary); font-size: 16px; font-weight: 720; }
.source-index__heading p { margin: 4px 0 0; color: var(--color-text-muted); font-size: 11px; }
.source-index__heading p strong { color: #247c91; font-size: 12px; }
.source-index__actions { display: flex; align-items: center; gap: 8px; }
.source-index__total { color: #7e8d95; font-size: 11px; white-space: nowrap; }
.source-index__rows { min-height: 0; max-height: 500px; flex: 1; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 0 10px; border-top: 1px solid #edf1f3; border-bottom: 1px solid #edf1f3; list-style: none; }
.source-record { margin: 2px 0; }
.source-record__button { position: relative; display: grid; width: 100%; min-height: 70px; grid-template-columns: 34px minmax(0, 1fr) max-content; align-items: center; gap: 10px; padding: 10px 9px; border: 1px solid transparent; border-radius: 8px; color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; transition: border-color 170ms ease, background-color 170ms ease; }
.source-record__button::before { position: absolute; top: 8px; bottom: 8px; left: 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--color-primary); content: ''; opacity: 0; transform: scaleY(.62); transition: opacity 170ms ease, transform 170ms ease; }
.source-record__button:hover { border-color: #e2edf0; background: #f9fbfc; }
.source-record__button--active { border-color: #d8edf1; background: #f1f9fb; }
.source-record__button--active::before { opacity: 1; transform: scaleY(1); }
.source-record__button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: -2px; }
.source-record__icon { position: relative; display: grid; width: 32px; height: 36px; place-items: center; border: 1px solid #d8e9ed; border-radius: 7px 7px 6px 6px; color: #318ba0; background: #f1f8fa; }
.source-record__icon::after { position: absolute; top: -1px; right: -1px; width: 9px; height: 9px; border-left: 1px solid #d8e9ed; border-bottom: 1px solid #d8e9ed; border-radius: 0 6px 0 4px; background: #fff; content: ''; }
.source-record__body { display: grid; min-width: 0; gap: 3px; }
.source-record__title { overflow: hidden; color: #2d4350; font-size: 12px; font-weight: 720; line-height: 1.4; text-overflow: ellipsis; }
.source-record__meta { display: flex; min-width: 0; flex-wrap: wrap; gap: 0 5px; color: #73838c; font-size: 10px; line-height: 1.45; }
.source-record__layers { overflow: hidden; color: #91a0a6; font-size: 10px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.source-record__rights { display: inline-flex; min-height: 22px; align-items: center; justify-content: center; gap: 5px; padding: 0 7px; border: 1px solid #eedcb5; border-radius: 999px; color: #8a651d; background: #fffaf0; font-size: 9px; font-weight: 700; line-height: 1.25; text-align: center; white-space: nowrap; }
.source-record__rights--pending { border-color: #e6e8ea; color: #68747b; background: #f7f8f9; }
.source-record__rights--conditional { border-color: #eedcb5; color: #8a651d; background: #fffaf0; }

.source-index__state { display: flex; min-height: 250px; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 24px; color: var(--color-text-muted); text-align: center; }
.source-index__state > strong { color: #385563; font-size: 14px; font-weight: 700; }
.source-index__state > span:not(.source-index__state-icon) { max-width: 390px; font-size: 12px; line-height: 1.6; }
.source-index__state-icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 12px; color: #59808f; background: #f0f6f8; }
.source-index__state--blocked .source-index__state-icon,.source-index__state--error .source-index__state-icon { color: #9a722d; background: #fbf6e9; }
.source-index__state--filtered .source-index__state-icon { color: #348ca4; background: #eff8fa; }
.source-index__pagination { display: flex; min-height: 52px; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 12px 5px 18px; color: #82929a; font-size: 11px; }
.source-index__pagination small { color: #a0acb1; font-size: 10px; }
.source-index__pagination > div { display: flex; align-items: center; gap: 2px; }
.source-index__pagination :deep(.app-button) { min-height: 34px; padding-inline: 8px; font-size: 11px; }

.source-inspector { display: flex; min-width: 0; min-height: 510px; grid-column: 3; grid-row: 2; flex-direction: column; padding: 17px 17px 9px; }
.source-inspector__topline { display: flex; min-height: 20px; align-items: center; justify-content: space-between; gap: 8px; color: #718590; font-size: 10px; font-weight: 800; letter-spacing: .07em; }
.source-inspector__topline code { max-width: 68%; overflow: hidden; color: #8a9aa2; font-size: 10px; font-weight: 500; letter-spacing: 0; text-overflow: ellipsis; white-space: nowrap; }
.source-inspector__empty { display: flex; min-height: 430px; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 9px; padding: 24px; color: var(--color-text-muted); text-align: center; }
.source-inspector__empty > strong { max-width: 100%; color: #334d5b; font-size: 14px; font-weight: 720; line-height: 1.45; }
.source-inspector__empty > span:not(.source-inspector__empty-icon):not(.source-inspector__paper) { max-width: 320px; color: #7b8c95; font-size: 11px; line-height: 1.55; }
.source-inspector__empty--error .source-inspector__empty-icon { color: #9a722d; background: #fbf6e9; }
.source-inspector__empty-icon { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 50%; color: #41889a; background: #eff7f9; }
.source-inspector__record { display: flex; min-height: 0; flex: 1; flex-direction: column; }
.source-inspector__summary { display: grid; min-height: 114px; grid-template-columns: 64px minmax(0, 1fr); align-items: center; gap: 12px; padding: 12px 0 13px; }
.source-inspector__identity { min-width: 0; }
.source-inspector__identity > span { color: #568291; font-size: 10px; font-weight: 700; }
.source-inspector__identity h2 { display: -webkit-box; overflow: hidden; margin: 3px 0; color: #2c4552; font-size: 15px; font-weight: 740; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.source-inspector__identity p { margin: 0; color: #819098; font-size: 10px; line-height: 1.5; }
.source-inspector__paper { position: relative; display: flex; width: 56px; height: 67px; flex: 0 0 56px; align-items: flex-end; justify-content: flex-end; padding: 0 0 5px 0; color: #34879a; }
.source-inspector__paper::before,.source-inspector__paper::after { position: absolute; width: 39px; height: 54px; border: 1px solid #d8e7eb; border-radius: 5px; background: #fff; box-shadow: 0 5px 12px rgb(59 89 102 / 7%); content: ''; }
.source-inspector__paper::before { top: 4px; left: 3px; transform: rotate(-7deg); }
.source-inspector__paper::after { top: 7px; left: 9px; background: #f9fcfd; transform: rotate(5deg); }
.source-inspector__paper i { position: absolute; z-index: 1; top: 21px; left: 17px; width: 21px; height: 2px; background: #dbe9ec; box-shadow: 0 7px #e6eff1, 0 14px #e6eff1; }
.source-inspector__paper i:nth-child(2) { top: 42px; width: 15px; opacity: .72; }
.source-inspector__paper svg { position: relative; z-index: 2; filter: drop-shadow(0 1px 2px #fff); }
.source-inspector__tabs { display: flex; min-width: 0; flex: 1; flex-direction: column; }
.source-inspector__tab-list { position: relative; display: grid; min-height: 41px; grid-template-columns: repeat(3,minmax(0,1fr)); border-bottom: 1px solid #e9eef0; }
.source-inspector__tab-indicator { position: absolute; top: auto; bottom: -1px; left: 0; width: var(--reka-tabs-indicator-size, 0px); height: max(var(--reka-tabs-indicator-thickness, 0px), 2px); background: var(--color-primary); transform: translateX(var(--reka-tabs-indicator-position, 0px)); transition: transform 190ms ease; pointer-events: none; }
.source-inspector__tab { position: relative; z-index: 1; display: flex; min-width: 0; min-height: 40px; align-items: center; justify-content: center; padding: 7px 4px; border: 0; color: #75868e; background: transparent; font: inherit; font-size: 11px; font-weight: 620; line-height: 1.35; text-align: center; white-space: nowrap; cursor: pointer; transition: color 170ms ease; }
.source-inspector__tab[data-state='active'] { color: #087e9d; font-weight: 720; }
.source-inspector__tab:focus-visible { z-index: 2; outline: 2px solid var(--color-primary); outline-offset: -2px; border-radius: 5px; }
.source-inspector__tab-panel { min-width: 0; min-height: 320px; flex: 1; padding: 13px 0 8px; }
.source-inspector__tab-panel[data-state='active'] { animation: source-panel-in 170ms ease both; }
.source-inspector__fields { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 16px; }
.source-inspector__fields > div { display: grid; min-width: 0; gap: 4px; padding: 9px 0; border-bottom: 1px solid #edf1f2; }
.source-inspector__fields span,.source-inspector__rights-list dt,.source-inspector__trace dt { color: #85939a; font-size: 10px; line-height: 1.4; }
.source-inspector__fields strong { color: #3b515b; font-size: 11px; font-weight: 620; line-height: 1.45; overflow-wrap: anywhere; }
.source-inspector__field-wide { grid-column: 1 / -1; }
.source-inspector__fields code,.source-inspector__trace code { color: #46616d; font-family: var(--font-mono); font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.source-inspector__abstract { margin-top: 13px; padding: 11px 12px; border: 1px solid #e8eef0; border-radius: 8px; background: #f9fbfc; }
.source-inspector__abstract h3 { margin: 0 0 5px; color: #49616b; font-size: 11px; font-weight: 700; }
.source-inspector__abstract p { margin: 0; color: #85939a; font-size: 10px; line-height: 1.55; }

.source-inspector__rights-list { display: grid; gap: 0; margin: 0; }
.source-inspector__rights-list > div { display: grid; grid-template-columns: minmax(92px,.34fr) minmax(0,1fr); gap: 12px; padding: 9px 0; border-bottom: 1px solid #edf1f2; }
.source-inspector__rights-list dd { min-width: 0; margin: 0; color: #40545e; font-size: 11px; line-height: 1.55; overflow-wrap: anywhere; }
.source-inspector__source-links { display: grid; gap: 5px; margin-top: 11px; }
.source-inspector__source-links a { display: grid; min-width: 0; grid-template-columns: minmax(0,1fr) auto 15px; align-items: center; gap: 7px; padding: 7px 0; border-bottom: 1px solid #f0f3f4; color: #187f99; font-size: 11px; font-weight: 650; text-decoration: none; }
.source-inspector__source-links a small { overflow: hidden; color: #8b9aa1; font-size: 10px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.source-inspector__source-links a:hover span { text-decoration: underline; text-underline-offset: 3px; }
.source-inspector__source-links a:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; border-radius: 4px; }
.source-inspector__source-links > p { margin: 6px 0; color: #87959b; font-size: 10px; }
.source-inspector__boundary { margin: 12px 0 0; padding: 9px 10px; border-left: 2px solid #d7e8eb; color: #71848d; background: #f8fbfc; font-size: 10px; line-height: 1.55; }

.source-inspector__trace { display: grid; gap: 11px; margin: 0; padding: 0; list-style: none; }
.source-inspector__trace > li { position: relative; display: grid; grid-template-columns: 25px minmax(0,1fr); gap: 9px; }
.source-inspector__trace > li:not(:last-child)::after { position: absolute; top: 26px; bottom: -12px; left: 12px; width: 1px; background: #dce8eb; content: ''; }
.source-inspector__trace-mark { position: relative; z-index: 1; display: grid; width: 25px; height: 25px; place-items: center; border: 1px solid #d9eaee; border-radius: 50%; color: #37859a; background: #f2f9fa; }
.source-inspector__trace > li > div { min-width: 0; padding: 2px 0 8px; }
.source-inspector__trace strong { color: #435a64; font-size: 11px; font-weight: 700; }
.source-inspector__trace dl { display: grid; gap: 4px; margin: 7px 0 0; }
.source-inspector__trace dl > div { display: grid; grid-template-columns: minmax(108px,.42fr) minmax(0,1fr); gap: 8px; align-items: start; }
.source-inspector__trace dd { display: flex; min-width: 0; align-items: flex-start; gap: 5px; margin: 0; color: #50646d; font-size: 10px; line-height: 1.45; overflow-wrap: anywhere; }
.source-inspector__trace dd code { min-width: 0; }
.source-inspector__hash-row dd { justify-content: space-between; }
.source-inspector__hash-row dd button { display: grid; width: 22px; height: 22px; flex: 0 0 22px; place-items: center; border: 0; border-radius: 5px; color: #6d858e; background: transparent; cursor: pointer; }
.source-inspector__hash-row dd button:hover { color: #127f99; background: #edf7f9; }
.source-inspector__hash-row dd button:focus-visible,.source-inspector__footer :deep(button:focus-visible) { outline: 2px solid var(--color-primary); outline-offset: 2px; }

.source-inspector__footer { display: flex; min-height: 43px; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; padding-top: 6px; border-top: 1px solid #edf1f2; }
.source-inspector__footer > span { min-width: 0; color: #60817e; font-size: 10px; text-align: right; }
.source-inspector__footer :deep(.app-button) { min-height: 33px; padding-inline: 8px; font-size: 11px; }

@keyframes source-panel-in { from { opacity: .6; } to { opacity: 1; } }

@media (max-width: 1140px) {
  .source-workbench { grid-template-columns: minmax(140px,165px) minmax(0,1fr); grid-template-rows: auto minmax(460px,1fr) auto; }
  .source-workbench__toolbar { grid-row: 1; grid-template-columns: minmax(180px,1fr) minmax(165px,195px) minmax(140px,165px); }
  .source-topics { grid-column: 1; grid-row: 2; }
  .source-index { grid-column: 2; grid-row: 2; border-right: 0; }
  .source-inspector { grid-column: 1 / -1; grid-row: 3; min-height: 440px; border-top: 1px solid #e8edf0; }
}
@media (max-width: 760px) {
  .source-catalog { gap: 12px; }
  .source-catalog__banner { min-height: 116px; padding: 16px 18px; }
  .source-catalog__banner h1 { max-width: 430px; font-size: 17px; }
  .source-catalog__books { min-width: 145px; transform: scale(.84); transform-origin: right center; }
  .source-workbench { grid-template-columns: minmax(0,1fr); grid-template-rows: auto auto minmax(460px,auto) auto; }
  .source-workbench__toolbar { grid-column: 1; grid-row: 1; grid-template-columns: minmax(0,1fr) minmax(0,1fr); padding: 12px 12px 7px; }
  .source-workbench__search { grid-column: 1 / -1; }
  .source-topics { grid-column: 1; grid-row: 2; padding: 12px 12px 10px; border-right: 0; border-bottom: 1px solid #e8edf0; }
  .source-topics__heading { padding: 0 3px 7px; }
  .source-topics__list { display: flex; gap: 5px; overflow-x: auto; padding: 1px 1px 4px; scrollbar-width: thin; }
  .source-topics__item { width: auto; min-width: max-content; min-height: 36px; grid-template-columns: 16px auto auto; gap: 6px; padding: 0 9px; }
  .source-index { grid-column: 1; grid-row: 3; min-height: 460px; border-right: 0; border-bottom: 1px solid #e8edf0; }
  .source-index__heading { min-height: 64px; padding-inline: 14px; }
  .source-index__rows { max-height: 440px; padding-inline: 7px; }
  .source-record__button { grid-template-columns: 32px minmax(0,1fr); gap: 8px; padding: 10px 8px; }
  .source-record__rights { grid-column: 2; justify-self: start; margin-top: 2px; }
  .source-inspector { grid-column: 1; grid-row: 4; min-height: 460px; padding: 15px 14px 9px; border-top: 0; }
  .source-inspector__summary { grid-template-columns: 56px minmax(0,1fr); gap: 10px; }
  .source-inspector__tab-panel { min-height: 300px; }
}
@media (max-width: 480px) {
  .source-catalog__banner { min-height: 110px; gap: 7px; padding: 14px 13px; }
  .source-catalog__banner h1 { max-width: 235px; font-size: 16px; }
  .source-catalog__banner p { max-width: 230px; font-size: 11px; }
  .source-catalog__books { min-width: 88px; height: 96px; gap: 4px; padding-inline: 3px; transform: scale(.68); transform-origin: right center; }
  .source-catalog__book { width: 23px; flex-basis: 23px; }
  .source-workbench__toolbar { grid-template-columns: 1fr; gap: 8px; }
  .source-workbench__search { grid-column: 1; }
  .source-workbench__select { min-height: 40px; }
  .source-index__heading { align-items: flex-start; }
  .source-index__actions { flex-direction: column; align-items: flex-end; gap: 4px; }
  .source-record__body { gap: 4px; }
  .source-record__title { font-size: 11px; }
  .source-record__meta,.source-record__layers { font-size: 9px; }
  .source-record__rights { max-width: 100%; white-space: normal; }
  .source-inspector__fields { grid-template-columns: 1fr; }
  .source-inspector__field-wide { grid-column: auto; }
  .source-inspector__rights-list > div { grid-template-columns: 100px minmax(0,1fr); gap: 7px; }
  .source-inspector__trace dl > div { grid-template-columns: minmax(0,1fr); gap: 2px; }
  .source-inspector__trace dd { word-break: break-all; }
  .source-inspector__tab { font-size: 10px; }
}

@media (prefers-reduced-motion: reduce) {
  .source-catalog__book,.source-workbench__search,.source-workbench__select,.source-topics__item,.source-record__button,.source-record__button::before,.source-inspector__tab-indicator,.source-inspector__tab { transition-duration: .01ms; }
  .source-catalog__banner:hover .source-catalog__book { transform: none; }
  .source-inspector__tab-panel[data-state='active'] { animation: none; }
}
</style>
