<script setup lang="ts">
import AppLogo from '@/components/app/AppLogo.vue'
</script>

<template>
  <div class="focus-layout app-shell">
    <header class="focus-header">
      <RouterLink class="focus-header__back" to="/student/assessments" aria-label="离开测评并返回我的测评">
        <svg class="focus-header__arrow" viewBox="0 0 32 32" aria-hidden="true">
          <path d="M13 3.5c0-.7-.5-1.3-1.2-1.5-.7-.2-1.4 0-1.9.5L.5 13.2a2 2 0 0 0 0 2.6l9.4 10.4c.5.5 1.2.7 1.9.5.7-.2 1.2-.9 1.2-1.6v-5.2c7.1.1 10.4 1.5 12.1 2.7 1.2.9 1.5 2.1 1.8 3.7.2 1.4 1.4 2.2 2.6 2.1 1.1-.1 1.9-.9 2-2 .2-3.4-.3-8-2.8-11.6C26 11.1 21.5 8.6 13 8.3V3.5Z" fill="currentColor" />
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
.focus-header__back { display: inline-flex; align-items: center; gap: 10px; width: fit-content; min-height: 36px; padding: 0; color: #3f424a; font-size: 16px; font-weight: 500; text-decoration: none; cursor: pointer; }
.focus-header__back span { color: #1e1d29; }
.focus-header__back:hover, .focus-header__back.active, .focus-header__back:active { color: #00b1e2; text-decoration: none; }
.focus-header__back:hover span, .focus-header__back.active span, .focus-header__back:active span { color: #00b1e2; }
.focus-header__back:focus-visible { border-radius: 3px; outline: 2px solid var(--color-focus-ring); outline-offset: 3px; }
.focus-header__arrow { display: block; width: 18px; height: 18px; flex: 0 0 18px; transform: translateY(0); }
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
