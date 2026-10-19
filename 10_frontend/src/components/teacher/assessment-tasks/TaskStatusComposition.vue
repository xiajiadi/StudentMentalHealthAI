<script setup lang="ts">
import { computed, type Component } from 'vue'
import { Activity, CalendarDays, Check, Clock3, RotateCcw } from '@lucide/vue'
import type { PlannerTask } from '@/utils/teacher-assessment-planner'

const props = defineProps<{ task: PlannerTask }>()

interface StatusSegment {
  key: 'completed' | 'in-progress' | 'not-started' | 'ended'
  label: string
  value: number
  icon: Component
}

const segments = computed<StatusSegment[]>(() => [
  { key: 'completed', label: '已完成', value: props.task.completedCount, icon: Check },
  { key: 'in-progress', label: '进行中', value: props.task.inProgressCount, icon: Activity },
  { key: 'not-started', label: '尚未开始', value: props.task.notStartedCount, icon: CalendarDays },
  { key: 'ended', label: '已结束或不可继续', value: props.task.endedCount, icon: Clock3 },
])

const statusTotal = computed(() => segments.value.reduce((sum, segment) => sum + segment.value, 0))
const widthFor = (value: number) => `${statusTotal.value ? value / statusTotal.value * 100 : 0}%`
</script>

<template>
  <section class="task-status-composition" aria-labelledby="task-status-composition-title">
    <header class="task-status-composition__header">
      <h3 id="task-status-composition-title">任务状态构成</h3>
      <span>共 {{ statusTotal }} 人次</span>
    </header>

    <div class="task-status-composition__bar" aria-hidden="true">
      <span
        v-for="segment in segments"
        :key="segment.key"
        class="task-status-composition__segment"
        :class="`task-status-composition__segment--${segment.key}`"
        :style="{ width: widthFor(segment.value) }"
      ></span>
    </div>

    <ul class="task-status-composition__grid">
      <li
        v-for="segment in segments"
        :key="segment.key"
        class="task-status-composition__item"
        :class="`task-status-composition__item--${segment.key}`"
      >
        <span class="task-status-composition__icon" aria-hidden="true">
          <component :is="segment.icon" :size="16" :stroke-width="2" />
        </span>
        <span class="task-status-composition__copy">
          <span>{{ segment.label }}</span>
          <strong>{{ segment.value }}<small> 人次</small></strong>
        </span>
      </li>
    </ul>

    <div class="task-status-composition__revoked">
      <RotateCcw :size="14" aria-hidden="true" />
      <span>已撤销报名</span>
      <strong>{{ task.revokedCount }} 人次</strong>
      <small>不计入有效报名</small>
    </div>
  </section>
</template>

<style scoped>
.task-status-composition { display: grid; gap: 11px; }
.task-status-composition__header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.task-status-composition__header h3 { margin: 0; color: var(--color-text-primary); font-size: 13px; font-weight: 650; }
.task-status-composition__header > span { color: var(--color-text-muted); font-size: 10px; font-variant-numeric: tabular-nums; }
.task-status-composition__bar { display: flex; height: 12px; overflow: hidden; border-radius: 999px; background: var(--color-surface-skeleton); }
.task-status-composition__segment { height: 100%; min-width: 0; transition: width var(--motion-normal) ease; }
.task-status-composition__segment--completed { background: var(--color-primary); }
.task-status-composition__segment--in-progress { background: #42a792; }
.task-status-composition__segment--not-started { background: #a8cfe1; }
.task-status-composition__segment--ended { background: var(--color-attention); }
.task-status-composition__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0; list-style: none; }
.task-status-composition__item { display: flex; min-width: 0; min-height: 57px; align-items: center; gap: 9px; padding: 9px 10px; border: 1px solid var(--color-border); border-radius: 9px; background: var(--color-surface); }
.task-status-composition__icon { display: inline-grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border-radius: 8px; color: var(--color-primary-active); background: var(--color-info-wash); }
.task-status-composition__item--in-progress .task-status-composition__icon { color: #19727d; background: var(--color-support-wash); }
.task-status-composition__item--not-started .task-status-composition__icon { color: #477b88; background: #edf6fa; }
.task-status-composition__item--ended .task-status-composition__icon { color: #8a5b17; background: var(--color-attention-wash); }
.task-status-composition__copy { display: grid; min-width: 0; gap: 2px; color: var(--color-text-muted); font-size: 10px; }
.task-status-composition__copy > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-status-composition__copy strong { color: var(--color-text-primary); font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
.task-status-composition__copy small { color: var(--color-text-muted); font-size: 9px; font-weight: 400; }
.task-status-composition__revoked { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 8px 10px; border-radius: 8px; color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 10px; }
.task-status-composition__revoked svg { color: var(--color-text-muted); }
.task-status-composition__revoked strong { color: var(--color-text-primary); font-variant-numeric: tabular-nums; }
.task-status-composition__revoked small { margin-left: auto; color: var(--color-text-muted); font-size: 9px; }
@media (prefers-reduced-motion: reduce) { .task-status-composition__segment { transition: none; } }
</style>
