<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts/core'
import { Activity, ArrowRight, CalendarClock, ChartColumn, ChartPie, ClipboardList, RotateCcw, UsersRound } from '@lucide/vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentPageArt } from '@/data/student-feature-cards'
import {
  formatTeacherDate,
  shortTeacherRef,
  summarizeTeacherClasses,
  summarizeTeacherProgress,
  taskCompletionRate,
  taskProgressCount,
  teacherChartColors,
  teacherEnrollmentStatusBreakdown,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
} from '@/utils/teacher-task-progress'

const { state, rows, errorMessage, refresh } = useTeacherTaskProgress()
const summary = computed(() => summarizeTeacherProgress(rows.value))
const classes = computed(() => summarizeTeacherClasses(rows.value))
const statusBreakdown = computed(() => teacherEnrollmentStatusBreakdown(rows.value).filter((item) => item.value > 0))
const currentRows = computed(() => rows.value
  .filter((row) => ['upcoming', 'in_progress'].includes(teacherTaskPhase(row)))
  .sort((a, b) => (Date.parse(a.due_at ?? '') || Number.MAX_SAFE_INTEGER) - (Date.parse(b.due_at ?? '') || Number.MAX_SAFE_INTEGER)))
const scheduleRows = computed(() => rows.value
  .filter((row) => ['upcoming', 'in_progress'].includes(teacherTaskPhase(row)) && Number.isFinite(Date.parse(row.opens_at)))
  .sort((a, b) => (Date.parse(a.due_at ?? '') || Number.MAX_SAFE_INTEGER) - (Date.parse(b.due_at ?? '') || Number.MAX_SAFE_INTEGER))
  .slice(0, 6))
const classCompletionOption = computed<EChartsOption>(() => ({
  grid: { left: 10, right: 26, top: 12, bottom: 14, containLabel: true },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value) => `${value}%` },
  xAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: teacherChartColors.muted, fontSize: 10 }, splitLine: { lineStyle: { color: teacherChartColors.grid } } },
  yAxis: { type: 'category', inverse: true, data: classes.value.map((item) => `班级 ${shortTeacherRef(item.classRef)}`), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: teacherChartColors.muted, fontSize: 11 } },
  series: [{ type: 'bar', data: classes.value.map((item) => item.completionRate), barMaxWidth: 20, itemStyle: { color: teacherChartColors.teal, borderRadius: [0, 6, 6, 0] }, emphasis: { focus: 'series' } }],
}))
const statusOption = computed<EChartsOption>(() => ({
  color: [teacherChartColors.sky, teacherChartColors.amber, teacherChartColors.teal, teacherChartColors.violet, '#b8c0c7'],
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 人次（{d}%）' },
  legend: { bottom: 0, left: 'center', itemWidth: 10, itemHeight: 10, textStyle: { color: teacherChartColors.muted, fontSize: 10 } },
  series: [{ type: 'pie', radius: ['44%', '70%'], center: ['50%', '43%'], avoidLabelOverlap: true, label: { show: false }, emphasis: { label: { show: true, fontSize: 12, fontWeight: 'bold' } }, data: statusBreakdown.value.map((item) => ({ name: item.label, value: item.value })) }],
}))
const taskProgressOption = computed<EChartsOption>(() => ({
  grid: { left: 12, right: 24, top: 12, bottom: 18, containLabel: true },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  legend: { top: 0, right: 0, textStyle: { color: teacherChartColors.muted, fontSize: 10 } },
  xAxis: { type: 'value', minInterval: 1, axisLabel: { color: teacherChartColors.muted, fontSize: 10 }, splitLine: { lineStyle: { color: teacherChartColors.grid } } },
  yAxis: { type: 'category', inverse: true, data: rows.value.map((row) => `班级 ${shortTeacherRef(row.class_ref)} · ${shortTeacherRef(row.task_ref)}`), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: teacherChartColors.muted, fontSize: 10, width: 170, overflow: 'truncate' } },
  series: [
    { name: '已完成', type: 'bar', stack: 'enrollments', barMaxWidth: 18, data: rows.value.map((row) => taskProgressCount(row, 'completed_count')), itemStyle: { color: teacherChartColors.teal, borderRadius: [0, 4, 4, 0] } },
    { name: '待完成', type: 'bar', stack: 'enrollments', barMaxWidth: 18, data: rows.value.map((row) => Math.max(0, taskProgressCount(row, 'active_enrollment_count') - taskProgressCount(row, 'completed_count'))), itemStyle: { color: '#dce9eb', borderRadius: [0, 4, 4, 0] } },
  ],
}))
const completionRateLabel = computed(() => summary.value.activeEnrollmentCount > 0 ? `${summary.value.completionRate}%` : '—')
const taskHref = (classRef: string, taskRef: string) => `/teacher/tasks/${encodeURIComponent(classRef)}/${encodeURIComponent(taskRef)}`
</script>

<template>
  <main class="content-wrap teacher-overview">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="工作概览" />
    <StudentPageHero
      eyebrow="TEACHER WORKSPACE · SCOPE A"
      title="工作概览"
      subtitle="快速查看授权班级的任务进展与近期安排。"
      :image="studentPageArt.assessments"
      image-position="center 48%"
      light-text
    />

    <AppStatusCallout
      tone="info"
      title="仅显示任务汇总"
      body="数据按班级任务和报名人次聚合，不展示学生名单、个人测评记录、作答、报告或支持对话。报名人次不等于学生人数。"
    />

    <AppCard class="overview-panel">
      <header class="overview-panel__heading">
        <div><h2>工作概览</h2><p>当前账号获授权的班级任务整体状态</p></div>
        <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton>
      </header>

      <div v-if="state === 'loading'" class="overview-state" aria-busy="true" role="status">正在读取任务汇总…</div>
      <div v-else-if="state === 'error'" class="overview-state overview-state--error" role="alert"><p>{{ errorMessage }}</p><AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton></div>
      <div v-else-if="rows.length === 0" class="overview-state" role="status">当前没有可查看的班级任务汇总。</div>
      <template v-else>
        <section class="overview-kpis" aria-label="任务进度指标">
          <AppCard class="overview-kpi"><span><UsersRound :size="16" aria-hidden="true" />有任务班级</span><strong>{{ summary.classCount }}</strong><small>当前汇总中出现的授权班级</small></AppCard>
          <AppCard class="overview-kpi"><span><ClipboardList :size="16" aria-hidden="true" />进行中班级任务</span><strong>{{ summary.currentTaskCount }}</strong><small>已开放且尚未截止的任务班级</small></AppCard>
          <AppCard class="overview-kpi overview-kpi--accent"><span><Activity :size="16" aria-hidden="true" />测评完成率</span><strong>{{ completionRateLabel }}</strong><small>{{ summary.completedCount }} / {{ summary.activeEnrollmentCount }} 有效报名人次</small></AppCard>
          <AppCard class="overview-kpi"><span><CalendarClock :size="16" aria-hidden="true" />待完成报名人次</span><strong>{{ summary.pendingCount }}</strong><small>有效报名人次中尚未完成的部分</small></AppCard>
        </section>

        <section class="overview-chart-grid" aria-label="任务数据图表">
          <AppCard class="overview-chart-card">
            <header><span class="overview-chart-icon"><ChartColumn :size="17" aria-hidden="true" /></span><div><h3>班级完成率对比</h3><p>按当前有效报名人次加权</p></div><RouterLink to="/teacher/classes">查看班级 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></header>
            <TeacherProgressChart :option="classCompletionOption" label="各授权班级任务汇总完成率横向条形图" :summary="`展示 ${classes.length} 个有任务记录的授权班级。`" :height="Math.max(220, classes.length * 38)" />
          </AppCard>
          <AppCard class="overview-chart-card">
            <header><span class="overview-chart-icon overview-chart-icon--teal"><ChartPie :size="17" aria-hidden="true" /></span><div><h3>测评状态分布</h3><p>按任务报名人次聚合</p></div><RouterLink to="/teacher/analytics">数据分析 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></header>
            <TeacherProgressChart :option="statusOption" label="测评任务报名状态分布环形图" :summary="`当前有效报名 ${summary.activeEnrollmentCount} 人次；已撤销报名 ${summary.revokedCount} 人次另行统计。`" :height="250" />
          </AppCard>
          <AppCard class="overview-chart-card overview-chart-card--wide">
            <header><span class="overview-chart-icon overview-chart-icon--amber"><ClipboardList :size="17" aria-hidden="true" /></span><div><h3>各任务完成情况</h3><p>已完成与仍待完成的有效报名人次</p></div><RouterLink to="/teacher/tasks">查看测评任务 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></header>
            <TeacherProgressChart :option="taskProgressOption" label="各班级任务已完成及待完成报名人次的堆叠条形图" :summary="`当前汇总 ${rows.length} 条班级任务记录。`" :height="Math.max(230, Math.min(rows.length, 8) * 42 + 60)" />
          </AppCard>
        </section>

        <section class="overview-bottom-grid">
          <AppCard class="overview-list-card">
            <header><div><h3>近期需要关注的任务</h3><p>开放中或即将开始的班级任务</p></div><RouterLink to="/teacher/tasks">全部任务 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></header>
            <div v-if="currentRows.length" class="overview-task-list">
              <RouterLink v-for="row in currentRows.slice(0, 5)" :key="`${row.class_ref}:${row.task_ref}`" class="overview-task-row" :to="taskHref(row.class_ref, row.task_ref)">
                <span class="overview-task-row__marker" aria-hidden="true"></span>
                <span class="overview-task-row__main"><strong>班级 {{ shortTeacherRef(row.class_ref) }} · 任务 {{ shortTeacherRef(row.task_ref) }}</strong><small>截止 {{ formatTeacherDate(row.due_at, '未设置截止时间') }}</small></span>
                <span class="overview-task-row__progress">{{ taskCompletionRate(row) }}%</span>
                <ArrowRight :size="15" aria-hidden="true" />
              </RouterLink>
            </div>
            <p v-else class="overview-empty-inline">当前没有进行中或即将开始的已发布任务。</p>
          </AppCard>

          <AppCard class="overview-list-card overview-schedule-card">
            <header><div><h3>任务时间安排</h3><p>按汇总接口提供的开放时间排列</p></div><CalendarClock :size="17" aria-hidden="true" /></header>
            <ol v-if="scheduleRows.length" class="overview-schedule-list">
              <li v-for="row in scheduleRows" :key="`${row.class_ref}:${row.task_ref}`">
                <span class="overview-schedule-list__dot" aria-hidden="true"></span>
                <div><strong>班级 {{ shortTeacherRef(row.class_ref) }} · 任务 {{ shortTeacherRef(row.task_ref) }}</strong><small>{{ formatTeacherDate(row.opens_at) }} <span>至</span> {{ formatTeacherDate(row.due_at, '未设置截止时间') }}</small></div>
                <span class="overview-schedule-list__phase">{{ teacherTaskPhaseLabel(teacherTaskPhase(row)) }}</span>
              </li>
            </ol>
            <p v-else class="overview-empty-inline">当前没有可显示开放时间的已发布任务。</p>
          </AppCard>
        </section>
      </template>
    </AppCard>
    <p class="overview-footnote">所有指标均来自当前授权任务的服务端汇总。详细任务清单与筛选可在班级进度、测评任务和数据分析中查看。</p>
  </main>
</template>

<style scoped>
.teacher-overview { display: grid; gap: 16px; padding-top: 0; padding-bottom: 56px; animation: page-in 220ms ease both; }
.teacher-overview :deep(.student-page-hero) { margin-bottom: 0; }
.overview-panel { display: grid; gap: 18px; padding: 22px; }
.overview-panel__heading,.overview-panel__heading > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.overview-panel__heading h2 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 17px; }
.overview-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.overview-state { display: grid; min-height: 126px; place-items: center; padding: 20px; border-radius: 12px; color: var(--color-text-secondary); background: #f8fafb; font-size: 13px; text-align: center; }
.overview-state--error { display: flex; align-items: center; justify-content: space-between; gap: 16px; color: #805c1d; background: #fcf7eb; text-align: left; }
.overview-state--error p { margin: 0; }
.overview-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.overview-kpi { display: grid; align-content: start; gap: 7px; min-width: 0; padding: 16px; background: #fff; }
.overview-kpi > span { display: flex; align-items: center; gap: 7px; color: var(--color-text-secondary); font-size: 11px; font-weight: 600; }
.overview-kpi > span svg { color: var(--color-support); }
.overview-kpi strong { color: var(--color-text-primary); font-size: 26px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.overview-kpi small { color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.overview-kpi--accent { background: #f2fbfc; }
.overview-kpi--accent strong,.overview-kpi--accent > span svg { color: var(--color-primary-active); }
.overview-chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.overview-chart-card { display: grid; gap: 10px; min-width: 0; padding: 17px; }
.overview-chart-card--wide { grid-column: 1 / -1; }
.overview-chart-card > header,.overview-list-card > header { display: flex; align-items: center; gap: 10px; min-width: 0; }
.overview-chart-card > header > div,.overview-list-card > header > div { flex: 1; min-width: 0; }
.overview-chart-icon { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border-radius: 11px; color: var(--color-primary-active); background: #e8f8fc; }
.overview-chart-icon--teal { color: var(--color-support); background: var(--color-support-wash); }
.overview-chart-icon--amber { color: var(--color-attention); background: var(--color-attention-wash); }
.overview-chart-card h3,.overview-list-card h3 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 14px; }
.overview-chart-card header p,.overview-list-card header p { margin: 0; color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.overview-chart-card header > a,.overview-list-card header > a { display: inline-flex; align-items: center; gap: 4px; color: var(--color-primary-active); font-size: 10px; font-weight: 650; text-decoration: none; white-space: nowrap; }
.overview-chart-card header > a:hover,.overview-list-card header > a:hover { text-decoration: underline; }
.overview-bottom-grid { display: grid; grid-template-columns: minmax(0, 1.12fr) minmax(0, .88fr); gap: 14px; }
.overview-list-card { display: grid; align-content: start; gap: 14px; min-width: 0; padding: 18px; }
.overview-list-card > header > svg { color: var(--color-support); }
.overview-task-list { display: grid; }
.overview-task-row { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto 16px; align-items: center; gap: 10px; min-width: 0; padding: 11px 2px; border-top: 1px solid #edf0f2; color: inherit; text-decoration: none; }
.overview-task-row:hover .overview-task-row__main strong { color: var(--color-primary-active); }
.overview-task-row__marker,.overview-schedule-list__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-primary); }
.overview-task-row__main { display: grid; gap: 4px; min-width: 0; }
.overview-task-row__main strong,.overview-schedule-list strong { overflow: hidden; color: var(--color-text-primary); font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.overview-task-row__main small,.overview-schedule-list small { color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.overview-task-row__progress { color: var(--color-support); font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.overview-task-row > svg { color: #99a2aa; }
.overview-task-row:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; border-radius: 4px; }
.overview-schedule-list { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.overview-schedule-list li { position: relative; display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; align-items: start; gap: 10px; padding: 11px 0; border-top: 1px solid #edf0f2; }
.overview-schedule-list li:not(:last-child)::after { position: absolute; top: 19px; bottom: -11px; left: 3px; width: 1px; background: #e4eaec; content: ''; }
.overview-schedule-list__dot { position: relative; z-index: 1; margin-top: 4px; box-shadow: 0 0 0 3px #fff; }
.overview-schedule-list li > div { display: grid; gap: 4px; min-width: 0; }
.overview-schedule-list small span { padding: 0 3px; color: var(--color-text-muted); }
.overview-schedule-list__phase { padding: 4px 7px; border-radius: 999px; color: #287765; background: #e8f4ef; font-size: 9px; white-space: nowrap; }
.overview-empty-inline { margin: 0; padding: 20px 10px; border-top: 1px solid #edf0f2; color: var(--color-text-muted); font-size: 11px; text-align: center; }
.overview-footnote { margin: 0 2px; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 1000px) { .overview-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }.overview-bottom-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .overview-chart-grid { grid-template-columns: 1fr; }.overview-chart-card--wide { grid-column: auto; } }
@media (max-width: 560px) { .overview-panel { padding: 16px; }.overview-panel__heading { align-items: flex-start; }.overview-kpis { gap: 8px; }.overview-kpi { padding: 12px; }.overview-kpi strong { font-size: 22px; }.overview-chart-card,.overview-list-card { padding: 14px; }.overview-chart-card > header { align-items: flex-start; }.overview-chart-card header > a { gap: 2px; font-size: 9px; } }
</style>
