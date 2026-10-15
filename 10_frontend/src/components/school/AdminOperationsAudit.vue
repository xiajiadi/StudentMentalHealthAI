<script setup lang="ts">
/* global AbortController */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Activity, ChevronLeft, ChevronRight, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import type {
  SchoolOperationsAuditCategory,
  SchoolOperationsAuditEvent,
} from '@/api/client'

const props = defineProps<{ scopeKey: string }>()

const categories: Array<{ value: SchoolOperationsAuditCategory | ''; label: string }> = [
  { value: '', label: '全部运营类别' },
  { value: 'organization', label: '学校' },
  { value: 'class', label: '班级' },
  { value: 'member', label: '成员' },
  { value: 'account_batch', label: '账号批次' },
  { value: 'account', label: '账号' },
  { value: 'task', label: '任务' },
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
  SUCCESS: '成功', FAILURE: '未完成', DENIED: '未获授权',
}

const pageSize = 25
const offset = ref(0)
const category = ref<SchoolOperationsAuditCategory | ''>('')
const items = ref<SchoolOperationsAuditEvent[]>([])
const hasMore = ref(false)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const isLoading = computed(() => state.value === 'loading')
const controller = ref<AbortController | null>(null)
let requestGeneration = 0

const load = async () => {
  const generation = ++requestGeneration
  controller.value?.abort()
  const nextController = new AbortController()
  controller.value = nextController
  state.value = 'loading'
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
  } catch {
    if (generation !== requestGeneration || nextController.signal.aborted) return
    items.value = []
    hasMore.value = false
    state.value = 'error'
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
  void load()
})
onMounted(() => void load())
onBeforeUnmount(() => {
  requestGeneration += 1
  controller.value?.abort()
  items.value = []
})
</script>

<template>
  <section class="operations-audit" aria-labelledby="operations-audit-title">
    <AppStatusCallout
      tone="info"
      title="本校运营记录"
      body="只显示能够关联到本校学校、班级、成员、账号批次、账号或测评任务的管理操作。无法证明本校归属的事件不会显示；此列表不包含作答、心理内容、私聊或个案复核，也不代表全库审计。"
    />
    <AppCard class="operations-audit__panel">
      <div class="operations-audit__heading">
        <div>
          <span class="operations-audit__eyebrow"><Activity :size="15" aria-hidden="true" />学校管理</span>
          <h2 id="operations-audit-title">运营记录</h2>
        </div>
        <div class="operations-audit__controls">
          <label class="sr-only" for="operations-audit-category">筛选运营类别</label>
          <select id="operations-audit-category" v-model="category">
            <option v-for="option in categories" :key="option.value || 'all'" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <button type="button" :disabled="isLoading" @click="load">
            <RefreshCw :size="15" aria-hidden="true" />刷新
          </button>
        </div>
      </div>

      <p class="operations-audit__scope">仅展示本校可验证归属的运营事件。操作者身份和资源编号不在此处显示。</p>
      <div v-if="state === 'loading'" class="operations-audit__message" aria-live="polite">正在读取本校运营记录…</div>
      <div v-else-if="state === 'error'" class="operations-audit__message operations-audit__message--error" role="status">
        暂时无法读取运营记录。请稍后刷新；当前不保留旧学校或旧身份的数据。
      </div>
      <div v-else-if="items.length === 0" class="operations-audit__message" role="status">
        当前筛选范围内没有可显示的运营记录。
      </div>
      <template v-else>
        <div class="operations-audit__table-wrap">
          <table>
            <thead><tr><th scope="col">时间</th><th scope="col">操作</th><th scope="col">类别</th><th scope="col">结果</th><th scope="col">数量</th></tr></thead>
            <tbody>
              <tr v-for="item in items" :key="item.event_ref">
                <td>{{ formatTime(item.created_at) }}</td>
                <td>{{ actionLabel[item.action] }}</td>
                <td>{{ categoryLabel[item.resource_category] }}</td>
                <td>{{ resultLabel[item.result] }}</td>
                <td>{{ item.record_count ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <nav class="operations-audit__pagination" aria-label="运营记录分页">
          <span>第 {{ Math.floor(offset / pageSize) + 1 }} 页</span>
          <div>
            <button type="button" :disabled="offset === 0 || isLoading" @click="previousPage">
              <ChevronLeft :size="15" aria-hidden="true" />上一页
            </button>
            <button type="button" :disabled="!hasMore || isLoading" @click="nextPage">
              下一页<ChevronRight :size="15" aria-hidden="true" />
            </button>
          </div>
        </nav>
      </template>
    </AppCard>
  </section>
</template>

<style scoped>
.operations-audit { display: grid; gap: 14px; }
.operations-audit__panel { padding: 22px; }
.operations-audit__heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.operations-audit__heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-size: 17px; }
.operations-audit__eyebrow { display: inline-flex; align-items: center; gap: 6px; color: #287765; font-size: 10px; font-weight: 750; }
.operations-audit__controls,.operations-audit__pagination,.operations-audit__pagination > div { display: flex; align-items: center; gap: 8px; }
.operations-audit button,.operations-audit select { min-height: 34px; padding: 0 10px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-secondary); background: #fff; font: inherit; font-size: 11px; }
.operations-audit button { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.operations-audit button:disabled { opacity: .5; cursor: default; }
.operations-audit__scope { margin: 12px 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
.operations-audit__message { margin-top: 14px; padding: 22px; border-radius: 9px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 12px; }
.operations-audit__message--error { color: #8f651d; background: #fcf7eb; }
.operations-audit__table-wrap { overflow-x: auto; border: 1px solid var(--color-border); border-radius: 9px; }
.operations-audit table { width: 100%; border-collapse: collapse; text-align: left; font-size: 11px; }
.operations-audit th,.operations-audit td { min-width: 100px; padding: 11px 12px; border-bottom: 1px solid var(--color-border); color: var(--color-text-secondary); }
.operations-audit th { color: var(--color-text-primary); background: #f7f8f9; font-weight: 700; }
.operations-audit tbody tr:last-child td { border-bottom: 0; }
.operations-audit__pagination { justify-content: space-between; margin-top: 14px; color: var(--color-text-muted); font-size: 11px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 700px) { .operations-audit__heading { align-items: flex-start; flex-direction: column; }.operations-audit__controls { width: 100%; }.operations-audit__controls select { flex: 1; min-width: 0; }.operations-audit__panel { padding: 16px; } }
</style>
