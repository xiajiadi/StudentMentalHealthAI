<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { CalendarDays, ClipboardList, History, Play } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import StudentAssessmentStatusFilter from '@/components/student/StudentAssessmentStatusFilter.vue'
import StudentAssessmentViewModeToggle from '@/components/student/StudentAssessmentViewModeToggle.vue'
import { studentAssessmentStatusFilters, type StudentAssessmentStatusFilterValue } from '@/components/student/assessment-status-filter'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt, studentPageBannerCopy, studentPageTitles } from '@/data/student-feature-cards'
import { frontendApi } from '@/services/mock-api'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { Assessment } from '@/types/contracts'
import type { AssessmentListEntry, StudentSchoolTask } from '@/api/client'
import { useRouter } from 'vue-router'

type AssessmentViewMode = 'grid' | 'list'
interface AssessmentLibraryCard {
  key: string
  item: AssessmentListEntry | null
  task: StudentSchoolTask | null
  status: Assessment['status']
  category: string
  title: string
  poster: string
  previewOnly?: boolean
}

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<AssessmentListEntry[]>([])
const schoolTasks = ref<StudentSchoolTask[]>([])
const schoolTasksState = ref<'loading' | 'ready' | 'error'>('loading')
const schoolTaskError = ref('')
const schoolTaskActionError = ref('')
const pendingSchoolTask = ref('')
const errorMessage = ref('')
const loadMoreError = ref('')
const activeFilter = ref<StudentAssessmentStatusFilterValue>('all')
const viewMode = ref<AssessmentViewMode>('grid')
const pageSize = 30
const nextOffset = ref(0)
const requestGeneration = ref(0)
const schoolTaskRequestGeneration = ref(0)
const isLoadingMore = ref(false)
const hasMoreAssessments = ref(false)
const visibleCardLimit = ref(6)
const cardsPerPage = computed(() => viewMode.value === 'grid' ? 6 : 4)
const embeddedLoadingMinDurationMs = 320
const showLoadMorePreview = import.meta.env.DEV
  && typeof window !== 'undefined'
  && new URLSearchParams(window.location.search).get('previewLoadMore') === '1'

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

const loadMorePreviewEntries: AssessmentListEntry[] = [
  { assessment_id: 'DEMO_LOAD_MORE_01', status: 'completed', items_answered: 5, started_at: '2026-10-14T09:10:00+08:00', completed_at: '2026-10-14T09:18:00+08:00' },
  { assessment_id: 'DEMO_LOAD_MORE_02', status: 'completed', items_answered: 4, started_at: '2026-10-13T14:20:00+08:00', completed_at: '2026-10-13T14:27:00+08:00' },
  { assessment_id: 'DEMO_LOAD_MORE_03', status: 'completed', items_answered: 6, started_at: '2026-10-12T10:05:00+08:00', completed_at: '2026-10-12T10:16:00+08:00' },
  { assessment_id: 'DEMO_LOAD_MORE_04', status: 'completed', items_answered: 5, started_at: '2026-10-11T16:30:00+08:00', completed_at: '2026-10-11T16:39:00+08:00' },
  { assessment_id: 'DEMO_LOAD_MORE_05', status: 'completed', items_answered: 3, started_at: '2026-10-10T11:45:00+08:00', completed_at: '2026-10-10T11:51:00+08:00' },
]

const filteredAssessments = computed(() => activeFilter.value === 'all'
  ? assessments.value
  : assessments.value.filter((item) => item.status === activeFilter.value))

const schoolTaskAssessmentStatus = (task: StudentSchoolTask): Assessment['status'] => task.assessment_status
  ?? (task.status.toUpperCase() === 'PUBLISHED' ? 'created' : 'invalid')

const schoolTaskStatusLabel = (task: StudentSchoolTask) => {
  if (task.assessment_status === 'completed') return '已完成'
  if (task.assessment_status === 'in_progress') return '进行中'
  if (task.assessment_status === 'created') return '待开始'
  if (task.status.toUpperCase() !== 'PUBLISHED') return '暂不可开始'
  return '待开始'
}

const schoolTaskActionLabel = (card: AssessmentLibraryCard) => {
  if (card.previewOnly) return '查看记录'
  if (!card.task) return card.item ? actionLabel(card.item) : ''
  if (card.status === 'completed') return '查看记录'
  return card.task.assessment_id ? '继续任务' : '开始任务'
}

const schoolTaskPoster = (task: StudentSchoolTask) => {
  const seed = [...task.task_ref].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 0)
  return `/assets/psynova/original-covers/${posterImages[seed % posterImages.length]}`
}

const compactTaskDateTime = (value: string | null | undefined, includeYear = false) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  const year = includeYear ? `${String(date.getFullYear()).slice(-2)}/` : ''
  return `${year}${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

const timelineDate = (value: string | null | undefined, includeYear = false) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  const year = includeYear ? `${date.getFullYear()}年` : ''
  return `${year}${date.getMonth() + 1}月${date.getDate()}日`
}

const timelineWeekday = (value: string | null | undefined) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN', { weekday: 'short' })
}

const timelineTime = (value: string | null | undefined) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间暂不可用' : `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

const schoolTaskCrossesYear = (task: StudentSchoolTask) => {
  if (!task.due_at) return false
  const startsAt = new Date(task.opens_at)
  const dueAt = new Date(task.due_at)
  return !Number.isNaN(startsAt.getTime()) && !Number.isNaN(dueAt.getTime()) && startsAt.getFullYear() !== dueAt.getFullYear()
}

const schoolTaskDateRange = (task: StudentSchoolTask) => {
  if (!task.due_at) return `${compactTaskDateTime(task.opens_at)} · 未设截止时间`
  const startsAt = new Date(task.opens_at)
  const dueAt = new Date(task.due_at)
  if (Number.isNaN(startsAt.getTime()) || Number.isNaN(dueAt.getTime())) {
    return `${formatDate(task.opens_at)} – ${formatDate(task.due_at)}`
  }
  const includeYear = schoolTaskCrossesYear(task)
  return `${compactTaskDateTime(task.opens_at, includeYear)}–${compactTaskDateTime(task.due_at, includeYear)}`
}

const schoolTaskDateRangeFull = (task: StudentSchoolTask) => `${formatDate(task.opens_at)} – ${task.due_at ? formatDate(task.due_at) : '未设置截止时间'}`

const assessmentCards = computed<AssessmentLibraryCard[]>(() => {
  const schoolAssessmentIds = new Set(schoolTasks.value
    .map((task) => task.assessment_id)
    .filter((assessmentId): assessmentId is string => Boolean(assessmentId)))
  const assignedCards = schoolTasks.value.map((task): AssessmentLibraryCard => {
    const item = task.assessment_id
      ? assessments.value.find((assessment) => assessment.assessment_id === task.assessment_id) ?? null
      : null
    const status = item?.status ?? schoolTaskAssessmentStatus(task)
    return {
      key: `school:${task.task_ref}`,
      item,
      task,
      status,
      category: '学校安排',
      title: `班级任务 ${task.task_ref.slice(-6)}`,
      poster: schoolTaskPoster(task),
    }
  }).filter((card) => activeFilter.value === 'all' || card.status === activeFilter.value)

  const sourceIndices = new Map(assessments.value.map((item, index) => [item.assessment_id, index]))
  const individualCards = filteredAssessments.value.filter((item) => !schoolAssessmentIds.has(item.assessment_id)).map((item) => {
    const index = sourceIndices.get(item.assessment_id) ?? 0
    return {
      key: `assessment:${item.assessment_id}`,
      item,
      task: null,
      status: item.status,
      category: assessmentProfiles[index % assessmentProfiles.length].category,
      title: assessmentProfiles[index % assessmentProfiles.length].title,
      poster: `/assets/psynova/original-covers/${posterImages[index % posterImages.length]}`,
    }
  })
  const previewCards = showLoadMorePreview
    ? loadMorePreviewEntries
      .filter((item) => activeFilter.value === 'all' || item.status === activeFilter.value)
      .map((item, index): AssessmentLibraryCard => ({
        key: `preview:${item.assessment_id}`,
        item,
        task: null,
        status: item.status,
        category: '演示数据 · 仅预览',
        title: `虚拟测评记录 ${String(index + 1).padStart(2, '0')}`,
        poster: `/assets/psynova/original-covers/${posterImages[(index + 18) % posterImages.length]}`,
        previewOnly: true,
      }))
    : []
  return [...assignedCards, ...individualCards, ...previewCards]
})

const visibleAssessmentCards = computed(() => assessmentCards.value.slice(0, visibleCardLimit.value))
const hasMoreCards = computed(() => visibleCardLimit.value < assessmentCards.value.length || hasMoreAssessments.value)

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

const cardStatusLabel = (card: AssessmentLibraryCard) => {
  if (card.task) return card.item ? statusLabel(card.item) : schoolTaskStatusLabel(card.task)
  return card.item ? statusLabel(card.item) : '不可用'
}

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

const schoolTaskRequestMessage = (error: unknown, fallback: string) => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前任务暂不可访问，请联系学校管理员确认报名状态。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '任务已不可用，请刷新任务列表。'
  if (code === 'workflow_conflict' || code === 'conflict' || code === '409') return '任务状态已变化，请刷新后重试。'
  return fallback
}

const keepEmbeddedSkeletonVisible = async (startedAt: number) => {
  if (!props.embedded) return
  const remaining = embeddedLoadingMinDurationMs - (performance.now() - startedAt)
  if (remaining > 0) await new Promise<void>((resolve) => window.setTimeout(resolve, remaining))
}

const loadStudentSchoolTasks = async () => {
  const generation = ++schoolTaskRequestGeneration.value
  schoolTasksState.value = 'loading'
  schoolTaskError.value = ''
  schoolTaskActionError.value = ''
  schoolTasks.value = []
  if (!frontendApi.listStudentSchoolTasks) {
    schoolTasksState.value = 'error'
    schoolTaskError.value = '当前运行环境未提供学校任务服务。'
    return
  }
  try {
    const result = await frontendApi.listStudentSchoolTasks()
    if (generation !== schoolTaskRequestGeneration.value) return
    schoolTasks.value = result.data
    schoolTasksState.value = 'ready'
  } catch (error) {
    if (generation !== schoolTaskRequestGeneration.value) return
    schoolTasksState.value = 'error'
    schoolTaskError.value = schoolTaskRequestMessage(error, '暂时无法读取分配给你的任务。')
  }
}

const load = async () => {
  const generation = ++requestGeneration.value
  const loadingStartedAt = performance.now()
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
    await keepEmbeddedSkeletonVisible(loadingStartedAt)
    if (generation !== requestGeneration.value) return
    assessments.value = rows
    nextOffset.value = rows.length
    hasMoreAssessments.value = rows.length === pageSize
    state.value = 'ready'
  } catch (error) {
    if (generation !== requestGeneration.value) return
    await keepEmbeddedSkeletonVisible(loadingStartedAt)
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

const loadMoreCards = async () => {
  const generation = requestGeneration.value
  const filter = activeFilter.value
  const mode = viewMode.value
  const nextLimit = visibleCardLimit.value + cardsPerPage.value
  if (nextLimit > assessmentCards.value.length && hasMoreAssessments.value) await loadMore()
  if (generation !== requestGeneration.value || filter !== activeFilter.value || mode !== viewMode.value) return
  visibleCardLimit.value = Math.min(nextLimit, assessmentCards.value.length)
}

watch(activeFilter, () => {
  visibleCardLimit.value = cardsPerPage.value
  void load()
  void loadStudentSchoolTasks()
}, { flush: 'post' })

watch(viewMode, () => {
  visibleCardLimit.value = cardsPerPage.value
})

const openAssessment = (assessment?: AssessmentListEntry) => {
  if (assessment?.status === 'completed') {
    void router.push(`/student/assessment/${encodeURIComponent(assessment.assessment_id)}/result`)
    return
  }
  if (assessment?.status === 'created' || assessment?.status === 'in_progress') {
    void router.push(`/student/assessment/${encodeURIComponent(assessment.assessment_id)}`)
    return
  }
  if (!assessment) void router.push({ path: '/student/assessment', query: { startAssigned: '1' } })
}

const openSchoolTask = async (card: AssessmentLibraryCard) => {
  const task = card.task
  if (!task || pendingSchoolTask.value) return
  schoolTaskActionError.value = ''
  if ((card.item?.status ?? task.assessment_status) === 'completed' && task.assessment_id) {
    await router.push(`/student/assessment/${encodeURIComponent(task.assessment_id)}/result`)
    return
  }
  if (task.status.toUpperCase() !== 'PUBLISHED') return
  if (!frontendApi.startStudentSchoolTask) {
    schoolTaskActionError.value = '当前运行环境未提供学校任务服务。'
    return
  }
  pendingSchoolTask.value = task.task_ref
  try {
    const result = await frontendApi.startStudentSchoolTask(task.task_ref)
    if (!result.data.assessment_id) throw new Error('task_session_unavailable')
    const destination = result.data.status === 'completed'
      ? `/student/assessment/${encodeURIComponent(result.data.assessment_id)}/result`
      : `/student/assessment/${encodeURIComponent(result.data.assessment_id)}`
    await router.push(destination)
  } catch (error) {
    schoolTaskActionError.value = schoolTaskRequestMessage(error, '任务暂时无法打开，请稍后重试。')
  } finally {
    pendingSchoolTask.value = ''
  }
}

const openAssessmentCard = (card: AssessmentLibraryCard) => {
  if (card.previewOnly) return
  if (card.task) void openSchoolTask(card)
  else if (card.item) openAssessment(card.item)
}

onMounted(() => {
  void load()
  void loadStudentSchoolTasks()
})
</script>

<template>
  <div :class="props.embedded ? 'student-assessments student-assessments--embedded' : 'content-wrap content-wrap--student student-assessments'">
    <WorkspaceBreadcrumb v-if="!props.embedded" current="我的测评" />
    <StudentPageHero
      v-if="!props.embedded"
      :eyebrow="studentPageBannerCopy.assessments.eyebrow"
      :title="studentPageTitles.assessments"
      :subtitle="studentPageBannerCopy.assessments.subtitle"
      :image="studentPageArt.assessments"
      image-position="center 48%"
      light-text
    >
      <template #actions>
        <AppButton @click="openAssessment()"><Play :size="15" aria-hidden="true" />开始测评</AppButton>
      </template>
    </StudentPageHero>

    <section class="assessment-library" :class="{ 'assessment-library--embedded': props.embedded }" aria-label="测评列表">
      <div class="assessment-toolbar">
        <StudentAssessmentStatusFilter v-model="activeFilter" aria-label="按状态筛选测评" />
        <div class="assessment-toolbar__actions">
          <StudentAssessmentViewModeToggle v-model="viewMode" aria-label="测评显示方式" />
        </div>
      </div>

      <AppStatusCallout v-if="schoolTaskActionError" tone="critical" title="任务操作未完成" :body="schoolTaskActionError" role="alert" />
      <AppStatusCallout v-if="schoolTasksState === 'error'" tone="attention" title="学校任务暂时无法加载" :body="schoolTaskError">
        <AppButton variant="secondary" size="sm" @click="loadStudentSchoolTasks">重新加载</AppButton>
      </AppStatusCallout>
      <AppStatusCallout v-if="state === 'error'" tone="critical" title="测评列表暂时无法加载" :body="errorMessage">
        <AppButton variant="secondary" size="sm" @click="load">重新加载</AppButton>
      </AppStatusCallout>
      <div v-if="state === 'loading' || schoolTasksState === 'loading'" class="assessment-loading" aria-busy="true" aria-label="正在加载测评和学校任务">
        <div class="assessment-loading__poster"></div>
        <div class="assessment-loading__copy"><span></span><span></span><span></span></div>
      </div>
      <div v-else-if="assessmentCards.length" class="assessment-cards" :class="`assessment-cards--${viewMode}`">
        <article v-for="card in visibleAssessmentCards" :key="card.key" class="assessment-card">
          <span
            v-if="viewMode === 'list'"
            class="assessment-card__status assessment-card__status--list"
            :class="`assessment-card__status--${card.status}`"
          >{{ cardStatusLabel(card) }}</span>
          <div class="assessment-card__poster">
            <img class="assessment-card__art" :src="card.poster" alt="" aria-hidden="true" />
            <span
              v-if="viewMode === 'grid'"
              class="assessment-card__status"
              :class="`assessment-card__status--${card.status}`"
            >{{ cardStatusLabel(card) }}</span>
          </div>
          <div class="assessment-card__body">
            <div v-if="viewMode === 'list'" class="assessment-card__timeline-date" :title="card.task ? schoolTaskDateRangeFull(card.task) : undefined">
              <template v-if="card.task">
                <strong>{{ timelineDate(card.task.opens_at, schoolTaskCrossesYear(card.task)) }}</strong>
                <span class="assessment-card__timeline-weekday">{{ timelineWeekday(card.task.opens_at) }}</span>
                <span class="assessment-card__timeline-time">{{ timelineTime(card.task.opens_at) }}</span>
                <template v-if="card.task.due_at">
                  <span class="assessment-card__timeline-range-separator" aria-hidden="true">–</span>
                  <small><span class="sr-only">至 </span>{{ timelineDate(card.task.due_at, schoolTaskCrossesYear(card.task)) }} {{ timelineTime(card.task.due_at) }}</small>
                </template>
                <small v-else>未设置截止时间</small>
              </template>
              <template v-else-if="card.item && (card.item.completed_at || card.item.started_at)">
                <strong>{{ timelineDate(card.item.completed_at || card.item.started_at) }}</strong>
                <span class="assessment-card__timeline-weekday">{{ timelineWeekday(card.item.completed_at || card.item.started_at) }}</span>
                <span class="assessment-card__timeline-time">{{ timelineTime(card.item.completed_at || card.item.started_at) }}</span>
              </template>
              <strong v-else>{{ card.item?.status === 'created' ? '尚未开始' : '时间未提供' }}</strong>
            </div>
            <div class="assessment-card__content">
              <span class="assessment-card__category">{{ card.category }}</span>
              <h2>{{ card.title }}</h2>
              <div class="assessment-card__details">
                <div class="assessment-card__metadata">
                  <p class="assessment-card__activity" :class="{ 'assessment-card__activity--range': card.task }">
                    <CalendarDays :size="15" aria-hidden="true" />
                    <span v-if="card.task" class="assessment-card__activity-text" :title="schoolTaskDateRangeFull(card.task)">{{ schoolTaskDateRange(card.task) }}</span>
                    <span v-else>{{ card.item?.status === 'created' ? '尚未开始' : card.item ? latestActivity(card.item) : '时间未提供' }}</span>
                  </p>
                  <p class="assessment-card__answers"><History :size="15" aria-hidden="true" />{{ card.item ? `${card.item.items_answered} 项已记录` : card.status === 'completed' ? '已完成' : card.status === 'in_progress' ? '已开始' : '尚未开始' }}</p>
                </div>
                <div v-if="schoolTaskActionLabel(card)" class="assessment-card__actions">
                  <AppButton
                    variant="primary"
                    size="md"
                    class="assessment-card__action"
                    :class="{ 'assessment-card__action--preview': card.previewOnly }"
                    :disabled="Boolean(card.previewOnly || (card.task && card.task.status.toUpperCase() !== 'PUBLISHED'))"
                    :loading="Boolean(card.task && pendingSchoolTask === card.task.task_ref)"
                    @click="openAssessmentCard(card)"
                  >
                    {{ schoolTaskActionLabel(card) }}
                  </AppButton>
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>
      <div v-else-if="state === 'ready'" class="assessment-empty" role="status">
        <span class="assessment-empty__icon"><ClipboardList :size="21" aria-hidden="true" /></span>
        <div>
          <strong>{{ activeFilter === 'all' ? '目前没有测评记录' : `没有${studentAssessmentStatusFilters.find((filter) => filter.id === activeFilter)?.label}的测评` }}</strong>
          <p>学校安排和自主测评记录会按状态显示在这里。</p>
        </div>
      </div>
      <div v-if="hasMoreCards" class="assessment-load-more">
        <button type="button" :disabled="isLoadingMore" @click="loadMoreCards">
          {{ isLoadingMore ? '正在加载…' : '加载更多' }}
        </button>
        <p v-if="loadMoreError" class="assessment-load-more__error" role="alert">{{ loadMoreError }}</p>
      </div>
      <div v-if="state === 'ready' && schoolTasksState === 'ready'" class="assessment-library__count" aria-live="polite">
        {{ hasMoreAssessments ? `已加载 ${assessmentCards.length} 条` : `${assessmentCards.length} 条` }}
      </div>
    </section>
  </div>
</template>

<style scoped>
.student-assessments { padding-top: 0; padding-bottom: 0; }
.student-assessments--embedded { width: 100%; }
.assessment-library { position: relative; margin-top: 18px; padding: 30px; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); }
.assessment-library--embedded { margin-top: 0; padding: 30px; border-radius: 12px; box-shadow: none; }
.assessment-library__count { margin-top: 24px; color: #737985; font-size: 12px; line-height: 1.45; text-align: right; }
.assessment-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.assessment-toolbar__actions { display: flex; flex: 0 0 auto; align-items: center; gap: 12px; }
.assessment-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 20px; row-gap: 38px; }
.assessment-card { display: flex; min-width: 0; flex-direction: column; }
.assessment-card__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; border-radius: 12px; background: #eaf3f5; }
.assessment-card__art { position: absolute; z-index: 0; inset: 0; display: block; width: 100%; height: 100%; object-fit: cover; }
.assessment-card__status { position: absolute; z-index: 2; top: 12px; right: 12px; left: auto; padding: 5px 10px; border-radius: 7px; color: #fff; background: #00addf; font-size: 13px; font-weight: 600; line-height: 1.3; }
.assessment-card__status--list { top: 0; right: auto; left: 0; padding: 6px 12px; border-radius: 11px 0 8px 0; font-size: 12px; }
.assessment-card__status--completed { background: #568f7d; }
.assessment-card__status--abandoned, .assessment-card__status--invalid { background: #717681; }
.assessment-card__body { display: grid; align-content: start; gap: 6px; padding-top: 12px; }
.assessment-cards--grid .assessment-card__body { flex: 1; min-height: 122px; align-content: stretch; }
.assessment-card__content { display: grid; min-width: 0; align-content: start; gap: 6px; }
.assessment-cards--grid .assessment-card__content { align-self: stretch; align-content: center; transform: translateY(2px); }
.assessment-card__category { color: #00a9dd; font-size: 14px; line-height: 1.3; }
.assessment-card h2 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 18px; font-weight: 600; line-height: 1.55; }
.assessment-card__details { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 10px; margin-top: 2px; }
.assessment-card__metadata { display: grid; min-width: 0; align-content: start; gap: 7px; }
.assessment-card__activity, .assessment-card__answers { display: flex; align-items: center; gap: 7px; margin: 0; color: #606775; font-size: 13px; line-height: 1.45; }
.assessment-card__activity svg, .assessment-card__answers svg { flex: 0 0 auto; }
.assessment-cards--grid .assessment-card__details { align-items: center; }
.assessment-card__activity--range { min-width: 0; white-space: nowrap; }
.assessment-card__activity-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assessment-card__actions { display: flex; justify-content: flex-end; margin: 0; }
.assessment-cards--grid .assessment-card__actions { transform: translateY(-6px); }
:deep(.assessment-card__action) { min-height: 43px; padding: 10px 20px; border-radius: 8px; font-size: 16px; }
:deep(.assessment-card__action--preview:disabled) { cursor: default; opacity: 1; }
.assessment-load-more { display: flex; align-items: center; flex-direction: column; gap: 8px; padding-top: 64px; }
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
.assessment-loading__poster { position: relative; overflow: hidden; aspect-ratio: 1.91 / 1; border-radius: 12px; background: var(--color-surface-skeleton); }
.assessment-loading__copy { display: grid; grid-column: 1 / -1; gap: 10px; }
.assessment-loading__copy span { position: relative; overflow: hidden; width: min(400px, 50%); height: 12px; border-radius: 6px; background: var(--color-surface-skeleton); }
.assessment-loading__copy span:first-child { width: min(240px, 30%); height: 18px; }
.assessment-loading__poster::after, .assessment-loading__copy span::after { position: absolute; inset: 0; content: ""; background: linear-gradient(100deg, transparent, rgb(255 255 255 / 62%), transparent); transform: translateX(-100%); animation: assessment-loading-shimmer 1.35s ease-in-out infinite; }
@keyframes assessment-loading-shimmer { to { transform: translateX(100%); } }
.assessment-library > .status-callout { margin-top: 4px; }
.assessment-cards--list { position: relative; grid-template-columns: 1fr; row-gap: 18px; }
.assessment-cards--list::before { position: absolute; z-index: 2; top: 0; bottom: 0; left: 196px; width: 1px; background: repeating-linear-gradient(to bottom, #d7dde3 0 5px, transparent 5px 10px); content: ""; pointer-events: none; }
.assessment-cards--list .assessment-card { position: relative; top: 0; z-index: 1; display: grid; grid-template-columns: minmax(0, 1fr) minmax(180px, 24%); align-items: center; gap: 32px; min-height: 196px; padding: 38px 24px 24px; border: 1px solid #eceef1; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); transition: top 100ms ease-out, box-shadow 200ms ease-out, background-image 200ms ease-out; }
.assessment-cards--list .assessment-card:hover, .assessment-cards--list .assessment-card:focus-within { top: -3px; box-shadow: 0 241px 96px rgb(0 0 0 / 2%), 0 136px 81px rgb(0 0 0 / 6%), 0 60px 60px rgb(0 0 0 / 10%), 0 15px 33px rgb(0 0 0 / 12%); }
.assessment-cards--list .assessment-card::after { position: absolute; right: 0; bottom: 0; left: 0; height: 0; border-radius: 0 0 12px 12px; background: transparent; content: ""; pointer-events: none; transition: height 200ms ease-out; }
.assessment-cards--list .assessment-card:hover::after, .assessment-cards--list .assessment-card:focus-within::after { height: 3px; }
.assessment-cards--list .assessment-card::before { position: absolute; z-index: 3; top: 50%; left: 196px; width: 10px; height: 10px; border: 2px solid #fff; border-radius: 50%; background: #cfd5dc; box-shadow: 0 0 0 1px #cfd5dc; content: ""; transform: translate(-50%, -50%); }
.assessment-cards--list .assessment-card__poster { grid-column: 2; grid-row: 1; }
.assessment-cards--list .assessment-card__body { grid-column: 1; grid-row: 1; display: grid; grid-template-columns: 160px 24px minmax(0, 1fr); align-items: center; gap: 0; min-width: 0; padding: 0; }
.assessment-cards--list .assessment-card__timeline-date { grid-column: 1; display: flex; min-width: 0; flex-direction: column; align-items: center; gap: 5px; text-align: center; }
.assessment-card__timeline-date strong { color: #242630; font-size: 15px; font-weight: 650; line-height: 1.35; }
.assessment-card__timeline-date span { color: #606775; font-size: 12px; line-height: 1.4; }
.assessment-card__timeline-date .assessment-card__timeline-weekday { font-size: 13px; }
.assessment-card__timeline-date .assessment-card__timeline-time { color: #424956; font-size: 13px; font-weight: 600; }
.assessment-card__timeline-date small { color: #69717d; font-size: 11px; line-height: 1.4; }
.assessment-card__timeline-range-separator { color: #a4aab3; font-size: 11px; line-height: 1; }
.assessment-cards--list .assessment-card__content { grid-column: 3; grid-row: 1; }
.assessment-cards--list .assessment-card__activity { display: none; }
.assessment-cards--list .assessment-card__details { grid-template-columns: minmax(0, 1fr); align-items: start; gap: 10px; margin-top: 8px; }
.assessment-cards--list .assessment-card__actions { justify-content: flex-start; }
.assessment-cards--list .assessment-card__actions .assessment-card__action { transform: none; }

@media (max-width: 980px) {
  .assessment-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .assessment-cards--list { grid-template-columns: 1fr; }
  .assessment-loading { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .assessment-loading__poster:last-of-type { display: none; }
}
@media (max-width: 680px) {
  .assessment-library { padding: 20px; }
  .assessment-toolbar { align-items: center; flex-direction: row; flex-wrap: wrap; gap: 12px; }
  .assessment-toolbar__actions { margin-left: auto; }
  .assessment-cards { grid-template-columns: 1fr; row-gap: 26px; }
  .assessment-cards--list { grid-template-columns: 1fr; }
  .assessment-cards--list::before, .assessment-cards--list .assessment-card::before { display: none; }
  .assessment-cards--list .assessment-card { grid-template-columns: minmax(0, 1fr) 96px; align-items: start; gap: 12px; min-height: 0; padding: 38px 16px 16px; }
  .assessment-cards--list .assessment-card__poster { grid-column: 2; grid-row: 1; }
  .assessment-cards--list .assessment-card__body { grid-column: 1; grid-row: 1; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 8px; }
  .assessment-cards--list .assessment-card__timeline-date { grid-column: 1; align-items: flex-start; text-align: left; }
  .assessment-cards--list .assessment-card__content { grid-column: 1; grid-row: 2; }
  .assessment-cards--list .assessment-card__timeline-date strong { font-size: 13px; }
  .assessment-cards--list .assessment-card__timeline-date span { font-size: 11px; }
  .assessment-cards--list .assessment-card__status--list { top: 0; left: 0; padding: 5px 9px; font-size: 10px; }
  .assessment-cards--list .assessment-card__details { grid-template-columns: 1fr; gap: 8px; }
  .assessment-cards--list .assessment-card__actions { justify-content: flex-start; }
  .assessment-card__actions { justify-content: flex-start; }
  :deep(.assessment-card__action) { min-height: 38px; padding: 8px 12px; font-size: 13px; }
  .assessment-loading { grid-template-columns: 1fr; }
  .assessment-loading__poster:not(:first-child) { display: none; }
  .assessment-empty { align-items: flex-start; justify-content: flex-start; }
}
@media (max-width: 520px) {
}
@media (prefers-reduced-motion: reduce) {
  .assessment-cards--list .assessment-card, .assessment-cards--list .assessment-card::after { transition: none; }
  .assessment-cards--list .assessment-card:hover, .assessment-cards--list .assessment-card:focus-within { top: 0; }
}
</style>
