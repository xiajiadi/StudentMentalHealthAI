<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { CalendarDays, ClipboardList, History, LayoutDashboard, Play, RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentAssignedTasks from '@/components/school/StudentAssignedTasks.vue'
import { frontendApi } from '@/services/mock-api'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { Assessment } from '@/types/contracts'
import type { AssessmentListEntry } from '@/api/client'
import { useRouter } from 'vue-router'

type AssessmentFilter = 'all' | 'created' | 'in_progress' | 'completed'
type AssessmentViewMode = 'grid' | 'list'

const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<AssessmentListEntry[]>([])
const errorMessage = ref('')
const loadMoreError = ref('')
const activeFilter = ref<AssessmentFilter>('all')
const viewMode = ref<AssessmentViewMode>('grid')
const pageSize = 30
const nextOffset = ref(0)
const requestGeneration = ref(0)
const isLoadingMore = ref(false)
const hasMoreAssessments = ref(false)

const filters: { id: AssessmentFilter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'created', label: '待开始' },
  { id: 'in_progress', label: '进行中' },
  { id: 'completed', label: '已完成' },
]

const posterImages = Array.from({ length: 28 }, (_, index) => `flow-${String(index + 1).padStart(2, '0')}.svg`)

const assessmentProfiles = [
  { category: '校园生活', title: '新生校园适应与生活' },
  { category: '学习与习惯', title: '学习节奏与时间管理' },
  { category: '关系与支持', title: '校园人际与支持体验' },
  { category: '日常感受', title: '作息习惯与休息安排' },
  { category: '成长规划', title: '学习目标与行动计划' },
  { category: '学习与习惯', title: '专注习惯与学习环境' },
  { category: '日常感受', title: '日常情绪与自我照顾' },
  { category: '校园生活', title: '校园归属与参与体验' },
  { category: '日常感受', title: '压力感受与放松方式' },
  { category: '学习与习惯', title: '任务推进与时间安排' },
  { category: '成长规划', title: '自我认识与成长方向' },
  { category: '日常感受', title: '生活节律与休息习惯' },
  { category: '学习与习惯', title: '课堂参与与学习体验' },
  { category: '关系与支持', title: '校园支持资源使用体验' },
  { category: '关系与支持', title: '沟通方式与相处体验' },
  { category: '成长规划', title: '面对变化的日常适应' },
  { category: '日常感受', title: '近期状态与生活感受' },
  { category: '学习与习惯', title: '学习投入与动力来源' },
  { category: '日常感受', title: '休息习惯与精力恢复' },
  { category: '关系与支持', title: '同伴交流与关系体验' },
  { category: '成长规划', title: '未来规划与个人目标' },
  { category: '校园生活', title: '校园公共空间使用体验' },
  { category: '日常感受', title: '日常放松与压力调节' },
  { category: '学习与习惯', title: '专注状态与学习安排' },
  { category: '日常感受', title: '生活习惯与时间分配' },
  { category: '成长规划', title: '学期目标与行动回顾' },
  { category: '校园生活', title: '课程与校园活动参与' },
  { category: '成长规划', title: '自我照顾与生活平衡' },
]

const filteredAssessments = computed(() => activeFilter.value === 'all'
  ? assessments.value
  : assessments.value.filter((item) => item.status === activeFilter.value))

const assessmentCards = computed(() => {
  const sourceIndices = new Map(assessments.value.map((item, index) => [item.assessment_id, index]))
  return filteredAssessments.value.map((item) => {
    const index = sourceIndices.get(item.assessment_id) ?? 0
    return {
      item,
      profile: assessmentProfiles[index % assessmentProfiles.length],
      poster: `/assets/psynova/original-covers/${posterImages[index % posterImages.length]}`,
    }
  })
})

const formatDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const latestActivity = (item: AssessmentListEntry) => formatDate(item.completed_at || item.started_at)
const statusLabel = (item: AssessmentListEntry) => {
  if (item.status === 'created') return '待开始'
  if (item.status === 'in_progress') return '进行中'
  if (item.status === 'completed') return '已完成'
  if (item.status === 'abandoned') return '已结束'
  return '不可用'
}

const actionLabel = (item: AssessmentListEntry) => {
  if (item.status === 'created') return '开始测评'
  if (item.status === 'in_progress') return '继续测评'
  if (item.status === 'completed') return '查看结果'
  return ''
}

const hasAction = (item: AssessmentListEntry) => Boolean(actionLabel(item))

const listAssessmentEntries = async (params: { limit: number; skip: number; status?: Assessment['status'] }) => {
  if (frontendApi.listAssessmentEntries) return (await frontendApi.listAssessmentEntries(params)).data
  const rows = (await frontendApi.listAssessments(params)).data
  return rows.map((assessment) => ({
    assessment_id: assessment.assessment_id,
    status: assessment.status,
    items_answered: assessment.response_summary.items_answered,
    started_at: assessment.timestamps.started_at,
    completed_at: assessment.timestamps.completed_at,
  }))
}

const load = async () => {
  const generation = ++requestGeneration.value
  state.value = 'loading'
  errorMessage.value = ''
  loadMoreError.value = ''
  isLoadingMore.value = false
  hasMoreAssessments.value = false
  nextOffset.value = 0
  assessments.value = []
  try {
    const status = activeFilter.value === 'all' ? undefined : activeFilter.value
    const rows = await listAssessmentEntries({ limit: pageSize, skip: 0, status })
    if (generation !== requestGeneration.value) return
    assessments.value = rows
    nextOffset.value = rows.length
    hasMoreAssessments.value = rows.length === pageSize
    state.value = 'ready'
  } catch (error) {
    if (generation !== requestGeneration.value) return
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '测评列表暂时无法加载，请稍后重试。')
  }
}

const loadMore = async () => {
  if (isLoadingMore.value || !hasMoreAssessments.value || state.value !== 'ready') return
  const generation = requestGeneration.value
  const status = activeFilter.value === 'all' ? undefined : activeFilter.value
  isLoadingMore.value = true
  loadMoreError.value = ''
  try {
    const rows = await listAssessmentEntries({
      limit: pageSize,
      skip: nextOffset.value,
      status,
    })
    if (generation !== requestGeneration.value) return
    const knownIds = new Set(assessments.value.map((item) => item.assessment_id))
    assessments.value = [
      ...assessments.value,
      ...rows.filter((item) => !knownIds.has(item.assessment_id)),
    ]
    nextOffset.value += rows.length
    hasMoreAssessments.value = rows.length === pageSize
  } catch (error) {
    if (generation !== requestGeneration.value) return
    loadMoreError.value = userFacingApiError(error, '暂时无法加载更多测评，请重试。')
  } finally {
    if (generation === requestGeneration.value) isLoadingMore.value = false
  }
}

watch(activeFilter, () => { void load() })

const openAssessment = (assessment?: AssessmentListEntry) => {
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
        <LayoutDashboard class="assessment-hero__icon" :size="28" stroke-width="1.8" aria-hidden="true" />
        <h1 id="assessment-page-title">我的测评</h1>
        <p>查看已保存的测评会话，或继续完成当前流程。</p>
      </div>
      <AppButton class="assessment-hero__action" @click="openAssessment()">
        <Play :size="15" aria-hidden="true" />开始测评
      </AppButton>
    </header>

    <StudentAssignedTasks />

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
            <svg class="assessment-view-toggle__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M3.0997 2.76764H1.69974C1.23308 2.76764 0.999756 3.00097 0.999756 3.46762V4.86758C0.999756 5.33424 1.23308 5.56756 1.69974 5.56756H3.0997C3.56635 5.56756 3.79968 5.33424 3.79968 4.86758V3.46762C3.79968 3.00097 3.56635 2.76764 3.0997 2.76764Z" fill="currentColor" />
              <path d="M18.4986 2.76764H5.89896C5.4323 2.76764 5.19897 3.00097 5.19897 3.46762V4.86758C5.19897 5.33424 5.4323 5.56756 5.89896 5.56756H18.4986C18.9653 5.56756 19.1986 5.33424 19.1986 4.86758V3.46762C19.1986 3.00097 18.9653 2.76764 18.4986 2.76764Z" fill="currentColor" />
              <path d="M1.69974 8.36764H3.0997C3.56635 8.36764 3.79968 8.60097 3.79968 9.06762V10.4676C3.79968 10.9342 3.56635 11.1676 3.0997 11.1676H1.69974C1.23308 11.1676 0.999756 10.9342 0.999756 10.4676V9.06762C0.999756 8.60097 1.23308 8.36764 1.69974 8.36764Z" fill="currentColor" />
              <path d="M18.4986 8.36774H5.89896C5.4323 8.36774 5.19897 8.60106 5.19897 9.06772V10.4677C5.19897 10.9343 5.4323 11.1677 5.89896 11.1677H18.4986C18.9653 11.1677 19.1986 10.9343 19.1986 10.4677V9.06772C19.1986 8.60106 18.9653 8.36774 18.4986 8.36774Z" fill="currentColor" />
              <path d="M1.69974 13.9676H3.0997C3.56635 13.9676 3.79968 14.201 3.79968 14.6676V16.0676C3.79968 16.5342 3.56635 16.7676 3.0997 16.7676H1.69974C1.23308 16.7676 0.999756 16.5344 0.999756 16.0678V14.6678C0.999756 14.2012 1.23308 13.9678 1.69974 13.9678Z" fill="currentColor" />
              <path d="M18.4986 13.9678H5.89896C5.4323 13.9678 5.19897 14.2012 5.19897 14.6678V16.0678C5.19897 16.5344 5.4323 16.7678 5.89896 16.7678H18.4986C18.9653 16.7678 19.1986 16.5344 19.1986 16.0678V14.6678C19.1986 14.2012 18.9653 13.9678 18.4986 13.9678Z" fill="currentColor" />
            </svg>
          </button>
          <span class="assessment-view-toggle__divider" aria-hidden="true"></span>
          <button
            type="button"
            aria-label="三列网格显示"
            :aria-pressed="viewMode === 'grid'"
            :class="{ 'assessment-view-toggle__button--active': viewMode === 'grid' }"
            @click="viewMode = 'grid'"
          >
            <svg class="assessment-view-toggle__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2.5" y="2.5" width="6.667" height="6.667" rx="0.833" /><rect x="10.833" y="2.5" width="6.667" height="6.667" rx="0.833" /><rect x="2.5" y="10.833" width="6.667" height="6.667" rx="0.833" /><rect x="10.833" y="10.833" width="6.667" height="6.667" rx="0.833" /></svg>
          </button>
        </div>
      </div>

      <div v-if="state === 'loading'" class="assessment-loading" aria-busy="true" aria-label="正在加载测评会话">
        <div class="assessment-loading__poster"></div>
        <div class="assessment-loading__copy"><span></span><span></span><span></span></div>
      </div>
      <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="测评列表暂时无法加载" :body="errorMessage">
        <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
      </AppStatusCallout>
      <div v-else-if="filteredAssessments.length" class="assessment-cards" :class="`assessment-cards--${viewMode}`">
        <article v-for="card in assessmentCards" :key="card.item.assessment_id" class="assessment-card">
          <div class="assessment-card__poster">
            <img class="assessment-card__art" :src="card.poster" alt="" aria-hidden="true" />
            <span class="assessment-card__status" :class="`assessment-card__status--${card.item.status}`">{{ statusLabel(card.item) }}</span>
          </div>
          <div class="assessment-card__body">
            <span class="assessment-card__category">{{ card.profile.category }}</span>
            <h2>{{ card.profile.title }}</h2>
            <div class="assessment-card__details">
              <div class="assessment-card__metadata">
                <p class="assessment-card__activity"><CalendarDays :size="15" aria-hidden="true" />{{ card.item.status === 'created' ? '尚未开始' : latestActivity(card.item) }}</p>
                <p class="assessment-card__answers"><History :size="15" aria-hidden="true" />{{ card.item.items_answered }} 项已记录</p>
              </div>
              <div v-if="hasAction(card.item)" class="assessment-card__actions">
                <AppButton
                  variant="primary"
                  size="md"
                  class="assessment-card__action"
                  @click="openAssessment(card.item)"
                >
                  {{ actionLabel(card.item) }}
                </AppButton>
              </div>
            </div>
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
      <div v-if="hasMoreAssessments" class="assessment-load-more">
        <button type="button" :disabled="isLoadingMore" @click="loadMore">
          {{ isLoadingMore ? '正在加载…' : '加载更多' }}
        </button>
        <p v-if="loadMoreError" class="assessment-load-more__error" role="alert">{{ loadMoreError }}</p>
      </div>
      <p class="assessment-library__count" aria-live="polite">{{ filteredAssessments.length }} 项</p>
    </section>
  </div>
</template>

<style scoped>
.student-assessments { padding-top: 0; padding-bottom: 0; }
.assessment-hero { display: flex; min-height: 208px; align-items: center; justify-content: space-between; gap: 28px; padding: 30px; border-radius: 12px; color: #fff; background: linear-gradient(118deg, #264ac5 0%, #3282e0 44%, #6850c9 100%); }
.assessment-hero__copy { display: grid; justify-items: start; gap: 8px; }
.assessment-hero__icon { color: #fff; }
.assessment-hero h1 { margin: 0; color: #fff; font-family: var(--font-sans); font-size: 26px; font-weight: 600; line-height: 1.25; }
.assessment-hero p { margin: 0; color: rgb(255 255 255 / 94%); font-size: 16px; line-height: 1.4; }
.assessment-hero__action { flex: 0 0 auto; }
.assessment-library { position: relative; margin-top: 18px; padding: 30px; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); }
.assessment-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.assessment-filters { display: flex; flex-wrap: wrap; gap: 10px; }
.assessment-filters button { min-height: 40px; padding: 0 16px; border: 0; border-radius: 8px; color: #292a32; background: #f0f0f2; cursor: pointer; font: inherit; font-size: 14px; font-weight: 600; transition: color var(--motion-fast), background-color var(--motion-fast); }
.assessment-filters button:hover { background: #e6e7e9; }
.assessment-filters button.assessment-filter--active { color: #fff; background: #00addf; }
.assessment-view-toggle { display: flex; width: 76px; height: 36px; flex: 0 0 auto; align-items: center; justify-content: center; padding: 3px 4px; border: 1px solid #dedfe3; border-radius: 9px; background: #fff; }
.assessment-view-toggle button { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border: 0; border-radius: 4px; color: #69707b; background: transparent; cursor: pointer; transition: color var(--motion-fast), background-color var(--motion-fast); }
.assessment-view-toggle button:hover { color: #252832; background: #f2f3f4; }
.assessment-view-toggle button.assessment-view-toggle__button--active { color: #00a9dd; }
.assessment-view-toggle__icon { width: 18px; height: 18px; fill: currentColor; }
.assessment-view-toggle__divider { width: 1px; height: 21px; flex: 0 0 1px; margin: 0 3px; background: #d9dce1; }
.assessment-view-toggle button:focus-visible, .assessment-filters button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.assessment-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 20px; row-gap: 38px; }
.assessment-card { display: flex; min-width: 0; flex-direction: column; }
.assessment-card__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; border-radius: 12px; background: #eaf3f5; }
.assessment-card__art { position: absolute; z-index: 0; inset: 0; display: block; width: 100%; height: 100%; object-fit: cover; }
.assessment-card__status { position: absolute; z-index: 2; top: 12px; right: 12px; left: auto; padding: 5px 10px; border-radius: 7px; color: #fff; background: #00addf; font-size: 13px; font-weight: 600; line-height: 1.3; }
.assessment-card__status--completed { background: #568f7d; }
.assessment-card__status--abandoned, .assessment-card__status--invalid { background: #717681; }
.assessment-card__body { display: grid; align-content: start; gap: 6px; padding-top: 12px; }
.assessment-card__category { color: #00a9dd; font-size: 14px; line-height: 1.3; }
.assessment-card h2 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 18px; font-weight: 600; line-height: 1.55; }
.assessment-card__details { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 10px; margin-top: 2px; }
.assessment-card__metadata { display: grid; min-width: 0; align-content: start; gap: 7px; }
.assessment-card__activity, .assessment-card__answers { display: flex; align-items: center; gap: 7px; margin: 0; color: #606775; font-size: 13px; line-height: 1.45; }
.assessment-card__activity svg, .assessment-card__answers svg { flex: 0 0 auto; }
.assessment-card__actions { display: flex; justify-content: flex-end; margin: 0; }
:deep(.assessment-card__action) { min-height: 43px; padding: 10px 20px; border-radius: 8px; font-size: 16px; }
.assessment-load-more { display: flex; align-items: center; flex-direction: column; gap: 8px; padding-top: 28px; }
.assessment-load-more button { min-width: 96px; min-height: 38px; padding: 0 16px; border: 1px solid #555b66; border-radius: 8px; color: #252832; background: #fff; cursor: pointer; font: inherit; font-size: 14px; font-weight: 500; transition: background-color var(--motion-fast), border-color var(--motion-fast); }
.assessment-load-more button:hover { border-color: #30343d; background: #f5f6f7; }
.assessment-load-more button:disabled { cursor: progress; opacity: .68; }
.assessment-load-more__error { margin: 0; color: #a1323a; font-size: 13px; }
.assessment-load-more button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
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
.assessment-cards--list .assessment-card { display: grid; grid-template-columns: minmax(160px, 24%) minmax(0, 1fr); align-items: center; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid #ebecef; }
.assessment-cards--list .assessment-card:last-child { padding-bottom: 0; border-bottom: 0; }
.assessment-cards--list .assessment-card__body { gap: 5px; padding-top: 0; }

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
  .assessment-cards--list .assessment-card__poster { grid-row: auto; }
  .assessment-cards--list .assessment-card__status { font-size: 11px; }
  .assessment-cards--list .assessment-card__status { top: 4px; right: 4px; padding: 3px 5px; font-size: 9px; }
  .assessment-cards--list .assessment-card__details { grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
  .assessment-cards--list .assessment-card__actions, .assessment-card__actions { justify-content: flex-start; }
  :deep(.assessment-card__action) { min-height: 38px; padding: 8px 12px; font-size: 13px; }
  .assessment-loading { grid-template-columns: 1fr; }
  .assessment-loading__poster:not(:first-child) { display: none; }
  .assessment-empty { align-items: flex-start; justify-content: flex-start; }
}
</style>
