<script setup lang="ts">
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { CalendarDays, X } from '@lucide/vue'
import TaskProgressRing from '@/components/teacher/assessment-tasks/TaskProgressRing.vue'
import TaskStatusComposition from '@/components/teacher/assessment-tasks/TaskStatusComposition.vue'
import { type PlannerTask } from '@/utils/teacher-assessment-planner'
import { teacherTaskStatusLabel } from '@/utils/teacher-task-progress'

defineProps<{
  open: boolean
  task: PlannerTask | null
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

const formatMoment = (date: Date | null, emptyLabel: string) => {
  if (!date) return emptyLabel
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date)
}
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="teacher-task-drawer__overlay" />
      <DialogContent class="teacher-task-drawer__content">
        <template v-if="task">
          <header class="teacher-task-drawer__header">
            <div class="teacher-task-drawer__heading">
              <DialogTitle class="teacher-task-drawer__title">{{ task.label }}</DialogTitle>
              <DialogDescription class="teacher-task-drawer__description">
                <span>{{ task.classLabel }}</span>
                <span>{{ task.phaseLabel }}</span>
                <span>{{ teacherTaskStatusLabel(task.row.task_status) }}</span>
              </DialogDescription>
            </div>
            <DialogClose as-child>
              <button type="button" class="teacher-task-drawer__close" aria-label="关闭任务详情"><X :size="17" aria-hidden="true" /></button>
            </DialogClose>
          </header>

          <div class="teacher-task-drawer__body">
            <section class="teacher-task-drawer__completion" aria-label="任务完成进度">
              <TaskProgressRing :rate="task.completionRate" :label="`${task.label}完成率`" :size="112" />
              <div class="teacher-task-drawer__completion-copy">
                <strong>已完成</strong>
                <span>{{ task.completedCount }} / {{ task.activeCount }} 人次</span>
              </div>
            </section>

            <section class="teacher-task-drawer__timeline" aria-labelledby="teacher-task-timeline-title">
              <header class="teacher-task-drawer__section-heading">
                <CalendarDays :size="16" aria-hidden="true" />
                <h3 id="teacher-task-timeline-title">任务时间</h3>
              </header>
              <ol class="teacher-task-timeline">
                <li>
                  <span class="teacher-task-timeline__marker teacher-task-timeline__marker--start" aria-hidden="true"></span>
                  <span class="teacher-task-timeline__label">开始时间</span>
                  <strong>{{ formatMoment(task.opensAt, '未设置开始时间') }}</strong>
                </li>
                <li>
                  <span class="teacher-task-timeline__marker teacher-task-timeline__marker--due" aria-hidden="true"></span>
                  <span class="teacher-task-timeline__label">截止时间</span>
                  <strong>{{ formatMoment(task.dueAt, '未设置截止时间') }}</strong>
                </li>
              </ol>
            </section>

            <TaskStatusComposition :task="task" />

            <aside class="teacher-task-drawer__scope">
              当前教师仅查看授权任务的整体进度，任务创建、调整及发布由学校管理员负责；不展示学生个人测评结果、作答或心理记录
            </aside>
          </div>
        </template>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.teacher-task-drawer__overlay { position: fixed; inset: 0; z-index: 80; background: rgb(23 32 51 / 34%); }
.teacher-task-drawer__content { position: fixed; inset: 0 0 0 auto; z-index: 90; display: flex; width: min(440px, 100vw); max-height: 100dvh; flex-direction: column; overflow: auto; border-left: 1px solid var(--color-border); background: var(--color-surface); box-shadow: -12px 0 38px rgb(23 32 51 / 12%); outline: 0; animation: drawer-in var(--motion-normal) ease both; }
.teacher-task-drawer__header { position: sticky; top: 0; z-index: 1; display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px 20px 15px; border-bottom: 1px solid var(--color-border); background: var(--color-surface); }
.teacher-task-drawer__heading { display: grid; min-width: 0; gap: 8px; }
.teacher-task-drawer__title { color: var(--color-text-primary); font-size: 21px; font-weight: 700; line-height: 1.3; overflow-wrap: anywhere; }
.teacher-task-drawer__description { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.45; }
.teacher-task-drawer__description span { padding: 4px 8px; border-radius: 999px; background: var(--color-surface-blue); }
.teacher-task-drawer__close { display: inline-grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid transparent; border-radius: 9px; color: var(--color-text-muted); background: var(--color-surface-blue); cursor: pointer; }
.teacher-task-drawer__close:hover { border-color: var(--color-border-strong); color: var(--color-primary-active); }
.teacher-task-drawer__close:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.teacher-task-drawer__body { display: grid; align-content: start; gap: 16px; padding: 18px 20px 24px; }
.teacher-task-drawer__completion { display: flex; min-height: 132px; align-items: center; justify-content: center; gap: 18px; padding: 10px; border-bottom: 1px solid var(--color-border); }
.teacher-task-drawer__completion-copy { display: grid; gap: 4px; color: var(--color-text-muted); font-size: 12px; }
.teacher-task-drawer__completion-copy strong { color: var(--color-text-primary); font-size: 14px; }
.teacher-task-drawer__completion-copy > span { color: var(--color-primary-active); font-size: 15px; font-weight: 650; font-variant-numeric: tabular-nums; }
.teacher-task-drawer__section-heading { display: flex; align-items: center; gap: 7px; color: var(--color-primary-active); }
.teacher-task-drawer__section-heading h3 { margin: 0; color: var(--color-text-primary); font-size: 13px; font-weight: 650; }
.teacher-task-drawer__timeline { display: grid; gap: 11px; padding: 0 2px; }
.teacher-task-timeline { display: grid; gap: 0; margin: 0; padding: 0 0 0 4px; list-style: none; }
.teacher-task-timeline li { position: relative; display: grid; min-width: 0; grid-template-columns: 13px minmax(0, 1fr) auto; align-items: center; gap: 9px; min-height: 41px; }
.teacher-task-timeline li + li { border-top: 1px solid var(--color-border); }
.teacher-task-timeline__marker { position: relative; z-index: 1; width: 9px; height: 9px; border: 2px solid #68aa97; border-radius: 50%; background: var(--color-surface); }
.teacher-task-timeline li:first-child .teacher-task-timeline__marker::after { position: absolute; top: 7px; left: 50%; width: 1px; height: 32px; background: var(--color-border-strong); content: ''; }
.teacher-task-timeline__marker--due { border-color: var(--color-primary); }
.teacher-task-timeline__label { color: var(--color-text-muted); font-size: 11px; }
.teacher-task-timeline strong { color: var(--color-text-primary); font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.teacher-task-drawer__scope { padding: 12px; border-radius: 9px; color: var(--color-text-secondary); background: var(--color-surface-blue); font-size: 10px; line-height: 1.65; }
@keyframes drawer-in { from { opacity: .85; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
@media (max-width: 560px) { .teacher-task-drawer__header { padding: 16px 14px 13px; }.teacher-task-drawer__body { padding: 15px 14px 22px; }.teacher-task-drawer__title { font-size: 19px; } }
@media (prefers-reduced-motion: reduce) { .teacher-task-drawer__content { animation: none; } }
</style>
