<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChartColumn, ChartPie, ListFilter } from '@lucide/vue'
import type { EChartsOption } from 'echarts/core'
import {
  summarizeTeacherClasses,
  summarizeTeacherProgress,
  taskActionablePendingCount,
  taskProgressCount,
  teacherClassDisplayLabel,
  teacherEnrollmentStatusBreakdown,
  teacherTaskDisplayLabel,
  teacherTaskHeatmapDimension,
} from '@/utils/teacher-task-progress'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import TeacherClassSelect from '@/components/teacher/TeacherClassSelect.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'

type TimeWindow = 'all' | '30' | '90' | '365'

const { state, rows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })
const selectedClass = ref('all')
const selectedTask = ref('all')
const timeWindow = ref<TimeWindow>('all')
const windowOptions: { value: TimeWindow; label: string }[] = [
  { value: 'all', label: '全部时间' },
  { value: '30', label: '近 30 天' },
  { value: '90', label: '近 90 天' },
  { value: '365', label: '近一年' },
]
const keyOf = (classRef: string, taskRef: string) => JSON.stringify([classRef, taskRef])
const taskKey = (row: { class_ref: string; task_ref: string }) => keyOf(row.class_ref, row.task_ref)

const classOptions = computed(() => [...new Set(rows.value.map((row) => row.class_ref))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const classSelectOptions = computed(() => [
  { value: 'all', label: '全部班级' },
  ...classOptions.value.map((classRef) => ({ value: classRef, label: teacherClassDisplayLabel(classRef, rows.value) })),
])
const taskOptions = computed(() => rows.value
  .filter((row) => selectedClass.value === 'all' || row.class_ref === selectedClass.value)
  .sort((a, b) => a.class_ref.localeCompare(b.class_ref, 'zh-CN') || a.task_ref.localeCompare(b.task_ref, 'zh-CN')))
const taskOptionLabel = (row: (typeof rows.value)[number]) => `${teacherClassDisplayLabel(row.class_ref, rows.value)}，${teacherTaskDisplayLabel(row)}`

watch([selectedClass, taskOptions], () => {
  if (selectedTask.value !== 'all' && !taskOptions.value.some((row) => taskKey(row) === selectedTask.value)) selectedTask.value = 'all'
})

const filteredRows = computed(() => {
  const now = Date.now()
  const days = timeWindow.value === 'all' ? null : Number(timeWindow.value)
  const start = days === null ? Number.NEGATIVE_INFINITY : now - days * 24 * 60 * 60 * 1000
  return rows.value.filter((row) => {
    if (selectedClass.value !== 'all' && row.class_ref !== selectedClass.value) return false
    if (selectedTask.value !== 'all' && taskKey(row) !== selectedTask.value) return false
    if (start !== Number.NEGATIVE_INFINITY) {
      const openedAt = Date.parse(row.opens_at)
      if (!Number.isFinite(openedAt) || openedAt < start || openedAt > now) return false
    }
    return true
  })
})

const progressSummary = computed(() => summarizeTeacherProgress(filteredRows.value))
const classSummary = computed(() => summarizeTeacherClasses(filteredRows.value))
const activeTaskRows = computed(() => filteredRows.value.filter((row) => taskProgressCount(row, 'active_enrollment_count') > 0))
const activeClassSummary = computed(() => classSummary.value.filter((item) => item.activeEnrollmentCount > 0))
const taskDimensionSummaries = computed(() => {
  const groups = new Map<string, { label: string; rows: typeof activeTaskRows.value }>()
  for (const row of activeTaskRows.value) {
    const dimension = teacherTaskHeatmapDimension(row)
    const group = groups.get(dimension.key) ?? { label: dimension.label, rows: [] }
    group.rows.push(row)
    groups.set(dimension.key, group)
  }
  return [...groups.entries()].map(([key, group]) => {
    const activeEnrollmentCount = group.rows.reduce((total, row) => total + taskProgressCount(row, 'active_enrollment_count'), 0)
    const completedCount = group.rows.reduce((total, row) => total + taskProgressCount(row, 'completed_count'), 0)
    return {
      key,
      label: group.label,
      completedCount,
      pendingCount: group.rows.reduce((total, row) => total + taskActionablePendingCount(row), 0),
      endedCount: group.rows.reduce((total, row) => total + taskProgressCount(row, 'abandoned_count') + taskProgressCount(row, 'invalid_count'), 0),
      completionRate: activeEnrollmentCount > 0 ? Math.min(100, Math.round(completedCount / activeEnrollmentCount * 100)) : 0,
    }
  }).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})
const statusBreakdown = computed(() => teacherEnrollmentStatusBreakdown(filteredRows.value).filter((item) => item.key !== 'revoked' && item.value > 0))
const classCompletionOption = computed<EChartsOption>(() => ({
  grid: { left: 12, right: 22, top: 20, bottom: 38, containLabel: true },
  tooltip: { trigger: 'axis', valueFormatter: (value) => `${value}%` },
  xAxis: { type: 'category', data: activeClassSummary.value.map((item) => teacherClassDisplayLabel(item.classRef, filteredRows.value)), axisLabel: { interval: 0, rotate: activeClassSummary.value.length > 5 ? 24 : 0, color: '#737985' }, axisLine: { lineStyle: { color: '#e4e7ec' } } },
  yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#737985' }, splitLine: { lineStyle: { color: '#edf0f2' } } },
  series: [{ type: 'bar', data: activeClassSummary.value.map((item) => item.completionRate), barMaxWidth: 36, itemStyle: { color: '#0f766e', borderRadius: [6, 6, 0, 0] }, emphasis: { focus: 'series' } }],
}))

const taskProgressOption = computed<EChartsOption>(() => {
  const chartRows = taskDimensionSummaries.value
  return {
    grid: { left: 12, right: 18, top: 28, bottom: 62, containLabel: true },
    color: ['#16a6c1', '#83c9d5', '#aab7c2'],
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value) => `${value} 人次` },
    legend: { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#737985', fontSize: 11 } },
    xAxis: { type: 'category', data: chartRows.map((row) => row.label), axisLabel: { interval: 0, rotate: chartRows.length > 5 ? 28 : 0, color: '#737985' }, axisLine: { lineStyle: { color: '#e4e7ec' } } },
    yAxis: { type: 'value', min: 0, axisLabel: { color: '#737985' }, splitLine: { lineStyle: { color: '#edf0f2' } } },
    series: [
      { name: '已完成', type: 'bar', stack: 'enrollment', data: chartRows.map((row) => row.completedCount), barMaxWidth: 36, itemStyle: { borderRadius: [0, 0, 0, 0] } },
      { name: '待完成', type: 'bar', stack: 'enrollment', data: chartRows.map((row) => row.pendingCount), barMaxWidth: 36 },
      { name: '已结束 / 不可继续', type: 'bar', stack: 'enrollment', data: chartRows.map((row) => row.endedCount), barMaxWidth: 36, itemStyle: { borderRadius: [5, 5, 0, 0] } },
    ],
  }
})

const taskRanking = computed(() => [...taskDimensionSummaries.value]
  .sort((a, b) => a.completionRate - b.completionRate
    || b.pendingCount - a.pendingCount
    || a.label.localeCompare(b.label, 'zh-CN'))
  .slice(0, 10))
const taskRankingOption = computed<EChartsOption>(() => ({
  grid: { left: 12, right: 36, top: 12, bottom: 12, containLabel: true },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value) => `${value}%` },
  xAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#737985' }, splitLine: { lineStyle: { color: '#edf0f2' } } },
  yAxis: { type: 'category', inverse: true, data: taskRanking.value.map((row) => row.label), axisLabel: { color: '#656b76', width: 150, overflow: 'truncate' }, axisLine: { show: false } },
  series: [{ type: 'bar', data: taskRanking.value.map((row) => row.completionRate), barMaxWidth: 22, itemStyle: { color: '#53a9cf', borderRadius: [0, 6, 6, 0] }, label: { show: true, position: 'right', formatter: '{c}%', color: '#45616e', fontSize: 10 } }],
}))

const futureDueRows = computed(() => {
  const now = Date.now()
  const end = now + 14 * 24 * 60 * 60 * 1000
  return filteredRows.value.flatMap((row) => {
    const dueAt = row.due_at ? Date.parse(row.due_at) : Number.NaN
    return Number.isFinite(dueAt) && dueAt >= now && dueAt <= end ? [{ row, dueAt }] : []
  })
})
const futureDueGroups = computed(() => {
  const groups = new Map<string, { timestamp: number; taskCount: number; pendingCount: number }>()
  for (const { row, dueAt } of futureDueRows.value) {
    const dueDate = new Date(dueAt)
    const key = `${dueDate.getFullYear()}-${String(dueDate.getMonth() + 1).padStart(2, '0')}-${String(dueDate.getDate()).padStart(2, '0')}`
    const group = groups.get(key) ?? { timestamp: new Date(dueDate.getFullYear(), dueDate.getMonth(), dueDate.getDate()).getTime(), taskCount: 0, pendingCount: 0 }
    group.taskCount += 1
    group.pendingCount += taskActionablePendingCount(row)
    groups.set(key, group)
  }
  return [...groups.entries()].sort((a, b) => a[1].timestamp - b[1].timestamp).map(([date, values]) => ({ date, ...values }))
})
const duePressureOption = computed<EChartsOption>(() => ({
  grid: { left: 12, right: 38, top: 25, bottom: 34, containLabel: true },
  color: ['#83c9d5', '#00a6c7'],
  tooltip: { trigger: 'axis', formatter: (params) => {
    const items = Array.isArray(params) ? params : [params]
    const heading = items[0]?.axisValueLabel ?? ''
    return [heading, ...items.map((item) => `${item.marker ?? ''}${item.seriesName}：${item.value}${item.seriesName === '到期任务' ? ' 项' : ' 人次'}`)].join('<br/>')
  } },
  legend: { top: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: '#737985', fontSize: 11 } },
  xAxis: { type: 'category', data: futureDueGroups.value.map((item) => item.date.slice(5).replace('-', '/')), axisLabel: { color: '#737985' }, axisLine: { lineStyle: { color: '#e4e7ec' } } },
  yAxis: [
    { type: 'value', min: 0, name: '任务数', nameTextStyle: { color: '#8a929d', fontSize: 10 }, axisLabel: { color: '#737985' }, splitLine: { lineStyle: { color: '#edf0f2' } } },
    { type: 'value', min: 0, name: '待完成人次', nameTextStyle: { color: '#8a929d', fontSize: 10 }, axisLabel: { color: '#737985' }, splitLine: { show: false } },
  ],
  series: [
    { name: '到期任务', type: 'bar', data: futureDueGroups.value.map((item) => item.taskCount), barMaxWidth: 24, itemStyle: { color: '#a9dce3', borderRadius: [5, 5, 0, 0] } },
    { name: '待完成人次', type: 'line', yAxisIndex: 1, data: futureDueGroups.value.map((item) => item.pendingCount), smooth: 0.22, symbolSize: 7, lineStyle: { width: 2.5 }, itemStyle: { color: '#00a6c7', borderColor: '#fff', borderWidth: 2 } },
  ],
}))

const statusOption = computed<EChartsOption>(() => ({
  color: ['#7da7d9', '#f0b35b', '#25a38e', '#9aa1aa'],
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 人次（{d}%）' },
  legend: { bottom: 0, left: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#656b76', fontSize: 11 } },
  series: [{ type: 'pie', radius: ['44%', '70%'], center: ['50%', '43%'], avoidLabelOverlap: true, label: { show: false }, emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold' } }, data: statusBreakdown.value.map((item) => ({ name: item.label, value: item.value })) }],
}))
const heatmapOption = computed<EChartsOption>(() => {
  const heatmapRows = activeTaskRows.value
  const classRefsForHeatmap = [...new Set(heatmapRows.map((row) => row.class_ref))].sort((a, b) => a.localeCompare(b, 'zh-CN'))
  const classLabels = classRefsForHeatmap.map((classRef) => teacherClassDisplayLabel(classRef, heatmapRows))
  const dimensions = new Map<string, { label: string; rows: typeof heatmapRows }>()
  for (const row of heatmapRows) {
    const dimension = teacherTaskHeatmapDimension(row)
    const current = dimensions.get(dimension.key) ?? { label: dimension.label, rows: [] }
    current.rows.push(row)
    dimensions.set(dimension.key, current)
  }
  const taskDimensions = [...dimensions.entries()]
    .map(([key, value]) => ({ key, ...value }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  const data: number[][] = []
  taskDimensions.forEach((dimension, taskIndex) => {
    classRefsForHeatmap.forEach((classRef, classIndex) => {
      const matchingRows = dimension.rows.filter((row) => row.class_ref === classRef)
      if (!matchingRows.length) return
      const active = matchingRows.reduce((total, row) => total + taskProgressCount(row, 'active_enrollment_count'), 0)
      if (active === 0) return
      const completed = matchingRows.reduce((total, row) => total + taskProgressCount(row, 'completed_count'), 0)
      data.push([taskIndex, classIndex, Math.min(100, Math.round(completed / active * 100)), active, completed])
    })
  })
  return {
    grid: { left: 12, right: 24, top: 16, bottom: 44, containLabel: true },
    tooltip: { position: 'top', formatter: (params) => {
      const point = Array.isArray(params) ? params[0] : params
      const value = Array.isArray(point.value) ? point.value : []
      return `${classLabels[Number(value[1])] ?? '班级'}，${taskDimensions[Number(value[0])]?.label ?? '任务'}<br/>有效报名：${value[3] ?? 0} 人次<br/>已完成：${value[4] ?? 0} 人次<br/>完成率：${value[2] ?? 0}%`
    } },
    xAxis: { type: 'category', data: taskDimensions.map((item) => item.label), splitArea: { show: true }, axisLabel: { color: '#656b76', interval: 0, rotate: taskDimensions.length > 5 ? 24 : 0 } },
    yAxis: { type: 'category', data: classLabels, splitArea: { show: true }, axisLabel: { color: '#656b76' } },
    visualMap: { dimension: 2, min: 0, max: 100, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#f1f5f7', '#c4e5ec', '#63b6d1', '#1679b6'] }, text: ['低完成率', '高完成率'], textStyle: { color: '#656b76', fontSize: 10 } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (params) => {
      const value = Array.isArray(params.data) ? params.data[2] : 0
      return `${value}%`
    }, color: '#16495a', fontSize: 10 }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgb(0 0 0 / 16%)' } } }],
  }
})

const timeSummary = computed(() => windowOptions.find((option) => option.value === timeWindow.value)?.label ?? '全部时间')
const formatPercent = (value: number, denominator = progressSummary.value.activeEnrollmentCount) => denominator === 0 ? '—' : `${value}%`
</script>

<template>
  <main class="teacher-analytics content-wrap">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="数据分析" />
    <header class="analytics-page-heading">
      <div><h1>数据分析</h1><p>按班级、任务和开放时间查看整体进度与状态分布。</p></div>
    </header>

    <p class="analytics-scope-note">仅显示授权范围内的班级与任务汇总，不包含个人心理记录。</p>

    <AppCard class="analytics-filter-card">
        <div class="filter-heading"><span><ListFilter :size="17" aria-hidden="true" />筛选范围</span><AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh">刷新数据</AppButton></div>
      <div class="filter-grid">
        <div class="filter-field"><span>班级</span><TeacherClassSelect v-model="selectedClass" :options="classSelectOptions" aria-label="按班级筛选分析数据" :disabled="state !== 'ready' || !rows.length" /></div>
        <div class="filter-field"><label for="analytics-task">任务</label><select id="analytics-task" v-model="selectedTask" :disabled="state !== 'ready' || !rows.length"><option value="all">全部任务</option><option v-for="row in taskOptions" :key="taskKey(row)" :value="taskKey(row)">{{ taskOptionLabel(row) }}</option></select></div>
        <div class="filter-field"><label for="analytics-window">时间范围</label><select id="analytics-window" v-model="timeWindow" :disabled="state !== 'ready' || !rows.length"><option v-for="option in windowOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><small>按任务开放时间筛选</small></div>
      </div>
    </AppCard>

    <div v-if="state === 'loading'" class="analytics-state" aria-busy="true" aria-live="polite">正在读取任务汇总数据…</div>
    <div v-else-if="state === 'error'" class="analytics-state analytics-state--error" role="alert"><p>{{ errorMessage }}</p><AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton></div>
    <AppCard v-else-if="!rows.length" class="analytics-state" role="status">当前没有可用于分析的班级任务汇总。</AppCard>
    <AppCard v-else-if="!filteredRows.length" class="analytics-state" role="status">所选条件下没有任务汇总记录。可以调整班级、任务或时间范围。</AppCard>
    <template v-else>
      <section class="analytics-summary" aria-label="所选范围的汇总指标">
        <AppCard class="summary-card"><span>班级</span><strong>{{ progressSummary.classCount }}</strong><small>个班级</small></AppCard>
        <AppCard class="summary-card"><span>任务</span><strong>{{ filteredRows.length }}</strong><small>项任务，{{ timeSummary }}</small></AppCard>
        <AppCard class="summary-card"><span>待完成人次</span><strong>{{ progressSummary.pendingCount }}</strong><small>有效报名中尚未完成</small></AppCard>
        <AppCard class="summary-card summary-card--accent"><span>整体完成率</span><strong>{{ formatPercent(progressSummary.completionRate) }}</strong><small>{{ progressSummary.completedCount }} / {{ progressSummary.activeEnrollmentCount }} 人次已完成</small></AppCard>
      </section>

      <section class="analytics-grid" aria-label="任务与班级分析图表">
        <AppCard class="analytics-chart-card"><header><span class="chart-icon"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>班级完成率</h2><p>按有效报名人次加权汇总</p></div></header><TeacherProgressChart v-if="activeClassSummary.length" :option="classCompletionOption" label="各班级汇总完成率柱状图" :summary="`当前范围包含 ${activeClassSummary.length} 个有有效报名的班级。`" :height="300" /><p v-else class="chart-empty">当前筛选范围没有有效报名，暂时无法计算班级完成率。</p></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon chart-icon--amber"><ChartPie :size="17" aria-hidden="true" /></span><div><h2>报名状态分布</h2><p>已撤销报名单独统计，不纳入环形图</p></div></header><TeacherProgressChart v-if="progressSummary.activeEnrollmentCount" :option="statusOption" label="任务报名状态分布饼图" :summary="`有效报名 ${progressSummary.activeEnrollmentCount} 人次；已撤销报名 ${progressSummary.revokedCount} 人次另行统计。`" :height="300" /><p v-else class="chart-empty">当前筛选范围没有有效报名，暂时无法展示状态分布。</p></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon chart-icon--teal"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>任务进度</h2><p>待完成按未开始、已创建和进行中汇总</p></div></header><TeacherProgressChart v-if="activeTaskRows.length" :option="taskProgressOption" label="各任务维度已完成待完成和已结束人次堆叠柱状图" :summary="`按 ${taskDimensionSummaries.length} 个任务维度汇总 ${activeTaskRows.length} 项任务；已结束包含 abandoned 与 invalid 状态。`" :height="300" /><p v-else class="chart-empty">当前筛选范围没有有效报名，暂时无法展示任务状态。</p></AppCard>
        <AppCard class="analytics-chart-card analytics-chart-card--wide"><header><span class="chart-icon chart-icon--teal"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>班级 × 任务完成热图</h2><p>颜色越深表示汇总完成率越高</p></div></header><TeacherProgressChart v-if="activeTaskRows.length" :option="heatmapOption" label="班级与任务汇总完成率热图" :summary="`横向为任务、纵向为班级，数据基于 ${activeTaskRows.length} 项有有效报名的任务。`" :height="Math.max(300, activeClassSummary.length * 42 + 80)" /><p v-else class="chart-empty">当前筛选范围没有有效报名，暂时无法绘制完成率矩阵。</p></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon chart-icon--amber"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>未来 14 天截止压力</h2><p>按实际截止日期汇总任务数和待完成人次</p></div></header><p v-if="!futureDueGroups.length" class="chart-empty">筛选范围内未来 14 天没有已设置截止日期的任务。</p><TeacherProgressChart v-else :option="duePressureOption" label="未来十四天到期任务数与待完成人次柱线组合图" :summary="`仅展示 ${futureDueRows.length} 项有有效未来截止时间的任务。`" :height="300" /></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>任务完成率排行</h2><p>从低到高排列，优先查看进度较慢的任务</p></div></header><TeacherProgressChart v-if="taskRanking.length" :option="taskRankingOption" label="任务完成率由低到高排行柱状图" :summary="`按完成率升序展示最多 ${taskRanking.length} 个任务维度。`" :height="300" /><p v-else class="chart-empty">当前筛选范围没有有效报名，暂无可排序的完成率。</p></AppCard>
      </section>
      <p class="analytics-footnote">时间范围按任务开放日期筛选；图表仅来自授权范围内的任务级汇总，不展示个人心理记录。历史完成率趋势暂缺每日历史快照，当前不展示。<span v-if="isDemo">当前为前端合成数据预览。</span></p>
    </template>
  </main>
</template>

<style scoped>
.teacher-analytics { display: grid; gap: 16px; padding-top: 0; animation: page-in 220ms ease both; }
.analytics-page-heading { display: flex; align-items: end; justify-content: space-between; gap: 12px; padding: 2px 0 4px; }
.analytics-page-heading h1 { margin: 0 0 5px; color: var(--color-text-primary); font-size: 23px; line-height: 1.25; }
.analytics-page-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
.analytics-scope-note { margin: -8px 0 0 2px; color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.analytics-filter-card { padding: 20px 22px; }
.filter-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.filter-heading > span { display: flex; align-items: center; gap: 8px; color: var(--color-text-primary); font-size: 14px; font-weight: 700; }
.filter-heading svg { color: var(--color-primary-active); }
.filter-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.filter-field { display: grid; gap: 6px; min-width: 0; }
.filter-field > label,.filter-field > span { color: var(--color-text-muted); font-size: 11px; font-weight: 600; }
.filter-field select { width: 100%; min-height: 38px; padding: 0 32px 0 11px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-primary); background: var(--color-surface); font-size: 12px; }
.filter-field select:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.filter-field select:disabled { color: var(--color-text-muted); background: var(--color-surface-soft); }
.filter-field small { color: var(--color-text-muted); font-size: 10px; }
.analytics-state { display: flex; min-height: 130px; align-items: center; justify-content: center; gap: 14px; padding: 20px; color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 13px; text-align: center; }
.analytics-state--error { justify-content: space-between; color: #805c1d; background: var(--color-attention-wash); text-align: left; }
.analytics-state--error p { margin: 0; }
.analytics-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.summary-card { display: grid; gap: 5px; min-width: 0; padding: 17px; }
.summary-card > span { color: var(--color-text-muted); font-size: 11px; }
.summary-card strong { color: var(--color-text-primary); font-size: 25px; line-height: 1.2; }
.summary-card small { color: var(--color-text-muted); font-size: 10px; line-height: 1.4; }
.summary-card--accent { background: #f2fbfc; }
.summary-card--accent strong { color: var(--color-primary-active); }
.analytics-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.analytics-chart-card { min-width: 0; padding: 18px; }
.analytics-chart-card--wide { grid-column: 1 / -1; }
.chart-empty { display: grid; min-height: 260px; margin: 0; place-items: center; color: var(--color-text-muted); font-size: 12px; text-align: center; }
.analytics-chart-card header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.chart-icon { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border-radius: 11px; color: var(--color-primary-active); background: #e8f8fc; }
.chart-icon--teal { color: var(--color-support); background: var(--color-support-wash); }
.chart-icon--amber { color: var(--color-attention); background: var(--color-attention-wash); }
.analytics-chart-card h2 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 14px; }
.analytics-chart-card header p { margin: 0; color: var(--color-text-muted); font-size: 10px; }
.analytics-footnote { margin: 0 2px; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 1000px) { .analytics-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .analytics-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .analytics-page-heading h1 { font-size: 20px; }.analytics-filter-card { padding: 17px; }.filter-grid { grid-template-columns: minmax(0, 1fr); }.analytics-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }.analytics-chart-card { padding: 15px; } }
</style>
