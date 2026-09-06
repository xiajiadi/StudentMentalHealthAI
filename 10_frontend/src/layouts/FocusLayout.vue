<script setup lang="ts">
import { ArrowLeft } from '@lucide/vue'
import AppLogo from '@/components/app/AppLogo.vue'
</script>

<template>
  <div class="focus-layout app-shell">
    <header class="focus-header">
      <RouterLink class="focus-header__back" to="/student/home" aria-label="离开测评并返回学生首页">
        <ArrowLeft :size="18" aria-hidden="true" />
        <span>离开测评</span>
      </RouterLink>
      <AppLogo />
      <span class="focus-header__privacy">仅展示合成流程</span>
    </header>
    <main class="focus-main"><slot /></main>
  </div>
</template>

<style scoped>
.focus-layout { min-height: 100vh; background: var(--color-canvas); }
.focus-header { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; width: min(100% - 48px, 980px); min-height: 72px; margin: 0 auto; border-bottom: 1px solid var(--color-border); }
.focus-header__back { display: inline-flex; align-items: center; gap: 7px; width: fit-content; min-height: 44px; padding: 0 10px 0 0; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; }
.focus-header__back:hover { color: var(--color-primary); }
.focus-header__privacy { justify-self: end; color: var(--color-text-muted); font-size: 11px; }
.focus-main { width: min(100% - 48px, 720px); margin: 0 auto; padding: 42px 0 56px; }

@media (max-width: 600px) {
  .focus-header { width: min(100% - 32px, 980px); min-height: 62px; }
  .focus-header__back span { display: none; }
  .focus-header__privacy { font-size: 10px; }
  .focus-main { width: min(100% - 32px, 720px); padding-top: 28px; }
}
</style>
