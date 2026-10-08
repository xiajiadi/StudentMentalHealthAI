<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, ClipboardCheck, RotateCcw, UsersRound } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { isTeacherForbidden, teacherApi, type TeacherOverview } from './teacher-api'

const state = ref<'loading' | 'ready' | 'error' | 'forbidden'>('loading')
const data = ref<TeacherOverview | null>(null)
const errorMessage = ref('')
const recentStudents = computed(() => data.value?.students.slice(0, 8) ?? [])

const metrics = computed(() => {
  if (!data.value) return []
  return [
    { label: '授权范围内的合成主体', value: data.value.subjects_count, helper: '仅统计存在合成测评记录的主体', icon: UsersRound, tone: 'blue' },
    { label: '测评记录', value: data.value.assessments_count, helper: `${data.value.completed_count} 条已完成`, icon: ClipboardCheck, tone: 'teal' },
    { label: '进行中的测评', value: data.value.in_progress_count, helper: '按当前记录状态统计', icon: ClipboardCheck, tone: 'amber' },
  ]
})

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    data.value = (await teacherApi.getTeacherOverview()).data
    state.value = 'ready'
  } catch (error) {
    state.value = isTeacherForbidden(error) ? 'forbidden' : 'error'
    errorMessage.value = state.value === 'forbidden' ? '当前账号没有查看此授权范围的权限。' : '教师工作区暂时无法加载，请稍后重试。'
  }
}

const formatTime = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '暂无记录'
const reportStatusLabel = (value: string) => ({
  requested: '已请求', safety_blocked: '流程已阻断', generating: '处理中', generated: '已生成',
  needs_review: '待人工复核', approved: '已审核', rejected: '未通过', abstained: '已停止', unknown: '状态未知',
}[value] ?? '状态未知')
const reviewStatusLabel = (value: string) => ({
  pending: '待处理', in_review: '复核中', approved: '已通过', rejected: '未通过', not_required: '无需复核', unknown: '状态未知',
}[value] ?? '状态未知')

onMounted(load)
</script>

<template>
  <div class="content-wrap teacher-overview">
    <div v-if="state === 'loading'" class="loading-state" aria-busy="true">正在读取授权范围内的合成记录…</div>

    <AppStatusCallout v-else-if="state === 'forbidden'" tone="critical" title="没有查看权限" :body="errorMessage" />
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="教师工作区暂时无法加载" :body="errorMessage">
      <button class="inline-retry" type="button" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</button>
    </AppStatusCallout>

    <template v-else-if="data">
      <AppPageHeader eyebrow="教师工作区" title="工作概览" intro="这里汇总当前账号授权范围内真实保存的合成测评记录。" />

      <AppStatusCallout tone="info" title="数据范围" body="只显示匿名主体、测评状态、记录数量和时间摘要；不展示作答内容、支持对话、心理测量参数或个体风险判断。" />

      <section class="summary-grid" aria-label="授权范围内的记录摘要">
        <AppCard v-for="item in metrics" :key="item.label" class="summary-card">
          <div class="summary-card__head"><span>{{ item.label }}</span><component :is="item.icon" :class="`summary-card__icon summary-card__icon--${item.tone}`" :size="18" aria-hidden="true" /></div>
          <strong>{{ item.value }}</strong>
          <p>{{ item.helper }}</p>
        </AppCard>
      </section>

      <section class="report-summary" aria-labelledby="report-summary-title">
        <AppCard class="report-summary__card">
          <div class="section-heading"><div><span class="section-label">记录状态</span><h2 id="report-summary-title" class="section-title">报告与复核状态计数</h2></div><AppBadge tone="blue">{{ data.reports_count }} 条关联记录</AppBadge></div>
          <div v-if="data.reports_count" class="status-counts">
            <div><h3>报告状态</h3><ul><li v-for="(count, status) in data.report_status_counts" :key="`report-${status}`"><span>{{ reportStatusLabel(String(status)) }}</span><strong>{{ count }}</strong></li></ul></div>
            <div><h3>复核状态</h3><ul><li v-for="(count, status) in data.review_status_counts" :key="`review-${status}`"><span>{{ reviewStatusLabel(String(status)) }}</span><strong>{{ count }}</strong></li></ul></div>
          </div>
          <p v-else class="empty-note">当前授权合成测评没有关联的报告记录。</p>
        </AppCard>
      </section>

      <section class="history-section" aria-labelledby="history-title">
        <div class="section-heading"><div><span class="section-label">测评历史</span><h2 id="history-title" class="section-title">最近有记录的匿名主体</h2></div><RouterLink class="text-link" to="/teacher/students">查看全部 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></div>
        <AppCard v-if="recentStudents.length" class="student-table" flush>
          <div class="student-table__header"><span>匿名主体</span><span>测评记录</span><span>已完成</span><span>进行中</span><span>最近记录</span></div>
          <RouterLink v-for="student in recentStudents" :key="student.subject_id" :to="`/teacher/students/${encodeURIComponent(student.subject_id)}`" class="student-row">
            <strong>{{ student.subject_id }}</strong>
            <span>{{ student.assessment_count }}</span>
            <span>{{ student.completed_count }}</span>
            <span>{{ student.in_progress_count }}</span>
            <time v-if="student.last_activity_at" :datetime="student.last_activity_at">{{ formatTime(student.last_activity_at) }}</time>
            <span v-else>暂无记录</span>
          </RouterLink>
        </AppCard>
        <AppCard v-else class="empty-state">
          <strong>当前授权范围内没有合成测评记录</strong>
          <p>有新记录后会显示真实保存的状态和时间摘要。</p>
        </AppCard>
      </section>
    </template>
  </div>
</template>

<style scoped>
.teacher-overview { animation: page-in 240ms ease both; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.summary-card { min-height: 132px; padding: 18px; }
.summary-card__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--color-text-secondary); font-size: 12px; font-weight: 700; }
.summary-card__icon { padding: 7px; width: 32px; height: 32px; border-radius: 8px; }
.summary-card__icon--blue { color: var(--color-primary); background: var(--color-info-wash); }
.summary-card__icon--teal { color: var(--color-support); background: var(--color-support-wash); }
.summary-card__icon--amber { color: var(--color-attention); background: var(--color-attention-wash); }
.summary-card > strong { display: block; margin-top: 17px; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 27px; }
.summary-card > p, .empty-note { margin: 4px 0 0; color: var(--color-text-muted); font-size: 11px; }
.report-summary, .history-section { margin-top: 26px; }
.report-summary__card { padding: 19px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.section-title { margin-top: 5px; }
.status-counts { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.status-counts h3 { margin: 0 0 8px; color: var(--color-text-secondary); font-size: 12px; }
.status-counts ul { display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.status-counts li { display: flex; justify-content: space-between; gap: 12px; padding: 8px 10px; border-radius: 6px; background: var(--color-surface-muted); color: var(--color-text-secondary); font-size: 12px; }
.status-counts li strong { color: var(--color-text-primary); font-family: var(--font-mono); }
.student-table { overflow: hidden; }
.student-table__header, .student-row { display: grid; grid-template-columns: minmax(140px, 1.2fr) repeat(3, minmax(66px, .6fr)) minmax(190px, 1.2fr); align-items: center; gap: 14px; padding: 12px 16px; }
.student-table__header { background: var(--color-surface-muted); color: var(--color-text-muted); font-size: 11px; font-weight: 700; }
.student-row { border-top: 1px solid var(--color-border); color: var(--color-text-secondary); font-size: 12px; }
.student-row:hover { background: var(--color-surface-soft); }
.student-row strong { overflow: hidden; color: var(--color-text-primary); font-family: var(--font-mono); font-size: 11px; text-overflow: ellipsis; }
.student-row time { color: var(--color-text-secondary); font-size: 11px; }
.text-link { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-size: 12px; font-weight: 700; }
.empty-state { display: grid; justify-items: center; padding: 35px 20px; text-align: center; }
.empty-state strong { color: var(--color-text-primary); font-size: 14px; }
.empty-state p { margin: 7px 0 0; color: var(--color-text-muted); font-size: 12px; }
.loading-state { padding: 22px 0; color: var(--color-text-secondary); font-size: 13px; }
.inline-retry { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; font-size: 12px; font-weight: 700; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 740px) { .student-table { overflow-x: auto; }.student-table__header, .student-row { min-width: 680px; } }
@media (max-width: 560px) { .summary-grid, .status-counts { grid-template-columns: 1fr; }.summary-card { min-height: 112px; }.summary-card > strong { margin-top: 11px; } }
</style>
