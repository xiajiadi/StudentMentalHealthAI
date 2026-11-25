<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import StudentHistoryLibrary from './StudentHistoryLibrary.vue'
import type { StudentHistoryLibraryItem } from './history-library'
import { independentConversations, type IndependentConversation } from '@/services/independent-conversations'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const session = useSessionStore()
const router = useRouter()
const rows = ref<IndependentConversation[]>([])
const offset = ref(0)
const hasMore = ref(false)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const loadMoreError = ref('')
const pageSize = 20
let generation = 0
const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

const items = computed<StudentHistoryLibraryItem[]>(() => rows.value.map((item) => {
  const active = item.status === 'active' || item.status === 'open'
  return {
    key: item.conversationId,
    kind: 'conversation',
    ref: item.conversationId,
    status: active ? 'in_progress' : 'completed',
    statusLabel: active ? '可继续' : '已结束',
    category: 'AI 对话',
    title: `AI 对话 · ${dateFormat.format(new Date(item.createdAt))}`,
    dateLabel: `更新于 ${dateFormat.format(new Date(item.updatedAt))}`,
    poster: '/assets/psynova/academy-feature-education-support.png',
    actionLabel: '查看对话',
    actionVariant: 'secondary',
  }
}))

async function load(append = false) {
  if (append && (!hasMore.value || loading.value || loadingMore.value)) return
  const request = ++generation
  const start = append ? offset.value : 0
  loading.value = !append
  loadingMore.value = append
  error.value = ''
  loadMoreError.value = ''
  if (!append) {
    rows.value = []
    offset.value = 0
    hasMore.value = false
  }
  try {
    const page = await independentConversations.list(start, pageSize)
    if (request !== generation) return
    const existing = new Set(rows.value.map((item) => item.conversationId))
    rows.value = [...rows.value, ...page.items.filter((item) => !existing.has(item.conversationId))]
    offset.value = start + page.items.length
    hasMore.value = page.hasMore && page.items.length > 0
  } catch (cause) {
    if (request !== generation) return
    const message = userFacingApiError(cause, '对话记录暂时无法读取。')
    if (append) loadMoreError.value = message
    else error.value = message
  } finally {
    if (request === generation) {
      loading.value = false
      loadingMore.value = false
    }
  }
}

function openConversation(item: StudentHistoryLibraryItem) {
  void router.push({ name: 'student-workspace', query: { conversation: item.ref } })
}

watch(
  () => [session.user?.userId, session.user?.role, session.user?.activeContext?.schoolRef],
  (_identity, _previous, onCleanup) => {
    onCleanup(() => { generation += 1 })
    if (session.user?.role === 'student') void load()
    else rows.value = []
  },
  { immediate: true },
)
</script>

<template>
  <StudentHistoryLibrary
    :items="items"
    :loading="loading"
    :error="error"
    :has-more="hasMore"
    :loading-more="loadingMore"
    :load-more-error="loadMoreError"
    fixed-view-mode="list"
    :show-toolbar="false"
    error-title="对话记录暂时无法加载"
    empty-title="还没有 AI 对话记录"
    empty-description="创建的会话会显示在这里。记录仅本人可见。"
    empty-icon="support"
    @retry="load()"
    @load-more="load(true)"
    @activate="openConversation"
  />
</template>
