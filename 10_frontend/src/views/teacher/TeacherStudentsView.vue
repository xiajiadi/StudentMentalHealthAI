<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts/core'
import { Activity, ChartColumn, ChartNoAxesCombined, ListChecks, Search } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import TeacherClassSelect from '@/components/teacher/TeacherClassSelect.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import {
  formatTeacherDate,
  taskCompletionRate,
  taskProgressCount,
  teacherChartColors,
  teacherClassDisplayLabel,
  teacherTaskDisplayLabel,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
  teacherTaskStatusLabel,
  teacherTaskStatusPalette,
} from '@/utils/teacher-task-progress'

type TaskFilter = 'all' | 'soon' | 'low'
type ChartStatusKey = 'notStarted' | 'inProgress' | 'completed' | 'ended'

const classStorageKey = 'psynova.teacher.class-workspace.selected.v1'
const soonWindowMs = 72 * 60 * 60 * 1000
const snapshotTime = Date.now()
const { state, rows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })
const selectedClassRef = ref(readSavedClass())
const selectedTaskRef = ref('')
const taskFilter = ref<TaskFilter>('all')
const taskQuery = ref('')
const taskFilterRoot = ref<HTMLElement | null>(null)
const allFilterButton = ref<HTMLButtonElement | null>(null)
const soonFilterButton = ref<HTMLButtonElement | null>(null)
const lowFilterButton = ref<HTMLButtonElement | null>(null)
const taskFilterSelectionStyle = ref({ width: '0px', transform: 'translateX(0)' })
const viewportWidth = ref(typeof window === 'undefined' ? 1280 : window.innerWidth)
const compactChartLabels = computed(() => viewportWidth.value <= 600)

const updateViewportWidth = () => { viewportWidth.value = window.innerWidth }
const updateTaskFilterSelection = () => {
  const root = taskFilterRoot.value
  const button = taskFilter.value === 'all'
    ? allFilterButton.value
    : taskFilter.value === 'soon' ? soonFilterButton.value : lowFilterButton.value
  if (!root || !button) return
  const rootLeft = root.getBoundingClientRect().left
  const buttonBounds = button.getBoundingClientRect()
  taskFilterSelectionStyle.value = {
    width: `${buttonBounds.width}px`,
    transform: `translateX(${buttonBounds.left - rootLeft - 4}px)`,
  }
}
let taskFilterResizeObserver: ResizeObserver | null = null
watch(taskFilter, updateTaskFilterSelection, { flush: 'post' })
onMounted(() => {
  window.addEventListener('resize', updateViewportWidth, { passive: true })
  if (!taskFilterRoot.value) return
  taskFilterResizeObserver = new ResizeObserver(updateTaskFilterSelection)
  taskFilterResizeObserver.observe(taskFilterRoot.value)
  const filterButtons = [allFilterButton.value, soonFilterButton.value, lowFilterButton.value]
  filterButtons.forEach((button) => {
    if (button) taskFilterResizeObserver?.observe(button)
  })
  updateTaskFilterSelection()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewportWidth)
  taskFilterResizeObserver?.disconnect()
  taskFilterResizeObserver = null
})

function readSavedClass() {
  if (typeof window === 'undefined') return ''
  try {
    return window.localStorage.getItem(classStorageKey) ?? ''
  } catch {
    return ''
  }
}

const isPublishedTask = (task: (typeof rows.value)[number]) => task.task_status.trim().toUpperCase() === 'PUBLISHED'
const dueTime = (task: (typeof rows.value)[number]) => {
  if (!task.due_at) return Number.POSITIVE_INFINITY
  const timestamp = Date.parse(task.due_at)
  return Number.isFinite(timestamp) ? timestamp : Number.POSITIVE_INFINITY
}

const compareByDeadline = (first: (typeof rows.value)[number], second: (typeof rows.value)[number]) => {
  const firstDue = dueTime(first)
  const secondDue = dueTime(second)
  if (firstDue !== secondDue) return firstDue < secondDue ? -1 : 1
  return teacherTaskDisplayLabel(first).localeCompare(teacherTaskDisplayLabel(second), 'zh-CN')
    || first.task_ref.localeCompare(second.task_ref)
}

const classOptions = computed(() => [...new Set(rows.value.map((row) => row.class_ref))]
  .map((classRef) => ({ value: classRef, label: teacherClassDisplayLabel(classRef, rows.value) }))
  .sort((first, second) => first.label.localeCompare(second.label, 'zh-CN')))

const chooseDefaultClassRef = () => {
  const classes = [...new Set(rows.value.map((row) => row.class_ref))]
  const candidates = classes.map((classRef) => {
    const tasks = rows.value.filter((row) => row.class_ref === classRef && isPublishedTask(row)).sort(compareByDeadline)
    return {
      classRef,
      earliestDue: tasks.length ? dueTime(tasks[0]) : Number.POSITIVE_INFINITY,
      label: teacherClassDisplayLabel(classRef, rows.value),
    }
  })
  candidates.sort((first, second) => first.earliestDue !== second.earliestDue
    ? first.earliestDue < second.earliestDue ? -1 : 1
    : first.label.localeCompare(second.label, 'zh-CN'))
  return candidates[0]?.classRef ?? ''
}

let initialClassResolved = false
watch(classOptions, (options) => {
  if (!options.length) {
    if (state.value === 'ready') selectedClassRef.value = ''
    return
  }
  if (!initialClassResolved) {
    const saved = readSavedClass()
    selectedClassRef.value = options.some((option) => option.value === saved) ? saved : chooseDefaultClassRef()
    initialClassResolved = true
  } else if (!options.some((option) => option.value === selectedClassRef.value)) {
    selectedClassRef.value = chooseDefaultClassRef()
  }
}, { immediate: true })

watch(selectedClassRef, (classRef) => {
  if (!classRef || !classOptions.value.some((option) => option.value === classRef)) return
  try {
    window.localStorage.setItem(classStorageKey, classRef)
  } catch {
    // Keep the current selection in memory when storage is disabled.
  }
})

const classTasks = computed(() => rows.value
  .filter((row) => row.class_ref === selectedClassRef.value && isPublishedTask(row))
  .sort(compareByDeadline))
const authorizedTaskCount = computed(() => new Set(classTasks.value.map((task) => task.task_ref)).size)

const getTaskCounts = (task: (typeof rows.value)[number]) => {
  const active = taskProgressCount(task, 'active_enrollment_count')
  return {
    active,
    notStarted: taskProgressCount(task, 'not_started_count'),
    inProgress: taskProgressCount(task, 'created_count') + taskProgressCount(task, 'in_progress_count'),
    completed: taskProgressCount(task, 'completed_count'),
    ended: taskProgressCount(task, 'abandoned_count') + taskProgressCount(task, 'invalid_count'),
    revoked: taskProgressCount(task, 'revoked_enrollment_count'),
  }
}

const taskRate = (task: (typeof rows.value)[number]) => {
  const active = taskProgressCount(task, 'active_enrollment_count')
  return active > 0 ? taskCompletionRate(task) : null
}

const classMetrics = computed(() => {
  const activeEnrollmentCount = classTasks.value.reduce((total, task) => total + taskProgressCount(task, 'active_enrollment_count'), 0)
  const completedCount = classTasks.value.reduce((total, task) => total + taskProgressCount(task, 'completed_count'), 0)
  return {
    taskCount: authorizedTaskCount.value,
    activeEnrollmentCount,
    completedCount,
    incompleteCount: Math.max(0, activeEnrollmentCount - completedCount),
    completionRate: activeEnrollmentCount > 0 ? Math.min(100, Math.round(completedCount / activeEnrollmentCount * 100)) : null,
  }
})

const chartTasks = computed(() => classTasks.value.filter((task) => taskProgressCount(task, 'active_enrollment_count') > 0))
const isDueSoon = (task: (typeof rows.value)[number]) => {
  const due = dueTime(task)
  return due >= snapshotTime && due <= snapshotTime + soonWindowMs
}
const isBelowClassRate = (task: (typeof rows.value)[number]) => {
  const rate = taskRate(task)
  const classRate = classMetrics.value.completionRate
  return rate !== null && classRate !== null && rate < classRate
}
const visibleTaskRows = computed(() => {
  const query = taskQuery.value.trim().toLocaleLowerCase()
  return classTasks.value.filter((task) => {
    if (taskFilter.value === 'soon' && !isDueSoon(task)) return false
    if (taskFilter.value === 'low' && !isBelowClassRate(task)) return false
    return !query || (teacherTaskDisplayLabel(task) + ' ' + task.task_ref).toLocaleLowerCase().includes(query)
  })
})
const chooseDefaultTask = (tasks: typeof classTasks.value) => [...tasks].sort(compareByDeadline)[0]

let previousClassRef = ''
watch([selectedClassRef, classTasks], ([classRef, tasks]) => {
  if (classRef !== previousClassRef || !tasks.some((task) => task.task_ref === selectedTaskRef.value)) {
    selectedTaskRef.value = chooseDefaultTask(tasks)?.task_ref ?? ''
  }
  previousClassRef = classRef
}, { immediate: true })
watch(visibleTaskRows, (tasks) => {
  if (!tasks.some((task) => task.task_ref === selectedTaskRef.value)) selectedTaskRef.value = tasks[0]?.task_ref ?? ''
}, { immediate: true })

const selectedTask = computed(() => visibleTaskRows.value.find((task) => task.task_ref === selectedTaskRef.value) ?? null)
const selectedTaskCounts = computed(() => selectedTask.value ? getTaskCounts(selectedTask.value) : null)
const selectTask = (taskRef: string) => {
  if (!classTasks.value.some((task) => task.task_ref === taskRef)) return
  if (!visibleTaskRows.value.some((task) => task.task_ref === taskRef)) {
    taskFilter.value = 'all'
    taskQuery.value = ''
  }
  selectedTaskRef.value = taskRef
}

const statusDefinitions: Array<{ key: ChartStatusKey; label: string; color: string }> = [
  { key: 'completed', label: '已完成', color: teacherTaskStatusPalette.completed.color },
  { key: 'inProgress', label: '进行中', color: teacherTaskStatusPalette.inProgress.color },
  { key: 'notStarted', label: '未开始', color: teacherTaskStatusPalette.notStarted.color },
  { key: 'ended', label: '已结束 / 不可继续', color: teacherTaskStatusPalette.ended.color },
]
const countForStatus = (task: (typeof rows.value)[number], key: ChartStatusKey) => getTaskCounts(task)[key]
const share = (value: number, total: number) => total > 0 ? value / total * 100 : 0
const formatShare = (value: number, total: number) => share(value, total).toFixed(1) + '%'
const selectedTaskStatusSegments = computed(() => {
  const counts = selectedTaskCounts.value
  return statusDefinitions.map((status) => {
    const count = counts?.[status.key] ?? 0
    return {
      ...status,
      count,
      percentage: share(count, counts?.active ?? 0),
      percentageLabel: formatShare(count, counts?.active ?? 0),
    }
  })
})
const selectedTaskStatusDescription = computed(() => {
  const counts = selectedTaskCounts.value
  if (!counts) return ''
  const statuses = selectedTaskStatusSegments.value.map((status) => `${status.label} ${status.count} 人次，${status.percentageLabel}`)
  return `有效报名 ${counts.active} 人次；${statuses.join('；')}；已撤销报名 ${counts.revoked} 人次`
})
const selectedTaskStatusMismatch = computed(() => {
  const counts = selectedTaskCounts.value
  return Boolean(counts && selectedTaskStatusSegments.value.reduce((total, status) => total + status.count, 0) !== counts.active)
})
const escapeHtml = (value: string) => value
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;')

const taskRefFromChartData = (data: unknown): string | null => {
  if (typeof data !== 'object' || data === null || !('taskRef' in data)) return null
  return typeof data.taskRef === 'string' ? data.taskRef : null
}
const chartTaskFromParams = (params: unknown) => {
  const list = Array.isArray(params) ? params : [params]
  const first = list[0]
  if (typeof first !== 'object' || first === null || !('data' in first)) return null
  const taskRef = taskRefFromChartData(first.data)
  return taskRef ? chartTasks.value.find((task) => task.task_ref === taskRef) ?? null : null
}
const stackTooltip = (task: (typeof rows.value)[number]) => {
  const counts = getTaskCounts(task)
  const lines = statusDefinitions.map((status) => {
    const value = counts[status.key]
    return '<div style="display:flex;align-items:center;gap:7px;margin-top:5px">'
      + '<span style="width:8px;height:8px;border-radius:2px;background:' + status.color + '"></span>'
      + '<span>' + status.label + '</span><strong style="margin-left:auto">' + value + ' 人次（' + formatShare(value, counts.active) + '）</strong></div>'
  }).join('')
  return '<div style="min-width:200px;color:#344657"><strong>' + escapeHtml(teacherTaskDisplayLabel(task)) + '</strong>'
    + '<div style="margin-top:4px;color:#8191a0">有效报名 ' + counts.active + ' 人次</div>' + lines + '</div>'
}

const stackOption = computed<EChartsOption>(() => ({
  animation: false,
  color: statusDefinitions.map((status) => status.color),
  tooltip: {
    trigger: 'axis',
    axisPointer: {
      type: 'shadow',
      shadowStyle: {
        shadowBlur: 8,
        shadowColor: 'rgba(0, 177, 226, 0.06)',
        color: {
          type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [
            { offset: 0, color: 'rgba(0, 177, 226, 0)' },
            { offset: 0.14, color: 'rgba(0, 177, 226, 0.065)' },
            { offset: 0.5, color: 'rgba(0, 177, 226, 0.11)' },
            { offset: 0.86, color: 'rgba(0, 177, 226, 0.065)' },
            { offset: 1, color: 'rgba(0, 177, 226, 0)' },
          ],
        },
      },
    },
    backgroundColor: 'rgba(255, 255, 255, 0.98)',
    borderColor: '#dce8ed',
    borderWidth: 1,
    borderRadius: 10,
    confine: true,
    padding: [10, 12],
    textStyle: {
      color: '#6f8191',
      fontFamily: 'var(--font-sans)',
      fontSize: 13,
      fontWeight: 400,
      lineHeight: 20,
    },
    extraCssText: 'box-shadow: 0 8px 22px rgba(52, 80, 96, 0.14);',
    formatter: (params) => {
      const task = chartTaskFromParams(params)
      return task ? stackTooltip(task) : ''
    },
  },
  grid: { top: 20, right: 54, bottom: chartTasks.value.length > 8 ? 76 : 58, left: 54, containLabel: false },
  xAxis: {
    type: 'category',
    data: chartTasks.value.map((task) => teacherTaskDisplayLabel(task)),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: teacherChartColors.grid } },
    axisLabel: {
      color: teacherChartColors.muted,
      fontSize: compactChartLabels.value ? 9 : 10,
      interval: compactChartLabels.value ? 'auto' : 0,
      rotate: 0,
      hideOverlap: true,
      rich: { rate: { color: '#7c8e9a', fontSize: 9, fontWeight: 600, padding: [3, 0, 0, 0] } },
      formatter: (value: string, index: number) => {
        const label = Array.from(value)
        const maxCharacters = compactChartLabels.value ? 3 : 5
        const task = chartTasks.value[index]
        const name = label.length > maxCharacters ? label.slice(0, maxCharacters).join('') + '…' : value
        const rate = task ? taskRate(task) : null
        return rate === null ? name : name + '\n{rate|' + rate + '%}'
      },
    },
  },
  yAxis: {
    type: 'value',
    min: 0,
    max: 100,
    interval: 25,
    axisLabel: { color: teacherChartColors.muted, fontSize: compactChartLabels.value ? 9 : 10, formatter: (value: number | string) => Number(value) + '%' },
    splitLine: { lineStyle: { color: teacherChartColors.grid } },
  },
  dataZoom: chartTasks.value.length > 8
    ? [
        { type: 'inside', zoomOnMouseWheel: false, moveOnMouseWheel: true },
        { type: 'slider', bottom: 28, height: 10, start: 0, end: Math.min(100, 800 / chartTasks.value.length), borderColor: 'transparent', fillerColor: '#d9eef2', handleStyle: { color: '#53a9cf' } },
      ]
    : [],
  series: statusDefinitions.map((status) => ({
    name: status.label,
    type: 'bar',
    stack: 'enrollment-status',
    barMaxWidth: 36,
    barCategoryGap: '34%',
    emphasis: { disabled: true },
    data: chartTasks.value.map((task) => {
      const selected = task.task_ref === selectedTaskRef.value
      return {
        value: share(countForStatus(task, status.key), taskProgressCount(task, 'active_enrollment_count')),
        taskRef: task.task_ref,
        itemStyle: {
          opacity: selectedTaskRef.value && !selected ? 0.3 : 1,
          borderColor: selected ? '#66808b' : 'transparent',
          borderWidth: selected ? 1 : 0,
        },
      }
    }),
  })),
}))

const scatterTasks = computed(() => chartTasks.value.filter((task) => Number.isFinite(dueTime(task))))
const scatterColor = (task: (typeof rows.value)[number]) => {
  const due = dueTime(task)
  if (due >= snapshotTime && due <= snapshotTime + soonWindowMs) return '#e1a76b'
  return '#8bd7e8'
}
const scatterRange = computed(() => {
  const times = scatterTasks.value.map(dueTime)
  if (!times.length) return { min: snapshotTime - 24 * 60 * 60 * 1000, max: snapshotTime + 24 * 60 * 60 * 1000 }
  const min = Math.min(...times)
  const max = Math.max(...times)
  const padding = Math.max((max - min) * 0.07, 24 * 60 * 60 * 1000)
  return { min: min - padding, max: max + padding }
})
const formatAxisDate = (value: string | number) => {
  const timestamp = Number(value)
  if (!Number.isFinite(timestamp)) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(timestamp)
}
const scatterTooltip = (task: (typeof rows.value)[number]) => {
  const counts = getTaskCounts(task)
  const rate = taskRate(task)
  const row = (label: string, value: string) => '<div style="display:flex;justify-content:space-between;gap:16px;margin-top:6px">'
    + '<span style="color:#8191a0">' + label + '</span><strong style="color:#344657;text-align:right">' + value + '</strong></div>'
  return '<div style="min-width:200px;color:#344657"><strong style="font-size:14px">' + escapeHtml(teacherTaskDisplayLabel(task)) + '</strong>'
    + row('截止时间', escapeHtml(formatTeacherDate(task.due_at, '未设置截止时间')))
    + row('完成率', rate === null ? '—' : rate + '%')
    + row('有效报名', counts.active + ' 人次')
    + row('未完成人次', String(Math.max(0, counts.active - counts.completed))) + '</div>'
}

const scatterOption = computed<EChartsOption>(() => ({
  animation: false,
  tooltip: {
    trigger: 'item',
    backgroundColor: 'rgba(255, 255, 255, 0.98)',
    borderColor: '#dce8ed',
    borderWidth: 1,
    borderRadius: 10,
    confine: true,
    padding: [10, 12],
    textStyle: {
      color: '#6f8191',
      fontFamily: 'var(--font-sans)',
      fontSize: 13,
      fontWeight: 400,
      lineHeight: 20,
    },
    extraCssText: 'box-shadow: 0 8px 22px rgba(52, 80, 96, 0.14);',
    formatter: (params) => {
      const task = chartTaskFromParams(params)
      return task ? scatterTooltip(task) : ''
    },
  },
  grid: { top: 20, right: 54, bottom: 42, left: 54, containLabel: false },
  xAxis: {
    type: 'time',
    min: scatterRange.value.min,
    max: scatterRange.value.max,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: teacherChartColors.grid } },
    axisLabel: { color: teacherChartColors.muted, fontSize: compactChartLabels.value ? 9 : 10, rotate: 0, margin: 12, hideOverlap: true, formatter: formatAxisDate },
    splitLine: { lineStyle: { color: teacherChartColors.grid, type: 'dashed' } },
  },
  yAxis: {
    type: 'value',
    min: 0,
    max: 100,
    interval: 25,
    axisLabel: { color: teacherChartColors.muted, fontSize: compactChartLabels.value ? 9 : 10, formatter: (value: number | string) => Number(value) + '%' },
    splitLine: { lineStyle: { color: teacherChartColors.grid } },
  },
  series: [{
    type: 'scatter',
    symbol: 'circle',
    data: scatterTasks.value.map((task) => {
      const selected = task.task_ref === selectedTaskRef.value
      const counts = getTaskCounts(task)
      return {
        value: [dueTime(task), taskRate(task) ?? 0],
        taskRef: task.task_ref,
        symbolSize: Math.min(18, 8 + Math.sqrt(Math.max(0, counts.active - counts.completed))),
        itemStyle: {
          color: scatterColor(task),
          opacity: selectedTaskRef.value && !selected ? 0.28 : 0.92,
          borderColor: selected ? '#1e1d29' : '#ffffff',
          borderWidth: selected ? 2 : 1,
        },
      }
    }),
    emphasis: { scale: 1.25, focus: 'self' },
  }],
}))

const statusCountsMismatch = computed(() => chartTasks.value.some((task) => {
  const counts = getTaskCounts(task)
  return counts.notStarted + counts.inProgress + counts.completed + counts.ended !== counts.active
}))
const phaseClass = (task: (typeof rows.value)[number]) => 'task-phase--' + teacherTaskPhase(task)
const formatShortDeadline = (value: string | null | undefined) => {
  const timestamp = value ? Date.parse(value) : Number.NaN
  if (!Number.isFinite(timestamp)) return '未设置截止'
  const date = new Date(timestamp)
  return (date.getMonth() + 1) + '/' + date.getDate() + ' 截止'
}
const taskUrgencyLabel = (task: (typeof rows.value)[number]) => isDueSoon(task) ? '临近截止' : teacherTaskPhaseLabel(teacherTaskPhase(task))
const taskUrgencyClass = (task: (typeof rows.value)[number]) => isDueSoon(task) ? 'task-phase--urgent' : phaseClass(task)
const taskAccessibleLabel = (task: (typeof rows.value)[number]) => {
  const counts = getTaskCounts(task)
  const rate = taskRate(task)
  return teacherTaskDisplayLabel(task) + '，截止' + formatTeacherDate(task.due_at, '未设置截止时间')
    + '，完成率' + (rate === null ? '不可用' : rate + '%')
    + '，已完成 ' + counts.completed + ' / ' + counts.active + ' 人次'
}
</script>

<template>
  <main class="content-wrap teacher-class-workspace" aria-label="教师工作区，班级进度">
    <header class="class-workspace-header">
      <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="班级进度" />
      <TeacherClassSelect
        v-model="selectedClassRef"
        class="class-workspace-filter"
        :options="classOptions"
        searchable
        :disabled="state !== 'ready' || classOptions.length === 0"
        :aria-label="isDemo ? '选择班级（合成数据预览）' : '选择授权班级'"
      />
    </header>

    <div v-if="state === 'loading'" class="class-workspace-state" role="status" aria-live="polite" aria-busy="true">正在读取授权班级任务汇总…</div>
    <AppStatusCallout v-else-if="state === 'error'" class="class-workspace-error" tone="critical" title="班级进度暂不可用" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton>
    </AppStatusCallout>
    <div v-else-if="classOptions.length === 0" class="class-workspace-state" role="status">当前账号没有可查看的授权班级任务汇总</div>

    <template v-else>
      <AppCard class="class-summary-band" aria-label="当前班级概况">
        <div class="class-summary-band__details">
          <div class="class-summary-band__identity">
            <span class="class-summary-band__eyebrow">当前授权班级</span>
            <h2>{{ teacherClassDisplayLabel(selectedClassRef, rows) }}</h2>
          </div>
          <dl class="class-summary-metrics">
            <div><dt>测评任务</dt><dd>{{ classMetrics.taskCount }} <span>项</span></dd></div>
            <div><dt>有效报名人次</dt><dd>{{ classMetrics.activeEnrollmentCount }} <span>人次</span></dd></div>
            <div><dt>尚未完成人次</dt><dd>{{ classMetrics.incompleteCount }} <span>人次</span></dd></div>
          </dl>
        </div>
        <div class="class-summary-rate" aria-label="总体完成率">
          <strong>{{ classMetrics.completionRate === null ? '—' : classMetrics.completionRate + '%' }}</strong>
          <span>总体完成率</span>
        </div>
      </AppCard>

      <section class="class-analysis-grid" aria-label="班级任务分析">
        <AppCard class="class-analysis-card">
          <header class="class-section-heading">
            <span class="class-section-heading__icon class-section-heading__icon--blue"><ChartColumn :size="17" aria-hidden="true" /></span>
            <div><h2>各任务完成构成</h2><p>按当前班级有效报名人次展示任务状态占比</p></div>
          </header>
          <TeacherProgressChart
            v-if="chartTasks.length"
            :option="stackOption"
            label="当前班级各任务完成构成百分比堆叠柱状图"
            :height="286"
            interactive
            @select="selectTask"
          />
          <div v-if="chartTasks.length" class="class-chart-legend" role="img" aria-label="任务状态图例">
            <span v-for="status in statusDefinitions" :key="status.key" class="class-chart-legend__item">
              <i class="class-chart-legend__swatch" :style="{ backgroundColor: status.color }"></i>{{ status.label }}
            </span>
          </div>
          <p v-if="statusCountsMismatch" class="class-chart-note" role="note">部分任务状态人数与有效报名人次不一致，图表按接口原值展示</p>
          <p v-else-if="!chartTasks.length" class="class-chart-empty">当前班级暂无有效报名，暂时无法展示任务状态占比</p>
        </AppCard>

        <AppCard class="class-analysis-card">
          <header class="class-section-heading">
            <span class="class-section-heading__icon class-section-heading__icon--teal"><ChartNoAxesCombined :size="17" aria-hidden="true" /></span>
            <div><h2>截止日与完成率</h2><p>比较任务截止时间、完成进度与未完成人次</p></div>
          </header>
          <TeacherProgressChart
            v-if="scatterTasks.length"
            :option="scatterOption"
            label="当前班级授权任务截止日期与完成率散点图"
            :height="286"
            interactive
            @select="selectTask"
          />
          <div v-if="scatterTasks.length" class="class-chart-legend class-chart-legend--scatter" role="img" aria-label="临近截止任务为橙色，一般任务为浅蓝色，点的大小代表未完成人次">
            <span class="class-chart-legend__item"><i class="class-chart-legend__swatch class-chart-legend__swatch--dot class-chart-legend__swatch--soon"></i>临近截止</span>
            <span class="class-chart-legend__item"><i class="class-chart-legend__swatch class-chart-legend__swatch--dot class-chart-legend__swatch--general"></i>一般任务</span>
            <span class="class-chart-legend__note">点的大小代表未完成人次</span>
          </div>
          <p v-else class="class-chart-empty">当前班级暂无设置截止时间且有有效报名的任务</p>
        </AppCard>
      </section>

      <AppCard class="task-workbench" aria-labelledby="task-workbench-title">
        <header class="task-workbench__header">
          <div class="class-section-heading">
            <span class="class-section-heading__icon class-section-heading__icon--amber"><ListChecks :size="17" aria-hidden="true" /></span>
            <div><h2 id="task-workbench-title">任务工作台</h2><p>选择任务查看汇总；图表和详情随选择同步</p></div>
          </div>
          <span class="task-workbench__count" :aria-label="`当前班级 ${authorizedTaskCount} 项授权任务`">{{ authorizedTaskCount }} 项授权任务</span>
        </header>

        <div class="task-workbench__body">
          <section class="task-timeline" aria-labelledby="task-timeline-title">
            <div class="task-timeline__toolbar">
              <h3 id="task-timeline-title">任务时间线</h3>
              <label class="task-timeline__search">
                <Search :size="14" aria-hidden="true" />
                <span class="sr-only">搜索当前班级任务</span>
                <input v-model="taskQuery" type="search" autocomplete="off" placeholder="搜索任务" aria-label="搜索当前班级任务" />
              </label>
            </div>

            <div ref="taskFilterRoot" class="task-filters" :class="'task-filters--' + taskFilter" role="group" aria-label="筛选任务">
              <span class="task-filters__selection" :style="taskFilterSelectionStyle" aria-hidden="true"></span>
              <button ref="allFilterButton" type="button" :aria-pressed="taskFilter === 'all'" @click="taskFilter = 'all'">全部</button>
              <button ref="soonFilterButton" type="button" :aria-pressed="taskFilter === 'soon'" @click="taskFilter = 'soon'">临近截止</button>
              <button ref="lowFilterButton" type="button" :aria-pressed="taskFilter === 'low'" @click="taskFilter = 'low'">完成率偏低</button>
            </div>
            <p v-if="taskFilter === 'soon'" class="task-filter-hint">按未来 72 小时内到期筛选</p>
            <p v-else-if="taskFilter === 'low'" class="task-filter-hint">
              按低于本班整体完成率筛选{{ classMetrics.completionRate === null ? '' : '（' + classMetrics.completionRate + '%）' }}
            </p>

            <div v-if="visibleTaskRows.length" class="task-timeline__list" aria-label="授权任务列表">
              <button
                v-for="task in visibleTaskRows"
                :key="task.task_ref"
                type="button"
                class="task-timeline-item"
                :class="{ 'task-timeline-item--selected': task.task_ref === selectedTaskRef }"
                :aria-pressed="task.task_ref === selectedTaskRef"
                :aria-label="taskAccessibleLabel(task)"
                @click="selectTask(task.task_ref)"
              >
                <span class="task-timeline-item__marker" aria-hidden="true"></span>
                <span class="task-timeline-item__content">
                  <strong class="task-timeline-item__name">{{ teacherTaskDisplayLabel(task) }}</strong>
                  <span class="task-timeline-item__meta">
                    <span>{{ formatShortDeadline(task.due_at) }}</span>
                    <span>{{ taskProgressCount(task, 'completed_count') }} / {{ taskProgressCount(task, 'active_enrollment_count') }} 已完成</span>
                    <span class="task-phase" :class="taskUrgencyClass(task)">{{ taskUrgencyLabel(task) }}</span>
                  </span>
                </span>
                <strong class="task-timeline-item__rate">{{ taskRate(task) === null ? '—' : taskRate(task) + '%' }}</strong>
              </button>
            </div>
            <div v-else class="task-timeline__empty" role="status">
              {{ classTasks.length ? '没有符合当前筛选条件的任务' : '当前班级暂无已发布任务汇总' }}
            </div>
          </section>

          <section class="task-detail" aria-labelledby="task-detail-title" aria-live="polite">
            <template v-if="selectedTask && selectedTaskCounts">
              <header class="task-detail__header">
                <div>
                  <span class="task-detail__eyebrow">任务汇总</span>
                  <h3 id="task-detail-title">{{ teacherTaskDisplayLabel(selectedTask) }}</h3>
                </div>
                <span class="task-phase" :class="phaseClass(selectedTask)">{{ teacherTaskPhaseLabel(teacherTaskPhase(selectedTask)) }}</span>
              </header>

              <div class="task-detail__completion">
                <div><strong>{{ taskRate(selectedTask) === null ? '—' : taskRate(selectedTask) + '%' }}</strong><span>任务完成率</span></div>
                <div
                  v-if="taskRate(selectedTask) !== null"
                  class="task-detail__track"
                  role="progressbar"
                  :aria-valuenow="taskRate(selectedTask) ?? 0"
                  aria-valuemin="0"
                  aria-valuemax="100"
                  :aria-label="teacherTaskDisplayLabel(selectedTask) + '完成率'"
                ><span :style="{ width: (taskRate(selectedTask) ?? 0) + '%' }"></span></div>
              </div>

              <dl class="task-detail__facts">
                <div><dt>所属班级</dt><dd>{{ teacherClassDisplayLabel(selectedClassRef, rows) }}</dd></div>
                <div><dt>开放时间</dt><dd>{{ formatTeacherDate(selectedTask.opens_at, '未设置开放时间') }}</dd></div>
                <div><dt>截止时间</dt><dd>{{ formatTeacherDate(selectedTask.due_at, '未设置截止时间') }}</dd></div>
                <div><dt>任务状态</dt><dd>{{ teacherTaskStatusLabel(selectedTask.task_status) }}</dd></div>
              </dl>

              <section class="task-detail__distribution" aria-label="报名状态构成">
                <header class="task-detail__distribution-header">
                  <h4>有效报名状态</h4>
                  <span><strong>{{ selectedTaskCounts.active }}</strong> 人次</span>
                </header>
                <div class="task-detail__distribution-bar" role="img" :aria-label="selectedTaskStatusDescription">
                  <span
                    v-for="status in selectedTaskStatusSegments"
                    :key="status.key"
                    :style="{ width: status.percentage + '%', backgroundColor: status.color }"
                  ></span>
                </div>
                <dl class="task-detail__distribution-items">
                  <div v-for="status in selectedTaskStatusSegments" :key="status.key">
                    <dt><i :style="{ backgroundColor: status.color }"></i>{{ status.label }}</dt>
                    <dd><strong>{{ status.count }}</strong><span>{{ status.percentageLabel }}</span></dd>
                  </div>
                </dl>
                <p v-if="selectedTaskStatusMismatch" class="task-detail__distribution-note" role="note">
                  状态人数与有效报名不一致，以上数据按接口返回值展示
                </p>
                <div class="task-detail__revoked">
                  <span>已撤销报名</span>
                  <strong>{{ selectedTaskCounts.revoked }}<small>人次</small></strong>
                </div>
              </section>
            </template>
            <div v-else class="task-detail__empty" role="status">
              <span class="class-section-heading__icon class-section-heading__icon--teal"><Activity :size="17" aria-hidden="true" /></span>
              <h3 id="task-detail-title">没有匹配的任务</h3>
              <p>调整筛选条件后，可查看当前班级任务汇总</p>
            </div>
          </section>
        </div>
      </AppCard>

    </template>
  </main>
</template>

<style scoped>
.teacher-class-workspace { display: grid; gap: 12px; padding-top: 0; padding-bottom: 35px; }
.class-workspace-header { position: relative; z-index: 2; display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 18px; padding: 4px 2px 0; }
.class-workspace-header :deep(.workspace-breadcrumb) { align-self: flex-start; margin: -4px 0 0; }
.class-workspace-filter { flex: 0 0 156px; }
.class-workspace-filter :deep(.teacher-class-select__trigger) { min-width: 0; height: 32px; }
.class-workspace-filter :deep(.teacher-class-select__menu) { min-width: 100%; }
.class-workspace-state { display: grid; min-height: 190px; place-items: center; padding: 24px; border: 1px solid var(--color-border); border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface); font-size: 13px; text-align: center; }
.class-workspace-error { margin: 0; }

.class-summary-band { display: flex; min-width: 0; align-items: stretch; gap: 22px; padding: 18px 24px; }
.class-summary-band__details { display: grid; min-width: 0; flex: 1 1 auto; grid-template-columns: minmax(145px, .9fr) minmax(0, 3fr); align-items: stretch; }
.class-summary-band__identity { display: grid; min-width: 0; align-content: center; padding-right: 20px; }
.class-summary-band__eyebrow { color: var(--color-text-muted); font-size: 12px; }
.class-summary-band__identity h2 { overflow: hidden; margin: 5px 0 0; color: var(--color-text-primary); font-size: 22px; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; }
.class-summary-metrics { display: grid; min-width: 0; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: stretch; margin: 0; }
.class-summary-metrics > div { display: grid; align-content: center; min-width: 0; padding: 0 16px; border-left: 1px solid var(--color-border); }
.class-summary-metrics dt { margin-bottom: 6px; color: var(--color-text-muted); font-size: 13px; line-height: 1.4; }
.class-summary-metrics dd { margin: 0; color: var(--color-text-primary); font-size: 18px; font-weight: 650; font-variant-numeric: tabular-nums; }
.class-summary-metrics dd span { color: var(--color-text-muted); font-size: 12px; font-weight: 400; }
.class-summary-rate { display: grid; flex: 0 0 auto; align-content: center; justify-items: end; gap: 3px; min-width: 102px; padding-left: 20px; border-left: 1px solid var(--color-border); }
.class-summary-rate strong { color: var(--color-primary-active); font-size: 36px; font-variant-numeric: tabular-nums; line-height: 1.1; }
.class-summary-rate span { color: var(--color-text-muted); font-size: 13px; }

.class-analysis-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: stretch; gap: 14px; }
.class-analysis-card { display: grid; min-width: 0; min-height: 366px; align-content: start; gap: 11px; padding: 18px 20px 14px; }
.class-section-heading { display: flex; min-width: 0; align-items: center; gap: 11px; }
.class-section-heading__icon { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border-radius: 11px; }
.class-section-heading__icon--blue { color: #117e9b; background: #e8f6f9; }
.class-section-heading__icon--teal { color: #0f766e; background: #eaf6f3; }
.class-section-heading__icon--amber { color: #9a6a1b; background: #f7f2e8; }
.class-section-heading h2 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 15px; line-height: 1.35; }
.class-section-heading p { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.45; }
.class-analysis-card :deep(.teacher-chart__summary) { min-height: 17px; font-size: 10px; }
.class-chart-legend { display: flex; min-height: 20px; flex-wrap: wrap; align-content: center; align-items: center; justify-content: center; gap: 5px 14px; margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.4; }
.class-chart-legend__item { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.class-chart-legend__swatch { display: inline-block; width: 10px; height: 10px; flex: 0 0 10px; border-radius: 2px; }
.class-chart-legend__swatch--dot { width: 8px; height: 8px; flex-basis: 8px; border-radius: 50%; }
.class-chart-legend__swatch--soon { background: #e1a76b; }
.class-chart-legend__swatch--general { background: #8bd7e8; }
.class-chart-legend__note { color: #7d8d99; white-space: nowrap; }
.class-chart-note { margin: 0; color: #966e3a; font-size: 11px; line-height: 1.45; }
.class-chart-empty { display: grid; min-height: 286px; margin: 0; place-items: center; padding: 22px; color: var(--color-text-muted); font-size: 12px; line-height: 1.6; text-align: center; }

.task-workbench { min-width: 0; padding: 18px 20px 16px; }
.task-workbench__header { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 14px; padding-bottom: 13px; border-bottom: 1px solid var(--color-border); }
.task-workbench .class-section-heading h2 { font-size: 17px; }
.task-workbench .class-section-heading p { font-size: 13px; }
.task-workbench__count { color: var(--color-text-muted); font-size: 13px; white-space: nowrap; }
.task-workbench__body { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.task-timeline { min-width: 0; padding: 15px 18px 3px 0; }
.task-timeline__toolbar { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12px; }
.task-timeline__toolbar h3 { margin: 0; color: var(--color-text-primary); font-size: 15px; }
.task-timeline__search { display: flex; width: min(210px, 52%); min-height: 36px; align-items: center; gap: 7px; padding: 0 10px; border: 1px solid #dfe7eb; border-radius: 9px; color: var(--color-text-muted); background: #fff; transition: border-color 140ms ease, box-shadow 140ms ease; }
.task-timeline__search input { width: 100%; min-width: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 13px; }
.task-timeline__search input::placeholder { color: var(--color-text-muted); }
.task-timeline__search:focus-within { border-color: #72bfd0; box-shadow: 0 0 0 3px rgb(0 177 226 / 12%); }
.task-timeline__search input:focus-visible { outline: none; }
.task-filters { position: relative; display: flex; width: max-content; max-width: 100%; gap: 0; margin-top: 12px; padding: 4px; border-radius: 10px; background: #f1f5f6; }
.task-filters__selection { position: absolute; top: 4px; bottom: 4px; left: 4px; width: 0; border-radius: 7px; background: #fff; box-shadow: 0 1px 3px rgb(31 63 78 / 14%); transition: transform 200ms cubic-bezier(.2,.75,.25,1), width 200ms cubic-bezier(.2,.75,.25,1); }
.task-filters button { position: relative; z-index: 1; display: inline-flex; min-width: 0; min-height: 30px; flex: 0 0 auto; align-items: center; justify-content: center; padding: 0 10px; border: 0; border-radius: 7px; color: var(--color-text-secondary); background: transparent; font: inherit; font-size: 11px; font-weight: 650; white-space: nowrap; cursor: pointer; }
.task-filters button[aria-pressed='true'] { color: #087d9b; font-weight: 700; }
.task-filters button:focus-visible { outline: 2px solid #279de0; outline-offset: 1px; }
.task-filter-hint { margin: 7px 0 0; color: var(--color-text-muted); font-size: 12px; line-height: 1.45; }
.task-timeline__list { display: grid; margin-top: 11px; padding: 1px 6px 1px 0; }
.task-timeline-item { position: relative; display: grid; min-width: 0; grid-template-columns: 14px minmax(0, 1fr) auto; align-items: center; gap: 11px; padding: 10px 10px 10px 3px; border: 0; border-radius: 9px; color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.task-timeline-item::before { position: absolute; top: 0; bottom: 0; left: 9px; width: 1px; background: #e5edef; content: ''; }
.task-timeline-item:first-child::before { top: 50%; }
.task-timeline-item:last-child::before { bottom: 50%; }
.task-timeline-item:hover { background: #f8fbfc; }
.task-timeline-item:focus-visible { outline: 2px solid #279de0; outline-offset: 1px; }
.task-timeline-item--selected { background: #eef8fa; }
.task-timeline-item__marker { z-index: 1; display: grid; width: 14px; height: 14px; margin: 0; place-items: center; border: 1px dashed #93d2e0; border-radius: 50%; background: #eff9fb; }
.task-timeline-item__marker::after { width: 6px; height: 6px; border-radius: 50%; background: #6db9c9; content: ''; }
.task-timeline-item--selected .task-timeline-item__marker { border-color: #83cbdc; background: #e6f6fa; box-shadow: 0 0 0 2px #e3f4f8; }
.task-timeline-item--selected .task-timeline-item__marker::after { width: 7px; height: 7px; background: var(--color-primary); }
.task-timeline-item__content { display: grid; min-width: 0; gap: 4px; }
.task-timeline-item__name { overflow: hidden; color: var(--color-text-primary); font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.task-timeline-item__rate { color: var(--color-primary-active); font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.task-phase { display: inline-flex; flex: 0 0 auto; align-items: center; padding: 3px 7px; border-radius: 999px; color: #19727d; background: #e8f6f3; font-size: 12px; font-weight: 650; white-space: nowrap; }
.task-phase--upcoming { color: #5f7090; background: #f0f1f8; }
.task-phase--urgent { color: #9a6a1b; background: #f7f2e8; }
.task-phase--ended { color: #65727a; background: #eef1f2; }
.task-phase--cancelled,.task-phase--unpublished { color: #876b49; background: #f6f0e8; }
.task-timeline-item__meta { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 5px 10px; color: var(--color-text-muted); font-size: 12px; line-height: 1.5; }
.task-timeline-item__meta > span { white-space: nowrap; }
.task-timeline__empty { display: grid; min-height: 180px; place-items: center; padding: 18px; color: var(--color-text-muted); font-size: 14px; text-align: center; }

.task-detail { min-width: 0; min-height: 300px; padding: 16px 4px 4px 20px; border-left: 1px solid var(--color-border); }
.task-detail__header { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 12px; }
.task-detail__eyebrow { color: var(--color-primary-active); font-size: 16px; font-weight: 650; }
.task-detail__header h3 { margin: 4px 0 0; color: var(--color-text-primary); font-size: 18px; line-height: 1.35; overflow-wrap: anywhere; }
.task-detail__completion { display: grid; gap: 9px; margin: 13px 0 12px; }
.task-detail__completion > div:first-child { display: flex; align-items: baseline; gap: 9px; }
.task-detail__completion strong { color: var(--color-primary-active); font-size: 29px; font-variant-numeric: tabular-nums; line-height: 1; }
.task-detail__completion span { color: var(--color-text-muted); font-size: 13px; }
.task-detail__track { height: 7px; overflow: hidden; border-radius: 999px; background: #e4edef; }
.task-detail__track > span { display: block; height: 100%; border-radius: inherit; background: #1e9caa; transition: width 180ms ease; }
.task-detail__facts { display: grid; margin: 0; }
.task-detail__facts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 14px; padding: 12px 0; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
.task-detail__facts dt { color: var(--color-text-muted); font-size: 12px; line-height: 1.45; }
.task-detail__facts dd { margin: 3px 0 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }
.task-detail__distribution { display: grid; gap: 9px; padding-top: 12px; }
.task-detail__distribution-header { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.task-detail__distribution-header h4 { margin: 0; color: var(--color-text-secondary); font-size: 13px; font-weight: 650; }
.task-detail__distribution-header > span { color: var(--color-text-muted); font-size: 12px; }
.task-detail__distribution-header > span strong { color: var(--color-primary-active); font-size: 15px; font-variant-numeric: tabular-nums; }
.task-detail__distribution-bar { display: flex; width: 100%; height: 9px; overflow: hidden; border-radius: 999px; background: #edf2f4; }
.task-detail__distribution-bar > span { display: block; height: 100%; min-width: 0; flex: 0 0 auto; }
.task-detail__distribution-items { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 0; }
.task-detail__distribution-items > div { display: grid; gap: 5px; min-width: 0; padding: 8px 10px; border: 1px solid #edf1f3; border-radius: 8px; background: #fbfcfd; }
.task-detail__distribution-items dt { display: flex; min-width: 0; align-items: center; gap: 6px; overflow: hidden; color: var(--color-text-muted); font-size: 11px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.task-detail__distribution-items dt i { display: block; width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; }
.task-detail__distribution-items dd { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 0; }
.task-detail__distribution-items dd strong { color: var(--color-text-primary); font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.task-detail__distribution-items dd span { color: #81919d; font-size: 11px; font-variant-numeric: tabular-nums; }
.task-detail__distribution-note { margin: 0; color: #966e3a; font-size: 11px; line-height: 1.45; }
.task-detail__revoked { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 30px; padding-top: 6px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 12px; }
.task-detail__revoked strong { color: var(--color-text-secondary); font-size: 13px; font-weight: 650; font-variant-numeric: tabular-nums; }
.task-detail__revoked small { margin-left: 4px; color: var(--color-text-muted); font-size: 11px; font-weight: 400; }
.task-detail__empty { display: grid; min-height: 260px; align-content: center; justify-items: center; gap: 9px; padding: 20px; text-align: center; }
.task-detail__empty h3 { margin: 2px 0 0; color: var(--color-text-primary); font-size: 16px; }
.task-detail__empty p { max-width: 260px; margin: 0; color: var(--color-text-muted); font-size: 13px; line-height: 1.5; }

@media (max-width: 1040px) {
  .class-summary-band { gap: 16px; padding-right: 18px; padding-left: 18px; }
  .class-summary-band__details { grid-template-columns: minmax(125px, .8fr) minmax(0, 3fr); }
  .class-summary-metrics > div { padding-right: 10px; padding-left: 10px; }
}

@media (max-width: 860px) {
  .class-analysis-grid { grid-template-columns: minmax(0, 1fr); }
  .class-analysis-card { min-height: 354px; }
  .task-workbench__body { grid-template-columns: minmax(0, 1fr); }
  .task-timeline { padding-right: 0; }
  .task-detail { min-height: 0; margin-top: 10px; padding: 19px 0 3px; border-top: 1px solid var(--color-border); border-left: 0; }
  .task-detail__empty { min-height: 180px; }
}

@media (max-width: 600px) {
  .teacher-class-workspace { gap: 12px; padding-bottom: 35px; }
  .class-workspace-header { align-items: stretch; flex-direction: column; gap: 10px; }
  .class-workspace-filter { width: 100%; flex-basis: auto; }
  .class-summary-band { align-items: stretch; flex-direction: column; gap: 13px; padding: 16px; }
  .class-summary-band__details { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .class-summary-band__identity { min-width: 0; padding: 0 0 10px; border-bottom: 1px solid var(--color-border); }
  .class-summary-metrics { width: 100%; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .class-summary-metrics > div { min-width: 0; padding: 0 8px; }
  .class-summary-metrics > div:first-child { padding-left: 0; border-left: 0; }
  .class-summary-metrics dt { font-size: 12px; }
  .class-summary-metrics dd { font-size: 16px; }
  .class-summary-metrics dd span { display: block; margin-top: 1px; }
  .class-summary-rate { justify-items: start; align-self: stretch; min-width: 0; padding: 10px 0 0; border-top: 1px solid var(--color-border); border-left: 0; }
  .class-summary-rate strong { font-size: 32px; }
  .class-analysis-card { min-height: 330px; padding: 16px 13px 12px; }
  .class-analysis-card :deep(.teacher-chart__canvas) { min-height: 230px; }
  .task-workbench { padding: 16px 13px 14px; }
  .task-workbench__header { align-items: flex-start; }
  .task-workbench__count { padding-top: 5px; font-size: 12px; }
  .task-timeline { padding-top: 15px; }
  .task-timeline__toolbar { align-items: flex-start; flex-direction: column; }
  .task-timeline__search { width: 100%; }
  .task-timeline-item { grid-template-columns: 14px minmax(0, 1fr) auto; gap: 8px; padding-right: 5px; }
  .task-timeline-item__meta { gap: 4px 8px; }
  .task-detail__facts { gap: 10px 9px; }
  .class-chart-legend { gap: 5px 12px; font-size: 10px; }
}

@media (prefers-reduced-motion: reduce) {
  .task-detail__track > span,.task-filters__selection { transition: none; }
}
</style>
