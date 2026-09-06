<script setup lang="ts">
import { ArrowLeft } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
</script>

<template>
  <main class="not-found">
    <span class="not-found__code">404</span>
    <h1>页面没有找到</h1>
    <p>这个演示入口不存在，或已经被移到当前角色允许的工作区之外。</p>
    <RouterLink to="/login">
      <AppButton variant="secondary"><ArrowLeft :size="16" aria-hidden="true" />返回登录</AppButton>
    </RouterLink>
  </main>
</template>

<style scoped>
.not-found { display: grid; justify-items: start; align-content: center; min-height: 100vh; width: min(100% - 40px, 560px); margin: 0 auto; }
.not-found__code { color: var(--color-primary); font-family: var(--font-mono); font-size: 12px; font-weight: 800; letter-spacing: 0.16em; }
.not-found h1 { margin: 16px 0 10px; color: var(--color-text-primary); font-family: var(--font-display); font-size: 32px; letter-spacing: -0.04em; }
.not-found p { max-width: 420px; margin: 0 0 24px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.8; }
</style>
