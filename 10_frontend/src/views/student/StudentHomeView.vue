<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, BookOpen, CheckCircle2, ClipboardList, History, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi } from '@/services/mock-api'
import { userFacingApiError } from '@/utils/user-facing-errors'
import type { AssessmentListEntry, ReportSummary } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const assessments = ref<AssessmentListEntry[]>([])
const reports = ref<ReportSummary[]>([])
const errorMessage = ref('')
const historyError = ref('')
const loadMoreError = ref('')
const assessmentPageSize = 30
const nextAssessmentOffset = ref(0)
const assessmentRequestGeneration = ref(0)
const isLoadingMoreAssessments = ref(false)
const hasMoreAssessments = ref(false)
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

const featureCards = [
  {
    tag: '自我探索',
    title: '从一次测评开始',
    description: '一题一答之间，记下此刻的学习、生活与感受。',
    image: '/assets/psynova/academy-feature-self-exploration.jpeg',
    imageAlt: '蓝色、青色与粉色交织的流动渐变',
  },
  {
    tag: '测评反馈',
    title: '换个角度看自己',
    description: '读一读已发布的反馈，从不同角度理解自己的近况。',
    image: '/assets/psynova/academy-feature-assessment-feedback.png',
    imageAlt: '绿色、青色与浅黄色交织的柔和渐变',
  },
  {
    tag: '教育支持',
    title: '有困惑，就聊聊',
    description: '学习、生活与人际相处的难题，都可以从一次对话说起。',
    image: '/assets/psynova/academy-feature-education-support.png',
    imageAlt: '橙色、紫色与粉色交织的柔和渐变',
  },
  {
    tag: '成长记录',
    title: '回望来时路',
    description: '翻看测评与支持记录，看看自己在不同阶段的变化。',
    image: '/assets/psynova/academy-feature-growth-record.png',
    imageAlt: '粉色、蓝色、紫色与淡金色交织的渐变',
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
    title: 'Welcome back',
    subtitle: "Let's unlock AI together",
    image: '/assets/psynova/academy-welcome-card.png',
    imageAlt: '柔和的蓝色、青色与粉色流动色彩',
  },
  ...pickDailyTips(wellbeingTipPool),
])
const academyCarouselArrowPath = 'M32 16C32 7.1776 24.824 0 16 0C7.1776 0 0 7.1776 0 16C0 24.8224 7.1776 32 16 32C24.824 32 32 24.8224 32 16ZM14.5385 9.59731C14.3049 9.36371 13.9977 9.24691 13.6921 9.24691C13.3849 9.24691 13.0761 9.36371 12.8425 9.60051C12.3753 10.0709 12.3769 10.8293 12.8457 11.2965L17.5705 16.0005L12.8457 20.7045C12.3769 21.1717 12.3753 21.9317 12.8425 22.4021C13.3113 22.8725 14.0697 22.8725 14.5385 22.4053L20.1177 16.8501C20.3433 16.6245 20.4697 16.3189 20.4697 16.0005C20.4697 15.6805 20.3433 15.3749 20.1177 15.1493L14.5385 9.59731Z'
const carouselIndex = ref(0)
const carouselSlide = computed(() => carouselSlides.value[carouselIndex.value])
const isHistory = computed(() => route.path === '/student/history')
const carouselIntervalMs = 30_000
let carouselTimer: number | undefined
let reducedMotionQuery: MediaQueryList | null = null
let pointerPaused = false
let focusPaused = false
const carouselMounted = ref(false)

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
  const generation = ++assessmentRequestGeneration.value
  state.value = 'loading'
  errorMessage.value = ''
  loadMoreError.value = ''
  hasMoreAssessments.value = false
  nextAssessmentOffset.value = 0
  isLoadingMoreAssessments.value = false
  assessments.value = []
  try {
    if (isHistory.value) {
      const rows = frontendApi.listAssessmentEntries
        ? (await frontendApi.listAssessmentEntries({ limit: assessmentPageSize, skip: 0 })).data
        : (await frontendApi.listAssessments({ limit: assessmentPageSize, skip: 0 })).data.map((assessment) => ({
            assessment_id: assessment.assessment_id,
            status: assessment.status,
            items_answered: assessment.response_summary.items_answered,
            started_at: assessment.timestamps.started_at,
            completed_at: assessment.timestamps.completed_at,
          }))
      if (generation !== assessmentRequestGeneration.value) return
      assessments.value = rows
      nextAssessmentOffset.value = rows.length
      hasMoreAssessments.value = rows.length === assessmentPageSize
    }
    try {
      const reportResponse = await frontendApi.listReports()
      if (generation !== assessmentRequestGeneration.value) return
      reports.value = reportResponse.data.items
      historyError.value = ''
    } catch (error) {
      if (generation !== assessmentRequestGeneration.value) return
      reports.value = []
      historyError.value = userFacingApiError(error, '支持记录暂时无法加载。')
    }
    if (generation !== assessmentRequestGeneration.value) return
    state.value = 'ready'
  } catch (error) {
    if (generation !== assessmentRequestGeneration.value) return
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '页面暂时无法加载，请稍后重试。')
  }
}

const loadMoreAssessments = async () => {
  if (isLoadingMoreAssessments.value || !hasMoreAssessments.value || state.value !== 'ready') return
  const generation = assessmentRequestGeneration.value
  isLoadingMoreAssessments.value = true
  loadMoreError.value = ''
  try {
    const rows = frontendApi.listAssessmentEntries
      ? (await frontendApi.listAssessmentEntries({ limit: assessmentPageSize, skip: nextAssessmentOffset.value })).data
      : (await frontendApi.listAssessments({ limit: assessmentPageSize, skip: nextAssessmentOffset.value })).data.map((assessment) => ({
          assessment_id: assessment.assessment_id,
          status: assessment.status,
          items_answered: assessment.response_summary.items_answered,
          started_at: assessment.timestamps.started_at,
          completed_at: assessment.timestamps.completed_at,
        }))
    if (generation !== assessmentRequestGeneration.value) return
    const existingIds = new Set(assessments.value.map((item) => item.assessment_id))
    assessments.value = [...assessments.value, ...rows.filter((item) => !existingIds.has(item.assessment_id))]
    nextAssessmentOffset.value += rows.length
    hasMoreAssessments.value = rows.length === assessmentPageSize
  } catch (error) {
    if (generation !== assessmentRequestGeneration.value) return
    const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code) : ''
    loadMoreError.value = userFacingApiError({ code }, '暂时无法加载更多测评记录，请重试。')
  } finally {
    if (generation === assessmentRequestGeneration.value) isLoadingMoreAssessments.value = false
  }
}

const continueOrStart = (assessment?: AssessmentListEntry) => {
  void router.push(assessment ? `/student/assessment/${encodeURIComponent(assessment.assessment_id)}` : '/student/assessment')
}
const openResult = (assessmentId: string) => void router.push(`/student/assessment/${encodeURIComponent(assessmentId)}/result`)
const openSupportHistory = (reportId: string) => void router.push(`/student/reports/${encodeURIComponent(reportId)}`)
const assessmentStatusLabel = (assessment: AssessmentListEntry) => {
  if (assessment.status === 'created') return '待开始'
  if (assessment.status === 'in_progress') return '进行中'
  if (assessment.status === 'completed') return '已完成'
  if (assessment.status === 'abandoned') return '已结束'
  return '状态暂不可用'
}
const formatHistoryDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}
const assessmentTimeLabel = (assessment: AssessmentListEntry) => assessment.status === 'created' && !assessment.started_at
  ? '尚未开始'
  : formatHistoryDate(assessment.completed_at || assessment.started_at)
const assessmentActionLabel = (assessment: AssessmentListEntry) => {
  if (assessment.status === 'created') return '开始测评'
  if (assessment.status === 'in_progress') return '继续测评'
  if (assessment.status === 'completed') return '查看结果'
  return ''
}
const openAssessmentEntry = (assessment: AssessmentListEntry) => {
  if (assessment.status === 'completed') openResult(assessment.assessment_id)
  else if (assessment.status === 'created' || assessment.status === 'in_progress') continueOrStart(assessment)
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
})
onMounted(() => {
  carouselMounted.value = true
  reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotionQuery.addEventListener('change', handleMotionPreferenceChange)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  scheduleCarouselRotation()
  load()
})
onUnmounted(() => {
  carouselMounted.value = false
  clearCarouselTimer()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  reducedMotionQuery?.removeEventListener('change', handleMotionPreferenceChange)
  reducedMotionQuery = null
})
</script>

<template>
  <div class="content-wrap content-wrap--student student-space">
    <div v-if="state === 'loading'" class="student-loading" aria-busy="true" aria-label="正在加载学生空间">
      <div class="skeleton skeleton--short"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--body"></div>
    </div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="学生空间暂时无法加载" :body="errorMessage">
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
                  <h1 id="student-home-title" class="student-carousel__welcome-title">{{ carouselSlide.title }} {{ welcomeName }}</h1>
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
        <h2 id="student-feature-title" class="student-feature__title">Build a better understanding of yourself with AI.</h2>
        <div class="student-feature__grid">
          <article v-for="card in featureCards" :key="card.tag" class="student-feature-card">
            <img class="student-feature-card__image" :src="card.image" :alt="card.imageAlt" />
            <div class="student-feature-card__content">
              <span class="student-feature-card__tag">{{ card.tag }}</span>
              <h3>{{ card.title }}</h3>
              <p>{{ card.description }}</p>
            </div>
          </article>
        </div>
        <RouterLink class="student-feature__action" to="/student/assessments">开始测评</RouterLink>
      </section>
    </template>
    <template v-else>
      <header class="history-heading">
        <div><span class="student-kicker">学生空间 · 我的记录</span><h1>测评与支持记录</h1><p>这里仅显示当前登录账号有权访问的记录。</p></div>
        <AppButton variant="secondary" @click="router.push('/student/home')"><ArrowLeft :size="16" aria-hidden="true" />返回首页</AppButton>
      </header>
      <section class="history-section" aria-labelledby="assessment-history-title">
        <div class="history-section__heading"><div><span class="student-kicker">测评</span><h2 id="assessment-history-title">我的测评</h2></div><span>{{ hasMoreAssessments ? `已显示 ${assessments.length} 条` : `${assessments.length} 条` }}</span></div>
        <AppCard v-if="assessments.length === 0" class="history-empty"><ClipboardList :size="21" aria-hidden="true" /><div><strong>还没有测评记录</strong><p>开始测评后，保存的记录会显示在这里。</p><AppButton size="sm" @click="continueOrStart()">开始测评 <ArrowRight :size="15" aria-hidden="true" /></AppButton></div></AppCard>
        <AppCard v-for="item in assessments" :key="item.assessment_id" class="history-row">
          <span class="history-row__icon" :class="{ 'history-row__icon--complete': item.status === 'completed' }"><CheckCircle2 v-if="item.status === 'completed'" :size="18" aria-hidden="true" /><History v-else :size="18" aria-hidden="true" /></span>
          <div class="history-row__copy"><strong>{{ item.status === 'completed' ? '已完成的合成测评' : item.status === 'created' ? '尚未开始的合成测评' : '测评记录' }}</strong><span>{{ item.items_answered }} 项已记录 · {{ assessmentTimeLabel(item) }}</span></div>
          <AppBadge :tone="item.status === 'completed' ? 'teal' : item.status === 'created' ? 'neutral' : 'blue'" dot>{{ assessmentStatusLabel(item) }}</AppBadge>
          <AppButton v-if="assessmentActionLabel(item)" variant="secondary" size="sm" @click="openAssessmentEntry(item)">{{ assessmentActionLabel(item) }} <ArrowRight :size="15" aria-hidden="true" /></AppButton>
        </AppCard>
        <div v-if="hasMoreAssessments || loadMoreError" class="history-load-more">
          <AppButton variant="secondary" :disabled="isLoadingMoreAssessments" @click="loadMoreAssessments">{{ isLoadingMoreAssessments ? '正在加载…' : '加载更多记录' }} <ArrowRight :size="15" aria-hidden="true" /></AppButton>
          <p v-if="loadMoreError" role="alert">{{ loadMoreError }}</p>
        </div>
      </section>
      <section class="history-section" aria-labelledby="report-history-title">
        <div class="history-section__heading"><div><span class="student-kicker">教育支持</span><h2 id="report-history-title">支持记录</h2></div><span>{{ reports.length }} 条</span></div>
        <AppStatusCallout v-if="historyError" tone="attention" title="支持记录暂时无法加载" :body="historyError"><AppButton variant="secondary" size="sm" @click="load">重新加载</AppButton></AppStatusCallout>
        <p v-else-if="reports.length === 0" class="history-empty-copy">还没有支持记录。独立支持生成目前受限；如果服务端已有可访问的记录，会显示在这里。</p>
        <AppCard v-for="report in reports" :key="report.report_id" class="history-row">
          <span class="history-row__icon history-row__icon--support"><BookOpen :size="18" aria-hidden="true" /></span>
          <div class="history-row__copy"><strong>{{ report.safety_action === 'CRISIS_ROUTE' ? '安全流程记录' : '教育支持记录' }}</strong><span>{{ formatHistoryDate(report.created_at) }} · {{ supportReportStatus(report) }}</span></div>
          <AppButton v-if="canOpenSupportReport(report)" variant="secondary" size="sm" @click="openSupportHistory(report.report_id)">查看反馈 <ArrowRight :size="15" aria-hidden="true" /></AppButton>
        </AppCard>
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
.history-section { margin-top: 40px; }
.history-section__heading { display: flex; align-items: end; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.history-section__heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 23px; }
.student-feature { margin-top: 40px; padding: 35px 59px 40px; overflow: hidden; border-radius: 12px; background: #fff; box-shadow: 0 0 26px rgb(0 0 0 / 5%); }
.student-feature__title { margin: 0 0 16px; color: #1e1d29; font-family: var(--font-sans); font-size: 28px; font-weight: 600; line-height: 1.6; text-align: center; }
.student-feature__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 20px; }
.student-feature-card { display: flex; min-width: 0; min-height: 380px; flex-direction: column; overflow: hidden; border: 1px solid #f3f5f8; border-radius: 12px; background: #f7faff; box-shadow: 0 20px 12px rgb(0 0 0 / 2%), 0 9px 9px rgb(0 0 0 / 2%), 0 2px 5px rgb(0 0 0 / 2%); }
.student-feature-card__image { display: block; width: 100%; aspect-ratio: 2.4 / 1; flex: 0 0 auto; object-fit: cover; }
.student-feature-card__content { display: grid; align-content: start; gap: 0; padding: 24px 28px 28px; }
.student-feature-card__tag { color: #00a9dd; font-family: var(--font-sans); font-size: 16px; font-weight: 500; line-height: 1.6; }
.student-feature-card h3 { margin: 0; color: #1e1d29; font-family: var(--font-sans); font-size: 26px; font-weight: 700; line-height: 1.55; overflow-wrap: anywhere; text-wrap: balance; }
.student-feature-card p { margin: 0; color: #171923; font-family: var(--font-sans); font-size: 16px; font-weight: 400; line-height: 1.6; }
.student-feature__action { display: flex; width: fit-content; min-height: 40px; align-items: center; justify-content: center; margin: 48px auto 0; padding: 9px 15px; border: 1px solid #41434b; border-radius: 8px; color: #1e1d29; background: #fff; font-family: var(--font-sans); font-size: 14px; font-weight: 600; line-height: 1.4; text-decoration: none; transition: background-color var(--motion-fast), color var(--motion-fast); }
.student-feature__action:hover { color: #1e1d29; background: rgb(0 0 0 / 5%); }
.student-feature__action:focus-visible { outline: 2px solid #249de0; outline-offset: 3px; }
.history-row__icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 36px; border-radius: 11px; color: #456f64; background: #eaf3ef; }
.history-row__icon--complete { color: #397c67; background: #e8f3ec; }
.history-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 15px 0 8px; }
.history-heading h1 { margin: 8px 0 5px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(28px, 4vw, 38px); letter-spacing: -.035em; }
.history-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
.history-section__heading > span { color: var(--color-text-muted); font-size: 11px; }
.history-row { display: flex; align-items: center; gap: 13px; margin-top: 9px; padding: 14px 16px; }
.history-row__icon--support { color: #957344; background: #f7f1e5; }
.history-row__copy { display: grid; min-width: 0; flex: 1; gap: 4px; }
.history-row__copy strong { color: var(--color-text-primary); font-size: 13px; }
.history-row__copy span { overflow: hidden; color: var(--color-text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.history-load-more { display: grid; justify-items: center; gap: 8px; margin-top: 16px; }
.history-load-more p { margin: 0; color: var(--color-critical); font-size: 12px; }
.history-empty { display: flex; align-items: flex-start; gap: 13px; padding: 20px; color: #54766b; }
.history-empty > div { display: grid; gap: 7px; }
.history-empty strong { color: var(--color-text-primary); font-size: 13px; }
.history-empty p, .history-empty-copy { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.history-empty-copy { padding: 12px 0; }
.history-section > .status-callout { margin-top: 9px; }
.student-loading { padding-top: 18px; }
.skeleton { border-radius: 7px; background: var(--color-surface-skeleton); }
.skeleton--short { width: 120px; height: 13px; }
.skeleton--title { width: min(480px, 70%); height: 35px; margin-top: 17px; }
.skeleton--body { width: min(620px, 90%); height: 16px; margin-top: 13px; }

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
  .history-heading { align-items: flex-start; flex-direction: column; }
  .history-row { align-items: flex-start; flex-wrap: wrap; }
  .history-row__copy { flex-basis: calc(100% - 52px); }
  .history-row .app-badge { margin-left: 48px; }
  .history-row .app-button { margin-left: 48px; }
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
