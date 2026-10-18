<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowUpDown, CalendarClock, ClipboardList, UsersRound } from '@lucide/vue'
import type { TeacherTaskPhase } from '@/utils/teacher-task-progress'
import {
  formatTeacherDate,
  shortTeacherRef,
  taskActionablePendingCount,
  taskCompletionRate,
  taskProgressCount,
  teacherClassDisplayLabel,
  teacherTaskDisplayLabel,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
  teacherTaskStatusLabel,
} from '@/utils/teacher-task-progress'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import TeacherClassSelect from '@/components/teacher/TeacherClassSelect.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'

type PhaseFilter = 'all' | TeacherTaskPhase
type SortOption = 'due_asc' | 'due_desc' | 'completion_asc' | 'completion_desc' | 'class_asc'

const phaseFilter = ref<PhaseFilter>('all')
const classFilter = ref('all')
const opensFrom = ref('')
const opensTo = ref('')
const sortBy = ref<SortOption>('due_asc')
const { state, rows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })

const phaseOptions: { value: PhaseFilter; label: string }[] = [
  { value: 'all', label: '全部阶段' },
  { value: 'upcoming', label: '待开始' },
  { value: 'in_progress', label: '进行中' },
  { value: 'ended', label: '已结束' },
  { value: 'cancelled', label: '已取消' },
  { value: 'unpublished', label: '未发布' },
]

const classOptions = computed(() => [...new Set(rows.value.map((row) => row.class_ref))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const classSelectOptions = computed(() => [
  { value: 'all', label: '全部班级' },
  ...classOptions.value.map((classRef) => ({ value: classRef, label: teacherClassDisplayLabel(classRef, rows.value) })),
])

const dateKey = (value: string | null) => {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  const year = parsed.getFullYear()
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  const day = String(parsed.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const filteredRows = computed(() => rows.value.filter((row) => {
  const opened = dateKey(row.opens_at)
  return (phaseFilter.value === 'all' || teacherTaskPhase(row) === phaseFilter.value)
    && (classFilter.value === 'all' || row.class_ref === classFilter.value)
    && (!opensFrom.value || (opened !== '' && opened >= opensFrom.value))
    && (!opensTo.value || (opened !== '' && opened <= opensTo.value))
}))

const sortedRows = computed(() => [...filteredRows.value].sort((a, b) => {
  const aDue = Date.parse(a.due_at ?? '')
  const bDue = Date.parse(b.due_at ?? '')
  switch (sortBy.value) {
    case 'due_desc': return (Number.isFinite(bDue) ? bDue : -Infinity) - (Number.isFinite(aDue) ? aDue : -Infinity)
    case 'completion_asc': return taskCompletionRate(a) - taskCompletionRate(b) || a.class_ref.localeCompare(b.class_ref, 'zh-CN')
    case 'completion_desc': return taskCompletionRate(b) - taskCompletionRate(a) || a.class_ref.localeCompare(b.class_ref, 'zh-CN')
    case 'class_asc': return a.class_ref.localeCompare(b.class_ref, 'zh-CN') || (Number.isFinite(aDue) ? aDue : Infinity) - (Number.isFinite(bDue) ? bDue : Infinity)
    default: return (Number.isFinite(aDue) ? aDue : Infinity) - (Number.isFinite(bDue) ? bDue : Infinity)
  }
}))

const summary = computed(() => sortedRows.value.reduce((result, row) => ({
  tasks: result.tasks + 1,
  active: result.active + taskProgressCount(row, 'active_enrollment_count'),
  completed: result.completed + taskProgressCount(row, 'completed_count'),
  pending: result.pending + taskActionablePendingCount(row),
}), { tasks: 0, active: 0, completed: 0, pending: 0 }))

const taskHref = (classRef: string, taskRef: string) => `/teacher/tasks/${encodeURIComponent(classRef)}/${encodeURIComponent(taskRef)}`
</script>

<template>
  <main class="teacher-tasks content-wrap">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="测评任务" />

    <header class="tasks-page-heading">
      <span class="tasks-page-heading__icon"><ClipboardList :size="20" aria-hidden="true" /></span>
      <div><h1>测评任务</h1><p>查看授权班级的任务安排与整体完成进度。</p></div>
    </header>

    <p class="tasks-scope-note">仅显示授权班级的任务汇总，不包含个人心理记录。</p>

    <AppCard class="tasks-panel">
      <header class="tasks-panel__heading">
        <div class="tasks-panel__title"><h2>全部测评任务</h2><p>当前筛选命中 {{ summary.tasks }} 项 · {{ summary.active }} 个有效报名人次 · {{ summary.completed }} 人次已完成</p></div>
        <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh">刷新</AppButton>
      </header>

      <div class="tasks-filters">
        <label>
          <span>所属班级</span>
          <TeacherClassSelect v-model="classFilter" :options="classSelectOptions" aria-label="按班级筛选任务" :disabled="state !== 'ready' || !rows.length" />
        </label>
        <label>
          <span>任务阶段</span>
          <select v-model="phaseFilter" :disabled="state !== 'ready' || !rows.length">
            <option v-for="option in phaseOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="tasks-filters__date">
          <span><CalendarClock :size="13" aria-hidden="true" /> 开始日期从</span>
          <input v-model="opensFrom" type="date" :disabled="state !== 'ready' || !rows.length" aria-label="开始日期起始时间">
        </label>
        <label class="tasks-filters__date">
          <span><CalendarClock :size="13" aria-hidden="true" /> 到</span>
          <input v-model="opensTo" type="date" :disabled="state !== 'ready' || !rows.length" aria-label="开始日期结束时间">
        </label>
        <label class="tasks-filters__sort">
          <span><ArrowUpDown :size="13" aria-hidden="true" /> 排序</span>
          <select v-model="sortBy" :disabled="state !== 'ready' || !rows.length">
            <option value="due_asc">按截止时间升序</option>
            <option value="due_desc">按截止时间降序</option>
            <option value="completion_asc">按完成率从低到高</option>
            <option value="completion_desc">按完成率从高到低</option>
            <option value="class_asc">按班级</option>
          </select>
        </label>
        <button v-if="classFilter !== 'all' || phaseFilter !== 'all' || opensFrom || opensTo" class="tasks-filters__clear" type="button" @click="classFilter = 'all'; phaseFilter = 'all'; opensFrom = ''; opensTo = ''">清除筛选</button>
      </div>

      <div v-if="state === 'loading'" class="tasks-state" aria-busy="true" aria-live="polite">正在读取班级任务汇总…</div>
      <div v-else-if="state === 'error'" class="tasks-state tasks-state--error" role="alert">
        <p>{{ errorMessage }}</p><AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton>
      </div>
      <div v-else-if="rows.length === 0" class="tasks-state" role="status">当前没有分配给你的班级任务。</div>
      <div v-else-if="sortedRows.length === 0" class="tasks-state" role="status">没有符合当前筛选条件的任务，请调整班级、阶段或开始日期。</div>
      <div v-else class="tasks-table-wrap">
        <table class="tasks-table">
          <thead><tr><th scope="col">测评任务</th><th scope="col">所属班级</th><th scope="col">开始时间</th><th scope="col">截止时间</th><th scope="col">有效报名</th><th scope="col">已完成</th><th scope="col">待完成人次</th><th scope="col">完成率</th><th scope="col">阶段</th><th scope="col"><span class="sr-only">查看</span></th></tr></thead>
          <tbody>
            <tr v-for="row in sortedRows" :key="`${row.class_ref}:${row.task_ref}`">
              <td><span class="tasks-table__primary">{{ teacherTaskDisplayLabel(row) }}</span><span class="tasks-table__secondary">{{ teacherTaskStatusLabel(row.task_status) }} · {{ shortTeacherRef(row.task_ref) }}</span></td>
              <td>{{ teacherClassDisplayLabel(row.class_ref, rows) }}</td>
              <td>{{ formatTeacherDate(row.opens_at) }}</td>
              <td>{{ formatTeacherDate(row.due_at, '未设截止日期') }}</td>
              <td><span class="tasks-table__number"><UsersRound :size="13" aria-hidden="true" />{{ taskProgressCount(row, 'active_enrollment_count') }}</span></td>
              <td>{{ taskProgressCount(row, 'completed_count') }}</td>
              <td>{{ taskActionablePendingCount(row) }}</td>
              <td><span class="tasks-table__rate">{{ taskProgressCount(row, 'active_enrollment_count') > 0 ? `${taskCompletionRate(row)}%` : '—' }}</span></td>
              <td><span class="task-phase" :class="`task-phase--${teacherTaskPhase(row)}`">{{ teacherTaskPhaseLabel(teacherTaskPhase(row)) }}</span></td>
              <td><RouterLink class="tasks-table__link" :to="taskHref(row.class_ref, row.task_ref)">查看详情 <span aria-hidden="true">→</span></RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer v-if="state === 'ready' && rows.length" class="tasks-panel__footer">
        <span>当前显示 {{ summary.tasks }} 项任务 · 待完成人次 {{ summary.pending }}</span>
        <span>统计仅包含当前有效报名中可继续的任务进度。</span>
      </footer>
    </AppCard>

    <p class="tasks-footnote">完成率按当前有效报名计算；待完成人次仅统计未开始、已创建及进行中的任务，不用于评价个人或推断心理状态。<span v-if="isDemo"> 当前数据由前端合成，仅用于界面预览。</span></p>
  </main>
</template>

<style scoped>
.teacher-tasks { display: grid; gap: 16px; padding-top: 0; animation: page-in 220ms ease both; }
.tasks-scope-note { margin: -8px 0 0 2px; color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.tasks-page-heading { display: flex; align-items: center; gap: 12px; min-height: 48px; }
.tasks-page-heading__icon { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 12px; color: var(--color-primary-active); background: #e8f8fc; }
.tasks-page-heading h1 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 20px; line-height: 1.25; }
.tasks-page-heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; }
.tasks-panel { padding: 20px 22px; }
.tasks-panel__heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.tasks-panel__title h2 { margin: 0 0 5px; color: var(--color-text-primary); font-size: 16px; }
.tasks-panel__title p { margin: 0; color: var(--color-text-muted); font-size: 11px; }
.tasks-filters { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; margin: 18px 0 14px; padding: 14px; border: 1px solid #e8eef2; border-radius: var(--radius-card); background: var(--color-surface-soft); }
.tasks-filters label { display: grid; gap: 5px; min-width: 128px; color: var(--color-text-muted); font-size: 10px; font-weight: 600; }
.tasks-filters label:first-child { min-width: 172px; }
.tasks-filters label > span { display: flex; align-items: center; gap: 4px; }
.tasks-filters select,.tasks-filters input { width: 100%; min-height: 34px; padding: 0 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-primary); background: var(--color-surface); font: inherit; font-size: 11px; }
.tasks-filters input { min-width: 132px; }
.tasks-filters select:focus-visible,.tasks-filters input:focus-visible,.tasks-filters__clear:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tasks-filters select:disabled,.tasks-filters input:disabled { cursor: not-allowed; opacity: .58; }
.tasks-filters__date { min-width: 144px !important; }
.tasks-filters__sort { margin-left: auto; }
.tasks-filters__clear { min-height: 34px; padding: 0 8px; border: 0; color: var(--color-primary-active); background: transparent; font: inherit; font-size: 11px; cursor: pointer; }
.tasks-state { display: flex; min-height: 126px; align-items: center; justify-content: center; gap: 14px; margin-top: 12px; padding: 20px; border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 13px; text-align: center; }
.tasks-state--error { justify-content: space-between; color: #805c1d; background: var(--color-attention-wash); text-align: left; }
.tasks-state p { margin: 0; }
.tasks-table-wrap { overflow-x: auto; border: 1px solid #e8edf0; border-radius: var(--radius-card); background: var(--color-surface); }
.tasks-table { width: 100%; min-width: 980px; border-collapse: collapse; text-align: left; }
.tasks-table th { padding: 11px 12px; border-bottom: 1px solid #e8edf0; color: var(--color-text-muted); background: #fbfcfd; font-size: 10px; font-weight: 650; white-space: nowrap; }
.tasks-table td { padding: 12px; border-bottom: 1px solid #edf1f3; color: var(--color-text-secondary); font-size: 11px; white-space: nowrap; }
.tasks-table tbody tr:last-child td { border-bottom: 0; }
.tasks-table tbody tr:hover { background: #f8fbfc; }
.tasks-table__primary,.tasks-table__secondary { display: block; }
.tasks-table__primary { color: var(--color-text-primary); font-weight: 650; }
.tasks-table__secondary { margin-top: 3px; color: var(--color-text-muted); font-size: 9px; }
.tasks-table__number { display: inline-flex; align-items: center; gap: 5px; }
.tasks-table__number svg { color: var(--color-primary-active); }
.tasks-table__rate { color: var(--color-primary-active); font-weight: 700; }
.task-phase { display: inline-flex; padding: 4px 8px; border-radius: 999px; color: #236b62; background: #e8f4ef; font-size: 10px; font-weight: 650; }
.task-phase--upcoming,.task-phase--unpublished { color: #236b88; background: #eaf7fb; }
.task-phase--ended,.task-phase--cancelled { color: #676b73; background: #f0f1f3; }
.tasks-table__link { color: var(--color-primary-active); font-weight: 650; text-decoration: none; }
.tasks-table__link:hover { text-decoration: underline; }
.tasks-table__link:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 3px; border-radius: 2px; }
.tasks-panel__footer { display: flex; justify-content: space-between; gap: 12px; margin-top: 12px; color: var(--color-text-muted); font-size: 10px; }
.tasks-footnote { margin: 0 2px; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 760px) { .tasks-panel { padding: 17px; }.tasks-filters__sort { margin-left: 0; }.tasks-panel__footer { flex-direction: column; gap: 4px; } }
@media (max-width: 560px) { .tasks-panel__heading { align-items: flex-start; }.tasks-filters label { flex: 1 1 132px; }.tasks-filters__date { flex: 1 1 145px !important; }.tasks-panel__heading :deep(button) { flex: 0 0 auto; } }
</style>
