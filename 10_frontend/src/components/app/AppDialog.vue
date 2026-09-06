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

defineProps<{
  open: boolean
  title: string
  description?: string
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="dialog-overlay" />
      <DialogContent class="dialog-content">
        <div class="dialog-header">
          <div>
            <DialogTitle class="dialog-title">{{ title }}</DialogTitle>
            <DialogDescription v-if="description" class="dialog-description">{{ description }}</DialogDescription>
          </div>
          <DialogClose as-child>
            <button class="dialog-close" type="button" aria-label="关闭对话框">
              <X :size="18" aria-hidden="true" />
            </button>
          </DialogClose>
        </div>
        <div class="dialog-body"><slot /></div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.dialog-overlay { position: fixed; inset: 0; z-index: 80; background: rgb(23 32 51 / 48%); }
.dialog-content {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 90;
  width: min(100% - 32px, 480px);
  max-height: calc(100vh - 32px);
  overflow: auto;
  padding: 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-dialog);
  background: var(--color-surface);
  box-shadow: 0 24px 64px rgb(23 32 51 / 18%);
  transform: translate(-50%, -50%);
}
.dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.dialog-title { color: var(--color-text-primary); font-family: var(--font-display); font-size: 20px; font-weight: 700; line-height: 1.35; }
.dialog-description { margin-top: 5px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.dialog-close { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; flex: 0 0 36px; border: 1px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; }
.dialog-close:hover { color: var(--color-primary); border-color: var(--color-primary); background: var(--color-info-wash); }
.dialog-body { margin-top: 20px; }
</style>
