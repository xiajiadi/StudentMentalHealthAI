<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft, RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { isTeacherForbidden, teacherApi, type TeacherStudentHistory } from './teacher-api'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const state = ref<'loading' | 'ready' | 'error' | 'forbidden'>('loading')
const data = ref<TeacherStudentHistory | null>(null)
const errorMessage = ref('')
const subjectId = typeof route.params.id === 'string' ? route.params.id : ''

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    data.value = (await teacherApi.getTeacherStudent(subjectId)).data
    state.value = 'ready'
  } catch (error) {
    state.value = isTeacherForbidden(error) ? 'forbidden' : 'error'
    errorMessage.value = state.value === 'forbidden' ? '此匿名主体不在当前账号的授权范围内。' : '测评历史暂时无法加载，请稍后重试。'
  }
}

const formatTime = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未记录'
const statusLabel = (value: string) => ({
  created: '尚未开始',
  in_progress: '进行中',
  completed: '已完成',
  abandoned: '已中止',
  invalid: '记录无效',
  unknown: '状态未知',
}[value] ?? '状态未知')
const statusTone = (value: string) => value === 'completed' ? 'teal' : value === 'in_progress' ? 'blue' : 'neutral'
const goBack = () => void router.push('/teacher/students')

onMounted(load)
</script>

<template>
  <div class="content-wrap teacher-detail">
    <div v-if="state === 'loading'" class="loading-state" aria-busy="true">正在读取匿名主体的测评历史…</div>
    <AppStatusCallout v-else-if="state === 'forbidden'" tone="critical" title="没有查看权限" :body="errorMessage"><AppButton variant="quiet" size="sm" @click="goBack"><ArrowLeft :size="15" aria-hidden="true" />返回历史列表</AppButton></AppStatusCallout>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="测评历史暂时无法加载" :body="errorMessage"><AppButton variant="secondary" size="sm" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</AppButton></AppStatusCallout>
    <template v-else-if="data">
      <AppPageHeader eyebrow="教师工作区 / 测评历史" :title="data.subject_id" intro="此页展示该授权匿名主体的测评状态与实际记录摘要。">
        <template #actions><AppButton variant="quiet" size="sm" @click="goBack"><ArrowLeft :size="15" aria-hidden="true" />返回历史列表</AppButton></template>
      </AppPageHeader>
      <AppStatusCallout tone="info" title="披露范围" body="仅展示测评 ID、状态、已记录题数和时间。不包含原始作答、对话、心理测量参数或个体风险解释。" />
      <section class="summary-grid" aria-label="测评数量摘要">
        <AppCard><span class="metric-label">测评记录</span><strong>{{ data.assessment_count }}</strong></AppCard>
        <AppCard><span class="metric-label">已完成</span><strong>{{ data.completed_count }}</strong></AppCard>
        <AppCard><span class="metric-label">进行中</span><strong>{{ data.in_progress_count }}</strong></AppCard>
      </section>
      <section class="history-list" aria-labelledby="history-title">
        <div class="section-heading"><div><span class="section-label">历史记录</span><h2 id="history-title" class="section-title">测评进度</h2></div></div>
        <AppCard v-if="data.assessments.length" class="history-table" flush>
          <div class="history-table__header"><span>测评 ID</span><span>状态</span><span>已记录题数</span><span>开始时间</span><span>完成时间</span></div>
          <div v-for="assessment in data.assessments" :key="assessment.assessment_id" class="history-row">
            <strong>{{ assessment.assessment_id }}</strong>
            <AppBadge :tone="statusTone(assessment.status)" dot>{{ statusLabel(assessment.status) }}</AppBadge>
            <span>{{ assessment.items_answered === null ? '未提供' : assessment.items_answered }}</span>
            <time v-if="assessment.started_at" :datetime="assessment.started_at">{{ formatTime(assessment.started_at) }}</time><span v-else>未记录</span>
            <time v-if="assessment.completed_at" :datetime="assessment.completed_at">{{ formatTime(assessment.completed_at) }}</time><span v-else>未记录</span>
          </div>
        </AppCard>
        <AppCard v-else class="empty-state"><strong>没有可显示的合成测评历史</strong><p>该主体的授权范围内当前没有符合条件的合成记录。</p></AppCard>
      </section>
    </template>
  </div>
</template>

<style scoped>
.teacher-detail { animation: page-in 240ms ease both; }
.loading-state { padding: 22px 0; color: var(--color-text-secondary); font-size: 13px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.summary-grid :deep(.app-card) { display: grid; gap: 10px; padding: 17px; }
.metric-label { color: var(--color-text-secondary); font-size: 12px; }
.summary-grid strong { color: var(--color-text-primary); font-family: var(--font-mono); font-size: 25px; }
.history-list { margin-top: 28px; }
.section-heading { margin-bottom: 13px; }
.section-title { margin-top: 5px; }
.history-table { overflow: hidden; }
.history-table__header, .history-row { display: grid; grid-template-columns: minmax(145px, 1.15fr) minmax(120px, .8fr) minmax(100px, .6fr) minmax(170px, 1fr) minmax(170px, 1fr); align-items: center; gap: 13px; padding: 12px 15px; }
.history-table__header { background: var(--color-surface-muted); color: var(--color-text-muted); font-size: 11px; font-weight: 700; }
.history-row { border-top: 1px solid var(--color-border); color: var(--color-text-secondary); font-size: 11px; }
.history-row strong { overflow: hidden; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 10px; text-overflow: ellipsis; }
.history-row time { font-size: 10px; }
.empty-state { display: grid; justify-items: center; padding: 36px 18px; text-align: center; }
.empty-state strong { color: var(--color-text-primary); font-size: 14px; }
.empty-state p { margin: 7px 0 0; color: var(--color-text-muted); font-size: 12px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 860px) { .history-table { overflow-x: auto; }.history-table__header, .history-row { min-width: 760px; } }
@media (max-width: 560px) { .summary-grid { grid-template-columns: 1fr; } }
</style>
