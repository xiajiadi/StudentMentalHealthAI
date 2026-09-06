<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  value: number
  max?: number
  label?: string
  valueLabel?: string
  tone?: 'blue' | 'teal' | 'amber'
}>(), {
  max: 100,
  label: '',
  valueLabel: '',
  tone: 'blue',
})

const displayValue = computed(() => props.valueLabel || (props.max === 100 ? `${props.value}%` : `${props.value}/${props.max}`))
</script>

<template>
  <div class="progress-wrap">
    <div v-if="props.label" class="progress-wrap__label"><span>{{ props.label }}</span><strong>{{ displayValue }}</strong></div>
    <div class="progress" role="progressbar" :aria-label="props.label || '进度'" :aria-valuenow="props.value" :aria-valuemin="0" :aria-valuemax="props.max">
      <span :class="`progress__fill progress__fill--${props.tone}`" :style="{ width: `${Math.min(100, Math.max(0, (props.value / props.max) * 100))}%` }"></span>
    </div>
  </div>
</template>

<style scoped>
.progress-wrap { display: grid; gap: 8px; }
.progress-wrap__label { display: flex; justify-content: space-between; gap: 12px; color: var(--color-text-secondary); font-size: 12px; }
.progress-wrap__label strong { color: var(--color-text-primary); font-variant-numeric: tabular-nums; }
.progress { height: 7px; overflow: hidden; border-radius: 99px; background: var(--color-surface-muted); }
.progress__fill { display: block; height: 100%; border-radius: inherit; transition: width var(--motion-normal) ease; }
.progress__fill--blue { background: var(--color-primary); }
.progress__fill--teal { background: var(--color-support); }
.progress__fill--amber { background: var(--color-attention); }
</style>
