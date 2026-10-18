<script setup lang="ts">
import { computed } from 'vue'
import { Activity, CalendarClock, CheckCircle2, Clock3, UsersRound, XCircle } from '@lucide/vue'
import type { TeacherTaskProgress } from '@/api/client'
import {
  formatTeacherDate,
  shortTeacherRef,
  taskCompletionRate,
  taskProgressCount,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
  teacherTaskStatusLabel,
} from '@/utils/teacher-task-progress'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt } from '@/data/student-feature-cards'
import { useRoute } from 'vue-router'

const route = useRoute()
const { state, rows, errorMessage, refresh } = useTeacherTaskProgress()
const classRef = computed(() => String(route.params.classRef ?? ''))
const taskRef = computed(() => String(route.params.taskRef ?? ''))
const task = computed(() => rows.value.find((row) => row.class_ref === classRef.value && row.task_ref === taskRef.value))
const rate = computed(() => task.value ? taskCompletionRate(task.value) : 0)

const counts = computed(() => {
  const row = task.value
  if (!row) return []
  return [
    { key: 'not-started', label: '未开始', count: taskProgressCount(row, 'not_started_count'), icon: Clock3, tone: 'blue' },
    { key: 'created', label: '准备中', count: taskProgressCount(row, 'created_count'), icon: CalendarClock, tone: 'blue' },
    { key: 'in-progress', label: '进行中', count: taskProgressCount(row, 'in_progress_count'), icon: Activity, tone: 'teal' },
    { key: 'completed', label: '已完成', count: taskProgressCount(row, 'completed_count'), icon: CheckCircle2, tone: 'teal' },
    { key: 'abandoned', label: '已结束', count: taskProgressCount(row, 'abandoned_count'), icon: Clock3, tone: 'muted' },
    { key: 'invalid', label: '不可继续', count: taskProgressCount(row, 'invalid_count'), icon: XCircle, tone: 'muted' },
    { key: 'revoked', label: '已撤销报名', count: taskProgressCount(row, 'revoked_enrollment_count'), icon: UsersRound, tone: 'muted' },
  ]
})

const statusSummary = (row: TeacherTaskProgress) => `共 ${row.active_enrollment_count} 个当前有效报名，其中 ${row.completed_count} 个已完成。`
</script>

<template>
  <main class="teacher-task-detail content-wrap">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" :parent="{ label: '测评任务', to: '/teacher/tasks' }" current="任务汇总" />
    <StudentPageHero
      eyebrow="TASK SUMMARY · SCOPE A"
      :title="task ? `班级 ${shortTeacherRef(task.class_ref)} · 任务 ${shortTeacherRef(task.task_ref)}` : '任务汇总'"
      subtitle="仅呈现该班级任务的整体状态计数与时间安排。"
      :image="studentPageArt.assessments"
      image-position="center 48%"
      light-text
    />

    <AppStatusCallout tone="info" title="范围说明" body="以下均为任务层级汇总。此页不包含学生名单、个人测评历史、作答、报告或支持对话。" />

    <AppCard class="detail-panel">
      <header class="detail-panel__heading"><div><h2>任务进度汇总</h2><p>状态仅用于班级任务安排，不代表个人测评结果。</p></div><RouterLink class="back-link" to="/teacher/tasks">返回任务列表</RouterLink></header>
      <div v-if="state === 'loading'" class="detail-state" aria-busy="true" aria-live="polite">正在读取任务汇总…</div>
      <div v-else-if="state === 'error'" class="detail-state detail-state--error" role="alert"><p>{{ errorMessage }}</p><AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton></div>
      <div v-else-if="!task" class="detail-state" role="status">没有找到此班级任务的汇总记录。任务可能已更新，或当前账号无权查看。</div>
      <template v-else>
        <section class="task-meta" aria-label="任务基本信息">
          <div class="task-meta__item"><span>任务阶段</span><strong>{{ teacherTaskPhaseLabel(teacherTaskPhase(task)) }}</strong></div>
          <div class="task-meta__item"><span>任务状态</span><strong>{{ teacherTaskStatusLabel(task.task_status) }}</strong></div>
          <div class="task-meta__item task-meta__dates"><span><CalendarClock :size="14" aria-hidden="true" />开放时间 / 截止时间</span><strong>{{ formatTeacherDate(task.opens_at) }}<i>至</i>{{ formatTeacherDate(task.due_at, '未设置截止日期') }}</strong></div>
        </section>

        <section class="completion-summary" aria-label="整体完成情况">
          <div><span>当前有效报名</span><strong>{{ task.active_enrollment_count }}</strong></div>
          <div class="completion-summary__rate"><span>汇总完成率</span><strong>{{ rate }}<small>%</small></strong><span class="completion-track" role="progressbar" :aria-valuenow="rate" aria-valuemin="0" aria-valuemax="100" aria-label="任务汇总完成率"><i :style="{ width: `${rate}%` }"></i></span></div>
          <p>{{ statusSummary(task) }}</p>
        </section>

        <section class="status-section" aria-labelledby="status-heading">
          <div class="status-section__heading"><h3 id="status-heading">状态分布</h3><span>按当前有效报名统计；撤销报名另列</span></div>
          <dl class="status-grid">
            <div v-for="item in counts" :key="item.key" class="status-tile" :class="`status-tile--${item.tone}`">
              <dt><component :is="item.icon" :size="15" aria-hidden="true" />{{ item.label }}</dt>
              <dd>{{ item.count }}</dd>
            </div>
          </dl>
        </section>
      </template>
    </AppCard>
  </main>
</template>

<style scoped>
.teacher-task-detail { display: grid; gap: 16px; padding-top: 0; animation: page-in 220ms ease both; }
.teacher-task-detail :deep(.student-page-hero) { margin-bottom: 0; }
.detail-panel { padding: 22px; }
.detail-panel__heading,.status-section__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.detail-panel h2 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 16px; }
.detail-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; }
.back-link { flex: 0 0 auto; color: var(--color-primary-active); font-size: 12px; font-weight: 650; }
.back-link:hover { text-decoration: underline; }
.detail-state { display: flex; min-height: 126px; align-items: center; justify-content: center; margin-top: 18px; padding: 20px; border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 13px; text-align: center; }
.detail-state--error { justify-content: space-between; gap: 16px; color: #805c1d; background: var(--color-attention-wash); text-align: left; }
.detail-state--error p { margin: 0; }
.task-meta { display: grid; grid-template-columns: minmax(130px, .65fr) minmax(130px, .65fr) minmax(260px, 1.7fr); gap: 12px; margin-top: 20px; }
.task-meta__item { display: grid; gap: 9px; min-width: 0; padding: 14px; border-radius: 10px; background: var(--color-surface-soft); }
.task-meta__item > span { color: var(--color-text-muted); font-size: 11px; }
.task-meta__item strong { color: var(--color-text-primary); font-size: 13px; line-height: 1.5; }
.task-meta__dates > span,.task-meta__dates strong { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.task-meta__dates > span svg { color: var(--color-primary-active); }
.task-meta__dates strong { font-size: 12px; }
.task-meta__dates i { color: var(--color-text-muted); font-size: 10px; font-style: normal; font-weight: 400; }
.completion-summary { display: grid; grid-template-columns: minmax(120px, .5fr) minmax(180px, .75fr) minmax(0, 1.6fr); align-items: center; gap: 16px; margin-top: 14px; padding: 16px; border: 1px solid #dceff3; border-radius: var(--radius-card); background: #f4fbfc; }
.completion-summary > div { display: grid; gap: 5px; }
.completion-summary > div > span:first-child { color: var(--color-text-muted); font-size: 11px; }
.completion-summary strong { color: var(--color-text-primary); font-size: 23px; }
.completion-summary__rate strong small { margin-left: 2px; color: var(--color-text-muted); font-size: 12px; }
.completion-summary p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.completion-track { display: block; height: 6px; overflow: hidden; border-radius: 999px; background: #dfecee; }
.completion-track i { display: block; height: 100%; border-radius: inherit; background: var(--color-primary); }
.status-section { margin-top: 23px; }
.status-section__heading { align-items: baseline; margin-bottom: 12px; }
.status-section h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.status-section__heading span { color: var(--color-text-muted); font-size: 10px; }
.status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0; }
.status-tile { display: grid; gap: 11px; min-width: 0; padding: 14px; border-radius: 10px; background: #f4f8fb; }
.status-tile dt { display: flex; align-items: center; gap: 6px; color: var(--color-text-secondary); font-size: 11px; }
.status-tile dd { margin: 0; color: var(--color-text-primary); font-size: 22px; font-weight: 700; }
.status-tile--blue dt svg { color: var(--color-primary-active); }
.status-tile--teal { background: #f1f8f5; }
.status-tile--teal dt svg { color: var(--color-support); }
.status-tile--muted { background: #f6f7f8; }
.status-tile--muted dt svg { color: var(--color-text-muted); }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 850px) { .task-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }.task-meta__dates { grid-column: 1 / -1; }.completion-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }.completion-summary p { grid-column: 1 / -1; }.status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 620px) { .detail-panel { padding: 17px; }.detail-panel__heading { flex-direction: column; }.task-meta,.completion-summary { grid-template-columns: minmax(0, 1fr); }.task-meta__dates,.completion-summary p { grid-column: auto; }.status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.status-section__heading { flex-direction: column; align-items: flex-start; gap: 4px; } }
</style>
