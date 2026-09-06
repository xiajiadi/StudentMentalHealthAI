<script setup lang="ts">
withDefaults(defineProps<{
  raised?: boolean
  flush?: boolean
}>(), {
  raised: false,
  flush: false,
})
</script>

<template>
  <section class="app-card" :class="{ 'app-card--raised': raised, 'app-card--flush': flush }">
    <slot />
  </section>
</template>

<style scoped>
.app-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-rest);
}

.app-card--raised {
  box-shadow: var(--shadow-raised);
}

.app-card--flush {
  overflow: hidden;
}
</style>
