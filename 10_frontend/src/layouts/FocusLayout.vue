<script setup lang="ts">
import AppLogo from '@/components/app/AppLogo.vue'
</script>

<template>
  <div class="focus-layout app-shell">
    <header class="focus-header">
      <RouterLink class="focus-header__back" to="/student/home" aria-label="离开测评并返回学生首页">
        <svg class="focus-header__arrow" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M10.5 3.5 6 8l4.5 4.5M6.25 8H14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span>离开测评</span>
      </RouterLink>
      <AppLogo />
    </header>
    <main class="focus-main"><slot /></main>
  </div>
</template>

<style scoped>
.focus-layout { display: flex; min-height: 100vh; min-height: 100svh; flex-direction: column; background: var(--color-canvas); }
.focus-header { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; width: min(100% - clamp(32px, 6vw, 96px), 980px); min-height: clamp(62px, 8svh, 70px); margin: 0 auto; border-bottom: 1px solid var(--color-border); }
.focus-header__back { display: inline-flex; align-items: center; gap: 6px; width: fit-content; min-height: 36px; padding: 0; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; }
.focus-header__back:hover { color: var(--color-primary); }
.focus-header__arrow { width: 16px; height: 16px; flex: 0 0 16px; }
.focus-header :deep(.app-logo) { gap: 6px; }
.focus-header :deep(.app-logo__mark) { width: 24px; height: 24px; }
.focus-header :deep(.app-logo__wordmark) { width: 84px; height: 42px; }
.focus-main { display: flex; flex: 1 0 auto; align-items: center; justify-content: center; box-sizing: border-box; width: min(calc(100% - clamp(32px, 6vw, 96px)), clamp(520px, calc(44vw + 16svh), 760px)); min-height: 0; margin: 0 auto; padding: clamp(14px, 2.8svh, 28px) 0; }

@media (max-width: 600px) {
  .focus-header { width: calc(100% - 32px); min-height: clamp(54px, 7svh, 60px); }
  .focus-header__back span { display: none; }
  .focus-main { width: calc(100% - 32px); padding-block: clamp(10px, 2.5svh, 20px); }
}
</style>
