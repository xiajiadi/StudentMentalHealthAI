<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'info' | 'support' | 'attention' | 'critical'
  title: string
  body?: string
}>(), {
  tone: 'info',
  body: '',
})
</script>

<template>
  <aside class="status-callout" :class="`status-callout--${tone}`" role="status">
    <span class="status-callout__bar" aria-hidden="true"></span>
    <div>
      <h2>{{ title }}</h2>
      <p v-if="body">{{ body }}</p>
      <slot />
    </div>
  </aside>
</template>

<style scoped>
.status-callout {
  display: flex;
  gap: 14px;
  padding: 15px 17px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
}

.status-callout__bar {
  flex: 0 0 3px;
  align-self: stretch;
  min-height: 30px;
  border-radius: 3px;
  background: var(--color-primary);
}

.status-callout h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.5;
}

.status-callout p {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.65;
}

.status-callout--support { border-color: rgb(15 118 110 / 17%); background: var(--color-support-wash); }
.status-callout--support .status-callout__bar { background: var(--color-support); }
.status-callout--attention { border-color: rgb(183 121 31 / 18%); background: var(--color-attention-wash); }
.status-callout--attention .status-callout__bar { background: var(--color-attention); }
.status-callout--critical { border-color: rgb(180 35 24 / 20%); background: var(--color-critical-wash); }
.status-callout--critical .status-callout__bar { background: var(--color-critical); }
</style>
