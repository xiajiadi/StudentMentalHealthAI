<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import StudentRefreshButton from '@/components/app/StudentRefreshButton.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import StudentHistoryLibrary from '@/components/student/StudentHistoryLibrary.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import type { StudentHistoryLibraryItem } from '@/components/student/history-library'
import { studentPageArt, studentPageBannerCopy, studentPageTitles } from '@/data/student-feature-cards'
import { useSessionStore } from '@/stores/session'
import { schoolFeedback, type StudentSchoolFeedback } from '@/services/school-feedback'
import { userFacingApiError } from '@/utils/user-facing-errors'
import { useRouter } from 'vue-router'
import StudentFeedbackDetailView from './StudentFeedbackDetailView.vue'

const props = defineProps<{ embedded?: boolean; initialFeedbackRef?: string }>()
const emit = defineEmits<{ support: [] }>()
const selectedFeedback = ref(props.initialFeedbackRef)

const schoolFeedbackState = ref<'loading' | 'ready' | 'error'>('loading')
const schoolFeedbackRows = ref<StudentSchoolFeedback[]>([])
const schoolFeedbackError = ref('')
const session = useSessionStore()
const router = useRouter()
const schoolFeedbackGeneration = ref(0)

const formatHistoryDate = (value: string | null | undefined) => {
  if (!value) return '时间未提供'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间暂不可用'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

const feedbackItems = computed<StudentHistoryLibraryItem[]>(() => schoolFeedbackRows.value.map((feedback) => ({
  key: `feedback:${feedback.feedback_ref}`,
  kind: 'assessment-feedback',
  ref: feedback.feedback_ref,
  status: 'completed',
  statusLabel: '已发布',
  category: '测评反馈',
  title: feedback.title,
  poster: studentPageArt.feedback,
  dateLabel: formatHistoryDate(feedback.published_at),
  actionLabel: '查看详情',
  actionSize: 'md',
  actionVariant: 'primary',
})))

const openFeedbackDetail = (item: StudentHistoryLibraryItem) => {
  if (item.kind !== 'assessment-feedback') return
  if (props.embedded) {
    selectedFeedback.value = item.ref
    return
  }
  void router.push({ name: 'student-feedback-detail', params: { id: item.ref } })
}

const loadSchoolFeedback = async () => {
  const generation = ++schoolFeedbackGeneration.value
  schoolFeedbackState.value = 'loading'
  schoolFeedbackRows.value = []
  schoolFeedbackError.value = ''
  try {
    const result = await schoolFeedback.listStudent()
    if (generation !== schoolFeedbackGeneration.value) return
    schoolFeedbackRows.value = result.items
    schoolFeedbackState.value = 'ready'
  } catch (error) {
    if (generation !== schoolFeedbackGeneration.value) return
    schoolFeedbackRows.value = []
    schoolFeedbackState.value = 'error'
    schoolFeedbackError.value = userFacingApiError(error, '已发布反馈暂时无法加载。')
  }
}

function backToList() {
  selectedFeedback.value = undefined
  void loadSchoolFeedback()
}

watch(
  () => [session.user?.role ?? null, session.user?.userId ?? null, session.user?.activeContext?.schoolRef ?? null, session.user?.activeContext ?? null] as const,
  (next, previous) => {
    if (!previous || next.every((value, index) => value === previous[index])) return
    selectedFeedback.value = undefined
    schoolFeedbackRows.value = []
    schoolFeedbackError.value = ''
    if (next[0] === 'student') void loadSchoolFeedback()
    else {
      schoolFeedbackGeneration.value += 1
      schoolFeedbackState.value = 'ready'
    }
  },
)

onBeforeUnmount(() => {
  schoolFeedbackGeneration.value += 1
})

onMounted(() => {
  if (!selectedFeedback.value) void loadSchoolFeedback()
})
</script>

<template>
  <div class="student-feedback" :class="{ 'content-wrap content-wrap--student': !embedded }">
    <WorkspaceBreadcrumb v-if="!embedded" current="测评反馈" />
    <StudentPageHero
      v-if="!embedded"
      :eyebrow="studentPageBannerCopy.feedback.eyebrow"
      :title="studentPageTitles.feedback"
      :subtitle="studentPageBannerCopy.feedback.subtitle"
      :image="studentPageArt.feedback"
      image-position="center 48%"
      light-text
    />

    <div v-if="embedded && selectedFeedback" class="feedback-section feedback-section--embedded">
      <AppButton variant="quiet" @click="backToList">返回反馈列表</AppButton>
      <StudentFeedbackDetailView :embedded-feedback-ref="selectedFeedback" @support="emit('support')" />
    </div>
    <section v-else class="feedback-section published-feedback" :class="{ 'feedback-section--embedded': embedded }" aria-labelledby="published-feedback-title">
      <header class="feedback-section__heading">
        <div><h2 id="published-feedback-title">已发布的学生测评反馈</h2></div>
        <StudentRefreshButton :loading="schoolFeedbackState === 'loading'" aria-label="刷新已发布反馈" @click="loadSchoolFeedback" />
      </header>
      <StudentHistoryLibrary
        fixed-view-mode="list"
        :show-toolbar="false"
        :items="feedbackItems"
        :loading="schoolFeedbackState === 'loading'"
        :error="schoolFeedbackError"
        error-title="已发布反馈暂时无法加载"
        empty-title="目前没有单独发布的反馈"
        empty-description="学校审核并发布后，反馈会显示在这里"
        empty-icon="feedback"
        @retry="loadSchoolFeedback"
        @activate="openFeedbackDetail"
      />
    </section>

  </div>
</template>

<style scoped>
.student-feedback { padding-top: 0; }
.feedback-section { margin-top: 34px; }
.feedback-section--embedded { margin-top: 0; }
.feedback-section__heading { display: flex; align-items: end; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.feedback-section__heading h2 { margin: 5px 0 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: 23px; }
</style>
