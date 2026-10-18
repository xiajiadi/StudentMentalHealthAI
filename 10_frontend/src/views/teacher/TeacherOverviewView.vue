<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts/core'
import { Activity, ArrowRight, CalendarDays, ChartColumn, ChartPie, ClipboardList, RotateCcw, UsersRound } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import TeacherClassSelect from '@/components/teacher/TeacherClassSelect.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import type { TeacherOverviewProgressRow } from '@/utils/teacher-task-progress'
import {
  shortTeacherRef,
  taskActionablePendingCount,
  taskProgressCount,
  teacherChartColors,
  teacherEnrollmentStatusBreakdown,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
} from '@/utils/teacher-task-progress'

type DataMode = 'demo' | 'real'
type DashboardState = 'loading' | 'ready' | 'error'

const isDevelopment = import.meta.env.DEV
const dataMode = ref<DataMode>(isDevelopment ? 'demo' : 'real')
const selectedClass = ref('all')
const demoRows = ref<TeacherOverviewProgressRow[]>([])
const demoState = ref<DashboardState>(isDevelopment ? 'loading' : 'ready')
const demoError = ref('')
const demoSeed = ref(0)
let demoGeneration = 0

const {
  state: realState,
  rows: realRows,
  errorMessage: realError,
  refresh: refreshReal,
} = useTeacherTaskProgress({ autoLoad: !isDevelopment })

const loadDemoRows = async (seed: number) => {
  if (!isDevelopment) return
  const generation = ++demoGeneration
  demoState.value = 'loading'
  demoError.value = ''
  try {
    const { createTeacherOverviewDemoRows } = await import('@/data/teacher-overview-demo-data')
    if (generation !== demoGeneration) return
    demoRows.value = createTeacherOverviewDemoRows(seed)
    demoState.value = 'ready'
  } catch {
    if (generation !== demoGeneration) return
    demoError.value = '无法载入本地示意数据。'
    demoState.value = 'error'
  }
}

onMounted(() => {
  if (isDevelopment) void loadDemoRows(demoSeed.value)
})

const sourceRows = computed<TeacherOverviewProgressRow[]>(() => dataMode.value === 'demo'
  ? demoRows.value
  : realRows.value)
const pageState = computed<DashboardState>(() => dataMode.value === 'demo' ? demoState.value : realState.value)
const pageError = computed(() => dataMode.value === 'demo' ? demoError.value : realError.value)

const classOptions = computed(() => {
  const labels = new Map<string, string>()
  for (const row of sourceRows.value) {
    labels.set(row.class_ref, row.class_label ?? `班级 ${shortTeacherRef(row.class_ref)}`)
  }
  return [...labels.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})
const classFilterOptions = computed(() => [{ value: 'all', label: '全部班级' }, ...classOptions.value])

watch(dataMode, (mode) => {
  selectedClass.value = 'all'
  if (mode === 'real') void refreshReal()
  else if (demoState.value !== 'ready') void loadDemoRows(demoSeed.value)
})
watch(classOptions, (options) => {
  if (selectedClass.value !== 'all' && !options.some((option) => option.value === selectedClass.value)) {
    selectedClass.value = 'all'
  }
})

const rows = computed(() => sourceRows.value.filter((row) => selectedClass.value === 'all' || row.class_ref === selectedClass.value))
const classLabel = (classRef: string) => rows.value.find((row) => row.class_ref === classRef)?.class_label ?? `班级 ${shortTeacherRef(classRef)}`
const taskLabel = (row: TeacherOverviewProgressRow) => row.task_label ?? `任务 ${shortTeacherRef(row.task_ref)}`
const matrixTaskLabel = (row: TeacherOverviewProgressRow) => row.task_group ?? row.task_label ?? `任务 ${shortTeacherRef(row.task_ref)}`
const formatPercent = (value: number | null) => value === null ? '—' : `${value.toFixed(1)}%`
const percent = (completed: number, total: number) => total > 0 ? Math.round(completed / total * 1000) / 10 : null
const formatDay = (value: string | null) => {
  if (!value) return '未设置'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间待确认'
  return `${date.getMonth() + 1}/${date.getDate()}`
}
const dateKey = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const dateLabel = (key: string) => {
  const [, month, day] = key.split('-')
  return `${Number(month)}/${Number(day)}`
}

const activeEnrollmentCount = computed(() => rows.value.reduce((sum, row) => sum + taskProgressCount(row, 'active_enrollment_count'), 0))
const completedCount = computed(() => rows.value.reduce((sum, row) => sum + taskProgressCount(row, 'completed_count'), 0))
const overallCompletionRate = computed(() => percent(completedCount.value, activeEnrollmentCount.value))
const currentTaskRows = computed(() => rows.value.filter((row) => ['in_progress', 'upcoming'].includes(teacherTaskPhase(row))))
const currentTaskCount = computed(() => new Set(currentTaskRows.value
  .filter((row) => teacherTaskPhase(row) === 'in_progress')
  .map((row) => row.task_ref)).size)
const pendingEnrollmentCount = computed(() => currentTaskRows.value.reduce((sum, row) => sum + taskActionablePendingCount(row), 0))

const classStats = computed(() => {
  const grouped = new Map<string, { active: number; completed: number }>()
  for (const row of rows.value) {
    const current = grouped.get(row.class_ref) ?? { active: 0, completed: 0 }
    current.active += taskProgressCount(row, 'active_enrollment_count')
    current.completed += taskProgressCount(row, 'completed_count')
    grouped.set(row.class_ref, current)
  }
  return [...grouped.entries()]
    .map(([classRef, counts]) => ({ ...counts, classRef, label: classLabel(classRef), rate: percent(counts.completed, counts.active) }))
    .filter((item) => item.rate !== null)
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})

const statusBreakdown = computed(() => teacherEnrollmentStatusBreakdown(rows.value))
const statusRingItems = computed(() => statusBreakdown.value.filter((item) => item.key !== 'revoked' && item.value > 0))
const revokedEnrollmentCount = computed(() => statusBreakdown.value.find((item) => item.key === 'revoked')?.value ?? 0)
const statusCountTotal = computed(() => statusBreakdown.value.reduce((sum, item) => sum + (item.key === 'revoked' ? 0 : item.value), 0))
const statusCountsMatch = computed(() => statusCountTotal.value === activeEnrollmentCount.value)

const classCompletionOption = computed<EChartsOption>(() => ({
  color: [teacherChartColors.sky],
  animation: false,
  grid: { left: 36, right: 18, top: 34, bottom: classStats.value.length > 6 ? 54 : 38, containLabel: true },
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
    formatter: (params) => {
      const point = Array.isArray(params) ? params[0] : params
      const item = classStats.value.find((entry) => entry.label === String(point?.axisValue))
      return item ? `${item.label}<br/>完成率：${formatPercent(item.rate)}<br/>已完成：${item.completed} / ${item.active} 人次` : ''
    },
  },
  xAxis: {
    type: 'category',
    data: classStats.value.map((item) => item.label),
    axisTick: { show: false },
    axisLine: { lineStyle: { color: '#e2e8ee' } },
    axisLabel: { color: '#8793a1', fontSize: 10, interval: 0, rotate: classStats.value.length > 6 ? 24 : 0 },
  },
  yAxis: {
    type: 'value', min: 0, max: 100, interval: 25,
    axisLabel: { color: '#8793a1', fontSize: 10, formatter: '{value}' },
    splitLine: { lineStyle: { color: '#edf1f5', type: 'solid' } },
  },
  series: [{
    name: '完成率', type: 'bar', data: classStats.value.map((item) => item.rate), barMaxWidth: 42,
    itemStyle: { color: '#39b0c7', borderRadius: [5, 5, 0, 0] },
    label: { show: true, position: 'top', color: '#477f91', fontSize: 10, fontWeight: 700, formatter: (params) => `${Number(params.value).toFixed(1)}%` },
    emphasis: { focus: 'series', itemStyle: { color: '#16a5bf' } },
  }],
}))

const statusOption = computed<EChartsOption>(() => ({
  color: ['#08a9c7', '#80cbbb', '#d7e6ed', '#aab8c2'],
  animation: false,
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 人次（{d}%）' },
  legend: {
    orient: 'vertical', right: 2, top: 'middle', itemWidth: 8, itemHeight: 8, itemGap: 13,
    textStyle: { color: '#6f8191', fontSize: 10 },
    formatter: (name) => {
      const item = statusRingItems.value.find((entry) => entry.label === name)
      return item ? `${name}    ${item.value}` : name
    },
  },
  series: [{
    name: '报名状态', type: 'pie', radius: ['54%', '75%'], center: ['31%', '50%'],
    avoidLabelOverlap: true, minAngle: 3,
    label: {
      show: activeEnrollmentCount.value > 0, position: 'center',
      formatter: `${activeEnrollmentCount.value}\n有效报名人次`,
      color: '#8c9aa7', fontSize: 12, lineHeight: 21, fontWeight: 600,
    },
    emphasis: { scale: true, scaleSize: 5, label: { show: true, fontSize: 14, fontWeight: 700 } },
    data: statusRingItems.value.map((item) => ({ name: item.label, value: item.value })),
  }],
}))

const heatmapCells = computed(() => {
  const classLabels = [...new Set(rows.value.map((row) => row.class_ref))].sort((a, b) => classLabel(a).localeCompare(classLabel(b), 'zh-CN'))
  const taskLabels = [...new Set(rows.value.map((row) => matrixTaskLabel(row)))].sort((a, b) => a.localeCompare(b, 'zh-CN'))
  const aggregates = new Map<string, { active: number; completed: number }>()
  for (const row of rows.value) {
    const label = matrixTaskLabel(row)
    const key = JSON.stringify([row.class_ref, label])
    const current = aggregates.get(key) ?? { active: 0, completed: 0 }
    current.active += taskProgressCount(row, 'active_enrollment_count')
    current.completed += taskProgressCount(row, 'completed_count')
    aggregates.set(key, current)
  }
  return {
    classLabels,
    taskLabels,
    data: [...aggregates.entries()].flatMap(([key, counts]) => {
      if (counts.active === 0) return []
      const [classRef, label] = JSON.parse(key) as [string, string]
      return [[taskLabels.indexOf(label), classLabels.indexOf(classRef), percent(counts.completed, counts.active) ?? 0, counts.active, counts.completed]]
    }),
  }
})
const heatmapOption = computed<EChartsOption>(() => ({
  animation: false,
  grid: { left: 78, right: 16, top: 12, bottom: heatmapCells.value.taskLabels.length > 6 ? 50 : 24, containLabel: true },
  tooltip: {
    position: 'top',
    formatter: (params) => {
      const point = Array.isArray(params) ? params[0] : params
      const value = Array.isArray(point?.value) ? point.value : []
      const task = heatmapCells.value.taskLabels[Number(value[0])] ?? '任务'
      const className = heatmapCells.value.classLabels[Number(value[1])] ?? '班级'
      return `${className} · ${task}<br/>完成率：${Number(value[2]).toFixed(1)}%<br/>已完成：${value[4]} / ${value[3]} 人次`
    },
  },
  xAxis: {
    type: 'category', data: heatmapCells.value.taskLabels, splitArea: { show: true },
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#e5ecf0' } },
    axisLabel: { color: '#8793a1', fontSize: 9, interval: 0, rotate: heatmapCells.value.taskLabels.length > 6 ? 24 : 0 },
  },
  yAxis: {
    type: 'category', inverse: true, data: heatmapCells.value.classLabels.map((item) => classLabel(item)), splitArea: { show: true },
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#e5ecf0' } }, axisLabel: { color: '#8793a1', fontSize: 10 },
  },
  visualMap: { min: 0, max: 100, calculable: false, show: false, inRange: { color: ['#e7f5f8', '#a5dce5', '#56bfd0', '#159bb6'] } },
  series: [{
    name: '完成率', type: 'heatmap', data: heatmapCells.value.data,
    label: { show: true, formatter: (params) => `${Number((params.value as number[])[2]).toFixed(0)}%`, color: '#315d6a', fontSize: 9, fontWeight: 700 },
    itemStyle: { borderColor: '#fff', borderWidth: 3, borderRadius: 6 },
    emphasis: { itemStyle: { borderColor: '#078da9', borderWidth: 2, shadowBlur: 7, shadowColor: 'rgb(8 85 105 / 16%)' } },
  }],
}))

const deadlineData = computed(() => {
  const today = new Date()
  const end = today.getTime() + 14 * 24 * 60 * 60 * 1000
  const buckets = new Map<string, { taskCount: number; pendingCount: number; classes: Set<string> }>()
  for (const row of rows.value) {
    if (!row.due_at || !['in_progress', 'upcoming'].includes(teacherTaskPhase(row))) continue
    const due = new Date(row.due_at)
    if (Number.isNaN(due.getTime()) || due.getTime() < today.getTime() || due.getTime() > end) continue
    const key = dateKey(row.due_at)
    const bucket = buckets.get(key) ?? { taskCount: 0, pendingCount: 0, classes: new Set<string>() }
    bucket.taskCount += 1
    bucket.pendingCount += taskActionablePendingCount(row)
    bucket.classes.add(row.class_ref)
    buckets.set(key, bucket)
  }
  return [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, bucket]) => ({ key, label: dateLabel(key), ...bucket }))
})
const deadlineOption = computed<EChartsOption>(() => ({
  animation: false,
  color: ['#b8e0e8', '#00a9c7'],
  grid: { left: 38, right: 40, top: 18, bottom: 36, containLabel: true },
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'cross' },
    formatter: (params) => {
      const items = Array.isArray(params) ? params : [params]
      const index = Number(items[0]?.dataIndex ?? 0)
      const day = deadlineData.value[index]
      return day ? `${day.label}<br/>到期任务：${day.taskCount} 项<br/>待完成人次：${day.pendingCount}<br/>涉及班级：${day.classes.size} 个` : ''
    },
  },
  legend: { top: 0, right: 0, itemWidth: 9, itemHeight: 9, textStyle: { color: '#8a98a6', fontSize: 9 } },
  xAxis: { type: 'category', data: deadlineData.value.map((item) => item.label), boundaryGap: true, axisTick: { show: false }, axisLine: { lineStyle: { color: '#e5ebef' } }, axisLabel: { color: '#8a98a6', fontSize: 9 } },
  yAxis: [
    { type: 'value', name: '任务数', minInterval: 1, nameTextStyle: { color: '#95a2ae', fontSize: 9 }, axisLabel: { color: '#95a2ae', fontSize: 9 }, splitLine: { lineStyle: { color: '#edf1f4' } } },
    { type: 'value', name: '人次', minInterval: 1, nameTextStyle: { color: '#95a2ae', fontSize: 9 }, axisLabel: { color: '#95a2ae', fontSize: 9 }, splitLine: { show: false } },
  ],
  series: [
    { name: '到期任务数（项）', type: 'bar', yAxisIndex: 0, barMaxWidth: 22, data: deadlineData.value.map((item) => item.taskCount), itemStyle: { color: '#b5dfe7', borderRadius: [4, 4, 0, 0] } },
    { name: '待完成人次（人次）', type: 'line', yAxisIndex: 1, data: deadlineData.value.map((item) => item.pendingCount), smooth: false, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2.5, color: '#00a9c7' }, itemStyle: { color: '#00a9c7', borderColor: '#fff', borderWidth: 2 } },
  ],
}))

const attentionRows = computed(() => rows.value
  .filter((row) => ['in_progress', 'upcoming'].includes(teacherTaskPhase(row)) && taskActionablePendingCount(row) > 0)
  .sort((a, b) => {
    const dueA = a.due_at ? Date.parse(a.due_at) : Number.POSITIVE_INFINITY
    const dueB = b.due_at ? Date.parse(b.due_at) : Number.POSITIVE_INFINITY
    return dueA - dueB || taskActionablePendingCount(b) - taskActionablePendingCount(a)
  })
  .slice(0, 6))
const urgencyLabel = (row: TeacherOverviewProgressRow) => {
  const phase = teacherTaskPhase(row)
  if (phase === 'upcoming') return { label: '待开始', tone: 'upcoming' }
  if (!row.due_at) return { label: '进行中', tone: 'active' }
  const untilDue = Date.parse(row.due_at) - Date.now()
  if (untilDue >= 0 && untilDue <= 72 * 60 * 60 * 1000) return { label: '即将截止', tone: 'urgent' }
  return { label: '进行中', tone: 'active' }
}

const pageTitleClassCount = computed(() => new Set(rows.value.map((row) => row.class_ref)).size)
const completionRateText = computed(() => formatPercent(overallCompletionRate.value))
const isStatusEmpty = computed(() => activeEnrollmentCount.value === 0 || statusRingItems.value.length === 0)

const setDataMode = (mode: DataMode) => {
  if (!isDevelopment || dataMode.value === mode) return
  dataMode.value = mode
}
const handleRefresh = () => {
  if (dataMode.value === 'demo') {
    demoSeed.value += 1
    void loadDemoRows(demoSeed.value)
  } else {
    void refreshReal()
  }
}
</script>

<template>
  <main class="content-wrap teacher-overview">
    <header class="overview-page-header">
      <div class="overview-page-heading">
        <h1>班级测评进度与近期任务</h1>
      </div>
      <div class="overview-toolbar" aria-label="数据筛选与刷新">
        <TeacherClassSelect
          v-model="selectedClass"
          class="overview-class-filter"
          :options="classFilterOptions"
          :disabled="pageState !== 'ready' || !classOptions.length"
          :aria-label="dataMode === 'demo' ? '按班级筛选' : '按授权班级筛选'"
        />
        <AppButton variant="secondary" size="sm" :disabled="pageState === 'loading'" @click="handleRefresh">
          <RotateCcw :size="14" aria-hidden="true" />{{ dataMode === 'demo' ? '刷新示意数据' : '刷新' }}
        </AppButton>
        <button v-if="isDevelopment" class="overview-mode-toggle" type="button" @click="setDataMode(dataMode === 'demo' ? 'real' : 'demo')">
          {{ dataMode === 'demo' ? '查看实际汇总' : '查看示意数据' }}
        </button>
      </div>
    </header>

    <div v-if="pageState === 'loading'" class="overview-state" role="status" aria-live="polite" aria-busy="true">正在载入授权任务数据…</div>
    <div v-else-if="pageState === 'error'" class="overview-state overview-state--error" role="alert">
      <div><strong>暂时无法载入工作概览</strong><p>{{ pageError }}</p></div>
      <div class="overview-state__actions">
        <AppButton variant="secondary" size="sm" @click="handleRefresh">重新读取</AppButton>
        <button v-if="isDevelopment && dataMode === 'real'" class="overview-mode-toggle" type="button" @click="setDataMode('demo')">切到示意数据</button>
      </div>
    </div>
    <section v-else-if="!rows.length" class="overview-empty-state" role="status">
      <span class="overview-empty-state__icon"><ChartColumn :size="21" aria-hidden="true" /></span>
      <h2>暂无可展示的班级任务进度</h2>
      <p>有授权的班级任务后，完成率、状态分布和截止安排会显示在这里。</p>
      <button v-if="isDevelopment && dataMode === 'real'" class="overview-mode-toggle" type="button" @click="setDataMode('demo')">查看示意数据</button>
    </section>
    <section v-else class="overview-board" aria-label="班级测评进度数据看板">
      <section class="overview-kpis" aria-label="关键指标">
        <AppCard class="overview-kpi">
          <span class="overview-kpi__label"><UsersRound :size="15" aria-hidden="true" />{{ dataMode === 'demo' ? '负责班级' : '有任务班级' }}</span>
          <strong>{{ pageTitleClassCount }}</strong>
          <small>{{ dataMode === 'demo' ? '本地示意授权范围' : '当前汇总中出现的授权班级' }}</small>
        </AppCard>
        <AppCard class="overview-kpi">
          <span class="overview-kpi__label"><ClipboardList :size="15" aria-hidden="true" />进行中任务</span>
          <strong>{{ currentTaskCount }}</strong>
          <small>已开放且未超过截止时间</small>
        </AppCard>
        <AppCard class="overview-kpi overview-kpi--accent">
          <span class="overview-kpi__label"><Activity :size="15" aria-hidden="true" />测评完成率</span>
          <strong>{{ completionRateText }}</strong>
          <small>{{ completedCount }} / {{ activeEnrollmentCount }} 有效报名人次</small>
        </AppCard>
        <AppCard class="overview-kpi">
          <span class="overview-kpi__label"><CalendarDays :size="15" aria-hidden="true" />待完成人次</span>
          <strong>{{ pendingEnrollmentCount }}</strong>
          <small>未开始、准备中及进行中；不含已结束与撤销</small>
        </AppCard>
      </section>

      <section class="overview-chart-grid" aria-label="完成进度与状态图表">
        <AppCard class="overview-chart-card">
          <header class="overview-chart-card__header">
            <span class="overview-chart-card__icon"><ChartColumn :size="16" aria-hidden="true" /></span>
            <div><h2>班级完成率对比</h2><p>不同授权班级的测评任务完成情况</p></div>
            <span class="overview-chart-card__type">竖向柱状图</span>
          </header>
          <TeacherProgressChart v-if="classStats.length" :option="classCompletionOption" label="授权班级测评完成率竖向柱状图" :height="282" />
          <div v-else class="overview-chart-empty">当前范围内没有有效报名人次。</div>
        </AppCard>

        <AppCard class="overview-chart-card">
          <header class="overview-chart-card__header">
            <span class="overview-chart-card__icon overview-chart-card__icon--teal"><ChartPie :size="16" aria-hidden="true" /></span>
            <div><h2>测评状态分布</h2><p>当前有效报名人次构成</p></div>
            <span class="overview-chart-card__type">环形图</span>
          </header>
          <TeacherProgressChart v-if="!isStatusEmpty" :option="statusOption" label="有效报名人次的测评状态环形图" :height="282" :summary="`已撤销报名 ${revokedEnrollmentCount} 人次另行统计。${statusCountsMatch ? '' : '状态明细与有效报名总数存在差异。'}`" />
          <div v-else class="overview-chart-empty">当前没有有效报名状态可供分布。</div>
        </AppCard>

        <AppCard class="overview-chart-card">
          <header class="overview-chart-card__header">
            <span class="overview-chart-card__icon overview-chart-card__icon--teal"><ChartColumn :size="16" aria-hidden="true" /></span>
            <div><h2>班级 × 测评任务</h2><p>颜色越深表示该班级任务完成率越高</p></div>
            <span class="overview-chart-card__type">热力矩阵</span>
          </header>
          <TeacherProgressChart v-if="heatmapCells.data.length" :option="heatmapOption" label="授权班级与测评任务完成率热力矩阵" :height="Math.max(270, heatmapCells.classLabels.length * 42 + 54)" />
          <div v-else class="overview-chart-empty">当前没有可以比较的班级任务组合。</div>
        </AppCard>

        <AppCard class="overview-chart-card">
          <header class="overview-chart-card__header">
            <span class="overview-chart-card__icon overview-chart-card__icon--amber"><CalendarDays :size="16" aria-hidden="true" /></span>
            <div><h2>近期任务截止压力</h2><p>未来 14 天的到期任务与待完成人次</p></div>
            <span class="overview-chart-card__type">柱线组合图</span>
          </header>
          <TeacherProgressChart v-if="deadlineData.length" :option="deadlineOption" label="未来十四天到期任务数与待完成人次柱线组合图" :height="282" />
          <div v-else class="overview-chart-empty">未来 14 天没有设置截止日期的已发布任务。</div>
        </AppCard>
      </section>

      <AppCard class="overview-task-table-card">
        <header class="overview-task-table-card__header">
          <div><h2>近期需要关注的任务</h2><p>按截止时间排列，优先显示仍有待完成人次的任务</p></div>
          <RouterLink v-if="dataMode === 'real'" class="overview-task-table-card__link" to="/teacher/tasks">任务汇总 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
          <span v-else class="overview-task-table-card__link overview-task-table-card__link--muted">任务汇总 <ArrowRight :size="14" aria-hidden="true" /></span>
        </header>
        <div v-if="attentionRows.length" class="overview-task-table-wrap">
          <table class="overview-task-table">
            <thead><tr><th scope="col">测评任务</th><th scope="col">班级</th><th scope="col">完成率</th><th scope="col">待完成人次</th><th scope="col">截止日期</th><th scope="col">状态</th></tr></thead>
            <tbody>
              <tr v-for="row in attentionRows" :key="`${row.class_ref}:${row.task_ref}`">
                <th scope="row">
                  <RouterLink v-if="dataMode === 'real'" :to="`/teacher/tasks/${encodeURIComponent(row.class_ref)}/${encodeURIComponent(row.task_ref)}`">{{ taskLabel(row) }}</RouterLink>
                  <span v-else>{{ taskLabel(row) }}</span>
                </th>
                <td>{{ classLabel(row.class_ref) }}</td>
                <td class="overview-task-table__number">{{ formatPercent(percent(taskProgressCount(row, 'completed_count'), taskProgressCount(row, 'active_enrollment_count'))) }}</td>
                <td class="overview-task-table__number">{{ taskActionablePendingCount(row) }}</td>
                <td>{{ formatDay(row.due_at) }}</td>
                <td><span class="overview-task-status" :class="`overview-task-status--${urgencyLabel(row).tone}`">{{ urgencyLabel(row).label }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="overview-table-empty">目前没有临近的未完成任务。</div>
      </AppCard>
      <p class="overview-footnote">{{ dataMode === 'demo' ? '此处为前端生成的示意数据，仅用于检查布局与图表；不会调用写入接口或代表真实业务记录。' : '仅显示授权班级与任务汇总，不包含学生个人心理信息。' }}</p>
    </section>
  </main>
</template>

<style scoped>
.teacher-overview { display: grid; gap: 12px; padding-top: 0; padding-bottom: 56px; animation: page-in 220ms ease both; }
.overview-page-header { position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 0 2px 4px; }
.overview-page-heading h1 { margin: 0; color: var(--color-text-secondary); font-size: 13px; font-weight: 600; line-height: 1.4; }
.overview-toolbar { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.overview-class-filter { flex: 0 0 156px; }
.overview-toolbar :deep(button:focus),.overview-toolbar :deep(button:focus-visible) { outline: 2px solid #279de0; outline-offset: 2px; }
.overview-mode-toggle:focus-visible { border-radius: 6px; }
.overview-mode-toggle { min-height: 32px; padding: 0 8px; border: 0; color: var(--color-primary-active); background: transparent; font: inherit; font-size: 10px; font-weight: 650; cursor: pointer; }
.overview-mode-toggle:hover { text-decoration: underline; text-underline-offset: 3px; }
.overview-board { display: grid; gap: 12px; padding: 14px; border: 1px solid #e6edf2; border-radius: 16px; background: #f5f8fb; }
.overview-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.overview-kpi { display: grid; align-content: start; gap: 7px; min-width: 0; min-height: 108px; padding: 15px 16px; border: 1px solid #e7edf2; border-radius: 12px; background: #fff; box-shadow: none; }
.overview-kpi__label { display: flex; align-items: center; gap: 7px; color: #8191a0; font-size: 10px; font-weight: 600; }
.overview-kpi__label svg { color: #83a8b7; }
.overview-kpi strong { color: #344657; font-size: 26px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
.overview-kpi small { color: #a0acb7; font-size: 9px; line-height: 1.45; }
.overview-kpi--accent strong,.overview-kpi--accent .overview-kpi__label svg { color: var(--color-primary); }
.overview-chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px; }
.overview-chart-card { display: grid; align-content: start; gap: 8px; min-width: 0; min-height: 360px; padding: 15px 16px 12px; border: 1px solid #e7edf2; border-radius: 12px; background: #fff; box-shadow: none; }
.overview-chart-card__header { display: flex; align-items: flex-start; gap: 9px; min-width: 0; min-height: 39px; }
.overview-chart-card__icon { display: grid; width: 29px; height: 29px; flex: 0 0 29px; place-items: center; border-radius: 9px; color: var(--color-primary-active); background: #e9f7fa; }
.overview-chart-card__icon--teal { color: #54a997; background: #edf8f5; }
.overview-chart-card__icon--amber { color: #af9c69; background: #f8f5ed; }
.overview-chart-card__header > div { flex: 1; min-width: 0; }
.overview-chart-card__header h2,.overview-task-table-card__header h2 { margin: 0 0 4px; color: #344657; font-size: 13px; font-weight: 700; }
.overview-chart-card__header p,.overview-task-table-card__header p { margin: 0; color: #9aa7b3; font-size: 9px; line-height: 1.45; }
.overview-chart-card__type { padding-top: 3px; color: #a2afba; font-size: 9px; white-space: nowrap; }
.overview-chart-empty,.overview-table-empty { display: grid; min-height: 254px; place-items: center; padding: 20px; color: #98a6b2; font-size: 11px; text-align: center; }
.overview-task-table-card { display: grid; gap: 10px; min-width: 0; padding: 16px; border: 1px solid #e7edf2; border-radius: 12px; background: #fff; box-shadow: none; }
.overview-task-table-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.overview-task-table-card__link { display: inline-flex; align-items: center; gap: 4px; color: var(--color-primary-active); font-size: 10px; font-weight: 650; text-decoration: none; white-space: nowrap; }
.overview-task-table-card__link:hover { text-decoration: underline; }
.overview-task-table-card__link--muted { color: #98a6b2; }
.overview-task-table-wrap { min-width: 0; overflow-x: auto; }
.overview-task-table { width: 100%; border-collapse: collapse; text-align: left; }
.overview-task-table th,.overview-task-table td { padding: 9px 8px; border-top: 1px solid #edf1f4; color: #7d8d9a; font-size: 10px; white-space: nowrap; }
.overview-task-table thead th { color: #98a6b2; font-size: 9px; font-weight: 600; }
.overview-task-table tbody th { font-weight: 600; }
.overview-task-table tbody th a,.overview-task-table tbody th span { color: #536979; text-decoration: none; }
.overview-task-table tbody th a:hover { color: var(--color-primary-active); text-decoration: underline; text-underline-offset: 2px; }
.overview-task-table__number { font-variant-numeric: tabular-nums; }
.overview-task-status { display: inline-flex; align-items: center; min-height: 22px; padding: 0 8px; border-radius: 999px; font-size: 9px; }
.overview-task-status--active { color: #378e9f; background: #edf8fa; }
.overview-task-status--upcoming { color: #6c8794; background: #eff4f6; }
.overview-task-status--urgent { color: #a98243; background: #fbf4e9; }
.overview-table-empty { min-height: 105px; border-top: 1px solid #edf1f4; }
.overview-footnote { margin: 0 3px; color: #98a6b2; font-size: 9px; line-height: 1.5; }
.overview-state { display: flex; align-items: center; justify-content: center; min-height: 155px; padding: 24px; border: 1px solid #e6edf2; border-radius: 14px; color: #718391; background: #fff; font-size: 12px; text-align: center; }
.overview-state--error { justify-content: space-between; gap: 20px; text-align: left; }
.overview-state--error strong { color: var(--color-text-primary); font-size: 13px; }
.overview-state--error p { margin: 5px 0 0; color: #8a98a5; font-size: 11px; }
.overview-state__actions { display: flex; align-items: center; gap: 6px; }
.overview-empty-state { display: grid; justify-items: center; min-height: 290px; padding: 34px 20px; border: 1px solid #e6edf2; border-radius: 14px; background: #fff; text-align: center; }
.overview-empty-state__icon { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 14px; color: var(--color-primary-active); background: #eaf7fa; }
.overview-empty-state h2 { margin: 13px 0 5px; color: #455b6b; font-size: 14px; }
.overview-empty-state p { max-width: 440px; margin: 0; color: #93a0ab; font-size: 11px; line-height: 1.6; }
.overview-empty-state .overview-mode-toggle { margin-top: 8px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 1100px) { .overview-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }.overview-chart-card { min-height: 350px; } }
@media (max-width: 850px) { .overview-page-header { align-items: flex-start; flex-direction: column; }.overview-toolbar { justify-content: flex-start; }.overview-chart-grid { grid-template-columns: minmax(0, 1fr); }.overview-chart-card { min-height: 338px; } }
@media (max-width: 560px) { .overview-page-header { gap: 12px; }.overview-toolbar { width: 100%; gap: 7px; }.overview-class-filter { flex: 1; }.overview-board { gap: 9px; padding: 9px; border-radius: 13px; }.overview-kpis { gap: 8px; }.overview-kpi { min-height: 99px; padding: 12px; }.overview-kpi strong { font-size: 23px; }.overview-kpi small { font-size: 8px; }.overview-chart-card { min-height: 330px; padding: 13px 12px 10px; }.overview-chart-card__type { font-size: 8px; }.overview-task-table-card { padding: 13px 11px; }.overview-task-table { min-width: 650px; }.overview-state--error { align-items: flex-start; flex-direction: column; }.overview-state__actions { flex-wrap: wrap; } }
</style>
