<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts/core'
import { ArrowRight, CalendarDays, ListChecks, RotateCcw, UsersRound } from '@lucide/vue'
import { useRoute } from 'vue-router'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import {
  formatTeacherDate,
  summarizeTeacherClasses,
  taskActionablePendingCount,
  taskCompletionRate,
  taskProgressCount,
  teacherClassDisplayLabel,
  teacherTaskDisplayLabel,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
  teacherTaskStatusLabel,
} from '@/utils/teacher-task-progress'

const route = useRoute()
const { state, rows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })
const classRef = computed(() => String(route.params.classRef ?? ''))
const summary = computed(() => summarizeTeacherClasses(rows.value).find((item) => item.classRef === classRef.value) ?? null)
const taskRoute = (taskRef: string) => `/teacher/tasks/${encodeURIComponent(classRef.value)}/${encodeURIComponent(taskRef)}`
const taskEndedCount = (task: (typeof rows.value)[number]) => taskProgressCount(task, 'abandoned_count') + taskProgressCount(task, 'invalid_count')
const taskChartOption = computed<EChartsOption>(() => {
  const tasks = summary.value?.tasks ?? []
  return {
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, textStyle: { color: '#65727a', fontSize: 11 } },
    grid: { top: 38, right: 12, bottom: 30, left: 36, containLabel: true },
    xAxis: {
      type: 'category',
      data: tasks.map((task) => teacherTaskDisplayLabel(task)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dbe5e7' } },
      axisLabel: { color: '#75838a', fontSize: 10 },
    },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#75838a', fontSize: 10 }, splitLine: { lineStyle: { color: '#edf2f3' } } },
    series: [
      { name: '未开始', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map((task) => taskProgressCount(task, 'not_started_count')), itemStyle: { color: '#c9e9f0' } },
      { name: '准备中', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map((task) => taskProgressCount(task, 'created_count')), itemStyle: { color: '#8acbd9' } },
      { name: '进行中', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map((task) => taskProgressCount(task, 'in_progress_count')), itemStyle: { color: '#36abc1' } },
      { name: '已完成', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map((task) => taskProgressCount(task, 'completed_count')), itemStyle: { color: '#117f9a' } },
      { name: '已结束 / 不可继续', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map(taskEndedCount), itemStyle: { color: '#aebfc7', borderRadius: [4, 4, 0, 0] } },
    ],
  }
})
const chartSummary = computed(() => {
  if (!summary.value) return '当前没有可显示的班级任务汇总。'
  return `按状态展示 ${summary.value.taskCount} 项授权任务的有效报名人次；已撤销报名不计入图表。`
})
</script>

<template>
  <main class="content-wrap teacher-class-detail">
    <WorkspaceBreadcrumb
      homeLabel="教师工作区"
      homeTo="/teacher/overview"
      :parent="{ label: '班级进度', to: '/teacher/classes' }"
      :current="summary ? teacherClassDisplayLabel(summary.classRef, rows) : '班级汇总'"
    />
    <header class="teacher-page-heading">
      <span class="teacher-page-heading__icon"><UsersRound :size="21" aria-hidden="true" /></span>
      <div><h1>{{ summary ? teacherClassDisplayLabel(summary.classRef, rows) : '班级任务汇总' }}</h1><p>查看该班级的授权任务、整体报名进度与截止时间。</p></div>
    </header>

    <AppCard v-if="state === 'loading'" class="teacher-class-detail__state" aria-busy="true" role="status">
      正在读取授权班级汇总…
    </AppCard>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="班级汇总暂不可用" :body="errorMessage">
      <AppButton variant="secondary" size="sm" @click="refresh"><RotateCcw :size="14" aria-hidden="true" />重新读取</AppButton>
    </AppStatusCallout>
    <AppCard v-else-if="!summary" class="teacher-class-detail__state" role="status">
      当前账号没有该班级的授权任务汇总，或汇总已发生变化。
    </AppCard>

    <template v-else>
      <section class="teacher-class-stats" aria-label="班级授权任务汇总">
        <AppCard class="teacher-class-stat"><span>授权任务</span><strong>{{ summary.taskCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat"><span>有效报名人次</span><strong>{{ summary.activeEnrollmentCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat"><span>已完成报名人次</span><strong>{{ summary.completedCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat"><span>待完成人次</span><strong>{{ summary.pendingCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat teacher-class-stat--rate"><span>汇总完成率</span><strong>{{ summary.activeEnrollmentCount > 0 ? `${summary.completionRate}%` : '—' }}</strong></AppCard>
      </section>

      <AppCard class="teacher-class-chart">
        <div class="teacher-class-section-heading">
          <span class="teacher-class-section-heading__icon"><ListChecks :size="18" aria-hidden="true" /></span>
          <div><h2>任务状态分布</h2><p>按任务查看报名人次的完成状态，撤销报名另行统计。</p></div>
        </div>
        <TeacherProgressChart v-if="summary.activeEnrollmentCount > 0"
          :option="taskChartOption"
          label="班级内各授权任务报名状态分布堆叠柱状图"
          :summary="chartSummary"
          :height="250"
        />
        <p v-else class="teacher-class-chart-empty">当前班级暂无有效报名，暂时无法展示任务状态分布。</p>
      </AppCard>

      <section class="teacher-task-section" aria-labelledby="teacher-task-section-heading">
        <header class="teacher-class-section-heading teacher-task-section__heading">
          <span class="teacher-class-section-heading__icon"><CalendarDays :size="18" aria-hidden="true" /></span>
          <div><h2 id="teacher-task-section-heading">授权任务</h2><p>时间和进度均按任务级汇总显示。</p></div>
        </header>
        <AppCard v-if="summary.tasks.length === 0" class="teacher-class-detail__state" role="status">当前没有可显示的授权任务。</AppCard>
        <div v-else class="teacher-task-list">
          <AppCard v-for="task in summary.tasks" :key="task.task_ref" class="teacher-task-card">
            <div class="teacher-task-card__header">
              <div><span class="teacher-task-card__eyebrow">授权任务</span><h3>{{ teacherTaskDisplayLabel(task) }}</h3></div>
              <div class="teacher-task-card__badges">
                <span class="teacher-task-card__phase" :class="`teacher-task-card__phase--${teacherTaskPhase(task)}`">{{ teacherTaskPhaseLabel(teacherTaskPhase(task)) }}</span>
                <span class="teacher-task-card__status">{{ teacherTaskStatusLabel(task.task_status) }}</span>
              </div>
            </div>
            <dl class="teacher-task-card__metrics">
              <div><dt>有效报名人次</dt><dd>{{ taskProgressCount(task, 'active_enrollment_count') }}</dd></div>
              <div><dt>已完成</dt><dd>{{ taskProgressCount(task, 'completed_count') }}</dd></div>
              <div><dt>待完成人次</dt><dd>{{ taskActionablePendingCount(task) }}</dd></div>
              <div><dt>已结束 / 不可继续</dt><dd>{{ taskEndedCount(task) }}</dd></div>
              <div><dt>已撤销报名</dt><dd>{{ taskProgressCount(task, 'revoked_enrollment_count') }}</dd></div>
              <div class="teacher-task-card__completion"><dt>任务完成率</dt><dd>{{ taskProgressCount(task, 'active_enrollment_count') > 0 ? `${taskCompletionRate(task)}%` : '—' }}</dd></div>
            </dl>
            <div class="teacher-task-card__dates">
              <span><strong>开放</strong>{{ formatTeacherDate(task.opens_at, '未设置') }}</span>
              <span><strong>截止</strong>{{ formatTeacherDate(task.due_at, '未设置截止时间') }}</span>
            </div>
            <RouterLink class="teacher-task-card__link" :to="taskRoute(task.task_ref)">
              查看任务汇总 <ArrowRight :size="15" aria-hidden="true" />
            </RouterLink>
          </AppCard>
        </div>
      </section>
      <p v-if="isDemo" class="teacher-class-demo-note">当前为前端合成数据预览，不代表实际业务记录。</p>
    </template>
  </main>
</template>

<style scoped>
.teacher-class-detail { display: grid; gap: 16px; padding-top: 0; padding-bottom: 56px; animation: page-in 220ms ease both; }
.teacher-page-heading { display: flex; align-items: center; gap: 13px; padding: 2px 0 4px; }
.teacher-page-heading__icon { display: grid; width: 42px; height: 42px; flex: 0 0 42px; place-items: center; border-radius: 13px; color: var(--color-primary-active); background: #e8f8fc; }
.teacher-page-heading h1 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 22px; line-height: 1.2; }
.teacher-page-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.5; }
.teacher-class-detail__state { display: grid; min-height: 120px; place-items: center; padding: 20px; color: var(--color-text-secondary); text-align: center; }
.teacher-class-stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.teacher-class-stat { display: grid; align-content: center; gap: 8px; min-width: 0; min-height: 104px; padding: 16px; }
.teacher-class-stat span { color: var(--color-text-muted); font-size: 11px; line-height: 1.4; }
.teacher-class-stat strong { color: var(--color-text-primary); font-size: clamp(20px, 2.2vw, 27px); font-weight: 700; font-variant-numeric: tabular-nums; }
.teacher-class-stat--rate strong { color: #147f8e; }
.teacher-class-chart { display: grid; gap: 14px; padding: 20px; }
.teacher-class-chart-empty { display: grid; min-height: 220px; margin: 0; place-items: center; color: var(--color-text-muted); font-size: 12px; text-align: center; }
.teacher-class-section-heading { display: flex; align-items: center; gap: 12px; }
.teacher-class-section-heading__icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 12px; color: #117e9b; background: #e8f6f9; }
.teacher-class-section-heading h2 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 15px; }
.teacher-class-section-heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; }
.teacher-task-section { display: grid; gap: 13px; }
.teacher-task-section__heading { padding: 1px 2px; }
.teacher-task-list { display: grid; gap: 12px; }
.teacher-task-card { display: grid; gap: 15px; min-width: 0; padding: 19px; }
.teacher-task-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.teacher-task-card__eyebrow { color: #127c94; font-size: 10px; font-weight: 700; letter-spacing: .04em; }
.teacher-task-card h3 { margin: 5px 0 0; color: var(--color-text-primary); font-size: 15px; }
.teacher-task-card__badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.teacher-task-card__badges > span { padding: 5px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; white-space: nowrap; }
.teacher-task-card__phase { color: #127b82; background: #e8f6f3; }
.teacher-task-card__phase--upcoming { color: #6e6e91; background: #f0eff8; }
.teacher-task-card__phase--ended,.teacher-task-card__phase--cancelled,.teacher-task-card__phase--unpublished { color: #7a6a58; background: #f5f0e9; }
.teacher-task-card__status { color: #47636d; background: #eef4f5; }
.teacher-task-card__metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; margin: 0; }
.teacher-task-card__metrics > div { display: grid; align-content: start; gap: 5px; min-width: 0; padding: 10px; border-radius: 10px; background: #f6f9fa; }
.teacher-task-card__metrics dt { color: var(--color-text-muted); font-size: 10px; line-height: 1.4; }
.teacher-task-card__metrics dd { margin: 0; color: var(--color-text-primary); font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.teacher-task-card__metrics .teacher-task-card__completion dd { color: #147f8e; }
.teacher-task-card__dates { display: flex; flex-wrap: wrap; gap: 8px 22px; padding-top: 12px; border-top: 1px solid #edf1f2; }
.teacher-task-card__dates span { display: flex; flex-wrap: wrap; gap: 7px; color: var(--color-text-secondary); font-size: 11px; }
.teacher-task-card__dates strong { color: var(--color-text-muted); font-weight: 600; }
.teacher-task-card__link { display: inline-flex; align-items: center; justify-self: start; gap: 7px; color: #117e9b; font-size: 12px; font-weight: 700; text-decoration: none; }
.teacher-task-card__link:hover { text-decoration: underline; text-underline-offset: 3px; }
.teacher-task-card__link:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 4px; border-radius: 3px; }
.teacher-class-demo-note { margin: -4px 2px 0; color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 560px) { .teacher-page-heading h1 { font-size: 20px; }.teacher-page-heading p { font-size: 12px; } }
@media (max-width: 900px) { .teacher-class-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }.teacher-task-card__metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 600px) { .teacher-class-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }.teacher-class-stat { min-height: 88px; padding: 13px; }.teacher-class-stat--rate { grid-column: 1 / -1; }.teacher-class-chart { padding: 16px; }.teacher-task-card { padding: 16px; }.teacher-task-card__header { flex-direction: column; }.teacher-task-card__badges { justify-content: flex-start; }.teacher-task-card__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.teacher-task-card__metrics .teacher-task-card__completion { grid-column: auto; } }
</style>
