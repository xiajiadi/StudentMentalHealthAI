<script setup lang="ts">
import { ref, watch } from 'vue'
import TaskProgressRing from '@/components/teacher/assessment-tasks/TaskProgressRing.vue'
import { formatPlannerDate, type PlannerFilterPhase, type PlannerTask } from '@/utils/teacher-assessment-planner'

export interface PlannerLane {
  phase: Exclude<PlannerFilterPhase, 'all'>
  label: string
  tasks: PlannerTask[]
}

const props = defineProps<{
  lanes: PlannerLane[]
  selectedTaskKey: string
}>()

const emit = defineEmits<{
  'open-task': [taskKey: string]
}>()

const pageSizes = ref<Record<string, number>>({})
const laneSignature = () => props.lanes.map((lane) => `${lane.phase}:${lane.tasks.map((task) => task.key).join(',')}`).join('|')
const visibleTasks = (lane: PlannerLane) => lane.tasks.slice(0, pageSizes.value[lane.phase] ?? 8)
const showMore = (phase: PlannerLane['phase']) => { pageSizes.value[phase] = (pageSizes.value[phase] ?? 8) + 8 }
const taskPeriod = (task: PlannerTask) => `${formatPlannerDate(task.opensAt, '未设置开始日期')} — ${formatPlannerDate(task.dueAt, '未设置截止日期')}`

watch(laneSignature, () => { pageSizes.value = {} })
</script>

<template>
  <section class="planner-kanban" aria-label="测评任务看板">
    <div class="planner-kanban__lanes" :style="{ '--lane-count': lanes.length }">
      <section v-for="lane in lanes" :key="lane.phase" class="planner-kanban-lane" :class="`planner-kanban-lane--${lane.phase}`" :aria-label="`${lane.label} ${lane.tasks.length} 项`">
        <header class="planner-kanban-lane__header">
          <span class="planner-kanban-lane__mark" aria-hidden="true"></span>
          <h2>{{ lane.label }}</h2>
          <span class="planner-kanban-lane__count">{{ lane.tasks.length }}</span>
        </header>

        <div v-if="lane.tasks.length" class="planner-kanban-lane__cards">
          <button
            v-for="task in visibleTasks(lane)"
            :key="task.key"
            type="button"
            class="planner-kanban-card"
            :class="{ 'planner-kanban-card--selected': selectedTaskKey === task.key }"
            :aria-label="`${task.label}，${task.classLabel}，${task.phaseLabel}，${task.completionRate === null ? '没有有效报名' : `${task.completionRate}% 完成`}，已完成 ${task.completedCount} / ${task.activeCount} 人次`"
            @click="emit('open-task', task.key)"
          >
            <span class="planner-kanban-card__top">
              <strong class="planner-kanban-card__name">{{ task.label }}</strong>
              <TaskProgressRing :rate="task.completionRate" :label="`${task.label}完成率`" :size="56" />
            </span>
            <span class="planner-kanban-card__class">{{ task.classLabel }}</span>
            <span class="planner-kanban-card__dates">{{ taskPeriod(task) }}</span>
            <span class="planner-kanban-card__footer">
              <span class="planner-task-status" :class="`planner-task-status--${task.phase}`">{{ task.phaseLabel }}</span>
              <span class="planner-kanban-card__progress">{{ task.completedCount }} / {{ task.activeCount }}</span>
            </span>
          </button>
          <button v-if="lane.tasks.length > visibleTasks(lane).length" class="planner-kanban-lane__more" type="button" @click="showMore(lane.phase)">
            再显示 8 项
          </button>
        </div>

        <div v-else class="planner-kanban-lane__empty" role="status">当前没有此阶段任务</div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.planner-kanban { min-width: 0; }
.planner-kanban__lanes { display: grid; grid-template-columns: repeat(var(--lane-count), minmax(0, 1fr)); align-items: start; gap: 12px; }
.planner-kanban-lane { display: grid; min-width: 0; gap: 10px; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface-blue); }
.planner-kanban-lane__header { display: flex; min-width: 0; align-items: center; gap: 8px; padding: 0 2px 2px; }
.planner-kanban-lane__mark { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: #8ba0ad; }
.planner-kanban-lane--in_progress .planner-kanban-lane__mark { background: var(--color-primary); }
.planner-kanban-lane--upcoming .planner-kanban-lane__mark { background: #65adbf; }
.planner-kanban-lane--ended .planner-kanban-lane__mark,.planner-kanban-lane--cancelled .planner-kanban-lane__mark,.planner-kanban-lane--unpublished .planner-kanban-lane__mark { background: #8c929c; }
.planner-kanban-lane__header h2 { overflow: hidden; flex: 1; margin: 0; color: var(--color-text-primary); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.planner-kanban-lane__count { display: inline-grid; min-width: 23px; height: 23px; place-items: center; padding: 0 6px; border-radius: 999px; color: var(--color-text-secondary); background: var(--color-surface); font-size: 10px; font-variant-numeric: tabular-nums; }
.planner-kanban-lane__cards { display: grid; align-content: start; gap: 8px; }
.planner-kanban-card { display: grid; min-width: 0; min-height: 146px; gap: 7px; padding: 12px; border: 1px solid var(--color-border); border-radius: 10px; color: inherit; background: var(--color-surface); text-align: left; cursor: pointer; transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease, transform var(--motion-fast) ease; }
.planner-kanban-card:hover { border-color: rgb(0 177 226 / 48%); box-shadow: 0 5px 16px rgb(0 0 0 / 5%); transform: translateY(-1px); }
.planner-kanban-card:focus-visible,.planner-kanban-lane__more:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.planner-kanban-card--selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px rgb(0 177 226 / 10%); }
.planner-kanban-card__top { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 8px; }
.planner-kanban-card__name { overflow: hidden; min-width: 0; padding-top: 2px; color: var(--color-text-primary); font-size: 12px; font-weight: 650; line-height: 1.4; text-overflow: ellipsis; }
.planner-kanban-card__class,.planner-kanban-card__dates { overflow: hidden; color: var(--color-text-muted); font-size: 10px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.planner-kanban-card__footer { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
.planner-kanban-card__progress { color: var(--color-text-muted); font-size: 10px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.planner-task-status { display: inline-flex; max-width: 100%; align-items: center; overflow: hidden; padding: 3px 7px; border-radius: 999px; color: #19727d; background: var(--color-support-wash); font-size: 9px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.planner-task-status--upcoming,.planner-task-status--unpublished { color: #236b88; background: var(--color-info-wash); }
.planner-task-status--ended,.planner-task-status--cancelled { color: var(--color-text-muted); background: var(--color-surface-skeleton); }
.planner-kanban-lane__more { min-height: 32px; border: 1px dashed var(--color-border-strong); border-radius: 8px; color: var(--color-primary-active); background: transparent; font-size: 10px; cursor: pointer; }
.planner-kanban-lane__more:hover { background: var(--color-info-wash); }
.planner-kanban-lane__empty { display: grid; min-height: 94px; place-items: center; padding: 12px; border: 1px dashed var(--color-border-strong); border-radius: 9px; color: var(--color-text-muted); font-size: 10px; text-align: center; }
@media (max-width: 980px) { .planner-kanban__lanes { grid-template-columns: repeat(2, minmax(230px, 1fr)); } }
@media (max-width: 560px) { .planner-kanban__lanes { grid-template-columns: repeat(var(--lane-count), minmax(240px, 1fr)); overflow-x: auto; padding-bottom: 6px; } }
@media (prefers-reduced-motion: reduce) { .planner-kanban-card { transition: none; } }
</style>
