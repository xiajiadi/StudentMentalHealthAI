<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChartColumn, ChartPie, ListFilter } from '@lucide/vue'
import type { EChartsOption } from 'echarts/core'
import {
  shortTeacherRef,
  summarizeTeacherClasses,
  summarizeTeacherProgress,
  taskCompletionRate,
  teacherEnrollmentStatusBreakdown,
} from '@/utils/teacher-task-progress'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt } from '@/data/student-feature-cards'

type TimeWindow = 'all' | '30' | '90' | '365'

const { state, rows, errorMessage, refresh } = useTeacherTaskProgress()
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
const taskOptions = computed(() => rows.value
  .filter((row) => selectedClass.value === 'all' || row.class_ref === selectedClass.value)
  .sort((a, b) => a.class_ref.localeCompare(b.class_ref, 'zh-CN') || a.task_ref.localeCompare(b.task_ref, 'zh-CN')))

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
const statusBreakdown = computed(() => teacherEnrollmentStatusBreakdown(filteredRows.value).filter((item) => item.value > 0))
const taskLabels = computed(() => filteredRows.value.map((row) => `班级 ${shortTeacherRef(row.class_ref)} · ${shortTeacherRef(row.task_ref)}`))
const taskValues = computed(() => filteredRows.value.map((row) => taskCompletionRate(row)))

const barOption = (labels: string[], values: number[], color = '#00b1e2'): EChartsOption => ({
  grid: { left: 12, right: 22, top: 18, bottom: 36, containLabel: true },
  tooltip: { trigger: 'axis', valueFormatter: (value) => `${value}%` },
  xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 5 ? 28 : 0, color: '#656b76' }, axisLine: { lineStyle: { color: '#e4e7ec' } } },
  yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#656b76' }, splitLine: { lineStyle: { color: '#edf0f2' } } },
  series: [{ type: 'bar', data: values, barMaxWidth: 36, itemStyle: { color, borderRadius: [6, 6, 0, 0] }, emphasis: { focus: 'series' } }],
})

const taskCompletionOption = computed(() => barOption(taskLabels.value, taskValues.value))
const classCompletionOption = computed(() => barOption(
  classSummary.value.map((item) => `班级 ${shortTeacherRef(item.classRef)}`),
  classSummary.value.map((item) => item.completionRate),
  '#0f766e',
))
const statusOption = computed<EChartsOption>(() => ({
  color: ['#7da7d9', '#f0b35b', '#25a38e', '#9aa1aa', '#c5c9ce'],
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 人次（{d}%）' },
  legend: { bottom: 0, left: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: '#656b76', fontSize: 11 } },
  series: [{ type: 'pie', radius: ['44%', '70%'], center: ['50%', '43%'], avoidLabelOverlap: true, label: { show: false }, emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold' } }, data: statusBreakdown.value.map((item) => ({ name: item.label, value: item.value })) }],
}))
const heatmapOption = computed<EChartsOption>(() => {
  const classLabels = classSummary.value.map((item) => `班级 ${shortTeacherRef(item.classRef)}`)
  const taskRefsForHeatmap = [...new Set(filteredRows.value.map((row) => row.task_ref))]
  const data = filteredRows.value.map((row) => [
    taskRefsForHeatmap.indexOf(row.task_ref),
    classSummary.value.findIndex((item) => item.classRef === row.class_ref),
    taskCompletionRate(row),
  ])
  return {
    grid: { left: 12, right: 24, top: 16, bottom: 34, containLabel: true },
    tooltip: { position: 'top', formatter: (params) => {
      const point = Array.isArray(params) ? params[0] : params
      const value = Array.isArray(point.value) ? point.value : []
      return `${classLabels[Number(value[1])] ?? '班级'} · 任务 ${shortTeacherRef(taskRefsForHeatmap[Number(value[0])] ?? '')}<br/>完成率：${value[2] ?? 0}%`
    } },
    xAxis: { type: 'category', data: taskRefsForHeatmap.map((ref) => `任务 ${shortTeacherRef(ref)}`), splitArea: { show: true }, axisLabel: { color: '#656b76' } },
    yAxis: { type: 'category', data: classLabels, splitArea: { show: true }, axisLabel: { color: '#656b76' } },
    visualMap: { min: 0, max: 100, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#edf7f8', '#89d5dc', '#00a6bd'] }, textStyle: { color: '#656b76', fontSize: 10 } },
    series: [{ type: 'heatmap', data, label: { show: true, formatter: (params) => {
      const value = Array.isArray(params.data) ? params.data[2] : 0
      return `${value}%`
    }, color: '#16495a', fontSize: 10 }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgb(0 0 0 / 22%)' } } }],
  }
})

const timeSummary = computed(() => windowOptions.find((option) => option.value === timeWindow.value)?.label ?? '全部时间')
const formatPercent = (value: number) => `${value}%`
</script>

<template>
  <main class="teacher-analytics content-wrap">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="数据分析" />
    <StudentPageHero
      eyebrow="CLASS ANALYTICS · SCOPE A"
      title="班级任务分析"
      subtitle="按班级、任务和开放时间查看整体进度与状态分布。"
      :image="studentPageArt.history"
      image-position="center 48%"
      light-text
    />

    <AppStatusCallout tone="info" title="仅呈现聚合统计" body="图表由任务汇总人数计算，不展示学生名单、个人记录、作答或心理内容。" />

    <AppCard class="analytics-filter-card">
        <div class="filter-heading"><span><ListFilter :size="17" aria-hidden="true" />筛选范围</span><AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh">刷新数据</AppButton></div>
      <div class="filter-grid">
        <div class="filter-field"><label for="analytics-class">班级</label><select id="analytics-class" v-model="selectedClass" :disabled="state !== 'ready' || !rows.length"><option value="all">全部班级</option><option v-for="classRef in classOptions" :key="classRef" :value="classRef">班级 {{ shortTeacherRef(classRef) }}</option></select></div>
        <div class="filter-field"><label for="analytics-task">任务</label><select id="analytics-task" v-model="selectedTask" :disabled="state !== 'ready' || !rows.length"><option value="all">全部任务</option><option v-for="row in taskOptions" :key="taskKey(row)" :value="taskKey(row)">班级 {{ shortTeacherRef(row.class_ref) }} · 任务 {{ shortTeacherRef(row.task_ref) }}</option></select></div>
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
        <AppCard class="summary-card"><span>任务</span><strong>{{ filteredRows.length }}</strong><small>项任务 · {{ timeSummary }}</small></AppCard>
        <AppCard class="summary-card"><span>当前有效报名</span><strong>{{ progressSummary.activeEnrollmentCount }}</strong><small>人次</small></AppCard>
        <AppCard class="summary-card summary-card--accent"><span>整体完成率</span><strong>{{ formatPercent(progressSummary.completionRate) }}</strong><small>{{ progressSummary.completedCount }} / {{ progressSummary.activeEnrollmentCount }} 人次已完成</small></AppCard>
      </section>

      <section class="analytics-grid" aria-label="任务与班级分析图表">
        <AppCard class="analytics-chart-card"><header><span class="chart-icon"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>任务完成率</h2><p>按班级区分的任务完成情况</p></div></header><TeacherProgressChart :option="taskCompletionOption" label="各班级任务完成率柱状图" :summary="`展示 ${filteredRows.length} 项任务的汇总完成率。`" :height="300" /></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon chart-icon--teal"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>班级完成率</h2><p>按有效报名人数汇总的班级进度</p></div></header><TeacherProgressChart :option="classCompletionOption" label="各班级汇总完成率柱状图" :summary="`当前范围包含 ${classSummary.length} 个班级。`" :height="300" /></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon chart-icon--amber"><ChartPie :size="17" aria-hidden="true" /></span><div><h2>报名状态分布</h2><p>汇总已开始、完成及结束状态</p></div></header><TeacherProgressChart :option="statusOption" label="任务报名状态分布饼图" :summary="`有效报名 ${progressSummary.activeEnrollmentCount} 人次，已撤销报名 ${progressSummary.revokedCount} 人次另行统计。`" :height="300" /></AppCard>
        <AppCard class="analytics-chart-card"><header><span class="chart-icon chart-icon--teal"><ChartColumn :size="17" aria-hidden="true" /></span><div><h2>班级 × 任务完成热图</h2><p>颜色越深表示汇总完成率越高</p></div></header><TeacherProgressChart :option="heatmapOption" label="班级与任务汇总完成率热图" :summary="`横向为任务、纵向为班级，数据基于 ${filteredRows.length} 项任务。`" :height="300" /></AppCard>
      </section>
      <p class="analytics-footnote">时间范围按任务开放日期筛选；完成率为任务级汇总，不用于评价个人或推断心理状态。</p>
    </template>
  </main>
</template>

<style scoped>
.teacher-analytics { display: grid; gap: 16px; padding-top: 0; animation: page-in 220ms ease both; }
.teacher-analytics :deep(.student-page-hero) { margin-bottom: 0; }
.analytics-filter-card { padding: 20px 22px; }
.filter-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.filter-heading > span { display: flex; align-items: center; gap: 8px; color: var(--color-text-primary); font-size: 14px; font-weight: 700; }
.filter-heading svg { color: var(--color-primary-active); }
.filter-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.filter-field { display: grid; gap: 6px; min-width: 0; }
.filter-field label { color: var(--color-text-muted); font-size: 11px; font-weight: 600; }
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
@media (max-width: 560px) { .analytics-filter-card { padding: 17px; }.filter-grid { grid-template-columns: minmax(0, 1fr); }.analytics-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }.analytics-chart-card { padding: 15px; } }
</style>
