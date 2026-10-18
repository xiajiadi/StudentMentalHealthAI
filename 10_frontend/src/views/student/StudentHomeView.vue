<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentRefreshButton from '@/components/app/StudentRefreshButton.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import StudentHistoryLibrary from '@/components/student/StudentHistoryLibrary.vue'
import StudentAssessmentsView from '@/views/student/StudentAssessmentsView.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentFeatureCards, studentPageArt, studentPageBannerCopy, studentPageTitles } from '@/data/student-feature-cards'
import { frontendApi } from '@/services/mock-api'
import { schoolFeedback, type StudentSchoolFeedback } from '@/services/school-feedback'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { ReportSummary } from '@/api/client'
import type { StudentHistoryLibraryItem } from '@/components/student/history-library'
import { useSessionStore } from '@/stores/session'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const reports = ref<ReportSummary[]>([])
const historyCategory = ref<'assessment' | 'feedback' | 'support'>('assessment')
const errorMessage = ref('')
const historyError = ref('')
const historyRequestGeneration = ref(0)
const feedbackRows = ref<StudentSchoolFeedback[]>([])
const feedbackState = ref<'loading' | 'ready' | 'error'>('loading')
const feedbackError = ref('')
const feedbackLoadMoreError = ref('')
const feedbackLoadingMore = ref(false)
const feedbackTotal = ref(0)
const feedbackRequestGeneration = ref(0)
type StudentCarouselSlide =
  | { kind: 'welcome'; title: string; subtitle: string; image: string; imageAlt: string }
  | { kind: 'tip'; title: string; body: string; image: string; imageAlt: string; backgroundPosition?: string }

const session = useSessionStore()
const welcomeName = computed(() => {
  const displayName = session.user?.displayName?.trim()
  if (!displayName || /^(?:USER|SYNTHETIC)_/i.test(displayName)) return '同学'
  return displayName
})

const wellbeingTipPool: Extract<StudentCarouselSlide, { kind: 'tip' }>[] = [
  {
    kind: 'tip',
    title: '给自己片刻留白',
    body: '心不必时时回答所有问题。先听见呼吸与脚步，答案可以晚一点到来。',
    image: '/assets/psynova/monet-wellbeing-postcards.png',
    imageAlt: '莫奈式晨光下的睡莲池明信片画作',
    backgroundPosition: '0% 0%',
  },
  {
    kind: 'tip',
    title: '让感受经过，也让自己留下',
    body: '情绪像天色，来去有时。看见它、说出它，不等于被它定义。',
    image: '/assets/psynova/monet-wellbeing-postcards.png',
    imageAlt: '莫奈式晨光花园小径明信片画作',
    backgroundPosition: '100% 0%',
  },
  {
    kind: 'tip',
    title: '让休息成为一部分',
    body: '停下不是落后。给身体一点安静，常能让下一步变得清楚。',
    image: '/assets/psynova/monet-wellbeing-postcards.png',
    imageAlt: '花树下两人安静交谈的莫奈式明信片画作',
    backgroundPosition: '0% 100%',
  },
  {
    kind: 'tip',
    title: '与人分享一点重量',
    body: '有些难处在说出口时会松一点。找可信任的人聊聊，不必一个人撑完。',
    image: '/assets/psynova/monet-wellbeing-postcards.png',
    imageAlt: '窗边阅读角与绿植的莫奈式明信片画作',
    backgroundPosition: '100% 100%',
  },
  {
    kind: 'tip',
    title: '先走眼前的一步',
    body: '不必一次看清整条路。先走好眼前这一步，路会在脚下慢慢显形。',
    image: '/assets/psynova/wellbeing-step-forward.webp',
    imageAlt: '莫奈式睡莲池边的小径通向花园深处',
  },
  {
    kind: 'tip',
    title: '给感受一处停靠',
    body: '把感受写下来，不是为了立刻解释，而是给心一个可以停靠的地方。',
    image: '/assets/psynova/wellbeing-feelings-shelter.webp',
    imageAlt: '莫奈式花园窗边的桌上放着空白笔记本和茶杯',
  },
  {
    kind: 'tip',
    title: '让支持有机会靠近',
    body: '说出难处，不会削弱自己。它只是让信任的人有机会与你分担。',
    image: '/assets/psynova/wellbeing-share-support.webp',
    imageAlt: '莫奈式花树下两位朋友在长椅上交谈倾听',
  },
  {
    kind: 'tip',
    title: '把休息留在生活里',
    body: '休息不是退出生活，而是让身体与心重新并肩。给自己一段不必证明什么的时间。',
    image: '/assets/psynova/wellbeing-rest-in-life.webp',
    imageAlt: '黎明时分柳树下临水的空长椅与平静河面',
  },
]

const pickDailyTips = (tips: Extract<StudentCarouselSlide, { kind: 'tip' }>[], date = new Date()) => {
  const dayKey = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
  let seed = Array.from(dayKey).reduce((value, char) => (value * 31 + char.charCodeAt(0)) >>> 0, 2166136261)
  const random = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0
    return seed / 0x100000000
  }
  const shuffled = [...tips]
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1))
    ;[shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]]
  }
  return shuffled.slice(0, 4)
}

const carouselSlides = computed<StudentCarouselSlide[]>(() => [
  {
    kind: 'welcome',
    title: '欢迎回来',
    subtitle: '一起探索 AI 的更多可能',
    image: '/assets/psynova/academy-welcome-card.png',
    imageAlt: '柔和的蓝色、青色与粉色流动色彩',
  },
  ...pickDailyTips(wellbeingTipPool),
])
const academyCarouselArrowPath = 'M32 16C32 7.1776 24.824 0 16 0C7.1776 0 0 7.1776 0 16C0 24.8224 7.1776 32 16 32C24.824 32 32 24.8224 32 16ZM14.5385 9.59731C14.3049 9.36371 13.9977 9.24691 13.6921 9.24691C13.3849 9.24691 13.0761 9.36371 12.8425 9.60051C12.3753 10.0709 12.3769 10.8293 12.8457 11.2965L17.5705 16.0005L12.8457 20.7045C12.3769 21.1717 12.3753 21.9317 12.8425 22.4021C13.3113 22.8725 14.0697 22.8725 14.5385 22.4053L20.1177 16.8501C20.3433 16.6245 20.4697 16.3189 20.4697 16.0005C20.4697 15.6805 20.3433 15.3749 20.1177 15.1493L14.5385 9.59731Z'
const carouselIndex = ref(0)
const carouselSlide = computed(() => carouselSlides.value[carouselIndex.value])
const isHistory = computed(() => route.path === '/student/history')
const historyCategoryOptions = [
  { value: 'assessment', label: '我的测评' },
  { value: 'feedback', label: '测评反馈' },
  { value: 'support', label: '教育支持' },
] as const
const historyFloatingVisible = ref(false)
const historyHeaderElement = ref<HTMLElement | null>(null)
const historyTabsElement = ref<HTMLElement | null>(null)
const historyFloatingBounds = ref({ left: 0, width: 0 })
const carouselIntervalMs = 30_000
let carouselTimer: number | undefined
let historyScrollFrame: number | undefined
let reducedMotionQuery: MediaQueryList | null = null
let pointerPaused = false
let focusPaused = false
const carouselMounted = ref(false)

const historyFloatingStyle = computed(() => ({
  left: `${historyFloatingBounds.value.left}px`,
  width: `${historyFloatingBounds.value.width}px`,
}))

const syncHistoryFloatingNav = () => {
  const header = historyHeaderElement.value
  const tabs = historyTabsElement.value
  if (!isHistory.value || !header || !tabs) {
    historyFloatingVisible.value = false
    return
  }

  const headerBounds = header.getBoundingClientRect()
  const topbarHeight = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--layout-topbar')) || 70
  historyFloatingBounds.value = { left: headerBounds.left, width: headerBounds.width }
  historyFloatingVisible.value = tabs.getBoundingClientRect().bottom <= topbarHeight
}

const scheduleHistoryFloatingNavSync = () => {
  if (historyScrollFrame !== undefined) return
  historyScrollFrame = window.requestAnimationFrame(() => {
    historyScrollFrame = undefined
    syncHistoryFloatingNav()
  })
}

const clearCarouselTimer = () => {
  if (carouselTimer !== undefined) window.clearTimeout(carouselTimer)
  carouselTimer = undefined
}

const scheduleCarouselRotation = () => {
  clearCarouselTimer()
  if (!carouselMounted.value || isHistory.value || pointerPaused || focusPaused || document.hidden || reducedMotionQuery?.matches) return
  carouselTimer = window.setTimeout(() => {
    carouselIndex.value = (carouselIndex.value + 1) % carouselSlides.value.length
    scheduleCarouselRotation()
  }, carouselIntervalMs)
}

const setCarouselSlide = (index: number) => {
  carouselIndex.value = (index + carouselSlides.value.length) % carouselSlides.value.length
  scheduleCarouselRotation()
}
const previousCarouselSlide = () => setCarouselSlide(carouselIndex.value - 1)
const nextCarouselSlide = () => setCarouselSlide(carouselIndex.value + 1)

const load = async () => {
  const generation = ++historyRequestGeneration.value
  state.value = 'loading'
  errorMessage.value = ''
  try {
    try {
      const reportResponse = await frontendApi.listReports()
      if (generation !== historyRequestGeneration.value) return
      reports.value = reportResponse.data.items
      historyError.value = ''
    } catch (error) {
      if (generation !== historyRequestGeneration.value) return
      reports.value = []
      historyError.value = userFacingApiError(error, '支持记录暂时无法加载。')
    }
    if (generation !== historyRequestGeneration.value) return
    state.value = 'ready'
  } catch (error) {
    if (generation !== historyRequestGeneration.value) return
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '页面暂时无法加载，请稍后重试。')
  }
}

const openSupportHistory = (reportId: string) => void router.push(`/student/reports/${encodeURIComponent(reportId)}`)
const formatHistoryDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}
const canOpenSupportReport = (report: ReportSummary) => report.status.toLowerCase() === 'generated' && report.safety_action !== 'CRISIS_ROUTE'
const supportReportStatus = (report: ReportSummary) => {
  if (report.safety_action === 'CRISIS_ROUTE') return '安全流程记录'
  const status = report.status.toLowerCase()
  if (status === 'generated') return '已发布反馈'
  if (status === 'needs_review' || status === 'pending' || status === 'in_review') return '待复核'
  if (status === 'approved' || status === 'closed') return '已批准，正文暂不可见'
  if (status === 'rejected') return '未获准发布'
  if (status === 'safety_blocked' || status === 'blocked') return '暂不可发布'
  return '处理中'
}
const supportReportLibraryStatus = (report: ReportSummary): StudentHistoryLibraryItem['status'] => {
  if (report.safety_action === 'CRISIS_ROUTE') return 'completed'
  const status = report.status.toLowerCase()
  return ['generated', 'approved', 'closed', 'rejected', 'safety_blocked', 'blocked'].includes(status)
    ? 'completed'
    : 'in_progress'
}
const supportHistoryItems = computed<StudentHistoryLibraryItem[]>(() => reports.value.map((report) => ({
  key: `support:${report.report_id}`,
  kind: 'support-report',
  ref: report.report_id,
  status: supportReportLibraryStatus(report),
  statusLabel: supportReportStatus(report),
  category: '教育支持',
  title: report.safety_action === 'CRISIS_ROUTE' ? '安全流程记录' : '支持反馈记录',
  poster: '/assets/psynova/academy-feature-education-support.png',
  dateLabel: formatHistoryDate(report.created_at),
  actionLabel: canOpenSupportReport(report) ? '查看反馈' : undefined,
  actionVariant: 'secondary',
})))
const feedbackHistoryItems = computed<StudentHistoryLibraryItem[]>(() => feedbackRows.value.map((feedback) => ({
  key: `feedback:${feedback.feedback_ref}`,
  kind: 'assessment-feedback',
  ref: feedback.feedback_ref,
  status: 'completed',
  statusLabel: '已发布',
  category: '测评反馈',
  title: feedback.title,
  poster: '/assets/psynova/academy-feature-assessment-feedback.png',
  dateLabel: formatHistoryDate(feedback.published_at),
  actionLabel: '查看详情',
  actionVariant: 'secondary',
})))
const feedbackHasMore = computed(() => feedbackRows.value.length < feedbackTotal.value)
const findFeedback = (feedbackRef: string) => feedbackRows.value.find((feedback) => feedback.feedback_ref === feedbackRef)

const loadStudentFeedback = async (append = false) => {
  if (append && (feedbackLoadingMore.value || !feedbackHasMore.value)) return
  const generation = append ? feedbackRequestGeneration.value : ++feedbackRequestGeneration.value
  const offset = append ? feedbackRows.value.length : 0
  if (append) {
    feedbackLoadingMore.value = true
    feedbackLoadMoreError.value = ''
  } else {
    feedbackState.value = 'loading'
    feedbackRows.value = []
    feedbackTotal.value = 0
    feedbackError.value = ''
    feedbackLoadMoreError.value = ''
  }
  try {
    const page = await schoolFeedback.listStudent(offset, 50)
    if (generation !== feedbackRequestGeneration.value) return
    const previousRefs = new Set(feedbackRows.value.map((item) => item.feedback_ref))
    feedbackRows.value = append
      ? [...feedbackRows.value, ...page.items.filter((item) => !previousRefs.has(item.feedback_ref))]
      : page.items
    feedbackTotal.value = page.total
    feedbackState.value = 'ready'
  } catch (error) {
    if (generation !== feedbackRequestGeneration.value) return
    const message = userFacingApiError(error, '测评反馈暂时无法加载。')
    if (append) feedbackLoadMoreError.value = message
    else {
      feedbackRows.value = []
      feedbackState.value = 'error'
      feedbackError.value = message
    }
  } finally {
    if (generation === feedbackRequestGeneration.value) feedbackLoadingMore.value = false
  }
}
const activateSupportRecord = (item: StudentHistoryLibraryItem) => {
  if (item.kind !== 'support-report') return
  const report = reports.value.find((candidate) => candidate.report_id === item.ref)
  if (report && canOpenSupportReport(report)) openSupportHistory(report.report_id)
}
const activateFeedbackRecord = (item: StudentHistoryLibraryItem) => {
  if (item.kind !== 'assessment-feedback') return
  void router.push({ name: 'student-feedback-detail', params: { id: item.ref } })
}

const pauseCarouselForPointer = () => {
  pointerPaused = true
  clearCarouselTimer()
}
const resumeCarouselForPointer = () => {
  pointerPaused = false
  scheduleCarouselRotation()
}
const pauseCarouselForFocus = (event: FocusEvent) => {
  if (!(event.target instanceof HTMLElement) || !event.target.matches(':focus-visible')) return
  focusPaused = true
  clearCarouselTimer()
}
const resumeCarouselAfterFocus = (event: FocusEvent) => {
  const carousel = event.currentTarget
  if (carousel instanceof HTMLElement && event.relatedTarget instanceof Node && carousel.contains(event.relatedTarget)) return
  focusPaused = false
  scheduleCarouselRotation()
}
const handleVisibilityChange = () => scheduleCarouselRotation()
const handleMotionPreferenceChange = () => scheduleCarouselRotation()

watch(isHistory, () => {
  scheduleCarouselRotation()
  void load()
  scheduleHistoryFloatingNavSync()
})
watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    feedbackRequestGeneration.value += 1
    feedbackRows.value = []
    feedbackTotal.value = 0
    feedbackError.value = ''
    feedbackLoadMoreError.value = ''
    feedbackLoadingMore.value = false
    if (next[0] === 'student' && isHistory.value && historyCategory.value === 'feedback') void loadStudentFeedback()
    else feedbackState.value = 'ready'
  },
)
watch(historyCategory, (category) => {
  if (!isHistory.value) return
  if (category === 'support') void load()
  else if (category === 'feedback') void loadStudentFeedback()
})
onMounted(() => {
  carouselMounted.value = true
  window.addEventListener('scroll', scheduleHistoryFloatingNavSync, { passive: true })
  window.addEventListener('resize', scheduleHistoryFloatingNavSync)
  reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotionQuery.addEventListener('change', handleMotionPreferenceChange)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  scheduleCarouselRotation()
  scheduleHistoryFloatingNavSync()
  load()
})
onUnmounted(() => {
  carouselMounted.value = false
  clearCarouselTimer()
  window.removeEventListener('scroll', scheduleHistoryFloatingNavSync)
  window.removeEventListener('resize', scheduleHistoryFloatingNavSync)
  if (historyScrollFrame !== undefined) window.cancelAnimationFrame(historyScrollFrame)
  historyScrollFrame = undefined
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  reducedMotionQuery?.removeEventListener('change', handleMotionPreferenceChange)
  reducedMotionQuery = null
})
</script>

<template>
  <div class="content-wrap content-wrap--student student-space">
    <div v-if="state === 'loading' && !isHistory" class="student-loading" aria-busy="true" aria-label="正在加载学生空间">
      <div class="skeleton skeleton--short"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--body"></div>
    </div>
    <AppStatusCallout v-else-if="state === 'error' && !isHistory" tone="critical" title="学生空间暂时无法加载" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
    </AppStatusCallout>
    <template v-else-if="!isHistory">
      <section
        class="student-carousel"
        role="region"
        aria-roledescription="carousel"
        aria-label="学生首页轮播"
        @mouseenter="pauseCarouselForPointer"
        @mouseleave="resumeCarouselForPointer"
        @focusin="pauseCarouselForFocus"
        @focusout="resumeCarouselAfterFocus"
        @keydown.left.prevent="previousCarouselSlide"
        @keydown.right.prevent="nextCarouselSlide"
      >
        <div class="student-carousel__stage">
          <Transition name="student-carousel-slide" mode="out-in">
            <article
              :key="carouselIndex"
              class="student-carousel__slide"
              role="group"
              aria-roledescription="slide"
              :aria-label="'第 ' + (carouselIndex + 1) + ' 张，共 ' + carouselSlides.length + ' 张'"
            >
              <div class="student-carousel__copy">
                <template v-if="carouselSlide.kind === 'welcome'">
                  <h1 id="student-home-title" class="student-carousel__welcome-title">{{ carouselSlide.title }}，{{ welcomeName }}</h1>
                  <p class="student-carousel__subtitle">{{ carouselSlide.subtitle }}</p>
                </template>
                <template v-else>
                  <h1 id="student-home-title">{{ carouselSlide.title }}</h1>
                  <p class="student-carousel__subtitle">{{ carouselSlide.body }}</p>
                </template>
              </div>
              <div
                class="student-carousel__art"
                :class="{ 'student-carousel__art--postcard': carouselSlide.kind === 'tip' && Boolean(carouselSlide.backgroundPosition) }"
                :style="carouselSlide.kind === 'tip'
                  ? (carouselSlide.backgroundPosition
                    ? { backgroundPosition: carouselSlide.backgroundPosition }
                    : { backgroundImage: 'url(' + carouselSlide.image + ')' })
                  : { backgroundImage: 'url(' + carouselSlide.image + ')' }"
                role="img"
                :aria-label="carouselSlide.imageAlt"
              ></div>
            </article>
          </Transition>
        </div>
        <button class="student-carousel__arrow student-carousel__arrow--previous" type="button" aria-label="上一张卡片" @click="previousCarouselSlide">
          <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><path :d="academyCarouselArrowPath" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" /></svg>
        </button>
        <button class="student-carousel__arrow student-carousel__arrow--next" type="button" aria-label="下一张卡片" @click="nextCarouselSlide">
          <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><path :d="academyCarouselArrowPath" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" /></svg>
        </button>
        <div class="student-carousel__dots" aria-label="轮播分页">
          <button
            v-for="(_, index) in carouselSlides"
            :key="index"
            type="button"
            :class="{ 'student-carousel__dot--active': carouselIndex === index }"
            :aria-label="'显示第 ' + (index + 1) + ' 张卡片'"
            :aria-current="carouselIndex === index ? 'true' : undefined"
            @click="setCarouselSlide(index)"
          ></button>
        </div>
      </section>

      <section class="student-feature" aria-labelledby="student-feature-title">
        <h2 id="student-feature-title" class="student-feature__title">借助 AI，更好地认识自己。</h2>
        <div class="student-feature__grid">
          <RouterLink v-for="card in studentFeatureCards" :key="card.tag" class="student-feature-card__link" :to="card.to" :aria-label="`${card.tag}，${card.title}。${card.description}`">
            <article class="student-feature-card">
              <img class="student-feature-card__image" :src="card.image" :alt="card.imageAlt" />
              <div class="student-feature-card__content">
                <span class="student-feature-card__tag">{{ card.tag }}</span>
                <h3>{{ card.title }}</h3>
                <p>{{ card.description }}</p>
              </div>
            </article>
          </RouterLink>
        </div>
        <RouterLink class="student-feature__action" :to="{ path: '/student/assessment', query: { startAssigned: '1' } }">开始测评</RouterLink>
      </section>
    </template>
    <template v-else>
      <WorkspaceBreadcrumb current="我的记录" />
      <div ref="historyHeaderElement" class="history-header">
        <StudentPageHero
          :eyebrow="studentPageBannerCopy.history.eyebrow"
          :title="studentPageTitles.history"
          :subtitle="studentPageBannerCopy.history.subtitle"
          :image="studentPageArt.history"
          image-position="center 48%"
          light-text
        />
        <nav ref="historyTabsElement" class="history-tabs" aria-label="记录类别">
          <div class="history-tabs__categories">
            <button v-for="option in historyCategoryOptions" :key="option.value" type="button" :aria-pressed="historyCategory === option.value" @click="historyCategory = option.value">{{ option.label }}</button>
          </div>
        </nav>
      </div>

      <Transition name="history-floating">
        <div v-if="historyFloatingVisible" class="history-floating-nav" :style="historyFloatingStyle">
          <WorkspaceBreadcrumb current="我的记录" />
          <nav class="history-tabs history-floating-nav__tabs" aria-label="记录类别快捷切换">
            <div class="history-tabs__categories">
              <button v-for="option in historyCategoryOptions" :key="option.value" type="button" :aria-pressed="historyCategory === option.value" @click="historyCategory = option.value">{{ option.label }}</button>
            </div>
          </nav>
        </div>
      </Transition>

      <section class="history-collection" aria-label="成长记录内容">
        <AppStatusCallout v-if="state === 'error'" tone="critical" title="成长记录暂时无法加载" :body="errorMessage">
          <StudentRefreshButton :loading="state === 'loading'" label="重新加载" @click="load" />
        </AppStatusCallout>
        <Transition v-else name="history-panel" mode="out-in">
        <StudentAssessmentsView v-if="historyCategory === 'assessment'" embedded />

        <StudentHistoryLibrary
          v-else-if="historyCategory === 'feedback'"
          :items="feedbackHistoryItems"
          :loading="feedbackState === 'loading'"
          :error="feedbackError"
          error-title="测评反馈暂时无法加载"
          empty-title="目前没有已发布的测评反馈"
          empty-description="只有学校审核发布给当前账号的反馈会显示在这里。"
          empty-icon="feedback"
          :has-more="feedbackHasMore"
          :loading-more="feedbackLoadingMore"
          :load-more-error="feedbackLoadMoreError"
          @retry="loadStudentFeedback()"
          @load-more="loadStudentFeedback(true)"
          @activate="activateFeedbackRecord"
        >
          <template #details="{ item }">
            <details v-if="findFeedback(item.ref)" class="history-feedback-details">
              <summary>查看反馈正文</summary>
              <p>{{ findFeedback(item.ref)?.body }}</p>
            </details>
          </template>
        </StudentHistoryLibrary>

        <StudentHistoryLibrary
          v-else
          :items="supportHistoryItems"
          :loading="state === 'loading'"
          :error="historyError"
          error-title="教育支持记录暂时无法加载"
          empty-title="目前没有教育支持记录"
          empty-description="服务端已保存且当前账号可查看的记录会显示在这里。"
          empty-icon="support"
          @retry="load"
          @activate="activateSupportRecord"
        />
        </Transition>
      </section>
    </template>
  </div>
</template>

<style scoped>
.student-space { padding-top: 0; padding-bottom: 0; }
.student-kicker { color: var(--color-primary); font-size: 12px; font-weight: 600; letter-spacing: .08em; }
.student-carousel { position: relative; width: 100%; }
.student-carousel__stage { position: relative; width: 100%; height: 316px; overflow: hidden; }
.student-carousel__slide { position: absolute; inset: 0; display: flex; align-items: center; justify-content: space-between; gap: 60px; padding: 0 clamp(74px, 10.12vw, 140px); }
.student-carousel__copy { width: min(380px, 42%); min-width: 0; color: #1e1d29; }
.student-carousel__copy h1 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 24px; font-weight: 500; letter-spacing: -.015em; line-height: 1.3; }
.student-carousel__welcome-title { display: -webkit-box; max-width: 100%; overflow: hidden; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.student-carousel__copy > p { margin: 20px 0 0; color: #555a64; font-size: 16px; font-weight: 500; line-height: 1.35; }
.student-carousel__art { display: block; width: min(30vw, 300px); height: auto; aspect-ratio: 4 / 3; flex: 0 0 auto; overflow: hidden; border: 0; background-color: #e9eff0; background-position: center; background-repeat: no-repeat; background-size: cover; box-shadow: none; }
.student-carousel__art--postcard { border: 1px solid #eee9dd; background-image: url('/assets/psynova/monet-wellbeing-postcards.png'); background-size: 200% 200%; box-shadow: 0 4px 14px rgb(30 29 41 / 10%); }
.student-carousel__arrow { position: absolute; z-index: 2; top: 50%; display: grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 50%; color: rgb(12 14 19 / 30%); background: transparent; cursor: pointer; opacity: 0; pointer-events: none; transform: translateY(-50%); transition: opacity var(--motion-fast), color var(--motion-fast), transform var(--motion-fast); }
.student-carousel:hover .student-carousel__arrow, .student-carousel__arrow:focus-visible { opacity: 1; pointer-events: auto; }
.student-carousel__arrow:hover { color: rgb(12 14 19 / 42%); transform: translateY(-50%) scale(1.03); }
.student-carousel__arrow svg { display: block; width: 34px; height: 34px; }
.student-carousel__arrow--previous svg { transform: scaleX(-1); }
.student-carousel__arrow:focus-visible, .student-carousel__dots button:focus-visible { outline: 2px solid #2c9df0; outline-offset: 3px; }
.student-carousel__arrow--previous { left: 8px; }
.student-carousel__arrow--next { right: 8px; }
.student-carousel__dots { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 5px; margin-top: 14px; }
.student-carousel__dots button { width: 7px; height: 5px; flex: 0 0 auto; padding: 0; border: 0; border-radius: 4px; background: #cccccc; cursor: pointer; transition: width var(--motion-fast), background-color var(--motion-fast); }
.student-carousel__dots button.student-carousel__dot--active { width: 18px; background: #888888; }
.student-carousel-slide-enter-active, .student-carousel-slide-leave-active { transition: opacity 220ms ease, transform 220ms ease; }
.student-carousel-slide-enter-from { opacity: 0; transform: translateX(12px); }
.student-carousel-slide-leave-to { opacity: 0; transform: translateX(-12px); }
.history-header { overflow: hidden; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); }
.history-header :deep(.student-page-hero) { margin-bottom: 0; border-bottom: 0; border-radius: 12px 12px 0 0; box-shadow: none; }
.history-floating-nav { position: fixed; z-index: 35; top: var(--layout-topbar); display: flex; flex-direction: column; overflow: hidden; border: 1px solid rgb(255 255 255 / 62%); border-radius: 0 0 12px 12px; background: rgb(255 255 255 / 76%); box-shadow: 0 14px 30px rgb(25 34 48 / 10%); backdrop-filter: blur(25px); -webkit-backdrop-filter: blur(25px); }
.history-floating-nav :deep(.workspace-breadcrumb) { margin: 0; padding: 12px 24px 8px; }
.history-floating-nav .history-tabs { position: relative; --history-floating-divider-inset: 24px; --history-floating-divider-fade: 10px; min-height: 58px; padding: 8px 24px; border-top: 0; border-bottom: 0; background: transparent; }
.history-floating-nav .history-tabs::before { position: absolute; top: 0; right: 0; left: 0; height: 1px; background: linear-gradient(90deg, transparent 0, transparent calc(var(--history-floating-divider-inset) - var(--history-floating-divider-fade)), rgb(15 23 42 / 8%) var(--history-floating-divider-inset), rgb(15 23 42 / 8%) calc(100% - var(--history-floating-divider-inset)), transparent calc(100% - var(--history-floating-divider-inset) + var(--history-floating-divider-fade)), transparent 100%); content: ""; pointer-events: none; }
.history-floating-enter-active, .history-floating-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.history-floating-enter-from, .history-floating-leave-to { opacity: 0; transform: translateY(-8px); }
.history-collection { margin-top: 18px; overflow: hidden; border-radius: 12px; background: #fff; box-shadow: var(--shadow-rest); }
.history-tabs { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 62px; padding: 10px 24px; border-bottom: 1px solid #eceef1; background: #fff; }
.history-tabs__categories { display: flex; min-width: 0; align-items: center; gap: 8px; }
.history-tabs button { min-height: 38px; flex: 0 0 auto; padding: 0 15px; border: 0; border-radius: 7px; color: #4e5663; background: transparent; cursor: pointer; font: inherit; font-size: 13px; font-weight: 600; transition: color var(--motion-fast), background-color var(--motion-fast); }
.history-tabs button:hover { color: #1e1d29; background: #f4f6f8; }
.history-tabs button[aria-pressed="true"] { color: #00a9dd; background: #e8f7fb; }
.history-tabs button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
:deep(.history-feedback-details) { padding-top: 8px; border-top: 1px solid var(--color-border); }
:deep(.history-feedback-details summary) { color: var(--color-primary); font-size: 11px; font-weight: 600; cursor: pointer; }
:deep(.history-feedback-details p) { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.history-panel-enter-active, .history-panel-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.history-panel-enter-from { opacity: 0; transform: translateY(4px); }
.history-panel-leave-to { opacity: 0; transform: translateY(-3px); }
.student-feature { margin-top: 40px; padding: 35px 59px 40px; overflow: hidden; border-radius: 12px; background: #fff; box-shadow: 0 0 26px rgb(0 0 0 / 5%); }
.student-feature__title { margin: 0 0 16px; color: #1e1d29; font-family: var(--font-sans); font-size: 28px; font-weight: 600; line-height: 1.6; text-align: center; }
.student-feature__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 20px; }
.student-feature-card__link { display: flex; min-width: 0; color: inherit; text-decoration: none; }
.student-feature-card { display: flex; width: 100%; min-width: 0; min-height: 380px; flex-direction: column; overflow: hidden; border: 1px solid #f3f5f8; border-radius: 12px; background: #f7faff; box-shadow: 0 20px 12px rgb(0 0 0 / 2%), 0 9px 9px rgb(0 0 0 / 2%), 0 2px 5px rgb(0 0 0 / 2%); transition: transform var(--motion-fast), border-color var(--motion-fast), box-shadow var(--motion-fast); }
.student-feature-card__link:hover .student-feature-card { transform: translateY(-2px); border-color: #dbeef5; box-shadow: 0 21px 18px rgb(0 0 0 / 5%), 0 8px 10px rgb(0 0 0 / 3%); }
.student-feature-card__link:focus-visible { border-radius: 12px; outline: 2px solid #249de0; outline-offset: 3px; }
.student-feature-card__link:focus-visible .student-feature-card { border-color: #75cde6; }
.student-feature-card__image { display: block; width: 100%; aspect-ratio: 2.4 / 1; flex: 0 0 auto; object-fit: cover; }
.student-feature-card__content { display: grid; align-content: start; gap: 0; padding: 24px 28px 28px; }
.student-feature-card__tag { color: #00a9dd; font-family: var(--font-sans); font-size: 16px; font-weight: 500; line-height: 1.6; }
.student-feature-card h3 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 26px; font-weight: 700; line-height: 1.55; overflow-wrap: anywhere; text-wrap: balance; }
.student-feature-card p { margin: 0; color: #171923; font-family: var(--font-sans); font-size: 16px; font-weight: 400; line-height: 1.6; }
.student-feature__action { display: flex; width: fit-content; min-height: 40px; align-items: center; justify-content: center; margin: 48px auto 0; padding: 9px 15px; border: 1px solid #41434b; border-radius: 8px; color: #1e1d29; background: #fff; font-family: var(--font-sans); font-size: 14px; font-weight: 600; line-height: 1.4; text-decoration: none; transition: background-color var(--motion-fast), color var(--motion-fast); }
.student-feature__action:hover { color: #1e1d29; background: rgb(0 0 0 / 5%); }
.student-feature__action:focus-visible { outline: 2px solid #249de0; outline-offset: 3px; }
.student-loading { padding-top: 18px; }
.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(100deg, transparent, rgb(255 255 255 / 62%), transparent); transform: translateX(-100%); animation: student-skeleton-shimmer 1.35s ease-in-out infinite; }
.skeleton--short { width: 120px; height: 13px; }
.skeleton--title { width: min(480px, 70%); height: 35px; margin-top: 17px; }
.skeleton--body { width: min(620px, 90%); height: 16px; margin-top: 13px; }
@keyframes student-skeleton-shimmer { to { transform: translateX(100%); } }

@media (max-width: 760px) {
  .student-carousel__stage { height: 392px; }
  .student-carousel__slide { align-items: flex-start; flex-direction: column; justify-content: center; gap: 18px; padding: 26px 52px; }
  .student-carousel__copy { width: 100%; max-width: none; }
  .student-carousel__copy h1 { font-size: 23px; }
  .student-carousel__copy > p { margin-top: 12px; font-size: 15px; }
  .student-carousel__art { width: min(180px, 48vw); height: auto; align-self: center; }
  .student-carousel__arrow { width: 34px; height: 34px; }
  .student-carousel__arrow--previous { left: 4px; }
  .student-carousel__arrow--next { right: 4px; }
  .student-feature { padding-right: 32px; padding-left: 32px; }
  .student-feature__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 520px) {
  .student-carousel__stage { height: 408px; }
  .student-carousel__slide { gap: 16px; padding: 24px 45px; }
  .student-carousel__copy h1 { font-size: 21px; }
  .student-carousel__copy > p { font-size: 14px; line-height: 1.55; }
  .student-carousel__art { width: min(172px, 48vw); height: auto; }
  .student-feature { padding: 28px 20px 32px; }
  .student-feature__title { margin-bottom: 18px; font-size: 23px; line-height: 1.4; }
  .student-feature-card { min-height: 0; }
  .student-feature-card__content { padding: 20px 22px 24px; }
  .student-feature-card h3 { font-size: 24px; }
  .student-feature__action { margin-top: 32px; }
  .history-collection { margin-top: 14px; }
  .history-tabs { min-height: 54px; gap: 4px; padding: 8px 12px; }
  .history-tabs button { min-height: 36px; padding: 0 11px; font-size: 12px; }
}

@media (max-width: 680px) {
  .history-tabs { align-items: flex-start; flex-direction: column; padding: 10px 16px; }
  .history-tabs__categories { width: 100%; overflow-x: auto; }
  .history-floating-nav :deep(.workspace-breadcrumb) { padding: 10px 16px 6px; }
  .history-floating-nav .history-tabs { --history-floating-divider-inset: 16px; --history-floating-divider-fade: 8px; padding: 6px 16px 10px; }
}

@media (prefers-reduced-motion: reduce) {
  .history-panel-enter-active, .history-panel-leave-active, .history-floating-enter-active, .history-floating-leave-active, .student-feature-card { transition: none; }
  .history-floating-enter-from, .history-floating-leave-to { opacity: 1; transform: none; }
  .student-feature-card__link:hover .student-feature-card { transform: none; }
}
@media (max-width: 620px) {
  .student-feature { padding-right: 20px; padding-left: 20px; }
  .student-feature__grid { grid-template-columns: 1fr; }
}
@media (hover: none), (pointer: coarse) {
  .student-carousel__arrow { opacity: 1; pointer-events: auto; }
}
@media (prefers-reduced-motion: reduce) {
  .student-carousel-slide-enter-active, .student-carousel-slide-leave-active { transition: none; }
}
</style>
