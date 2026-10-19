<script setup lang="ts">
import { X } from '@lucide/vue'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'

withDefaults(defineProps<{
  open: boolean
  title: string
  description?: string
  closeLabel?: string
}>(), {
  description: undefined,
  closeLabel: '关闭详情',
})

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="workspace-sheet__overlay" />
      <DialogContent class="workspace-sheet__panel">
        <header class="workspace-sheet__header">
          <div class="workspace-sheet__heading">
            <DialogTitle class="workspace-sheet__title">{{ title }}</DialogTitle>
            <DialogDescription v-if="description" class="workspace-sheet__description">{{ description }}</DialogDescription>
          </div>
          <DialogClose as-child>
            <button class="workspace-sheet__close" type="button" :aria-label="closeLabel">
              <X :size="18" aria-hidden="true" />
            </button>
          </DialogClose>
        </header>
        <div class="workspace-sheet__body"><slot /></div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
:deep(.workspace-sheet__overlay) {
  position: fixed;
  z-index: 80;
  inset: 0;
  background: rgb(23 32 51 / 36%);
  animation: workspace-sheet-fade-in 180ms ease both;
}

:deep(.workspace-sheet__panel) {
  position: fixed;
  z-index: 90;
  top: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  width: min(100vw, 460px);
  height: 100dvh;
  max-height: 100dvh;
  padding: 24px;
  overflow: auto;
  border-left: 1px solid var(--color-border);
  border-radius: 18px 0 0 18px;
  background: var(--color-surface, #fff);
  box-shadow: -20px 0 56px rgb(29 49 43 / 12%);
  animation: workspace-sheet-enter 220ms cubic-bezier(.2, .8, .2, 1) both;
}

.workspace-sheet__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding-bottom: 17px; border-bottom: 1px solid var(--color-border); }
.workspace-sheet__heading { min-width: 0; }
.workspace-sheet__title { display: block; color: var(--color-text-primary); font-family: var(--font-display); font-size: 20px; font-weight: 720; line-height: 1.35; }
.workspace-sheet__description { display: block; margin-top: 6px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.6; }
.workspace-sheet__close { display: inline-grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border: 1px solid var(--color-border); border-radius: 10px; color: var(--color-text-secondary); background: #fff; cursor: pointer; }
.workspace-sheet__close:hover { border-color: #b7d3ca; color: #286c5d; background: #f4f9f6; }
.workspace-sheet__close:focus-visible { outline: 3px solid var(--color-focus-ring, #38a4bf); outline-offset: 2px; }
.workspace-sheet__body { min-height: 0; padding-top: 18px; }

@keyframes workspace-sheet-enter { from { opacity: .65; transform: translateX(28px); } to { opacity: 1; transform: translateX(0); } }
@keyframes workspace-sheet-fade-in { from { opacity: 0; } to { opacity: 1; } }

@media (max-width: 560px) {
  :deep(.workspace-sheet__panel) { width: 100vw; padding: 18px; border-radius: 0; }
}

@media (prefers-reduced-motion: reduce) {
  :deep(.workspace-sheet__overlay),:deep(.workspace-sheet__panel) { animation-duration: .01ms; }
}
</style>
