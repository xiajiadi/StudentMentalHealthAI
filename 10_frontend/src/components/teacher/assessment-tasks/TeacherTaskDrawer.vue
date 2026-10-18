<script setup lang="ts">
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import { X } from '@lucide/vue'
import TaskProgressRing from '@/components/teacher/assessment-tasks/TaskProgressRing.vue'
import { type PlannerTask } from '@/utils/teacher-assessment-planner'

defineProps<{
  open: boolean
  task: PlannerTask | null
  isDemo?: boolean
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
              <div class="teacher-task-drawer__breadcrumb"><span>测评任务</span><span aria-hidden="true">/</span><span>查看详情</span></div>
              <span class="teacher-task-drawer__eyebrow">{{ isDemo ? '合成数据预览' : '授权任务 · 只读' }}</span>
              <DialogTitle class="teacher-task-drawer__title">{{ task.label }}</DialogTitle>
              <DialogDescription class="teacher-task-drawer__description">
                {{ task.classLabel }} · {{ task.phaseLabel }} · {{ task.row.task_status }}
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
                <small>有效报名中的整体进度</small>
              </div>
            </section>

            <dl class="teacher-task-drawer__facts">
              <div><dt>开始时间</dt><dd>{{ formatMoment(task.opensAt, '未设置开始时间') }}</dd></div>
              <div><dt>截止时间</dt><dd>{{ formatMoment(task.dueAt, '未设置截止时间') }}</dd></div>
              <div><dt>任务状态</dt><dd><span class="planner-task-status" :class="`planner-task-status--${task.phase}`">{{ task.phaseLabel }}</span></dd></div>
              <div><dt>有效报名</dt><dd>{{ task.activeCount }} 人次</dd></div>
              <div><dt>已完成</dt><dd>{{ task.completedCount }} 人次</dd></div>
              <div><dt>进行中</dt><dd>{{ task.inProgressCount }} 人次</dd></div>
              <div><dt>尚未开始</dt><dd>{{ task.notStartedCount }} 人次</dd></div>
              <div><dt>已结束 / 不可继续</dt><dd>{{ task.endedCount }} 人次</dd></div>
              <div v-if="task.revokedCount > 0"><dt>已撤销报名</dt><dd>{{ task.revokedCount }} 人次</dd></div>
            </dl>

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
.teacher-task-drawer__breadcrumb { display: flex; align-items: center; gap: 7px; color: var(--color-text-muted); font-size: 10px; }
.teacher-task-drawer__eyebrow { color: var(--color-primary-active); font-size: 9px; font-weight: 700; letter-spacing: .08em; }
.teacher-task-drawer__title { color: var(--color-text-primary); font-size: 21px; font-weight: 700; line-height: 1.3; overflow-wrap: anywhere; }
.teacher-task-drawer__description { color: var(--color-text-secondary); font-size: 11px; line-height: 1.45; }
.teacher-task-drawer__close { display: inline-grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid transparent; border-radius: 9px; color: var(--color-text-muted); background: var(--color-surface-blue); cursor: pointer; }
.teacher-task-drawer__close:hover { border-color: var(--color-border-strong); color: var(--color-primary-active); }
.teacher-task-drawer__close:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.teacher-task-drawer__body { display: grid; align-content: start; gap: 18px; padding: 18px 20px 24px; }
.teacher-task-drawer__completion { display: flex; min-height: 132px; align-items: center; justify-content: center; gap: 18px; padding: 10px; border-bottom: 1px solid var(--color-border); }
.teacher-task-drawer__completion-copy { display: grid; gap: 4px; color: var(--color-text-muted); font-size: 12px; }
.teacher-task-drawer__completion-copy strong { color: var(--color-text-primary); font-size: 13px; }
.teacher-task-drawer__completion-copy > span { color: var(--color-primary-active); font-size: 14px; font-weight: 650; font-variant-numeric: tabular-nums; }
.teacher-task-drawer__completion-copy small { color: var(--color-text-muted); font-size: 10px; }
.teacher-task-drawer__facts { display: grid; margin: 0; }
.teacher-task-drawer__facts > div { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 12px; min-height: 43px; padding: 8px 0; border-bottom: 1px solid var(--color-border); }
.teacher-task-drawer__facts dt { color: var(--color-text-muted); font-size: 11px; }
.teacher-task-drawer__facts dd { margin: 0; color: var(--color-text-primary); font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; overflow-wrap: anywhere; }
.teacher-task-drawer__facts .planner-task-status { font-weight: 500; }
.planner-task-status { display: inline-flex; align-items: center; padding: 3px 7px; border-radius: 999px; color: #19727d; background: var(--color-support-wash); font-size: 9px; line-height: 1.25; }
.planner-task-status--upcoming,.planner-task-status--unpublished { color: #236b88; background: var(--color-info-wash); }
.planner-task-status--ended,.planner-task-status--cancelled { color: var(--color-text-muted); background: var(--color-surface-skeleton); }
.teacher-task-drawer__scope { padding: 12px; border-radius: 9px; color: var(--color-text-secondary); background: var(--color-surface-blue); font-size: 10px; line-height: 1.65; }
@keyframes drawer-in { from { opacity: .85; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
@media (max-width: 560px) { .teacher-task-drawer__header { padding: 16px 14px 13px; }.teacher-task-drawer__body { padding: 15px 14px 22px; }.teacher-task-drawer__title { font-size: 19px; } }
@media (prefers-reduced-motion: reduce) { .teacher-task-drawer__content { animation: none; } }
</style>
