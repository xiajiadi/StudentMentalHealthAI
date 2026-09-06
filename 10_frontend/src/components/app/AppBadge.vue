<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'neutral' | 'blue' | 'teal' | 'amber' | 'critical'
  dot?: boolean
}>(), {
  tone: 'neutral',
  dot: false,
})
</script>

<template>
  <span class="app-badge" :class="`app-badge--${tone}`">
    <span v-if="dot" class="app-badge__dot" aria-hidden="true"></span>
    <slot />
  </span>
</template>

<style scoped>
.app-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
}

.app-badge--neutral { border-color: var(--color-border); color: var(--color-text-secondary); background: var(--color-surface-muted); }
.app-badge--blue { border-color: rgb(37 99 235 / 18%); color: var(--color-primary); background: var(--color-info-wash); }
.app-badge--teal { border-color: rgb(15 118 110 / 18%); color: var(--color-support); background: var(--color-support-wash); }
.app-badge--amber { border-color: rgb(183 121 31 / 22%); color: var(--color-attention); background: var(--color-attention-wash); }
.app-badge--critical { border-color: rgb(180 35 24 / 22%); color: var(--color-critical); background: var(--color-critical-wash); }

.app-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
</style>
