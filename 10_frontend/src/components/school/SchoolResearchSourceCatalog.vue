<script setup lang="ts">
/* global AbortController */

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { BookOpenCheck, ExternalLink, RefreshCw, ShieldCheck } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import type {
  ResearchSourceCatalogPage,
  ResearchSourceDetail,
  ResearchSourceSummary,
} from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const scopeKey = computed(() => [
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
].join('|'))

type LoadState = 'loading' | 'ready' | 'error' | 'unavailable'
const state = ref<LoadState>('loading')
const page = ref<ResearchSourceCatalogPage | null>(null)
const selectedSourceRef = ref('')
const detail = ref<ResearchSourceDetail | null>(null)
const detailState = ref<LoadState>('loading')
const errorMessage = ref('')
const requestGeneration = ref(0)
const detailGeneration = ref(0)
let catalogController: AbortController | null = null
let detailController: AbortController | null = null

const abortRequests = () => {
  catalogController?.abort()
  detailController?.abort()
  catalogController = null
  detailController = null
}

const loadCatalog = async (offset = 0) => {
  const generation = ++requestGeneration.value
  detailGeneration.value += 1
  catalogController?.abort()
  detailController?.abort()
  detail.value = null
  selectedSourceRef.value = ''
  detailState.value = 'loading'
  errorMessage.value = ''
  if (!frontendApi.listResearchSourceCatalog) {
    page.value = null
    state.value = 'unavailable'
    return
  }
  const scope = scopeKey.value
  catalogController = new AbortController()
  state.value = 'loading'
  try {
    const result = await frontendApi.listResearchSourceCatalog({ limit: 20, offset, signal: catalogController.signal })
    if (generation !== requestGeneration.value || scope !== scopeKey.value) return
    page.value = result.data
    state.value = 'ready'
  } catch {
    if (catalogController?.signal.aborted || generation !== requestGeneration.value || scope !== scopeKey.value) return
    page.value = null
    state.value = 'error'
    errorMessage.value = '当前无法读取经过校验的来源目录。'
  } finally {
    if (generation === requestGeneration.value) catalogController = null
  }
}

const openDetail = async (item: ResearchSourceSummary) => {
  const generation = ++detailGeneration.value
  const scope = scopeKey.value
  detailController?.abort()
  selectedSourceRef.value = item.source_ref
  detail.value = null
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
  } catch {
    if (detailController?.signal.aborted || generation !== detailGeneration.value || scope !== scopeKey.value) return
    detail.value = null
    detailState.value = 'error'
  } finally {
    if (generation === detailGeneration.value) detailController = null
  }
}

const nextPage = () => {
  if (page.value?.has_more) void loadCatalog(page.value.offset + page.value.limit)
}
const previousPage = () => {
  if (page.value && page.value.offset > 0) void loadCatalog(Math.max(0, page.value.offset - page.value.limit))
}
const rightsLabel = (status: ResearchSourceSummary['rights_status']) =>
  status === 'VERIFIED_WITH_CONDITIONS' ? '有条件的权利记录' : '待核验'
const layerLabel = (layer: ResearchSourceSummary['layers'][number]) => ({
  policy: '政策', theory: '理论', intervention: '干预',
}[layer])

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
    <header class="source-catalog__heading">
      <div>
        <span class="source-catalog__eyebrow">AI_ENGINEERING · 只读目录</span>
        <h2 id="source-catalog-title">研究教育来源</h2>
        <p>展示当前固定来源包的文献信息、权利记录和适用范围，不包含片段正文。</p>
      </div>
      <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="loadCatalog(page?.offset ?? 0)">
        <RefreshCw :size="14" aria-hidden="true" />刷新目录
      </AppButton>
    </header>

    <AppStatusCallout
      tone="info"
      title="工程审核状态不等于专业批准"
      body="页面展示来源包内的 AI_ENGINEERING review_status 原值。该字段是包内记录，不代表本次人工审阅结论。心理、伦理、临床、心理测量学和正式发布批准均未授予。"
    />

    <AppCard v-if="state === 'loading'" class="source-message" aria-busy="true"><p>正在读取固定来源包…</p></AppCard>
    <AppCard v-else-if="state === 'unavailable' || state === 'error'" class="source-message source-message--error" role="status">
      <p>{{ errorMessage || '当前运行环境没有可读取的已校验来源目录。' }}</p>
      <AppButton variant="secondary" size="sm" @click="loadCatalog(0)">重新读取</AppButton>
    </AppCard>
    <template v-else-if="page">
      <AppCard class="source-package">
        <div><span>固定来源包</span><strong>{{ page.source_package_ref }}</strong></div>
        <div><span>Manifest SHA-256</span><code>{{ page.manifest_sha256 }}</code></div>
        <div><span>研究通道年龄范围</span><strong>{{ page.consumer_age_min }}–{{ page.consumer_age_max }} 岁</strong></div>
        <div><span>包内审核元数据</span><strong>{{ page.review.reviewer_kind }} · {{ page.review.review_status }}</strong></div>
      </AppCard>

      <div class="source-layout">
        <AppCard class="source-list" aria-label="来源目录条目">
          <div class="source-list__heading"><h3>来源目录</h3><span>{{ page.total }} 条</span></div>
          <p v-if="!page.items.length" class="source-empty">当前固定来源包没有可展示的来源记录。</p>
          <button
            v-for="item in page.items"
            :key="item.source_ref"
            class="source-row"
            type="button"
            :aria-pressed="selectedSourceRef === item.source_ref"
            @click="openDetail(item)"
          >
            <span class="source-row__title">{{ item.title }}</span>
            <span class="source-row__organization">{{ item.organization }} · {{ item.publication_date }}</span>
            <span class="source-row__meta">
              <span>{{ rightsLabel(item.rights_status) }}</span>
              <span>{{ item.retrieval_eligible ? '当前包检索标记：是' : '当前包检索标记：否' }}</span>
            </span>
          </button>
          <div class="source-pagination">
            <AppButton variant="secondary" size="sm" :disabled="page.offset === 0" @click="previousPage">上一页</AppButton>
            <span>{{ page.total ? `${page.offset + 1}–${page.offset + page.items.length} / ${page.total}` : '0 条' }}</span>
            <AppButton variant="secondary" size="sm" :disabled="!page.has_more" @click="nextPage">下一页</AppButton>
          </div>
        </AppCard>

        <AppCard class="source-detail" aria-live="polite">
          <div v-if="!selectedSourceRef" class="source-empty source-empty--detail">
            <BookOpenCheck :size="19" aria-hidden="true" /><p>选择一条来源查看权利证据和使用限制。</p>
          </div>
          <div v-else-if="detailState === 'loading'" class="source-empty" aria-busy="true">正在读取来源详情…</div>
          <div v-else-if="detailState !== 'ready' || !detail" class="source-empty source-empty--error" role="status">
            <p>详情暂时无法读取；未展示未验证内容。</p>
          </div>
          <template v-else>
            <div class="source-detail__heading">
              <span class="source-detail__eyebrow"><ShieldCheck :size="14" aria-hidden="true" />来源元数据</span>
              <h3>{{ detail.title }}</h3>
              <p>{{ detail.organization }} · {{ detail.publication_date }}</p>
            </div>
            <dl class="source-fields">
              <div><dt>来源范围</dt><dd>{{ detail.source_population_scope }}</dd></div>
              <div><dt>来源语言</dt><dd>{{ detail.source_language }}</dd></div>
              <div><dt>配置研究通道</dt><dd>{{ page.consumer_age_min }}–{{ page.consumer_age_max }} 岁；不代表原始研究样本年龄</dd></div>
              <div><dt>来源分类</dt><dd>{{ detail.layers.length ? detail.layers.map(layerLabel).join('、') : '未分类' }}</dd></div>
              <div><dt>权利记录</dt><dd>{{ rightsLabel(detail.rights_status) }} · {{ detail.license }}</dd></div>
              <div><dt>权利范围说明</dt><dd>{{ detail.rights_scope_note }}</dd></div>
              <div><dt>归属信息</dt><dd>{{ detail.attribution }}</dd></div>
              <div><dt>来源包状态</dt><dd>{{ detail.review.package_status }}</dd></div>
              <div><dt>包内审核元数据</dt><dd>{{ detail.review.reviewer_kind }} · {{ detail.review.review_status }}</dd></div>
              <div><dt>专业、伦理、临床及测量学批准</dt><dd>均未授予</dd></div>
              <div><dt>正式发布 / 生产使用</dt><dd>未批准</dd></div>
              <div><dt>当前包检索标记</dt><dd>{{ detail.retrieval_eligible ? '是' : '否' }}；不等于权利或专业批准</dd></div>
              <div><dt>权利证据 SHA-256</dt><dd><code>{{ detail.rights_evidence_sha256 }}</code></dd></div>
              <div v-if="detail.source_capture_sha256"><dt>来源快照 SHA-256</dt><dd><code>{{ detail.source_capture_sha256 }}</code></dd></div>
            </dl>
            <div class="source-links">
              <a :href="detail.canonical_url" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">打开来源页面 <ExternalLink :size="13" aria-hidden="true" /></a>
              <a :href="detail.license_url" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">查看许可说明 <ExternalLink :size="13" aria-hidden="true" /></a>
              <a :href="detail.rights_evidence_url" target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer">查看权利证据 <ExternalLink :size="13" aria-hidden="true" /></a>
            </div>
          </template>
        </AppCard>
      </div>
    </template>
  </section>
</template>

<style scoped>
.source-catalog { display: grid; gap: 13px; margin-bottom: 16px; }
.source-catalog__heading,.source-list__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.source-catalog__heading h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 19px; }
.source-catalog__heading p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.source-catalog__eyebrow,.source-detail__eyebrow { display: inline-flex; align-items: center; gap: 5px; color: #54809c; font-size: 10px; font-weight: 800; letter-spacing: .06em; }
.source-package { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; padding: 13px 16px; }
.source-package > div { display: grid; gap: 4px; min-width: 0; }
.source-package span { color: var(--color-text-muted); font-size: 10px; }
.source-package strong,.source-package code { overflow-wrap: anywhere; color: var(--color-text-primary); font-size: 11px; font-weight: 650; }
.source-layout { display: grid; grid-template-columns: minmax(230px,.72fr) minmax(0,1.28fr); align-items: start; gap: 13px; }
.source-list,.source-detail { min-width: 0; padding: 16px; }
.source-list__heading h3,.source-detail__heading h3 { margin: 0; color: var(--color-text-primary); font-size: 15px; }
.source-list__heading span { color: var(--color-text-muted); font-size: 10px; }
.source-row { display: grid; width: 100%; gap: 5px; margin-top: 8px; padding: 11px; border: 1px solid var(--color-border); border-radius: 9px; color: inherit; background: #fff; text-align: left; cursor: pointer; }
.source-row[aria-pressed="true"] { border-color: #4d9c8a; background: #f3f9f6; box-shadow: 0 0 0 2px rgb(77 156 138 / 12%); }
.source-row:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.source-row__title { color: var(--color-text-primary); font-size: 12px; font-weight: 750; line-height: 1.45; }
.source-row__organization,.source-row__meta { color: var(--color-text-secondary); font-size: 10px; }
.source-row__meta { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.source-pagination { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 12px; color: var(--color-text-muted); font-size: 10px; }
.source-pagination :deep(button) { min-width: 68px; }
.source-detail__heading p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 11px; }
.source-fields { display: grid; gap: 0; margin: 13px 0 0; border-top: 1px solid var(--color-border); }
.source-fields > div { display: grid; grid-template-columns: minmax(120px,.36fr) minmax(0,1fr); gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--color-border); }
.source-fields dt { color: var(--color-text-muted); font-size: 10px; }
.source-fields dd { min-width: 0; margin: 0; color: var(--color-text-primary); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.source-fields code { font-size: 10px; overflow-wrap: anywhere; }
.source-links { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 13px; }
.source-links a { display: inline-flex; align-items: center; gap: 4px; color: #167e9b; font-size: 11px; font-weight: 700; text-decoration: none; }
.source-links a:hover { text-decoration: underline; text-underline-offset: 3px; }
.source-message,.source-empty { display: flex; align-items: center; gap: 8px; min-height: 52px; padding: 12px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 11px; line-height: 1.55; }
.source-message p,.source-empty p { margin: 0; }
.source-message--error,.source-empty--error { color: #8f651d; background: #fcf7eb; }
.source-empty--detail { min-height: 160px; justify-content: center; }
@media(max-width:820px) { .source-layout { grid-template-columns: 1fr; }.source-package { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media(max-width:520px) { .source-catalog__heading { align-items: flex-start; }.source-catalog__heading p { max-width: 260px; }.source-package { grid-template-columns: 1fr; }.source-fields > div { grid-template-columns: minmax(100px,.42fr) minmax(0,1fr); } }
</style>
