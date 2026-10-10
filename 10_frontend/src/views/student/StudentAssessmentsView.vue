<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, CalendarDays, ClipboardList, Grid2X2, List, Play, RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { Assessment } from '@/types/contracts'
import { useRouter } from 'vue-router'

type AssessmentFilter = 'all' | 'created' | 'in_progress' | 'completed'
type AssessmentViewMode = 'grid' | 'list'

const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<Assessment[]>([])
const errorMessage = ref('')
const activeFilter = ref<AssessmentFilter>('all')
const viewMode = ref<AssessmentViewMode>('grid')

const filters: { id: AssessmentFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'created', label: '待开始' },
  { id: 'in_progress', label: '进行中' },
  { id: 'completed', label: '已完成' },
]

const posterImages = [
  '/assets/psynova/academy-feature-self-exploration.jpeg',
  '/assets/psynova/academy-feature-assessment-feedback.png',
  '/assets/psynova/academy-feature-education-support.png',
  '/assets/psynova/academy-feature-growth-record.png',
]

const filteredAssessments = computed(() => activeFilter.value === 'all'
  ? assessments.value
  : assessments.value.filter((item) => item.status === activeFilter.value))

const formatDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const latestActivity = (item: Assessment) => formatDate(item.timestamps.completed_at || item.timestamps.started_at)
const statusLabel = (item: Assessment) => {
  if (item.status === 'created') return '待开始'
  if (item.status === 'in_progress') return '进行中'
  if (item.status === 'completed') return '已完成'
  if (item.status === 'abandoned') return '已结束'
  return '不可用'
}

const actionLabel = (item: Assessment) => {
  if (item.status === 'created') return '开始测评'
  if (item.status === 'in_progress') return '继续测评'
  if (item.status === 'completed') return '查看结果'
  return ''
}

const hasAction = (item: Assessment) => Boolean(actionLabel(item))

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    assessments.value = (await frontendApi.listAssessments()).data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '测评列表暂时无法加载，请稍后重试。')
  }
}

const openAssessment = (assessment?: Assessment) => {
  if (assessment?.status === 'completed') {
    void router.push(`/student/assessment/${encodeURIComponent(assessment.assessment_id)}/result`)
    return
  }
  if (assessment?.status === 'created' || assessment?.status === 'in_progress') {
    void router.push(`/student/assessment/${encodeURIComponent(assessment.assessment_id)}`)
    return
  }
  if (!assessment) void router.push('/student/assessment')
}

onMounted(load)
</script>

<template>
  <div class="content-wrap content-wrap--student student-assessments">
    <header class="assessment-hero" aria-labelledby="assessment-page-title">
      <div class="assessment-hero__copy">
        <span class="assessment-hero__eyebrow">学生空间 · 我的测评</span>
        <h1 id="assessment-page-title">我的测评</h1>
        <p>查看已保存的测评会话，或继续完成当前流程。</p>
      </div>
      <AppButton class="assessment-hero__action" @click="openAssessment()">
        <Play :size="15" aria-hidden="true" />开始测评
      </AppButton>
    </header>

    <section class="assessment-library" aria-label="测评列表">
      <div class="assessment-toolbar">
        <div class="assessment-filters" role="group" aria-label="按状态筛选测评">
          <button
            v-for="filter in filters"
            :key="filter.id"
            type="button"
            :class="{ 'assessment-filter--active': activeFilter === filter.id }"
            :aria-pressed="activeFilter === filter.id"
            @click="activeFilter = filter.id"
          >
            {{ filter.label }}
          </button>
        </div>
        <div class="assessment-view-toggle" role="group" aria-label="测评显示方式">
          <button
            type="button"
            aria-label="列表显示"
            :aria-pressed="viewMode === 'list'"
            :class="{ 'assessment-view-toggle__button--active': viewMode === 'list' }"
            @click="viewMode = 'list'"
          >
            <List :size="18" aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label="三列网格显示"
            :aria-pressed="viewMode === 'grid'"
            :class="{ 'assessment-view-toggle__button--active': viewMode === 'grid' }"
            @click="viewMode = 'grid'"
          >
            <Grid2X2 :size="18" aria-hidden="true" />
          </button>
        </div>
      </div>

      <p class="assessment-library__notice">学校分配任务暂未接入；此处显示当前账号可访问的测评会话。</p>

      <div v-if="state === 'loading'" class="assessment-loading" aria-busy="true" aria-label="正在加载测评会话">
        <div class="assessment-loading__poster"></div>
        <div class="assessment-loading__copy"><span></span><span></span><span></span></div>
      </div>
      <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="测评列表暂时无法加载" :body="errorMessage">
        <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
      </AppStatusCallout>
      <div v-else-if="filteredAssessments.length" class="assessment-cards" :class="`assessment-cards--${viewMode}`">
        <article v-for="(item, index) in filteredAssessments" :key="item.assessment_id" class="assessment-card">
          <div class="assessment-card__poster">
            <img :src="posterImages[index % posterImages.length]" alt="" aria-hidden="true" />
            <span class="assessment-card__status" :class="`assessment-card__status--${item.status}`">{{ statusLabel(item) }}</span>
          </div>
          <div class="assessment-card__body">
            <span class="assessment-card__category">测评记录</span>
            <h2>合成演示测评</h2>
            <p class="assessment-card__activity"><CalendarDays :size="15" aria-hidden="true" />{{ item.status === 'created' ? '尚未开始' : latestActivity(item) }}</p>
            <p class="assessment-card__answers"><ClipboardList :size="15" aria-hidden="true" />{{ item.response_summary.items_answered }} 项已记录</p>
          </div>
          <div v-if="hasAction(item)" class="assessment-card__actions">
            <AppButton variant="secondary" size="sm" @click="openAssessment(item)">
              {{ actionLabel(item) }} <ArrowRight :size="15" aria-hidden="true" />
            </AppButton>
          </div>
        </article>
      </div>
      <div v-else class="assessment-empty" role="status">
        <span class="assessment-empty__icon"><ClipboardList :size="21" aria-hidden="true" /></span>
        <div>
          <strong>{{ activeFilter === 'all' ? '目前没有测评记录' : `没有${filters.find((filter) => filter.id === activeFilter)?.label}的测评` }}</strong>
          <p>开始测评后，当前账号可访问的会话会显示在这里。</p>
        </div>
      </div>
      <p class="assessment-library__count" aria-live="polite">{{ filteredAssessments.length }} 项</p>
    </section>
  </div>
</template>

<style scoped>
.student-assessments { padding-top: 0; padding-bottom: 0; }
.assessment-hero { display: flex; min-height: 208px; align-items: center; justify-content: space-between; gap: 28px; padding: 30px; border-radius: 12px; color: #fff; background: linear-gradient(118deg, #264ac5 0%, #3282e0 44%, #6850c9 100%); }
.assessment-hero__copy { display: grid; gap: 8px; }
.assessment-hero__eyebrow { color: rgb(255 255 255 / 78%); font-size: 13px; font-weight: 600; }
.assessment-hero h1 { margin: 0; color: #fff; font-family: var(--font-sans); font-size: 26px; font-weight: 600; line-height: 1.25; }
.assessment-hero p { margin: 0; color: rgb(255 255 255 / 94%); font-size: 16px; line-height: 1.4; }
.assessment-hero__action { flex: 0 0 auto; }
.assessment-library { position: relative; margin-top: 18px; padding: 30px; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); }
.assessment-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.assessment-filters { display: flex; flex-wrap: wrap; gap: 10px; }
.assessment-filters button { min-height: 40px; padding: 0 16px; border: 0; border-radius: 8px; color: #292a32; background: #f0f0f2; cursor: pointer; font: inherit; font-size: 14px; font-weight: 600; transition: color var(--motion-fast), background-color var(--motion-fast); }
.assessment-filters button:hover { background: #e6e7e9; }
.assessment-filters button.assessment-filter--active { color: #fff; background: #00addf; }
.assessment-view-toggle { display: flex; flex: 0 0 auto; gap: 2px; padding: 3px; border: 1px solid #e0e1e5; border-radius: 8px; }
.assessment-view-toggle button { display: grid; width: 34px; height: 32px; place-items: center; border: 0; border-radius: 5px; color: #707682; background: transparent; cursor: pointer; transition: color var(--motion-fast), background-color var(--motion-fast); }
.assessment-view-toggle button:hover { color: #22242a; background: #f2f3f4; }
.assessment-view-toggle button.assessment-view-toggle__button--active { color: #00a9dd; }
.assessment-view-toggle button:focus-visible, .assessment-filters button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.assessment-library__notice { margin: 0 0 22px; color: #6c727f; font-size: 12px; line-height: 1.5; }
.assessment-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 20px; row-gap: 38px; }
.assessment-card { display: flex; min-width: 0; flex-direction: column; }
.assessment-card__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; border-radius: 12px; background: #eaf3f5; }
.assessment-card__poster img { display: block; width: 100%; height: 100%; object-fit: cover; }
.assessment-card__status { position: absolute; top: 0; left: 0; padding: 5px 10px; border-radius: 0 0 10px 0; color: #fff; background: #00addf; font-size: 14px; font-weight: 600; line-height: 1.3; }
.assessment-card__status--completed { background: #568f7d; }
.assessment-card__status--abandoned, .assessment-card__status--invalid { background: #717681; }
.assessment-card__body { display: grid; align-content: start; gap: 6px; padding-top: 12px; }
.assessment-card__category { color: #00a9dd; font-size: 14px; line-height: 1.3; }
.assessment-card h2 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 18px; font-weight: 600; line-height: 1.55; }
.assessment-card__activity, .assessment-card__answers { display: flex; align-items: center; gap: 7px; margin: 0; color: #606775; font-size: 13px; line-height: 1.45; }
.assessment-card__activity svg, .assessment-card__answers svg { flex: 0 0 auto; }
.assessment-card__actions { display: flex; justify-content: flex-end; margin-top: 12px; }
.assessment-empty { display: flex; min-height: 180px; align-items: center; justify-content: center; gap: 16px; padding: 24px; border: 1px solid #eceef1; border-radius: 12px; background: #fafbfd; }
.assessment-empty__icon { display: grid; width: 44px; height: 44px; flex: 0 0 44px; place-items: center; border-radius: 12px; color: #4a766b; background: #eaf3ef; }
.assessment-empty strong { color: #22242a; font-size: 15px; }
.assessment-empty p { margin: 6px 0 0; color: #686f7a; font-size: 13px; line-height: 1.55; }
.assessment-loading { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; }
.assessment-loading__poster { aspect-ratio: 1.91 / 1; border-radius: 12px; background: var(--color-surface-skeleton); }
.assessment-loading__copy { display: grid; grid-column: 1 / -1; gap: 10px; }
.assessment-loading__copy span { width: min(400px, 50%); height: 12px; border-radius: 6px; background: var(--color-surface-skeleton); }
.assessment-loading__copy span:first-child { width: min(240px, 30%); height: 18px; }
.assessment-library > .status-callout { margin-top: 4px; }
.assessment-library__count { margin: 18px 0 0; color: #737985; font-size: 12px; text-align: right; }
.assessment-cards--list { grid-template-columns: 1fr; row-gap: 18px; }
.assessment-cards--list .assessment-card { display: grid; grid-template-columns: minmax(160px, 24%) minmax(0, 1fr) auto; align-items: center; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid #ebecef; }
.assessment-cards--list .assessment-card:last-child { padding-bottom: 0; border-bottom: 0; }
.assessment-cards--list .assessment-card__body { gap: 5px; padding-top: 0; }
.assessment-cards--list .assessment-card__actions { margin: 0; }

@media (max-width: 980px) {
  .assessment-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .assessment-cards--list { grid-template-columns: 1fr; }
  .assessment-loading { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .assessment-loading__poster:last-of-type { display: none; }
}
@media (max-width: 680px) {
  .assessment-hero { min-height: 0; align-items: flex-start; flex-direction: column; padding: 24px; }
  .assessment-hero h1 { font-size: 24px; }
  .assessment-hero p { font-size: 14px; }
  .assessment-library { padding: 20px; }
  .assessment-toolbar { align-items: flex-start; flex-direction: column; }
  .assessment-filters { gap: 7px; }
  .assessment-filters button { min-height: 36px; padding: 0 12px; font-size: 13px; }
  .assessment-view-toggle { align-self: flex-end; margin-top: -50px; }
  .assessment-cards { grid-template-columns: 1fr; row-gap: 26px; }
  .assessment-cards--list { grid-template-columns: 1fr; }
  .assessment-cards--list .assessment-card { grid-template-columns: 112px minmax(0, 1fr); gap: 13px; }
  .assessment-cards--list .assessment-card__poster { grid-row: span 2; }
  .assessment-cards--list .assessment-card__status { font-size: 11px; }
  .assessment-cards--list .assessment-card__actions { grid-column: 2; justify-content: flex-start; }
  .assessment-card__actions { justify-content: flex-start; }
  .assessment-loading { grid-template-columns: 1fr; }
  .assessment-loading__poster:not(:first-child) { display: none; }
  .assessment-empty { align-items: flex-start; justify-content: flex-start; }
}
</style>
