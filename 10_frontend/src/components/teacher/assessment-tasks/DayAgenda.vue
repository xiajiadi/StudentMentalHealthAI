<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CalendarDays } from '@lucide/vue'
import type { PlannerAgendaItem } from '@/utils/teacher-assessment-planner'

const props = defineProps<{
  dateKey: string
  dateLabel: string
  items: PlannerAgendaItem[]
}>()

const emit = defineEmits<{
  'open-task': [taskKey: string]
}>()

const visibleCount = ref(8)
const visibleItems = computed(() => props.items.slice(0, visibleCount.value))
const itemCountLabel = computed(() => `${props.items.length} 项日程`)

watch(() => props.dateKey, () => { visibleCount.value = 8 })
watch(() => props.items.map((item) => item.key).join('|'), () => { visibleCount.value = 8 })

const eventText = (event: PlannerAgendaItem['events'][number]) => `${event.kind === 'start' ? '开始' : '截止'} ${event.timeLabel}`
</script>

<template>
  <section class="planner-agenda" aria-labelledby="planner-agenda-title">
    <header class="planner-agenda__header">
      <div>
        <span class="planner-agenda__eyebrow">当日日程</span>
        <h2 id="planner-agenda-title">{{ dateLabel }}</h2>
      </div>
      <span class="planner-agenda__count">{{ itemCountLabel }}</span>
    </header>

    <div v-if="!items.length" class="planner-agenda__empty" role="status">
      <span class="planner-agenda__empty-icon" aria-hidden="true"><CalendarDays :size="22" :stroke-width="1.8" /></span>
      <strong>当日没有任务安排</strong>
      <span>选择其他日期查看日程</span>
    </div>

    <div v-else class="planner-agenda__list" aria-label="当天任务">
      <button
        v-for="item in visibleItems"
        :key="item.key"
        type="button"
        class="planner-agenda-item"
        @click="emit('open-task', item.task.key)"
      >
        <span class="planner-agenda-item__events">
          <span
            v-for="event in item.events"
            :key="event.key"
            class="planner-agenda-item__time"
            :class="{
              'planner-agenda-item__time--due': event.kind === 'due',
              'planner-agenda-item__time--urgent': event.kind === 'due' && event.task.isDueSoon,
            }"
          >{{ eventText(event) }}</span>
        </span>
        <strong class="planner-agenda-item__name">{{ item.task.label }}</strong>
        <span class="planner-agenda-item__class">{{ item.task.classLabel }}</span>
        <span class="planner-agenda-item__footer">
          <span class="planner-task-status" :class="`planner-task-status--${item.task.phase}`">{{ item.task.phaseLabel }}</span>
          <span class="planner-agenda-item__completion">
            {{ item.task.completedCount }} / {{ item.task.activeCount }} 已完成
          </span>
        </span>
      </button>
    </div>

    <button v-if="items.length > visibleCount" class="planner-agenda__more" type="button" @click="visibleCount += 8">
      查看更多日程
    </button>
  </section>
</template>

<style scoped>
.planner-agenda { display: flex; min-width: 0; flex-direction: column; gap: 11px; padding: 15px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.planner-agenda__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 10px; border-bottom: 1px solid var(--color-border); }
.planner-agenda__eyebrow { color: var(--color-primary-active); font-size: 13px; font-weight: 650; }
.planner-agenda__header h2 { margin: 3px 0 0; color: var(--color-text-primary); font-size: 17px; line-height: 1.35; }
.planner-agenda__count { padding: 4px 7px; border-radius: 999px; color: var(--color-primary-active); background: var(--color-info-wash); font-size: 11px; white-space: nowrap; }
.planner-agenda__list { display: grid; align-content: start; gap: 8px; }
.planner-agenda-item { display: grid; gap: 5px; min-width: 0; padding: 10px 11px; border: 1px solid var(--color-border); border-radius: 9px; color: inherit; background: var(--color-surface); text-align: left; cursor: pointer; transition: border-color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.planner-agenda-item:hover { border-color: rgb(0 177 226 / 36%); background: var(--color-surface-blue); }
.planner-agenda-item:focus-visible,.planner-agenda__more:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.planner-agenda-item__events { display: flex; flex-wrap: wrap; gap: 4px; }
.planner-agenda-item__time { padding: 3px 6px; border-radius: 4px; color: #477b88; background: var(--color-support-wash); font-size: 11px; }
.planner-agenda-item__time--due { color: var(--color-primary-active); background: var(--color-info-wash); }
.planner-agenda-item__time--urgent { color: #8a5b17; background: var(--color-attention-wash); }
.planner-agenda-item__name { overflow: hidden; color: var(--color-text-primary); font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.planner-agenda-item__class { overflow: hidden; color: var(--color-text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.planner-agenda-item__footer { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; margin-top: 2px; }
.planner-task-status { display: inline-flex; max-width: 100%; align-items: center; overflow: hidden; padding: 4px 8px; border-radius: 999px; color: #19727d; background: var(--color-support-wash); font-size: 11px; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.planner-task-status--upcoming,.planner-task-status--unpublished { color: #236b88; background: var(--color-info-wash); }
.planner-task-status--ended,.planner-task-status--cancelled { color: var(--color-text-muted); background: var(--color-surface-skeleton); }
.planner-agenda-item__completion { color: var(--color-text-muted); font-size: 11px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.planner-agenda__empty { display: grid; min-height: 170px; align-content: center; justify-items: center; gap: 8px; padding: 16px; color: var(--color-text-muted); text-align: center; }
.planner-agenda__empty strong { color: var(--color-text-secondary); font-size: 14px; font-weight: 600; }
.planner-agenda__empty > span:last-child { font-size: 12px; }
.planner-agenda__empty-icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 11px; color: var(--color-primary-active); background: var(--color-info-wash); }
.planner-agenda__more { align-self: center; padding: 6px 9px; border: 0; border-radius: var(--radius-button); color: var(--color-primary-active); background: transparent; font-size: 10px; cursor: pointer; }
.planner-agenda__more:hover { background: var(--color-info-wash); }
</style>
