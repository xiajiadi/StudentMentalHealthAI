<script setup lang="ts">
defineProps<{
  compact?: boolean
}>()
</script>

<template>
  <div class="app-logo" :class="{ 'app-logo--compact': compact }">
    <span class="app-logo__mark" aria-hidden="true"><span></span><span></span></span>
    <span v-if="!compact" class="app-logo__wordmark">
      <strong>心桥</strong>
      <small>教育支持</small>
    </span>
  </div>
</template>

<style scoped>
.app-logo {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: inherit;
}

.app-logo__mark {
  position: relative;
  display: inline-flex;
  align-items: flex-end;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid currentColor;
  border-radius: 9px 9px 9px 3px;
  color: var(--color-primary);
  transform: rotate(-4deg);
}

.app-logo__mark::after {
  position: absolute;
  right: 4px;
  bottom: -5px;
  width: 7px;
  height: 7px;
  border-right: 1px solid currentColor;
  border-bottom: 1px solid currentColor;
  content: "";
  transform: skewY(-26deg);
}

.app-logo__mark span {
  display: block;
  width: 3px;
  margin: 0 2px 6px;
  border-radius: 3px;
  background: currentColor;
}

.app-logo__mark span:first-child {
  height: 9px;
  opacity: 0.52;
}

.app-logo__mark span:last-child {
  height: 15px;
}

.app-logo__wordmark {
  display: grid;
  gap: 1px;
}

.app-logo__wordmark strong {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.1;
}

.app-logo__wordmark small {
  color: var(--color-text-muted);
  font-size: 10px;
  letter-spacing: 0.14em;
  line-height: 1.2;
}

.app-logo--compact .app-logo__mark {
  width: 25px;
  height: 25px;
}
</style>
