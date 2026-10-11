<script setup lang="ts">
defineProps<{
  compact?: boolean
}>()
</script>

<template>
  <div class="app-logo" :class="{ 'app-logo--compact': compact }">
    <img class="app-logo__mark" src="/assets/psynova/mark.png" alt="" aria-hidden="true">
    <img v-if="!compact" class="app-logo__wordmark" src="/assets/psynova/wordmark.png" alt="PsyNova">
  </div>
</template>

<style scoped>
.app-logo {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: inherit;
}

.app-logo__mark {
  display: block;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  object-fit: contain;
}

.app-logo__wordmark {
  display: block;
  width: 112px;
  height: 56px;
  flex: 0 0 auto;
  object-fit: contain;
}

.app-logo--compact .app-logo__mark {
  width: 50px;
  height: 50px;
}
</style>
