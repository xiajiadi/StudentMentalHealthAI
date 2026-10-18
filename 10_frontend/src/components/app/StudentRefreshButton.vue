<script setup lang="ts">
import { LoaderCircle, RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'

withDefaults(defineProps<{
  loading?: boolean
  disabled?: boolean
  ariaLabel?: string
  label?: string
}>(), {
  loading: false,
  disabled: false,
  label: '刷新',
})

const emit = defineEmits<{ click: [event: MouseEvent] }>()
</script>

<template>
  <AppButton
    class="student-refresh-button"
    variant="secondary"
    size="sm"
    :disabled="disabled || loading"
    :aria-busy="loading"
    :aria-label="ariaLabel"
    @click="emit('click', $event)"
  >
    <LoaderCircle v-if="loading" class="student-refresh-button__loader" :size="15" aria-hidden="true" />
    <RotateCcw v-else :size="15" aria-hidden="true" />
    {{ label }}
  </AppButton>
</template>

<style scoped>
.student-refresh-button.app-button--secondary { border-color: #7ecbeb; color: #009fd4; background: #fff; }
.student-refresh-button.app-button--secondary:hover:not(:disabled) { border-color: #00a9dd; color: #009acb; background: #f2fbff; filter: none; }
.student-refresh-button.app-button--secondary:active:not(:disabled) { background: #e7f7fd; }
.student-refresh-button.app-button--secondary:focus-visible { outline: 2px solid #249de0; outline-offset: 3px; }
.student-refresh-button__loader { animation: student-refresh-spin 800ms linear infinite; }
@keyframes student-refresh-spin { to { transform: rotate(360deg); } }
</style>
