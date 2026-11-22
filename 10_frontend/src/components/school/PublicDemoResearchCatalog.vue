<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowUpRight, BookOpen, BookOpenCheck, Library, Search, ShieldCheck, Upload } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppInput from '@/components/app/AppInput.vue'
import AppSelect from '@/components/app/AppSelect.vue'
import SchoolResearchLibrary from './SchoolResearchLibrary.vue'

type Layer = 'policy' | 'theory' | 'intervention'
type Entry = {
  id: string
  title: string
  authors: string
  journal: string
  published: string
  license: string
  layer: Layer
  doi: string | null
}
const layers = { policy: '政策与实施', theory: '理论与研究', intervention: '预防与干预' }
const entries = ref<Entry[]>([])
const phase = ref<'loading' | 'ready' | 'error'>('loading')
const layer = ref<Layer | 'all'>('all')
const query = ref('')
const scope = ref('all')
const showImport = ref(false)
const library = ref<InstanceType<typeof SchoolResearchLibrary>>()
const scopeOptions = [
  { value: 'all', label: '全部来源' },
  { value: 'public', label: '公开文献' },
  { value: 'school', label: '本校资料' },
]
const layerIcons = { all: Library, policy: ShieldCheck, theory: BookOpen, intervention: BookOpenCheck }
const sort = ref('recent')
const selectedId = ref('')
const page = ref(1)
const pageSize = 12
const options = [{ value: 'all', label: '全部资料' }, ...Object.entries(layers).map(([value, label]) => ({ value, label }))]
const counts = computed(() => ({
  all: entries.value.length,
  policy: entries.value.filter((entry) => entry.layer === 'policy').length,
  theory: entries.value.filter((entry) => entry.layer === 'theory').length,
  intervention: entries.value.filter((entry) => entry.layer === 'intervention').length,
}))
const filtered = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return entries.value
    .filter((entry) => (layer.value === 'all' || entry.layer === layer.value)
      && (!keyword || [entry.title, entry.authors, entry.journal, entry.doi, entry.id, layers[entry.layer]].some((text) => text?.toLowerCase().includes(keyword))))
    .sort((a, b) => sort.value === 'title' ? a.title.localeCompare(b.title) : b.published.localeCompare(a.published))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visible = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const selected = computed(() => visible.value.find((entry) => entry.id === selectedId.value) ?? visible.value[0])
watch([layer, query, sort], () => { page.value = 1; selectedId.value = '' })
watch(scope, submitSearch)
watch(query, () => { void library.value?.search('') })

function submitSearch() {
  if (scope.value !== 'public') void library.value?.search(query.value)
}

async function load() {
  phase.value = 'loading'
  try {
    const response = await fetch('/assets/psynova/public-research-catalog.v1.json')
    if (!response.ok) throw new Error()
    const payload = await response.json()
    if (payload.source !== 'Europe PMC' || !Array.isArray(payload.items)) throw new Error()
    entries.value = payload.items
    phase.value = 'ready'
  } catch {
    phase.value = 'error'
  }
}
onMounted(load)
</script>

<template>
  <section class="public-catalog" aria-labelledby="public-catalog-title">
    <h1 id="public-catalog-title" class="sr-only">专业资料</h1>
    <section class="public-catalog__search" aria-label="资料检索与导入">
      <form class="public-catalog__filters" @submit.prevent="submitSearch">
        <div class="public-catalog__search-group">
          <AppInput id="public-source-search" v-model="query" label="搜索资料" label-hidden type="search" placeholder="输入关键词、标题、作者或 DOI" />
          <AppButton type="submit" variant="secondary"><Search :size="16" aria-hidden="true" />搜索</AppButton>
        </div>
        <div class="public-catalog__actions">
          <AppSelect id="public-source-scope" v-model="scope" :options="scopeOptions" aria-label="资料来源" single-line />
          <AppSelect v-if="scope !== 'school'" id="public-source-sort" v-model="sort" aria-label="文献排序" single-line :options="[{ value: 'recent', label: '最新发表' }, { value: 'title', label: '按标题排序' }]" />
          <AppButton type="button" aria-haspopup="dialog" @click="showImport = true"><Upload :size="16" aria-hidden="true" />导入资料</AppButton>
        </div>
      </form>
      <SchoolResearchLibrary ref="library" v-model:show-import="showImport" :show-results="scope !== 'public'" :show-empty="scope === 'school'" @imported="submitSearch" />
    </section>
    <template v-if="scope !== 'school'">
    <p v-if="phase === 'loading'" class="public-catalog__state" role="status">正在读取专业资料目录…</p>
    <div v-else-if="phase === 'error'" class="public-catalog__state" role="alert">
      <p>专业资料目录暂时无法读取。</p>
      <AppButton variant="secondary" @click="load">重新读取</AppButton>
    </div>
    <div v-else class="public-catalog__layout">
      <nav class="public-catalog__layers" aria-label="资料主题">
        <AppButton v-for="option in options" :key="option.value" variant="quiet" :aria-pressed="option.value === layer" @click="layer = option.value as Layer | 'all'">
          <span><component :is="layerIcons[option.value as Layer | 'all']" :size="16" aria-hidden="true" />{{ option.label }}</span><strong>{{ counts[option.value as Layer | 'all'] }}</strong>
        </AppButton>
      </nav>
      <div class="public-catalog__results">
        <h2>资料索引 <small>{{ filtered.length }} 份</small></h2>
        <p v-if="!visible.length" class="public-catalog__state">没有符合条件的文献。</p>
        <ul v-else>
          <li v-for="entry in visible" :key="entry.id">
            <button type="button" :aria-pressed="entry.id === selected?.id" @click="selectedId = entry.id">
              <strong>{{ entry.title }}</strong>
              <small>{{ entry.journal }} · {{ entry.published }}</small>
            </button>
          </li>
        </ul>
        <div v-if="pageCount > 1" class="public-catalog__pagination" aria-label="资料分页">
          <AppButton size="sm" variant="secondary" :disabled="page === 1" @click="page -= 1">上一页</AppButton>
          <span>第 {{ page }} / {{ pageCount }} 页</span>
          <AppButton size="sm" variant="secondary" :disabled="page === pageCount" @click="page += 1">下一页</AppButton>
        </div>
      </div>
      <aside class="public-catalog__record" aria-label="文献详情" :aria-live="selectedId ? 'polite' : 'off'">
        <BookOpen :size="22" aria-hidden="true" />
        <template v-if="selected">
          <h2>{{ selected.title }}</h2>
          <dl>
            <div><dt>主题</dt><dd>{{ layers[selected.layer] }}</dd></div>
            <div><dt>作者</dt><dd>{{ selected.authors }}</dd></div>
            <div><dt>期刊</dt><dd>{{ selected.journal }}</dd></div>
            <div><dt>发表</dt><dd>{{ selected.published }}</dd></div>
            <div><dt>开放许可</dt><dd>{{ selected.license }}，具体条款以文献原文为准。</dd></div>
            <div v-if="selected.doi"><dt>DOI</dt><dd>{{ selected.doi }}</dd></div>
          </dl>
          <a :href="`https://europepmc.org/articles/${selected.id}`" target="_blank" rel="noopener noreferrer">打开原文 <ArrowUpRight :size="15" aria-hidden="true" /></a>
        </template>
        <p v-else>选择一份资料查看详情。</p>
      </aside>
    </div>
    </template>
  </section>
</template>

<style scoped>
.public-catalog { display: grid; gap: 14px; }
.public-catalog__search, .public-catalog__layout, .public-catalog__state { border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.public-catalog h2 { margin: 0; }
.public-catalog__record > svg { color: var(--color-primary); flex: none; }
.public-catalog__filters { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; padding: 14px; }
.public-catalog__search-group { display: flex; flex: 1 1 280px; gap: 8px; min-width: 0; }
.public-catalog__search-group > :first-child { flex: 1; min-width: 0; }
.public-catalog__search-group button { flex: none; min-height: 46px; }
.public-catalog__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.public-catalog__actions button { min-height: 46px; }
.public-catalog__actions :deep(.app-select) { width: auto; min-width: 126px; }
.public-catalog__layout { display: grid; grid-template-columns: 175px minmax(0, 1fr) minmax(250px, 31%); }
.public-catalog__layout > * { min-width: 0; padding: 14px; }
.public-catalog__layers { display: flex; flex-direction: column; gap: 6px; border-right: 1px solid var(--color-border); }
.public-catalog__layers button { justify-content: space-between; white-space: normal; }
.public-catalog__layers button span { display: inline-flex; align-items: center; gap: 7px; }
.public-catalog__layers button[aria-pressed='true'] { background: var(--color-info-wash); color: var(--color-primary); }
.public-catalog__results h2 { font-size: 16px; }
.public-catalog__results h2 small { margin-inline-start: 6px; color: var(--color-text-secondary); font-size: 12px; }
.public-catalog__results ul { display: grid; gap: 5px; padding: 0; list-style: none; }
.public-catalog__results li button { display: grid; width: 100%; gap: 5px; padding: 9px 11px; border: 1px solid transparent; border-radius: var(--radius-control); background: transparent; text-align: start; font: inherit; cursor: pointer; }
.public-catalog__results li button:is(:hover,[aria-pressed='true']) { border-color: var(--color-border); background: var(--color-info-wash); }
.public-catalog__results li strong { font-size: 13px; line-height: 1.45; }
.public-catalog__results li small { color: var(--color-text-secondary); font-size: 11px; }
.public-catalog__pagination { display: flex; gap: 8px; align-items: center; color: var(--color-text-secondary); font-size: 12px; }
.public-catalog__record { display: grid; align-content: start; gap: 10px; border-left: 1px solid var(--color-border); }
.public-catalog__record h2 { font-size: 15px; line-height: 1.45; }
.public-catalog__record dl { display: grid; gap: 8px; margin: 0; font-size: 12px; }
.public-catalog__record dt { color: var(--color-text-secondary); }
.public-catalog__record dd { margin: 2px 0 0; overflow-wrap: anywhere; }
.public-catalog__record a { display: inline-flex; gap: 4px; align-items: center; color: var(--color-primary); font-size: 13px; }
.public-catalog__state { padding: 18px; color: var(--color-text-secondary); }
@media (max-width: 890px) {
  .public-catalog__layout { grid-template-columns: 156px minmax(0,1fr); }
  .public-catalog__record { grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--color-border); }
}
@media (max-width: 540px) {
  .public-catalog__layout { grid-template-columns: minmax(0, 1fr); }
  .public-catalog__layers { flex-direction: row; flex-wrap: wrap; border-right: 0; border-bottom: 1px solid var(--color-border); }
  .public-catalog__layers button { gap: 7px; }
}
</style>
