<script setup lang="ts">
/* global AbortController */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Clock3, Search, X } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import TeacherClassSelect, { type TeacherClassOption } from '@/components/teacher/TeacherClassSelect.vue'
import { frontendApi } from '@/services/mock-api'
import type { SchoolOperationsAuditCategory, SchoolOperationsAuditEvent } from '@/api/client'

type LoadState = 'loading' | 'ready' | 'error'
type ResultFilter = SchoolOperationsAuditEvent['result'] | ''

const props = defineProps<{ scopeKey: string }>()
const emit = defineEmits<{
  'summary-change': [summary: { state: LoadState; count: number | null }]
}>()

const categories: Array<{ value: SchoolOperationsAuditCategory | ''; label: string }> = [
  { value: '', label: '全部类别' },
  { value: 'organization', label: '学校' },
  { value: 'class', label: '班级' },
  { value: 'member', label: '成员' },
  { value: 'account_batch', label: '账号批次' },
  { value: 'account', label: '账号' },
  { value: 'task', label: '任务' },
]
const categoryOptions: TeacherClassOption[] = categories.map(({ value, label }) => ({ value, label }))
const resultOptions: TeacherClassOption[] = [
  { value: '', label: '全部结果' },
  { value: 'SUCCESS', label: '成功' },
  { value: 'FAILURE', label: '失败' },
  { value: 'DENIED', label: '未获授权' },
]
const categoryLabel: Record<SchoolOperationsAuditCategory, string> = {
  organization: '学校', class: '班级', member: '成员',
  account_batch: '账号批次', account: '账号', task: '任务',
}
const actionLabel: Record<SchoolOperationsAuditEvent['action'], string> = {
  'school_directory.rename_school': '调整学校名称',
  'school_directory.rename_class': '调整班级名称',
  'school_directory.rename_member': '调整成员名称',
  'school_directory.import_accounts': '导入账号批次',
  'school_directory.activate_account': '激活账号',
  'school_tasks.task.published': '发布测评任务',
}
const resultLabel: Record<SchoolOperationsAuditEvent['result'], string> = {
  SUCCESS: '成功', FAILURE: '失败', DENIED: '未获授权',
}
const resultTone: Record<SchoolOperationsAuditEvent['result'], string> = {
  SUCCESS: 'audit-result--success', FAILURE: 'audit-result--failure', DENIED: 'audit-result--denied',
}

const pageSize = 25
const offset = ref(0)
const category = ref<SchoolOperationsAuditCategory | ''>('')
const resultFilter = ref<ResultFilter>('')
const searchQuery = ref('')
const items = ref<SchoolOperationsAuditEvent[]>([])
const hasMore = ref(false)
const state = ref<LoadState>('loading')
const errorMessage = ref('')
const selectedEventRef = ref('')
const controller = ref<AbortController | null>(null)
let requestGeneration = 0

const visibleItems = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return items.value.filter((item) => {
    if (resultFilter.value && item.result !== resultFilter.value) return false
    if (!query) return true
    return `${actionLabel[item.action]} ${item.action}`.toLocaleLowerCase().includes(query)
  })
})
const selectedEvent = computed(() => visibleItems.value.find((item) => item.event_ref === selectedEventRef.value)
  ?? visibleItems.value[0]
  ?? null)
const currentPage = computed(() => Math.floor(offset.value / pageSize) + 1)
const pageCountText = computed(() => `本页 ${items.value.length} 条`)
const localFilterActive = computed(() => Boolean(searchQuery.value.trim()) || Boolean(resultFilter.value))
const categoryModel = computed<string>({
  get: () => category.value,
  set: (value) => {
    if (categories.some((option) => option.value === value)) category.value = value as SchoolOperationsAuditCategory | ''
  },
})
const resultModel = computed<string>({
  get: () => resultFilter.value,
  set: (value) => {
    if (resultOptions.some((option) => option.value === value)) resultFilter.value = value as ResultFilter
  },
})

watch(visibleItems, (rows) => {
  if (!rows.some((item) => item.event_ref === selectedEventRef.value)) {
    selectedEventRef.value = rows[0]?.event_ref ?? ''
  }
}, { immediate: true })

const errorText = (error: unknown) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  if (['FORBIDDEN', '403'].includes(code)) return '当前账号没有查看本校运营记录的权限。'
  if (['AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(code)) return '登录状态已失效，请重新登录。'
  return '暂时无法读取运营记录，请稍后刷新。'
}

const load = async () => {
  const generation = ++requestGeneration
  controller.value?.abort()
  const nextController = new AbortController()
  controller.value = nextController
  state.value = 'loading'
  errorMessage.value = ''
  emit('summary-change', { state: 'loading', count: null })
  try {
    if (!frontendApi.listSchoolOperationsAudit) throw new Error('unavailable')
    const page = await frontendApi.listSchoolOperationsAudit({
      offset: offset.value,
      limit: pageSize,
      category: category.value || null,
      signal: nextController.signal,
    })
    if (generation !== requestGeneration) return
    items.value = page.data.items
    hasMore.value = page.data.has_more
    state.value = 'ready'
    emit('summary-change', { state: 'ready', count: page.data.items.length })
  } catch (error) {
    if (generation !== requestGeneration || nextController.signal.aborted) return
    items.value = []
    hasMore.value = false
    state.value = 'error'
    errorMessage.value = errorText(error)
    emit('summary-change', { state: 'error', count: null })
  }
}

const changeCategory = () => {
  offset.value = 0
  void load()
}
const previousPage = () => {
  if (offset.value === 0 || state.value === 'loading') return
  offset.value = Math.max(0, offset.value - pageSize)
  void load()
}
const nextPage = () => {
  if (!hasMore.value || state.value === 'loading') return
  offset.value += pageSize
  void load()
}
const clearSearch = () => { searchQuery.value = '' }
const selectEvent = (item: SchoolOperationsAuditEvent) => { selectedEventRef.value = item.event_ref }
const formatTime = (value: string) => {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '时间未知'
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

watch(category, changeCategory)
watch(() => props.scopeKey, () => {
  requestGeneration += 1
  controller.value?.abort()
  offset.value = 0
  items.value = []
  hasMore.value = false
  selectedEventRef.value = ''
  void load()
})
onMounted(() => void load())
onBeforeUnmount(() => {
  requestGeneration += 1
  controller.value?.abort()
  items.value = []
})

defineExpose({ refresh: load })
</script>

<template>
  <section class="operations-audit" aria-label="操作记录" :aria-busy="state === 'loading'">
    <div class="operations-audit__toolbar">
      <label class="operations-audit__search">
        <span class="sr-only">搜索操作类型</span>
        <Search :size="16" aria-hidden="true" />
        <input v-model="searchQuery" type="search" autocomplete="off" placeholder="搜索本页操作类型…">
        <button v-if="searchQuery" type="button" aria-label="清空搜索" @click="clearSearch"><X :size="15" aria-hidden="true" /></button>
      </label>
      <TeacherClassSelect v-model="categoryModel" :options="categoryOptions" aria-label="操作类别" />
      <TeacherClassSelect v-model="resultModel" :options="resultOptions" aria-label="操作结果" />
    </div>

    <div class="operations-audit__layout">
      <AppCard class="operations-audit__list-panel">
        <header class="operations-audit__list-heading">
          <div><h2>操作记录</h2><span>{{ pageCountText }}</span></div>
          <span>第 {{ currentPage }} 页</span>
        </header>
        <div v-if="state === 'loading'" class="operations-audit__state" role="status" aria-live="polite" aria-busy="true">正在读取本校记录…</div>
        <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="记录暂不可用" :body="errorMessage" role="alert" />
        <div v-else-if="!visibleItems.length" class="operations-audit__state" role="status">
          <strong>{{ items.length ? '本页没有匹配记录' : offset ? '当前页记录已变化' : '没有可显示的运营记录' }}</strong>
          <span>{{ items.length ? '调整搜索或结果筛选，也可以继续翻页。' : offset ? '返回上一页或刷新列表。' : '服务端当前筛选范围未返回记录。' }}</span>
        </div>
        <div v-else class="operations-audit__table-wrap">
          <table>
            <thead><tr><th scope="col">时间</th><th scope="col">操作</th><th scope="col">类别</th><th scope="col">结果</th></tr></thead>
            <tbody>
              <tr
                v-for="item in visibleItems"
                :key="item.event_ref"
                :class="{ 'operations-audit__row--selected': selectedEvent?.event_ref === item.event_ref }"
                :aria-selected="selectedEvent?.event_ref === item.event_ref"
                tabindex="0"
                @click="selectEvent(item)"
                @keydown.enter.prevent="selectEvent(item)"
                @keydown.space.prevent="selectEvent(item)"
              >
                <td><span class="operations-audit__time"><Clock3 :size="13" aria-hidden="true" />{{ formatTime(item.created_at) }}</span></td>
                <td><strong>{{ actionLabel[item.action] }}</strong><small>{{ item.action }}</small></td>
                <td>{{ categoryLabel[item.resource_category] }}</td>
                <td><span class="audit-result" :class="resultTone[item.result]">{{ resultLabel[item.result] }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <nav class="operations-audit__pagination" aria-label="操作记录分页">
          <span>第 {{ currentPage }} 页 · {{ localFilterActive ? '本页筛选' : '服务端分页' }}</span>
          <div>
            <button type="button" :disabled="offset === 0 || state === 'loading'" @click="previousPage"><ChevronLeft :size="15" aria-hidden="true" />上一页</button>
            <button type="button" :disabled="!hasMore || state === 'loading'" @click="nextPage">下一页<ChevronRight :size="15" aria-hidden="true" /></button>
          </div>
        </nav>
      </AppCard>

      <AppCard class="operations-audit__detail" aria-label="操作详情">
        <template v-if="selectedEvent">
          <header><span>操作详情</span><strong>{{ actionLabel[selectedEvent.action] }}</strong></header>
          <dl>
            <div><dt>时间</dt><dd>{{ formatTime(selectedEvent.created_at) }}</dd></div>
            <div><dt>类别</dt><dd>{{ categoryLabel[selectedEvent.resource_category] }}</dd></div>
            <div><dt>结果</dt><dd><span class="audit-result" :class="resultTone[selectedEvent.result]">{{ resultLabel[selectedEvent.result] }}</span></dd></div>
            <div><dt>记录数量</dt><dd>{{ selectedEvent.record_count ?? '—' }}</dd></div>
          </dl>
        </template>
        <div v-else class="operations-audit__detail-empty"><strong>{{ state === 'loading' ? '正在同步记录' : '选择一条记录' }}</strong><span>详情仅包含服务端提供的运营字段。</span></div>
      </AppCard>
    </div>
  </section>
</template>

<style scoped>
.operations-audit { display: grid; gap: 8px; min-width: 0; }
.operations-audit__toolbar { display: grid; grid-template-columns: minmax(220px,1fr) minmax(145px,.38fr) minmax(145px,.38fr); gap: 9px; }
.operations-audit__search { display: flex; min-width: 0; min-height: 40px; align-items: center; gap: 8px; padding: 0 11px; border: 1px solid var(--color-border); border-radius: 9px; color: #82939b; background: #fff; }
.operations-audit__search:focus-within { border-color: #78c4d4; box-shadow: 0 0 0 3px rgb(0 177 226 / 9%); }
.operations-audit__search input { width: 100%; min-width: 0; height: 36px; padding: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 15px; }
.operations-audit__search input::placeholder { color: #94a1a9; font-size: 14px; }
.operations-audit__search button { display: grid; width: 25px; height: 25px; flex: 0 0 25px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: #7d8e98; background: transparent; cursor: pointer; }
.operations-audit__toolbar :deep(.teacher-class-select__trigger) { height: 40px; font-size: 13px; }
.operations-audit__toolbar :deep(.teacher-class-select__option) { font-size: 14px; }
.operations-audit__toolbar :deep(.teacher-class-select__empty) { font-size: 13px; }
.operations-audit__toolbar :deep(.teacher-class-select__search input) { font-size: 13px; }
.operations-audit__layout { display: grid; grid-template-columns: minmax(0,1.5fr) minmax(280px,1fr); align-items: stretch; gap: 12px; min-width: 0; }
.operations-audit__list-panel { display: flex; min-width: 0; flex-direction: column; overflow: hidden; padding: 0; }
.operations-audit__list-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 58px; padding: 12px 16px; border-bottom: 1px solid #edf1f3; }
.operations-audit__list-heading > div { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.operations-audit__list-heading h2 { margin: 0; color: #2c4655; font-size: 17px; font-weight: 700; }
.operations-audit__list-heading span { color: #82929a; font-size: 13px; }
.operations-audit__table-wrap { min-width: 0; overflow-x: auto; }
.operations-audit table { width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }
.operations-audit th { padding: 10px 12px; border-bottom: 1px solid #edf1f3; color: #82929a; background: #fbfcfd; font-size: 13px; font-weight: 650; white-space: nowrap; }
.operations-audit td { min-width: 85px; padding: 11px 12px; border-bottom: 1px solid #f0f3f5; color: #506774; vertical-align: middle; }
.operations-audit td:nth-child(2) { min-width: 170px; }
.operations-audit tbody tr { outline: none; cursor: pointer; transition: background-color 150ms ease, box-shadow 150ms ease; }
.operations-audit tbody tr:hover { background: #f8fcfd; }
.operations-audit tbody tr:focus-visible { box-shadow: inset 0 0 0 2px #55bad0; }
.operations-audit tbody tr:last-child td { border-bottom: 0; }
.operations-audit__row--selected { background: #eef9fb; box-shadow: inset 3px 0 #36b1cc; }
.operations-audit td strong,.operations-audit td small { display: block; }
.operations-audit td strong { color: #3a5665; font-size: 14px; font-weight: 680; }
.operations-audit td small { margin-top: 3px; color: #9aa8ae; font-family: var(--font-mono); font-size: 11px; }
.operations-audit__time { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.operations-audit__time svg { flex: 0 0 auto; color: #8b9ba2; }
.audit-result { display: inline-flex; min-height: 24px; align-items: center; padding: 3px 8px; border-radius: 999px; font-size: 13px; font-weight: 700; white-space: nowrap; }
.audit-result--success { color: #247765; background: #eaf5f1; }
.audit-result--failure { color: #9c5b38; background: #fbf0e9; }
.audit-result--denied { color: #75623e; background: #f6f2e8; }
.operations-audit__state { display: grid; min-height: 230px; align-content: center; justify-items: center; gap: 7px; padding: 22px; color: #728690; text-align: center; }
.operations-audit__state strong { color: #435e6c; font-size: 16px; }
.operations-audit__state span { font-size: 14px; line-height: 1.5; }
.operations-audit__pagination { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: auto; padding: 11px 14px; border-top: 1px solid #edf1f3; color: #81919a; font-size: 13px; }
.operations-audit__pagination > div { display: flex; gap: 6px; }
.operations-audit__pagination button { display: inline-flex; min-height: 31px; align-items: center; gap: 4px; padding: 0 8px; border: 1px solid var(--color-border); border-radius: 7px; color: #536b77; background: #fff; font: inherit; font-size: 13px; cursor: pointer; }
.operations-audit__pagination button:disabled { opacity: .48; cursor: default; }
.operations-audit__detail { display: flex; min-width: 0; flex-direction: column; padding: 18px; }
.operations-audit__detail > header { display: grid; gap: 7px; padding-bottom: 14px; border-bottom: 1px solid #edf1f3; }
.operations-audit__detail > header > span { color: #75909b; font-size: 13px; }
.operations-audit__detail > header strong { overflow-wrap: anywhere; color: #2e4a58; font-size: 19px; }
.operations-audit__detail dl { display: grid; gap: 0; margin: 8px 0 0; }
.operations-audit__detail dl > div { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; padding: 12px 0; border-bottom: 1px solid #f0f3f5; }
.operations-audit__detail dt { color: #84949c; font-size: 13px; }
.operations-audit__detail dd { margin: 0; color: #405c69; font-size: 14px; font-weight: 620; text-align: right; overflow-wrap: anywhere; }
.operations-audit__detail-empty { display: grid; min-height: 220px; align-content: center; justify-items: center; gap: 7px; color: #81919a; text-align: center; }
.operations-audit__detail-empty strong { color: #435e6c; font-size: 16px; }
.operations-audit__detail-empty span { font-size: 14px; line-height: 1.5; }
.operations-audit :deep(.status-callout h2) { font-size: 16px; }
.operations-audit :deep(.status-callout p) { font-size: 15px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 900px) { .operations-audit__layout { grid-template-columns: minmax(0,1fr); }.operations-audit__detail { min-height: 210px; } }
@media (max-width: 660px) { .operations-audit__toolbar { grid-template-columns: repeat(2,minmax(0,1fr)); }.operations-audit__search { grid-column: 1 / -1; }.operations-audit__layout { gap: 10px; }.operations-audit__list-heading { padding-inline: 12px; }.operations-audit th,.operations-audit td { padding: 9px 10px; }.operations-audit__detail { padding: 15px; } }
@media (prefers-reduced-motion: reduce) { .operations-audit tbody tr { transition: none; } }
</style>
