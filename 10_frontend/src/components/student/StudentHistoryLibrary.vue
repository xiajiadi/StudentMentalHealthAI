<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CalendarDays, History } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { workspaceConfig } from '@/components/shell/navigation'
import StudentAssessmentStatusFilter from './StudentAssessmentStatusFilter.vue'
import StudentAssessmentViewModeToggle from './StudentAssessmentViewModeToggle.vue'
import type { StudentAssessmentStatusFilterValue } from './assessment-status-filter'
import type { StudentHistoryLibraryItem } from './history-library'

type ViewMode = 'grid' | 'list'

const props = withDefaults(defineProps<{
  items: StudentHistoryLibraryItem[]
  fixedViewMode?: ViewMode
  showToolbar?: boolean
  loading?: boolean
  error?: string
  errorTitle?: string
  emptyTitle: string
  emptyDescription: string
  emptyIcon?: 'feedback' | 'support'
  hasMore?: boolean
  loadingMore?: boolean
  loadMoreError?: string
}>(), {
  loading: false,
  error: '',
  errorTitle: '记录暂时无法加载',
  hasMore: false,
  loadingMore: false,
  loadMoreError: '',
  showToolbar: true,
})

const emit = defineEmits<{
  activate: [item: StudentHistoryLibraryItem]
  retry: []
  loadMore: []
}>()

const selectedFilter = ref<StudentAssessmentStatusFilterValue>('all')
const viewMode = ref<ViewMode>(props.fixedViewMode ?? 'grid')
const visibleLimit = ref(6)
const emptyIconComponent = computed(() => {
  const target = props.emptyIcon === 'feedback'
    ? '/student/feedback'
    : props.emptyIcon === 'support' ? '/student/support' : '/student/history'
  return workspaceConfig.student?.items.find((item) => item.to === target)?.icon ?? History
})
const cardsPerPage = computed(() => viewMode.value === 'grid' ? 6 : 4)
const filteredItems = computed(() => selectedFilter.value === 'all'
  ? props.items
  : props.items.filter((item) => item.status === selectedFilter.value))
const visibleItems = computed(() => filteredItems.value.slice(0, visibleLimit.value))
const canLoadMore = computed(() => filteredItems.value.length > visibleLimit.value || props.hasMore)

watch([selectedFilter, viewMode], () => {
  visibleLimit.value = cardsPerPage.value
})
watch(() => props.fixedViewMode, (mode) => {
  if (mode) viewMode.value = mode
})
watch(() => props.items.length, () => {
  visibleLimit.value = Math.max(visibleLimit.value, cardsPerPage.value)
})

const requestMore = () => {
  if (props.loadingMore) return
  const nextLimit = visibleLimit.value + cardsPerPage.value
  if (nextLimit > filteredItems.value.length && props.hasMore) {
    visibleLimit.value = nextLimit
    emit('loadMore')
    return
  }
  visibleLimit.value = Math.min(nextLimit, filteredItems.value.length)
}
</script>

<template>
  <section class="history-library" aria-label="记录列表">
    <div v-if="showToolbar && !fixedViewMode" class="history-library__toolbar">
      <StudentAssessmentStatusFilter v-model="selectedFilter" aria-label="按状态筛选记录" />
      <StudentAssessmentViewModeToggle v-model="viewMode" aria-label="记录显示方式" />
    </div>

    <AppStatusCallout v-if="error" tone="attention" :title="errorTitle" :body="error">
      <AppButton variant="secondary" size="sm" @click="emit('retry')">重新加载</AppButton>
    </AppStatusCallout>

    <div v-if="loading && !items.length" class="history-library__loading" :class="{ 'history-library__loading--list': viewMode === 'list' }" aria-busy="true" aria-label="正在加载记录">
      <div v-for="index in 3" :key="index" class="history-library__skeleton">
        <span></span><i></i><i></i>
      </div>
    </div>
    <div v-else-if="visibleItems.length" class="history-library__cards" :class="`history-library__cards--${viewMode}`">
      <article v-for="item in visibleItems" :key="item.key" class="history-library__card">
        <span
          v-if="viewMode === 'list'"
          class="history-library__status history-library__status--list"
          :class="`history-library__status--${item.status}`"
        >{{ item.statusLabel }}</span>
        <div class="history-library__poster">
          <img :src="item.poster" alt="" aria-hidden="true" />
          <span
            v-if="viewMode === 'grid'"
            class="history-library__status"
            :class="`history-library__status--${item.status}`"
          >{{ item.statusLabel }}</span>
        </div>
        <div class="history-library__body">
          <div v-if="viewMode === 'list'" class="history-library__timeline-date">
            <CalendarDays :size="15" aria-hidden="true" />
            <span>{{ item.dateLabel || '时间未提供' }}</span>
          </div>
          <div class="history-library__content">
            <span class="history-library__category">{{ item.category }}</span>
            <h3>{{ item.title }}</h3>
            <div class="history-library__details">
              <div class="history-library__metadata">
                <p v-if="viewMode === 'grid' && item.dateLabel"><CalendarDays :size="14" aria-hidden="true" />{{ item.dateLabel }}</p>
                <p v-if="item.activityLabel"><History :size="14" aria-hidden="true" />{{ item.activityLabel }}</p>
              </div>
              <div v-if="item.actionLabel" class="history-library__actions">
                <AppButton
                  :size="item.actionSize ?? 'sm'"
                  :variant="item.actionVariant ?? 'primary'"
                  :disabled="item.actionDisabled"
                  @click="emit('activate', item)"
                >{{ item.actionLabel }}</AppButton>
              </div>
            </div>
            <div v-if="$slots.details" class="history-library__extra">
              <slot name="details" :item="item" />
            </div>
          </div>
        </div>
      </article>
    </div>
    <div v-else-if="items.length" class="history-library__empty" role="status">
      <span class="history-library__empty-icon"><component :is="emptyIconComponent" :size="22" aria-hidden="true" /></span>
      <div><strong>这个状态下没有记录</strong><p>切换状态可以查看其他记录</p></div>
    </div>
    <div v-else-if="!error && !loading" class="history-library__empty" role="status">
      <span class="history-library__empty-icon"><component :is="emptyIconComponent" :size="22" aria-hidden="true" /></span>
      <div><strong>{{ emptyTitle }}</strong><p>{{ emptyDescription }}</p></div>
    </div>

    <div v-if="canLoadMore || loadMoreError" class="history-library__load-more">
      <AppButton variant="secondary" :disabled="loadingMore" @click="requestMore">
        {{ loadingMore ? '正在加载…' : '加载更多' }}
      </AppButton>
      <p v-if="loadMoreError" role="alert">{{ loadMoreError }}</p>
    </div>
    <div v-if="!loading" class="history-library__count" aria-live="polite">{{ filteredItems.length }} 条</div>
  </section>
</template>

<style scoped>
.history-library { display: grid; gap: 20px; padding: 30px; }
.history-library__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.history-library__cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px 20px; }
.history-library__card { position: relative; display: flex; min-width: 0; flex-direction: column; border: 1px solid #e8edf1; border-radius: 12px; background: #fff; box-shadow: 0 4px 14px rgb(20 36 50 / 6%); transition: transform 180ms ease, box-shadow 180ms ease; }
.history-library__card:hover, .history-library__card:focus-within { transform: translateY(-2px); box-shadow: 0 10px 22px rgb(20 36 50 / 12%); }
.history-library__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; border-radius: 11px 11px 0 0; background: #eaf3f5; }
.history-library__poster img { display: block; width: 100%; height: 100%; object-fit: cover; }
.history-library__status { position: absolute; top: 10px; right: 10px; max-width: calc(100% - 20px); overflow: hidden; padding: 5px 9px; border-radius: 7px; color: #fff; background: #00addf; font-size: 11px; font-weight: 600; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.history-library__status--completed { background: #568f7d; }
.history-library__status--created { color: #fff; background: #00addf; }
.history-library__status--terminal { background: #737985; }
.history-library__status--in_progress { background: #00addf; }
.history-library__status--list { top: 0; right: auto; left: 0; z-index: 3; width: fit-content; padding: 5px 9px; border-radius: 8px 0 8px 0; font-size: 10px; }
.history-library__body { display: flex; min-width: 0; flex: 1; flex-direction: column; padding: 13px 15px 16px; }
.history-library__content { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 6px; }
.history-library__category { color: #00a9dd; font-size: 13px; line-height: 1.35; }
.history-library__content h3 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 17px; font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; }
.history-library__details { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; margin-top: auto; padding-top: 12px; }
.history-library__metadata { display: grid; min-width: 0; gap: 6px; }
.history-library__metadata p { display: flex; align-items: center; gap: 6px; margin: 0; color: #606775; font-size: 12px; line-height: 1.4; }
.history-library__metadata svg { flex: 0 0 auto; }
.history-library__actions { display: flex; justify-content: flex-end; }
.history-library__extra { display: grid; gap: 8px; margin-top: 3px; }
.history-library__timeline-date { display: none; }
.history-library__loading { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.history-library__loading--list { grid-template-columns: minmax(0, 1fr); }
.history-library__loading--list .history-library__skeleton { grid-template-columns: minmax(120px, 160px) minmax(0, 1fr) minmax(160px, 24%); align-items: center; gap: 10px 24px; min-height: 152px; padding: 20px 24px; border: 1px solid #eceef1; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); }
.history-library__loading--list .history-library__skeleton span { grid-column: 3; grid-row: 1 / 4; }
.history-library__loading--list .history-library__skeleton i { grid-column: 2; width: 72%; }
.history-library__loading--list .history-library__skeleton i:last-child { width: 48%; }
.history-library__skeleton { display: grid; align-content: start; gap: 10px; }
.history-library__skeleton span, .history-library__skeleton i { position: relative; display: block; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.history-library__skeleton span { aspect-ratio: 1.91 / 1; border-radius: 11px; }
.history-library__skeleton i { width: 68%; height: 12px; }
.history-library__skeleton i:last-child { width: 48%; }
.history-library__skeleton span::after, .history-library__skeleton i::after { position: absolute; inset: 0; content: ""; background: linear-gradient(100deg, transparent, rgb(255 255 255 / 62%), transparent); transform: translateX(-100%); animation: history-library-shimmer 1.35s ease-in-out infinite; }
.history-library__empty { display: flex; min-height: 180px; align-items: center; justify-content: center; gap: 16px; padding: 24px; border: 1px solid #eceef1; border-radius: 12px; color: #4a766b; background: #fafbfd; }
.history-library__empty-icon { display: grid; width: 44px; height: 44px; flex: 0 0 44px; place-items: center; border-radius: 12px; color: #4a766b; background: #eaf3ef; }
.history-library__empty > div { display: grid; gap: 5px; }
.history-library__empty strong { color: #252832; font-size: 15px; }
.history-library__empty p { margin: 0; color: #686f7a; font-size: 13px; line-height: 1.55; }
.history-library__load-more { display: grid; justify-items: center; gap: 8px; }
.history-library__load-more p { margin: 0; color: var(--color-critical); font-size: 12px; }
.history-library__count { color: #737985; font-size: 12px; line-height: 1.45; text-align: right; }
.history-library__cards--list { position: relative; grid-template-columns: 1fr; row-gap: 18px; }
.history-library__cards--list::before { position: absolute; z-index: 2; top: 0; bottom: 0; left: 196px; width: 1px; background: repeating-linear-gradient(to bottom, #d7dde3 0 5px, transparent 5px 10px); content: ""; pointer-events: none; }
.history-library__cards--list .history-library__card { display: grid; grid-template-columns: minmax(0, 1fr) minmax(180px, 24%); align-items: center; gap: 32px; min-height: 196px; padding: 38px 24px 24px; border: 1px solid #eceef1; box-shadow: var(--shadow-rest); }
.history-library__cards--list .history-library__card::before { position: absolute; z-index: 3; top: 50%; left: 196px; width: 10px; height: 10px; border: 2px solid #fff; border-radius: 50%; background: #cfd5dc; box-shadow: 0 0 0 1px #cfd5dc; content: ""; transform: translate(-50%, -50%); }
.history-library__cards--list .history-library__poster { grid-column: 2; grid-row: 1; border-radius: 8px; }
.history-library__cards--list .history-library__body { grid-column: 1; grid-row: 1; display: grid; grid-template-columns: 160px 24px minmax(0, 1fr); align-items: center; gap: 0; padding: 0; }
.history-library__cards--list .history-library__timeline-date { grid-column: 1; display: flex; min-width: 0; align-items: flex-start; gap: 7px; color: #606775; font-size: 12px; line-height: 1.4; }
.history-library__cards--list .history-library__timeline-date span { min-width: 0; overflow-wrap: anywhere; }
.history-library__cards--list .history-library__content { grid-column: 3; grid-row: 1; }
.history-library__cards--list .history-library__details { grid-template-columns: minmax(0, 1fr); align-items: start; gap: 10px; }
.history-library__cards--list .history-library__actions { justify-content: flex-start; }
.history-library__cards--list .history-library__extra { grid-column: 1 / -1; }
.history-library__cards--list .history-library__card:hover { transform: translateY(-3px); }
@keyframes history-library-shimmer { to { transform: translateX(100%); } }

@media (max-width: 980px) {
  .history-library { padding: 24px; }
  .history-library__cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .history-library__loading { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .history-library__skeleton:last-child { display: none; }
}
@media (max-width: 760px) {
  .history-library { padding: 20px; }
  .history-library__cards--list { grid-template-columns: 1fr; }
  .history-library__cards--list::before, .history-library__cards--list .history-library__card::before { display: none; }
  .history-library__cards--list .history-library__card { grid-template-columns: minmax(0, 1fr) 96px; align-items: start; gap: 12px; min-height: 0; padding: 38px 16px 16px; }
  .history-library__cards--list .history-library__poster { grid-column: 2; grid-row: 1; }
  .history-library__cards--list .history-library__body { grid-column: 1; grid-row: 1; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 8px; }
  .history-library__cards--list .history-library__timeline-date { grid-column: 1; align-items: flex-start; }
  .history-library__cards--list .history-library__content { grid-column: 1; grid-row: 2; }
  .history-library__cards--list .history-library__card::before { display: none; }
  .history-library__cards--list .history-library__status--list { top: 0; left: 0; padding: 5px 9px; font-size: 10px; }
  .history-library__cards--list .history-library__details { grid-template-columns: 1fr; gap: 8px; }
  .history-library__cards--list .history-library__actions { justify-content: flex-start; }
  .history-library__loading { grid-template-columns: 1fr; }
  .history-library__skeleton:not(:first-child) { display: none; }
  .history-library__loading--list .history-library__skeleton { grid-template-columns: minmax(0, 1fr) 96px; gap: 10px 12px; padding: 36px 16px 16px; }
  .history-library__loading--list .history-library__skeleton span { grid-column: 2; grid-row: 1 / 4; }
  .history-library__loading--list .history-library__skeleton i { grid-column: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .history-library__card { transition: none; }
  .history-library__card:hover, .history-library__card:focus-within { transform: none; }
  .history-library__skeleton span::after, .history-library__skeleton i::after { animation: none; transform: none; }
}
</style>
