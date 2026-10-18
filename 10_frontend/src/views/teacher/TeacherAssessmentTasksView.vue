<script setup lang="ts">
import { computed, ref } from 'vue'
import { Activity, CalendarClock, ClipboardList, UsersRound } from '@lucide/vue'
import type { TeacherTaskPhase } from '@/utils/teacher-task-progress'
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

type PhaseFilter = 'all' | TeacherTaskPhase

const phaseFilter = ref<PhaseFilter>('all')
const { state, rows, errorMessage, refresh } = useTeacherTaskProgress()
const phaseOptions: { value: PhaseFilter; label: string }[] = [
  { value: 'all', label: '全部阶段' },
  { value: 'upcoming', label: '待开始' },
  { value: 'in_progress', label: '进行中' },
  { value: 'ended', label: '已结束' },
  { value: 'cancelled', label: '已取消' },
  { value: 'unpublished', label: '未发布' },
]

const sortedRows = computed(() => [...rows.value].sort((a, b) => {
  const phaseOrder = phaseOptions.findIndex((option) => option.value === teacherTaskPhase(a)) - phaseOptions.findIndex((option) => option.value === teacherTaskPhase(b))
  if (phaseOrder !== 0 && phaseFilter.value === 'all') return phaseOrder
  return (Date.parse(b.opens_at) || 0) - (Date.parse(a.opens_at) || 0)
}))
const filteredRows = computed(() => sortedRows.value.filter((row) => phaseFilter.value === 'all' || teacherTaskPhase(row) === phaseFilter.value))
const taskHref = (classRef: string, taskRef: string) => `/teacher/tasks/${encodeURIComponent(classRef)}/${encodeURIComponent(taskRef)}`
</script>

<template>
  <main class="teacher-tasks content-wrap">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="测评任务" />
    <StudentPageHero
      eyebrow="ASSESSMENT TASKS · SCOPE A"
      title="班级测评任务"
      subtitle="查看分配给你的班级任务、开放时间与整体完成进度。"
      :image="studentPageArt.assessments"
      image-position="center 48%"
      light-text
    />

    <AppStatusCallout tone="info" title="仅显示班级任务汇总" body="页面不包含学生名单、个人测评历史、作答、报告或支持对话。" />

    <AppCard class="tasks-panel">
      <header class="tasks-panel__heading">
        <div class="tasks-panel__title"><span class="tasks-panel__icon"><ClipboardList :size="18" aria-hidden="true" /></span><div><h2>任务列表</h2><p>按阶段查看任务；打开详情可查看该任务的汇总计数。</p></div></div>
        <div class="tasks-panel__controls">
          <label class="sr-only" for="task-phase-filter">按任务阶段筛选</label>
          <select id="task-phase-filter" v-model="phaseFilter" class="task-filter">
            <option v-for="option in phaseOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh">刷新</AppButton>
        </div>
      </header>

      <div v-if="state === 'loading'" class="tasks-state" aria-busy="true" aria-live="polite">正在读取班级任务汇总…</div>
      <div v-else-if="state === 'error'" class="tasks-state tasks-state--error" role="alert">
        <p>{{ errorMessage }}</p><AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton>
      </div>
      <div v-else-if="rows.length === 0" class="tasks-state" role="status">当前没有分配给你的班级任务。</div>
      <div v-else-if="filteredRows.length === 0" class="tasks-state" role="status">此阶段没有任务。</div>
      <div v-else class="task-list">
        <article v-for="row in filteredRows" :key="`${row.class_ref}:${row.task_ref}`" class="task-row">
          <header class="task-row__header">
            <div><span class="task-row__class">班级 · {{ shortTeacherRef(row.class_ref) }}</span><h3>任务 {{ shortTeacherRef(row.task_ref) }}</h3></div>
            <span class="task-phase" :class="`task-phase--${teacherTaskPhase(row)}`">{{ teacherTaskPhaseLabel(teacherTaskPhase(row)) }}</span>
          </header>
          <dl class="task-row__metrics">
            <div class="task-row__date"><dt><CalendarClock :size="14" aria-hidden="true" />开始 / 截止</dt><dd>{{ formatTeacherDate(row.opens_at) }}<span>至</span>{{ formatTeacherDate(row.due_at, '未设截止日期') }}</dd></div>
            <div><dt><UsersRound :size="14" aria-hidden="true" />当前有效报名</dt><dd>{{ taskProgressCount(row, 'active_enrollment_count') }}</dd></div>
            <div class="task-row__completion"><dt><Activity :size="14" aria-hidden="true" />完成率</dt><dd>{{ taskCompletionRate(row) }}<small>%</small></dd><span class="task-row__track" role="progressbar" :aria-valuenow="taskCompletionRate(row)" aria-valuemin="0" aria-valuemax="100" :aria-label="`班级 ${shortTeacherRef(row.class_ref)} 任务 ${shortTeacherRef(row.task_ref)} 汇总完成率`"><i :style="{ width: `${taskCompletionRate(row)}%` }"></i></span></div>
          </dl>
          <footer class="task-row__footer"><span>任务状态：{{ teacherTaskStatusLabel(row.task_status) }}</span><RouterLink :to="taskHref(row.class_ref, row.task_ref)">查看任务汇总 <span aria-hidden="true">→</span></RouterLink></footer>
        </article>
      </div>
    </AppCard>

    <p class="tasks-footnote">完成率按当前有效报名计算，只用于安排班级任务，不表示个人测评结果或心理状态。</p>
  </main>
</template>

<style scoped>
.teacher-tasks { display: grid; gap: 16px; padding-top: 0; animation: page-in 220ms ease both; }
.teacher-tasks :deep(.student-page-hero) { margin-bottom: 0; }
.tasks-panel { padding: 22px; }
.tasks-panel__heading,.tasks-panel__title,.tasks-panel__controls { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.tasks-panel__title { justify-content: flex-start; min-width: 0; }
.tasks-panel__icon { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 12px; color: var(--color-primary-active); background: #e8f8fc; }
.tasks-panel h2 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 16px; }
.tasks-panel__title p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; }
.tasks-panel__controls { flex: 0 0 auto; }
.task-filter { min-height: 36px; padding: 0 32px 0 11px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-primary); background: var(--color-surface); font-size: 12px; }
.task-filter:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tasks-state { display: flex; min-height: 126px; align-items: center; justify-content: center; margin-top: 18px; padding: 20px; border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 13px; text-align: center; }
.tasks-state--error { justify-content: space-between; gap: 16px; color: #805c1d; background: var(--color-attention-wash); text-align: left; }
.tasks-state--error p { margin: 0; }
.task-list { display: grid; gap: 12px; margin-top: 18px; }
.task-row { min-width: 0; padding: 18px; border: 1px solid #e8edf0; border-radius: var(--radius-card); background: #fff; }
.task-row__header,.task-row__footer { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.task-row__class { color: var(--color-text-muted); font-size: 11px; font-weight: 600; }
.task-row h3 { margin: 4px 0 0; color: var(--color-text-primary); font-size: 16px; }
.task-phase { flex: 0 0 auto; padding: 5px 9px; border-radius: 999px; color: #236b62; background: #e8f4ef; font-size: 11px; font-weight: 650; }
.task-phase--upcoming,.task-phase--unpublished { color: #236b88; background: #eaf7fb; }
.task-phase--ended,.task-phase--cancelled { color: #676b73; background: #f0f1f3; }
.task-row__metrics { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(130px, .8fr) minmax(150px, .8fr); gap: 12px; margin: 17px 0 0; }
.task-row__metrics > div { display: grid; align-content: start; gap: 8px; min-width: 0; padding: 13px; border-radius: 10px; background: var(--color-surface-soft); }
.task-row__metrics dt { display: flex; align-items: center; gap: 6px; color: var(--color-text-muted); font-size: 10px; font-weight: 600; }
.task-row__metrics dt svg { color: var(--color-primary-active); }
.task-row__metrics dd { margin: 0; color: var(--color-text-primary); font-size: 18px; font-weight: 700; }
.task-row__date dd { display: flex; align-items: baseline; flex-wrap: wrap; gap: 5px; font-size: 12px; font-weight: 600; line-height: 1.5; }
.task-row__date dd span { color: var(--color-text-muted); font-size: 10px; font-weight: 400; }
.task-row__completion dd small { margin-left: 2px; color: var(--color-text-muted); font-size: 11px; }
.task-row__track { display: block; height: 6px; overflow: hidden; border-radius: 999px; background: #e6eef0; }
.task-row__track i { display: block; height: 100%; border-radius: inherit; background: var(--color-primary); }
.task-row__footer { align-items: center; margin-top: 14px; color: var(--color-text-muted); font-size: 11px; }
.task-row__footer a { color: var(--color-primary-active); font-weight: 650; text-decoration: none; }
.task-row__footer a:hover { text-decoration: underline; }
.task-row__footer a:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 3px; border-radius: 2px; }
.tasks-footnote { margin: 0 2px; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 850px) { .task-row__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.task-row__date { grid-column: 1 / -1; } }
@media (max-width: 620px) { .tasks-panel { padding: 17px; }.tasks-panel__heading { align-items: flex-start; flex-direction: column; }.tasks-panel__controls { width: 100%; justify-content: flex-start; }.task-row { padding: 14px; }.task-row__metrics { grid-template-columns: minmax(0, 1fr); }.task-row__date { grid-column: auto; }.task-row__footer { align-items: flex-start; flex-direction: column; } }
</style>
