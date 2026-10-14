<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { schoolResearchFeedback, type StudentResearchFeedback } from '@/services/school-research-feedback'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'

const PAGE_SIZE = 20
const session = useSessionStore()
const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const rows = ref<StudentResearchFeedback[]>([])
const total = ref(0)
const offset = ref(0)
const requestError = ref('')
const sequence = ref(0)
const isStudent = computed(() => session.user?.role === 'student')
const hasMore = computed(() => offset.value + rows.value.length < total.value)
let mounted = false

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function clearPrivateState() {
  rows.value = []
  total.value = 0
  offset.value = 0
  requestError.value = ''
  sequence.value += 1
}

async function load(nextOffset = 0) {
  if (!isStudent.value) {
    clearPrivateState()
    state.value = 'idle'
    return
  }
  const current = ++sequence.value
  state.value = 'loading'
  requestError.value = ''
  try {
    const result = await schoolResearchFeedback.listStudent(nextOffset, PAGE_SIZE)
    if (!mounted || current !== sequence.value || !isStudent.value) return
    rows.value = result.items
    total.value = result.total
    offset.value = nextOffset
    state.value = 'ready'
  } catch (error) {
    if (current !== sequence.value || !isStudent.value) return
    rows.value = []
    total.value = 0
    state.value = 'error'
    requestError.value = userFacingApiError(error, '研究演示反馈暂时无法加载。')
  }
}

watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    clearPrivateState()
    if (next[0] === 'student') void load()
    else state.value = 'idle'
  },
)

onMounted(() => {
  mounted = true
  if (isStudent.value) void load()
})

onBeforeUnmount(() => {
  mounted = false
  clearPrivateState()
})
</script>

<template>
  <section class="student-research-feedback" aria-labelledby="student-research-feedback-title">
    <header class="student-research-feedback__header">
      <div><span class="student-research-feedback__kicker">研究模拟 · 教育支持</span><h2 id="student-research-feedback-title">研究演示反馈</h2><p>这里只显示服务端已发布给当前合成演示账户的内容。</p></div>
      <AppButton variant="quiet" size="sm" :disabled="state === 'loading'" aria-label="刷新研究演示反馈" @click="load(offset)"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton>
    </header>
    <AppStatusCallout tone="info" title="仅限研究演示" body="内容属于一般教育支持，不是诊断、治疗或心理测量结论；当前流程未获准用于正式发布或运营。" />
    <p v-if="state === 'loading'" class="student-research-feedback__state" role="status" aria-busy="true">正在读取已发布内容…</p>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="研究演示反馈暂不可用" :body="requestError"><AppButton variant="secondary" size="sm" @click="load(offset)">重新加载</AppButton></AppStatusCallout>
    <AppCard v-else-if="state === 'ready' && !rows.length" class="student-research-feedback__empty"><strong>目前没有单独发布的研究演示反馈</strong><p>完成记录本身不会显示反馈正文；只有服务端明确发布的内容才会出现在这里。</p></AppCard>
    <div v-else class="student-research-feedback__list">
      <AppCard v-for="item in rows" :key="item.feedback_ref" class="student-research-feedback__item">
        <header><h3>{{ item.title }}</h3><AppBadge tone="teal" dot>演示账户可见</AppBadge></header>
        <p class="student-research-feedback__body">{{ item.body }}</p>
        <p class="student-research-feedback__time">发布于 {{ formatDate(item.published_at) }}</p>
      </AppCard>
    </div>
    <footer v-if="state === 'ready' && total > PAGE_SIZE" class="student-research-feedback__pager">
      <span>{{ offset + 1 }}–{{ offset + rows.length }} / {{ total }}</span>
      <span><AppButton variant="quiet" size="sm" :disabled="state === 'loading' || offset === 0" @click="load(Math.max(0, offset - PAGE_SIZE))">上一页</AppButton><AppButton variant="quiet" size="sm" :disabled="state === 'loading' || !hasMore" @click="load(offset + PAGE_SIZE)">下一页</AppButton></span>
    </footer>
  </section>
</template>

<style scoped>
.student-research-feedback { display: grid; gap: 12px; margin-top: 30px; }
.student-research-feedback__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 14px; }
.student-research-feedback__header h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 23px; }
.student-research-feedback__header p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.student-research-feedback__kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.student-research-feedback__item { display: grid; gap: 9px; padding: 16px 18px; }
.student-research-feedback__item>header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.student-research-feedback__item h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.student-research-feedback__body { margin: 0; color: var(--color-text-primary); font-size: 13px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.student-research-feedback__time,.student-research-feedback__state { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.55; }
.student-research-feedback__empty { display: grid; gap: 7px; padding: 20px; }
.student-research-feedback__empty strong { color: var(--color-text-primary); font-size: 13px; }
.student-research-feedback__empty p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.student-research-feedback__pager { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--color-text-muted); font-size: 10px; }
.student-research-feedback__pager>span:last-child { display: flex; gap: 5px; }
.student-research-feedback :deep(.status-callout) { margin: 0; }
@media(max-width:680px) { .student-research-feedback__header,.student-research-feedback__item>header { align-items: flex-start; flex-direction: column; }.student-research-feedback__pager { align-items: flex-start; flex-direction: column; } }
</style>
