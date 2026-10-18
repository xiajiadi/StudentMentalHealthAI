<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentRecordDetailLayout from '@/components/student/StudentRecordDetailLayout.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt } from '@/data/student-feature-cards'
import { schoolFeedback } from '@/services/school-feedback'
import { useSessionStore } from '@/stores/session'
import { userFacingApiError } from '@/utils/user-facing-errors'
import { useRoute } from 'vue-router'

const route = useRoute()
const session = useSessionStore()
const state = ref<'loading' | 'ready' | 'error'>('loading')
const feedback = ref<{ title: string; body: string; published_at: string | null } | null>(null)
const errorMessage = ref('')
let requestGeneration = 0
const isPreviewRoute = () => import.meta.env.DEV && route.params.id === 'demo' && route.query.preview === '1'
const previewFeedback = {
  title: '学习节奏与安排',
  body: '如果最近想整理学习安排，可以先选一件最想完成的事，把它拆成几个容易开始的小步骤，再给第一步留出一个具体时间。之后可以回看哪种安排更适合自己。',
  published_at: null,
}

const formatDate = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const load = async () => {
  const generation = ++requestGeneration
  const feedbackRef = typeof route.params.id === 'string' ? route.params.id : ''
  state.value = 'loading'
  feedback.value = null
  errorMessage.value = ''
  try {
    if (!feedbackRef) throw new Error('反馈记录编号不可用，请从测评反馈或我的记录重新打开。')
    if (isPreviewRoute()) {
      feedback.value = previewFeedback
      state.value = 'ready'
      return
    }
    const result = await schoolFeedback.getStudent(feedbackRef)
    if (generation !== requestGeneration) return
    feedback.value = result
    state.value = 'ready'
  } catch (error) {
    if (generation !== requestGeneration) return
    state.value = 'error'
    errorMessage.value = userFacingApiError(error, '这条反馈暂时无法打开。')
  }
}

watch(
  () => [route.params.id, route.query.preview, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null] as const,
  () => { void load() },
  { immediate: true },
)

onBeforeUnmount(() => { requestGeneration += 1 })
</script>

<template>
  <div class="content-wrap content-wrap--student feedback-detail">
    <WorkspaceBreadcrumb v-if="state !== 'ready'" current="反馈详情" :parent="{ label: '测评反馈', to: '/student/feedback' }" />
    <div v-if="state === 'loading'" class="feedback-detail__loading" aria-busy="true" aria-label="正在加载反馈详情">
      <span></span><i></i><i></i><section></section>
    </div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="这条反馈暂时无法打开" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton>
    </AppStatusCallout>
    <StudentRecordDetailLayout
      v-else-if="feedback"
      current="反馈详情"
      :parent="{ label: '测评反馈', to: '/student/feedback' }"
      eyebrow="ASSESSMENT FEEDBACK"
      :title="feedback.title"
      :summary="isPreviewRoute() ? '这是一条本地合成样例，用来预览记录详情页的展示方式。' : '查看老师审核发布的测评反馈内容。'"
      :image="studentPageArt.feedback"
      image-position="center 48%"
      :metadata="[{ label: isPreviewRoute() ? '内容状态' : '发布时间', value: isPreviewRoute() ? '本地预览' : formatDate(feedback.published_at) }]"
      :badges="[isPreviewRoute() ? '本地合成预览 · 非正式反馈' : '合成演示 · L3']"
      :table-of-contents="[{ id: 'feedback-content', label: '反馈内容' }, { id: 'feedback-record', label: '记录信息' }]"
    >
      <section id="feedback-content" class="feedback-detail__section" aria-labelledby="feedback-content-title">
        <div class="feedback-detail__section-heading"><span>FEEDBACK</span><h2 id="feedback-content-title">反馈内容</h2></div>
        <AppStatusCallout v-if="isPreviewRoute()" tone="info" title="本地演示预览" body="此合成内容只用于查看页面样式，不依据个人测评数据，也不是老师审核发布的反馈。" />
        <AppCard class="feedback-detail__body"><p>{{ feedback.body }}</p></AppCard>
      </section>
      <section id="feedback-record" class="feedback-detail__section" aria-labelledby="feedback-record-title">
        <div class="feedback-detail__section-heading"><span>RECORD</span><h2 id="feedback-record-title">记录信息</h2></div>
        <AppCard class="feedback-detail__facts">
          <div><span>{{ isPreviewRoute() ? '内容状态' : '发布状态' }}</span><strong>{{ isPreviewRoute() ? '本地预览' : '已发布' }}</strong></div>
          <div><span>{{ isPreviewRoute() ? '内容性质' : '反馈级别' }}</span><strong>{{ isPreviewRoute() ? '合成样例' : 'L3' }}</strong></div>
          <div><span>{{ isPreviewRoute() ? '使用说明' : '发布时间' }}</span><strong>{{ isPreviewRoute() ? '非正式反馈' : formatDate(feedback.published_at) }}</strong></div>
        </AppCard>
      </section>
    </StudentRecordDetailLayout>
  </div>
</template>

<style scoped>
.feedback-detail { padding-top: 0; }
.feedback-detail__section { display: grid; gap: 12px; scroll-margin-top: 86px; }
.feedback-detail__section-heading > span { color: #6f8490; font-size: 10px; font-weight: 700; letter-spacing: .1em; }
.feedback-detail__section-heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 21px; }
.feedback-detail__body { padding: 22px 24px; }
.feedback-detail__body p { margin: 0; color: var(--color-text-primary); font-size: 14px; line-height: 1.9; white-space: pre-wrap; overflow-wrap: anywhere; }
.feedback-detail__facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding: 17px 19px; }
.feedback-detail__facts div { display: grid; gap: 5px; min-width: 0; }
.feedback-detail__facts span { color: var(--color-text-muted); font-size: 11px; }
.feedback-detail__facts strong { color: var(--color-text-primary); font-size: 12px; font-weight: 600; overflow-wrap: anywhere; }
.feedback-detail__loading { display: grid; grid-template-columns: minmax(0, 1fr) 38%; gap: 14px 24px; min-height: 360px; padding: 26px; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.feedback-detail__loading span, .feedback-detail__loading i, .feedback-detail__loading section { position: relative; display: block; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }
.feedback-detail__loading span { width: 160px; height: 24px; }
.feedback-detail__loading i { width: 65%; height: 16px; }
.feedback-detail__loading i:nth-of-type(2) { width: 42%; }
.feedback-detail__loading section { grid-column: 2; grid-row: 1 / 4; min-height: 210px; }
.feedback-detail__loading span::after, .feedback-detail__loading i::after, .feedback-detail__loading section::after { position: absolute; inset: 0; content: ""; background: linear-gradient(100deg, transparent, rgb(255 255 255 / 66%), transparent); transform: translateX(-100%); animation: feedback-detail-shimmer 1.35s ease-in-out infinite; }
@keyframes feedback-detail-shimmer { to { transform: translateX(100%); } }

@media (max-width: 640px) {
  .feedback-detail__facts { grid-template-columns: 1fr; }
  .feedback-detail__loading { grid-template-columns: 1fr; min-height: 280px; padding: 18px; }
  .feedback-detail__loading section { grid-column: 1; grid-row: auto; }
}

@media (prefers-reduced-motion: reduce) {
  .feedback-detail__loading span::after, .feedback-detail__loading i::after, .feedback-detail__loading section::after { animation: none; transform: none; }
}
</style>
