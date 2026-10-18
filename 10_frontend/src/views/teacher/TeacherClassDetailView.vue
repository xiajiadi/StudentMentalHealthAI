<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts/core'
import { ArrowRight, CalendarDays, ListChecks, RotateCcw } from '@lucide/vue'
import { useRoute } from 'vue-router'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import {
  formatTeacherDate,
  shortTeacherRef,
  summarizeTeacherClasses,
  taskCompletionRate,
  taskProgressCount,
  teacherTaskPhase,
  teacherTaskPhaseLabel,
  teacherTaskStatusLabel,
} from '@/utils/teacher-task-progress'
import { studentPageArt } from '@/data/student-feature-cards'

const route = useRoute()
const { state, rows, errorMessage, refresh } = useTeacherTaskProgress()
const classRef = computed(() => String(route.params.classRef ?? ''))
const summary = computed(() => summarizeTeacherClasses(rows.value).find((item) => item.classRef === classRef.value) ?? null)
const taskRoute = (taskRef: string) => `/teacher/tasks/${encodeURIComponent(classRef.value)}/${encodeURIComponent(taskRef)}`
const taskChartOption = computed<EChartsOption>(() => {
  const tasks = summary.value?.tasks ?? []
  return {
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 0, textStyle: { color: '#65727a', fontSize: 11 } },
    grid: { top: 38, right: 12, bottom: 30, left: 36, containLabel: true },
    xAxis: {
      type: 'category',
      data: tasks.map((task) => shortTeacherRef(task.task_ref)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dbe5e7' } },
      axisLabel: { color: '#75838a', fontSize: 10 },
    },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#75838a', fontSize: 10 }, splitLine: { lineStyle: { color: '#edf2f3' } } },
    series: [
      { name: '已完成', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map((task) => taskProgressCount(task, 'completed_count')), itemStyle: { color: '#27a0a6', borderRadius: [4, 4, 0, 0] } },
      { name: '待完成', type: 'bar', stack: 'events', barMaxWidth: 28, data: tasks.map((task) => Math.max(0, taskProgressCount(task, 'active_enrollment_count') - taskProgressCount(task, 'completed_count'))), itemStyle: { color: '#d8e9ea', borderRadius: [4, 4, 0, 0] } },
    ],
  }
})
const chartSummary = computed(() => {
  if (!summary.value) return '当前没有可显示的班级任务汇总。'
  return `图表展示 ${summary.value.taskCount} 项授权任务的已完成与待完成报名事件汇总。`
})
</script>

<template>
  <main class="content-wrap teacher-class-detail">
    <WorkspaceBreadcrumb
      homeLabel="教师工作区"
      homeTo="/teacher/overview"
      :parent="{ label: '班级进度', to: '/teacher/classes' }"
      :current="summary ? `班级 ${shortTeacherRef(summary.classRef)}` : '班级汇总'"
    />
    <StudentPageHero
      eyebrow="CLASS SUMMARY · SCOPE A"
      :title="summary ? `班级 ${shortTeacherRef(summary.classRef)}` : '班级任务汇总'"
      subtitle="仅汇总当前账号获授权任务的报名事件与完成进度。"
      :image="studentPageArt.educationSupport"
      image-position="center 48%"
      light-text
    />

    <AppStatusCallout
      tone="info"
      title="仅显示任务级汇总"
      body="页面不读取或展示学生身份、个人测评记录、作答、报告或对话内容。"
    />

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
        <AppCard class="teacher-class-stat"><span>有效报名事件</span><strong>{{ summary.activeEnrollmentCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat"><span>已完成事件</span><strong>{{ summary.completedCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat"><span>待完成事件</span><strong>{{ summary.pendingCount }}</strong></AppCard>
        <AppCard class="teacher-class-stat teacher-class-stat--rate"><span>汇总完成率</span><strong>{{ summary.completionRate }}%</strong></AppCard>
      </section>

      <AppCard class="teacher-class-chart">
        <div class="teacher-class-section-heading">
          <span class="teacher-class-section-heading__icon"><ListChecks :size="18" aria-hidden="true" /></span>
          <div><h2>任务完成概览</h2><p>每个柱形按任务展示已完成与待完成报名事件。</p></div>
        </div>
        <TeacherProgressChart
          :option="taskChartOption"
          label="班级内各授权任务已完成和待完成报名事件的堆叠柱状图"
          :summary="chartSummary"
          :height="250"
        />
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
              <div><span class="teacher-task-card__eyebrow">授权任务</span><h3>任务 {{ shortTeacherRef(task.task_ref) }}</h3></div>
              <div class="teacher-task-card__badges">
                <span class="teacher-task-card__phase" :class="`teacher-task-card__phase--${teacherTaskPhase(task)}`">{{ teacherTaskPhaseLabel(teacherTaskPhase(task)) }}</span>
                <span class="teacher-task-card__status">{{ teacherTaskStatusLabel(task.task_status) }}</span>
              </div>
            </div>
            <dl class="teacher-task-card__metrics">
              <div><dt>有效报名事件</dt><dd>{{ taskProgressCount(task, 'active_enrollment_count') }}</dd></div>
              <div><dt>已完成</dt><dd>{{ taskProgressCount(task, 'completed_count') }}</dd></div>
              <div><dt>待完成</dt><dd>{{ Math.max(0, taskProgressCount(task, 'active_enrollment_count') - taskProgressCount(task, 'completed_count')) }}</dd></div>
              <div><dt>已撤销</dt><dd>{{ taskProgressCount(task, 'revoked_enrollment_count') }}</dd></div>
              <div class="teacher-task-card__completion"><dt>任务完成率</dt><dd>{{ taskCompletionRate(task) }}%</dd></div>
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
    </template>
  </main>
</template>

<style scoped>
.teacher-class-detail { display: grid; gap: 16px; padding-top: 0; padding-bottom: 56px; animation: page-in 220ms ease both; }
.teacher-class-detail :deep(.student-page-hero) { margin-bottom: 0; }
.teacher-class-detail__state { display: grid; min-height: 120px; place-items: center; padding: 20px; color: var(--color-text-secondary); text-align: center; }
.teacher-class-stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.teacher-class-stat { display: grid; align-content: center; gap: 8px; min-width: 0; min-height: 104px; padding: 16px; }
.teacher-class-stat span { color: var(--color-text-muted); font-size: 11px; line-height: 1.4; }
.teacher-class-stat strong { color: var(--color-text-primary); font-size: clamp(20px, 2.2vw, 27px); font-weight: 700; font-variant-numeric: tabular-nums; }
.teacher-class-stat--rate strong { color: #147f8e; }
.teacher-class-chart { display: grid; gap: 14px; padding: 20px; }
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
.teacher-task-card__metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin: 0; }
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
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 900px) { .teacher-class-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }.teacher-task-card__metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 600px) { .teacher-class-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }.teacher-class-stat { min-height: 88px; padding: 13px; }.teacher-class-stat--rate { grid-column: 1 / -1; }.teacher-class-chart { padding: 16px; }.teacher-task-card { padding: 16px; }.teacher-task-card__header { flex-direction: column; }.teacher-task-card__badges { justify-content: flex-start; }.teacher-task-card__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }.teacher-task-card__metrics .teacher-task-card__completion { grid-column: auto; } }
</style>
