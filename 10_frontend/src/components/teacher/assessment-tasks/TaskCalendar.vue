<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { buildCalendarCells, type PlannerEvent } from '@/utils/teacher-assessment-planner'

const props = defineProps<{
  month: Date
  eventsByDate: Map<string, PlannerEvent[]>
  todayKey: string
  selectedDate: string
}>()

const emit = defineEmits<{
  'select-date': [dateKey: string]
  'change-month': [offset: number]
  'go-today': []
  'open-task': [taskKey: string]
}>()

const weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const monthTitle = computed(() => new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long' }).format(props.month))
const cells = computed(() => buildCalendarCells(props.month, props.eventsByDate, props.todayKey, props.selectedDate))
const weeks = computed(() => Array.from({ length: cells.value.length / 7 }, (_, index) => cells.value.slice(index * 7, index * 7 + 7)))
const eventLabel = (event: PlannerEvent) => `${event.kind === 'start' ? '开始' : '截止'}：${event.task.label}，${event.task.classLabel}，${event.timeLabel}`

const selectDate = (dateKey: string) => emit('select-date', dateKey)
</script>

<template>
  <section class="planner-calendar" aria-label="测评任务日历">
    <header class="planner-calendar__header">
      <h2>{{ monthTitle }}</h2>
      <div class="planner-calendar__navigation" aria-label="月份导航">
        <button type="button" aria-label="上个月" @click="emit('change-month', -1)"><ChevronLeft :size="16" aria-hidden="true" /></button>
        <button type="button" class="planner-calendar__today" @click="emit('go-today')">今天</button>
        <button type="button" aria-label="下个月" @click="emit('change-month', 1)"><ChevronRight :size="16" aria-hidden="true" /></button>
      </div>
    </header>

    <div class="planner-calendar__weekdays" role="row">
      <div v-for="weekday in weekdays" :key="weekday" role="columnheader">{{ weekday }}</div>
    </div>

    <div class="planner-calendar__weeks" role="grid" :aria-label="`${monthTitle}任务日历`">
      <div v-for="(week, weekIndex) in weeks" :key="weekIndex" class="planner-calendar__week" role="row">
        <div
          v-for="cell in week"
          :key="cell.dateKey"
          class="planner-calendar__day"
          :class="{
            'planner-calendar__day--outside': !cell.inCurrentMonth,
            'planner-calendar__day--selected': cell.isSelected,
            'planner-calendar__day--today': cell.isToday,
          }"
          role="gridcell"
          :aria-selected="cell.isSelected"
        >
          <button
            type="button"
            class="planner-calendar__date"
            :aria-label="`${cell.dateKey}，${(props.eventsByDate.get(cell.dateKey) ?? []).length} 项日程`"
            :aria-pressed="cell.isSelected"
            @click="selectDate(cell.dateKey)"
          >{{ cell.dayNumber }}</button>
          <div class="planner-calendar__events" :aria-label="`${cell.dateKey}的任务`">
            <button
              v-for="event in cell.events"
              :key="event.key"
              type="button"
              class="planner-calendar-event"
              :class="[
                `planner-calendar-event--${event.kind}`,
                `planner-calendar-event--${event.task.phase}`,
                { 'planner-calendar-event--urgent': event.kind === 'due' && event.task.isDueSoon },
              ]"
              :aria-label="eventLabel(event)"
              @click.stop="emit('open-task', event.task.key)"
            >
              <span class="planner-calendar-event__kind">{{ event.kind === 'start' ? '始' : '止' }} ·</span>
              <span class="planner-calendar-event__name">{{ event.task.label }}</span>
            </button>
            <button
              v-if="cell.moreCount"
              type="button"
              class="planner-calendar__more"
              :aria-label="`查看${cell.dateKey}另外 ${cell.moreCount} 项日程`"
              @click.stop="selectDate(cell.dateKey)"
            >+{{ cell.moreCount }} 项</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.planner-calendar { min-width: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.planner-calendar__header { display: flex; min-height: 62px; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--color-border); }
.planner-calendar__header h2 { margin: 0; color: var(--color-text-primary); font-size: 18px; font-weight: 650; line-height: 1.3; }
.planner-calendar__navigation { display: flex; align-items: center; gap: 5px; }
.planner-calendar__navigation button { display: inline-flex; min-width: 32px; min-height: 30px; align-items: center; justify-content: center; padding: 0 8px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-secondary); background: var(--color-surface); font-size: 11px; cursor: pointer; transition: background-color var(--motion-fast) ease, border-color var(--motion-fast) ease, color var(--motion-fast) ease; }
.planner-calendar__navigation button:hover { border-color: var(--color-primary); color: var(--color-primary-active); background: var(--color-info-wash); }
.planner-calendar__navigation .planner-calendar__today { min-width: 42px; }
.planner-calendar__weekdays,.planner-calendar__week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.planner-calendar__weekdays { min-height: 34px; align-items: center; border-bottom: 1px solid var(--color-border); color: var(--color-text-muted); background: var(--color-surface-soft); font-size: 10px; text-align: center; }
.planner-calendar__weeks { display: grid; }
.planner-calendar__day { display: flex; min-width: 0; min-height: 90px; flex-direction: column; gap: 3px; padding: 6px 5px; border-right: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); background: var(--color-surface); transition: background-color var(--motion-fast) ease; }
.planner-calendar__day:nth-child(7) { border-right: 0; }
.planner-calendar__day--outside { background: var(--color-surface-soft); }
.planner-calendar__day--selected { background: var(--color-surface-blue); box-shadow: inset 0 0 0 1px var(--color-primary); }
.planner-calendar__date { display: inline-grid; width: 22px; height: 22px; flex: 0 0 22px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 6px; color: var(--color-text-secondary); background: transparent; font-size: 11px; font-variant-numeric: tabular-nums; cursor: pointer; }
.planner-calendar__day--outside .planner-calendar__date { color: #9aa3ad; }
.planner-calendar__day--today .planner-calendar__date { color: #fff; border-color: var(--color-primary-active); background: var(--color-primary-active); font-weight: 700; }
.planner-calendar__day--selected:not(.planner-calendar__day--today) .planner-calendar__date { color: var(--color-primary-active); border-color: rgb(0 177 226 / 26%); background: var(--color-surface); font-weight: 700; }
.planner-calendar__events { display: grid; min-width: 0; align-content: start; gap: 3px; }
.planner-calendar-event { display: flex; min-width: 0; height: 18px; align-items: center; gap: 3px; overflow: hidden; padding: 0 4px; border: 0; border-radius: 4px; color: #477b88; background: var(--color-support-wash); font-size: 9px; line-height: 1; text-align: left; cursor: pointer; }
.planner-calendar-event--due { color: var(--color-primary-active); background: var(--color-info-wash); }
.planner-calendar-event--urgent { color: #8a5b17; background: var(--color-attention-wash); }
.planner-calendar-event--cancelled,.planner-calendar-event--unpublished { color: var(--color-text-muted); background: var(--color-surface-skeleton); text-decoration: line-through; }
.planner-calendar-event__kind { flex: 0 0 auto; font-size: 8px; font-weight: 700; }
.planner-calendar-event__name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.planner-calendar-event:hover { filter: saturate(1.18); }
.planner-calendar__more { width: fit-content; padding: 1px 3px; border: 0; color: var(--color-primary-active); background: transparent; font-size: 9px; text-align: left; cursor: pointer; }
.planner-calendar__more:hover { text-decoration: underline; }
.planner-calendar__date:focus-visible,.planner-calendar-event:focus-visible,.planner-calendar__more:focus-visible,.planner-calendar__navigation button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
@media (max-width: 560px) {
  .planner-calendar__header { min-height: 54px; padding: 10px 11px; }
  .planner-calendar__header h2 { font-size: 16px; }
  .planner-calendar__weekdays { min-height: 31px; font-size: 9px; }
  .planner-calendar__day { min-height: 76px; padding: 4px 2px; }
  .planner-calendar__date { width: 20px; height: 20px; flex-basis: 20px; font-size: 10px; }
  .planner-calendar-event { height: 18px; gap: 2px; padding: 0 2px; font-size: 8px; }
  .planner-calendar-event__kind { font-size: 8px; }
  .planner-calendar-event__name { display: none; }
  .planner-calendar__more { padding-left: 1px; font-size: 8px; }
}
@media (prefers-reduced-motion: reduce) { .planner-calendar__navigation button { transition: none; } }
</style>
