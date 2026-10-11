<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'

withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'quiet' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  loading?: boolean
  block?: boolean
}>(), {
  variant: 'primary',
  size: 'md',
  type: 'button',
  disabled: false,
  loading: false,
  block: false,
})

defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading"
    :class="['app-button', `app-button--${variant}`, `app-button--${size}`, { 'app-button--block': block }]"
    @click="$emit('click', $event)"
  >
    <LoaderCircle v-if="loading" class="app-button__loader" :size="16" aria-hidden="true" />
    <span class="app-button__label"><slot /></span>
  </button>
</template>

<style scoped>
.app-button {
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 44px;
  border: 1px solid transparent;
  border-radius: var(--radius-button);
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  white-space: nowrap;
  transition: all var(--motion-fast) ease;
}

.app-button__label {
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.app-button__label :deep(svg) {
  flex: 0 0 auto;
}

.app-button:hover:not(:disabled) {
  filter: brightness(1.1);
}

.app-button:active:not(:disabled) {
  filter: brightness(1.1);
  transform: none;
}

.app-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.app-button--sm {
  min-height: 38px;
  padding: 0 13px;
  font-size: 13px;
}

.app-button--md {
  padding: 0 18px;
}

.app-button--lg {
  min-height: 48px;
  padding: 0 22px;
  font-size: 15px;
}

.app-button--block {
  width: 100%;
}

.app-button--primary {
  color: var(--color-text-inverse);
  background: var(--color-primary);
  box-shadow: none;
}

.app-button--primary:hover:not(:disabled) {
  background: var(--color-primary-hover);
  box-shadow: none;
}

.app-button--primary:active:not(:disabled) {
  background: var(--color-primary-active);
}

.app-button--secondary {
  border-color: var(--color-text-secondary);
  color: var(--color-text-primary);
  background: transparent;
}

.app-button--secondary:hover:not(:disabled) {
  border-color: var(--color-text-secondary);
  color: var(--color-text-primary);
  background: rgb(0 0 0 / 5%);
}

.app-button--quiet {
  color: var(--color-text-secondary);
  background: transparent;
}

.app-button--quiet:hover:not(:disabled) {
  color: var(--color-text-primary);
  background: rgb(0 0 0 / 5%);
}

.app-button--danger {
  color: var(--color-critical);
  background: var(--color-critical-wash);
  border-color: rgb(180 35 24 / 20%);
}

.app-button--danger:hover:not(:disabled) {
  background: var(--color-critical-soft);
}

.app-button__loader {
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
