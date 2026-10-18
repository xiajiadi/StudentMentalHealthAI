<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CalendarDays, Columns3, Search } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import TeacherClassSelect from '@/components/teacher/TeacherClassSelect.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import DayAgenda from '@/components/teacher/assessment-tasks/DayAgenda.vue'
import TaskCalendar from '@/components/teacher/assessment-tasks/TaskCalendar.vue'
import TaskKanbanBoard from '@/components/teacher/assessment-tasks/TaskKanbanBoard.vue'
import TeacherTaskDrawer from '@/components/teacher/assessment-tasks/TeacherTaskDrawer.vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import {
  buildAgendaItems,
  buildPlannerEvents,
  createPlannerTask,
  dateFromKey,
  localDateKey,
  type PlannerFilterPhase,
} from '@/utils/teacher-assessment-planner'
import { teacherTaskPhaseLabel, type TeacherTaskPhase } from '@/utils/teacher-task-progress'

type PlannerViewMode = 'calendar' | 'board'

const { state, rows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })
const searchQuery = ref('')
const classFilter = ref('all')
const phaseFilter = ref<PlannerFilterPhase>('all')
const viewMode = ref<PlannerViewMode>('calendar')
const now = Date.now()
const today = new Date(now)
const todayKey = localDateKey(today)
const monthCursor = ref(new Date(today.getFullYear(), today.getMonth(), 1))
const selectedDate = ref(todayKey)
const selectedTaskKey = ref('')

const plannerTasks = computed(() => rows.value.map((row) => createPlannerTask(row, rows.value, now)))
const classOptions = computed(() => {
  const classRefs = [...new Set(rows.value.map((row) => row.class_ref))]
    .sort((first, second) => first.localeCompare(second, 'zh-CN'))
  return [
    { value: 'all', label: '全部班级' },
    ...classRefs.map((classRef) => ({
      value: classRef,
      label: plannerTasks.value.find((task) => task.row.class_ref === classRef)?.classLabel ?? `班级 ${classRef.slice(-6)}`,
    })),
  ]
})

const phaseOptions = computed(() => {
  const options: Array<{ value: PlannerFilterPhase; label: string }> = [
    { value: 'all', label: '全部状态' },
    { value: 'in_progress', label: teacherTaskPhaseLabel('in_progress') },
    { value: 'upcoming', label: '尚未开始' },
    { value: 'ended', label: teacherTaskPhaseLabel('ended') },
    { value: 'cancelled', label: teacherTaskPhaseLabel('cancelled') },
  ]
  if (plannerTasks.value.some((task) => task.phase === 'unpublished')) {
    options.push({ value: 'unpublished', label: teacherTaskPhaseLabel('unpublished') })
  }
  return options
})

const filteredTasks = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return plannerTasks.value
    .filter((task) => classFilter.value === 'all' || task.row.class_ref === classFilter.value)
    .filter((task) => phaseFilter.value === 'all' || task.phase === phaseFilter.value)
    .filter((task) => !query || `${task.label} ${task.classLabel} ${task.row.task_ref}`.toLocaleLowerCase().includes(query))
    .sort((first, second) => {
      const firstDue = first.dueAt?.getTime() ?? Number.POSITIVE_INFINITY
      const secondDue = second.dueAt?.getTime() ?? Number.POSITIVE_INFINITY
      return firstDue - secondDue || first.label.localeCompare(second.label, 'zh-CN') || first.row.class_ref.localeCompare(second.row.class_ref)
    })
})

const activeCount = computed(() => filteredTasks.value.filter((task) => task.phase === 'in_progress').length)
const dueSoonCount = computed(() => filteredTasks.value.filter((task) => task.isDueSoon).length)
const eventsByDate = computed(() => buildPlannerEvents(filteredTasks.value))
const agendaItems = computed(() => buildAgendaItems(eventsByDate.value.get(selectedDate.value) ?? []))
const selectedDateLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' }).format(dateFromKey(selectedDate.value)))
const selectedTask = computed(() => filteredTasks.value.find((task) => task.key === selectedTaskKey.value) ?? null)
const displayedErrorMessage = computed(() => errorMessage.value.replace(/[。]+$/u, ''))

const boardLanes = computed(() => {
  const laneDefinitions: Array<{ phase: Exclude<TeacherTaskPhase, 'all'>; label: string }> = [
    { phase: 'upcoming', label: '尚未开始' },
    { phase: 'in_progress', label: '进行中' },
    { phase: 'ended', label: '已结束' },
    { phase: 'cancelled', label: '已取消' },
    { phase: 'unpublished', label: '未发布' },
  ]
  return laneDefinitions
    .filter(({ phase }) => ['upcoming', 'in_progress', 'ended'].includes(phase)
      || filteredTasks.value.some((task) => task.phase === phase)
      || phaseFilter.value === phase)
    .map((lane) => ({ ...lane, tasks: filteredTasks.value.filter((task) => task.phase === lane.phase) }))
})

const selectDate = (dateKey: string) => {
  selectedDate.value = dateKey
  const date = dateFromKey(dateKey)
  if (date.getFullYear() !== monthCursor.value.getFullYear() || date.getMonth() !== monthCursor.value.getMonth()) {
    monthCursor.value = new Date(date.getFullYear(), date.getMonth(), 1)
  }
}

const changeMonth = (offset: number) => {
  const selected = dateFromKey(selectedDate.value)
  const nextMonth = new Date(monthCursor.value.getFullYear(), monthCursor.value.getMonth() + offset, 1)
  const maxDay = new Date(nextMonth.getFullYear(), nextMonth.getMonth() + 1, 0).getDate()
  monthCursor.value = nextMonth
  selectedDate.value = localDateKey(new Date(nextMonth.getFullYear(), nextMonth.getMonth(), Math.min(selected.getDate(), maxDay)))
}

const goToToday = () => {
  monthCursor.value = new Date(today.getFullYear(), today.getMonth(), 1)
  selectedDate.value = todayKey
}

const openTask = (taskKey: string) => {
  if (filteredTasks.value.some((task) => task.key === taskKey)) selectedTaskKey.value = taskKey
}

const updateDrawerOpen = (open: boolean) => {
  if (!open) selectedTaskKey.value = ''
}

const clearFilters = () => {
  searchQuery.value = ''
  classFilter.value = 'all'
  phaseFilter.value = 'all'
}

const hasActiveFilters = computed(() => Boolean(searchQuery.value.trim()) || classFilter.value !== 'all' || phaseFilter.value !== 'all')

watch(filteredTasks, (tasks) => {
  if (selectedTaskKey.value && !tasks.some((task) => task.key === selectedTaskKey.value)) selectedTaskKey.value = ''
})
</script>

<template>
  <main class="teacher-assessment-page content-wrap" aria-label="教师工作区，测评任务">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="测评任务" />

    <header class="assessment-page-heading">
      <div>
        <h1>测评任务</h1>
        <p>按时间与执行状态查看任务安排</p>
      </div>
      <span class="assessment-page-heading__badge">{{ isDemo ? '合成数据预览 · 只读' : '教师视图 · 只读' }}</span>
    </header>

    <section class="assessment-filterbar" aria-label="任务筛选与视图切换">
      <label class="assessment-search">
        <Search :size="16" aria-hidden="true" />
        <span class="sr-only">搜索测评任务或班级</span>
        <input v-model="searchQuery" type="search" autocomplete="off" placeholder="搜索测评任务或班级" aria-label="搜索测评任务或班级">
      </label>

      <TeacherClassSelect
        v-model="classFilter"
        class="assessment-class-filter"
        :options="classOptions"
        searchable
        :disabled="state !== 'ready' || !rows.length"
        :aria-label="isDemo ? '按班级筛选（合成数据预览）' : '按授权班级筛选'"
      />

      <label class="assessment-status-filter">
        <span class="sr-only">按任务状态筛选</span>
        <select v-model="phaseFilter" :disabled="state !== 'ready' || !rows.length" aria-label="按任务状态筛选">
          <option v-for="option in phaseOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>

      <div class="assessment-view-switch" role="group" aria-label="任务视图">
        <button type="button" :aria-pressed="viewMode === 'calendar'" @click="viewMode = 'calendar'">
          <CalendarDays :size="14" aria-hidden="true" />日历
        </button>
        <button type="button" :aria-pressed="viewMode === 'board'" @click="viewMode = 'board'">
          <Columns3 :size="14" aria-hidden="true" />看板
        </button>
      </div>
    </section>

    <button v-if="hasActiveFilters" class="assessment-clear-filters" type="button" @click="clearFilters">清除筛选</button>

    <div v-if="state === 'loading'" class="assessment-state assessment-state--loading" role="status" aria-live="polite" aria-busy="true">
      <span class="assessment-skeleton" aria-hidden="true"></span>
      <span>正在读取教师授权任务</span>
    </div>

    <section v-else-if="state === 'error'" class="assessment-state assessment-state--error" role="alert">
      <div><strong>暂时无法读取任务安排</strong><p>{{ displayedErrorMessage }}</p></div>
      <AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton>
    </section>

    <template v-else>
      <div class="assessment-summary" aria-live="polite">
        <span><strong>{{ filteredTasks.length }}</strong> 项匹配任务</span>
        <i aria-hidden="true"></i>
        <span><strong>{{ activeCount }}</strong> 项进行中</span>
        <i aria-hidden="true"></i>
        <span><strong>{{ dueSoonCount }}</strong> 项 7 日内截止</span>
      </div>

      <section v-if="!rows.length" class="assessment-state assessment-state--empty" role="status">
        <span class="assessment-state__mark" aria-hidden="true"></span>
        <strong>当前没有可查看的授权任务</strong>
        <span>获得班级任务授权后，日历与看板会显示任务安排</span>
      </section>

      <section v-else-if="!filteredTasks.length" class="assessment-state assessment-state--empty" role="status">
        <span class="assessment-state__mark" aria-hidden="true"></span>
        <strong>{{ searchQuery.trim() ? '未找到匹配任务' : '当前筛选下没有任务' }}</strong>
        <span>调整班级或任务状态后再查看</span>
      </section>

      <div v-else-if="viewMode === 'calendar'" class="assessment-calendar-layout">
        <TaskCalendar
          :month="monthCursor"
          :events-by-date="eventsByDate"
          :today-key="todayKey"
          :selected-date="selectedDate"
          @select-date="selectDate"
          @change-month="changeMonth"
          @go-today="goToToday"
          @open-task="openTask"
        />
        <DayAgenda
          :date-key="selectedDate"
          :date-label="selectedDateLabel"
          :items="agendaItems"
          @open-task="openTask"
        />
      </div>

      <TaskKanbanBoard v-else :lanes="boardLanes" :selected-task-key="selectedTaskKey" @open-task="openTask" />
    </template>

    <p class="assessment-page-note">
      日历展示任务开始与截止日期，统计按授权任务计算；不包含学生个人心理记录
      <span v-if="isDemo"> · 当前使用合成数据预览</span>
    </p>

    <TeacherTaskDrawer :open="Boolean(selectedTask)" :task="selectedTask" :is-demo="isDemo" @update:open="updateDrawerOpen" />
  </main>
</template>

<style scoped>
.teacher-assessment-page { display: grid; gap: 13px; padding-top: 0; padding-bottom: 32px; }
.assessment-page-heading { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 16px; padding: 2px 2px 3px; }
.assessment-page-heading h1 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 22px; font-weight: 700; line-height: 1.25; }
.assessment-page-heading p { margin: 0; color: var(--color-text-muted); font-size: 12px; }
.assessment-page-heading__badge { flex: 0 0 auto; padding: 7px 10px; border-radius: 999px; color: var(--color-text-muted); background: var(--color-surface-blue); font-size: 10px; white-space: nowrap; }
.assessment-filterbar { display: grid; grid-template-columns: minmax(220px, 1.4fr) minmax(155px, .85fr) minmax(135px, .7fr) auto; align-items: center; gap: 8px; padding: 11px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.assessment-search { display: flex; min-width: 0; min-height: 38px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-muted); background: var(--color-surface); }
.assessment-search:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(0 177 226 / 12%); }
.assessment-search input { width: 100%; min-width: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font-size: 11px; }
.assessment-search input::placeholder { color: var(--color-text-muted); }
.assessment-class-filter { min-width: 0; }
.assessment-class-filter :deep(.teacher-class-select__trigger) { min-width: 0; min-height: 38px; border-radius: var(--radius-button); }
.assessment-class-filter :deep(.teacher-class-select__menu) { z-index: 50; }
.assessment-status-filter select { width: 100%; min-height: 38px; padding: 0 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-primary); background: var(--color-surface); font-size: 11px; cursor: pointer; }
.assessment-status-filter select:disabled { cursor: not-allowed; opacity: .58; }
.assessment-view-switch { display: flex; min-height: 38px; align-items: center; gap: 3px; padding: 3px; border-radius: var(--radius-button); background: var(--color-surface-blue); }
.assessment-view-switch button { display: inline-flex; min-width: 62px; min-height: 31px; align-items: center; justify-content: center; gap: 5px; padding: 0 9px; border: 0; border-radius: 6px; color: var(--color-text-muted); background: transparent; font-size: 10px; cursor: pointer; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.assessment-view-switch button[aria-pressed='true'] { color: var(--color-primary-active); background: var(--color-surface); box-shadow: 0 1px 4px rgb(31 63 78 / 12%); font-weight: 650; }
.assessment-view-switch button:focus-visible,.assessment-status-filter select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.assessment-clear-filters { justify-self: end; margin-top: -6px; padding: 3px 7px; border: 0; color: var(--color-primary-active); background: transparent; font-size: 10px; cursor: pointer; }
.assessment-clear-filters:hover { text-decoration: underline; }
.assessment-summary { display: flex; min-height: 22px; flex-wrap: wrap; align-items: center; gap: 8px; padding: 0 2px; color: var(--color-text-muted); font-size: 11px; }
.assessment-summary span { white-space: nowrap; }
.assessment-summary strong { color: var(--color-text-primary); font-size: 12px; font-variant-numeric: tabular-nums; }
.assessment-summary i { width: 3px; height: 3px; border-radius: 50%; background: #b3bdc5; }
.assessment-calendar-layout { display: grid; min-width: 0; grid-template-columns: minmax(0, 2.65fr) minmax(270px, 1fr); align-items: stretch; gap: 12px; }
.assessment-state { display: flex; min-height: 180px; align-items: center; justify-content: center; gap: 13px; padding: 22px; border: 1px solid var(--color-border); border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface); font-size: 12px; text-align: center; }
.assessment-state--loading { position: relative; overflow: hidden; background: var(--color-surface); }
.assessment-skeleton { width: 18px; height: 18px; border: 2px solid var(--color-surface-skeleton); border-top-color: var(--color-primary); border-radius: 50%; animation: assessment-spin 850ms linear infinite; }
.assessment-state--error { justify-content: space-between; color: var(--color-critical); text-align: left; }
.assessment-state--error p { margin: 4px 0 0; color: var(--color-text-muted); font-size: 11px; }
.assessment-state--empty { display: grid; align-content: center; justify-items: center; gap: 7px; color: var(--color-text-muted); }
.assessment-state--empty strong { color: var(--color-text-secondary); font-size: 12px; font-weight: 650; }
.assessment-state--empty span:last-child { font-size: 10px; }
.assessment-state__mark { width: 30px; height: 30px; border: 1px solid var(--color-border-strong); border-radius: 50%; background: var(--color-surface-soft); }
.assessment-page-note { margin: 0 2px; color: var(--color-text-muted); font-size: 10px; line-height: 1.55; }
@keyframes assessment-spin { to { transform: rotate(360deg); } }
@media (max-width: 1060px) { .assessment-calendar-layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 900px) {
  .assessment-filterbar { grid-template-columns: minmax(0, 1fr) minmax(150px, .7fr); }
  .assessment-search { min-width: 0; }
  .assessment-view-switch { justify-self: start; }
}
@media (max-width: 560px) {
  .teacher-assessment-page { gap: 11px; padding-bottom: 28px; }
  .assessment-page-heading { align-items: flex-start; }
  .assessment-page-heading h1 { font-size: 20px; }
  .assessment-page-heading__badge { padding: 6px 8px; font-size: 9px; }
  .assessment-filterbar { grid-template-columns: minmax(0, 1fr); gap: 8px; padding: 10px; }
  .assessment-view-switch { display: grid; width: 100%; grid-template-columns: 1fr 1fr; }
  .assessment-view-switch button { width: 100%; }
  .assessment-summary { gap: 6px; font-size: 10px; }
  .assessment-summary strong { font-size: 11px; }
  .assessment-state { min-height: 150px; }
}
@media (prefers-reduced-motion: reduce) {
  .assessment-skeleton { animation: none; }
  .assessment-view-switch button { transition: none; }
}
</style>
