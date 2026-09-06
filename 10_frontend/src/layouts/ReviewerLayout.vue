<script setup lang="ts">
import { Menu } from '@lucide/vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import RoleSidebar from '@/components/shell/RoleSidebar.vue'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const session = useSessionStore()
const sidebarOpen = ref(false)

const logout = () => {
  session.signOut()
  void router.push('/login')
}
</script>

<template>
  <div class="workspace-layout app-shell">
    <RoleSidebar v-model:mobile-open="sidebarOpen" role="reviewer" :user="session.user" @logout="logout" />
    <header class="workspace-mobile-header">
      <button class="workspace-mobile-header__menu" type="button" aria-label="打开复核导航" @click="sidebarOpen = true">
        <Menu :size="20" aria-hidden="true" />
      </button>
      <span class="workspace-mobile-header__title">安全复核工作区</span>
      <span class="workspace-mobile-header__user">{{ session.user?.initials || '复' }}</span>
    </header>
    <main class="app-main"><slot /></main>
  </div>
</template>

<style scoped>
.workspace-mobile-header { display: none; }
@media (max-width: 1023px) {
  .workspace-mobile-header { position: sticky; z-index: 35; top: 0; display: flex; align-items: center; gap: 12px; min-height: 60px; padding: 0 16px; border-bottom: 1px solid var(--color-border); background: rgb(247 248 250 / 94%); backdrop-filter: blur(12px); }
  .workspace-mobile-header__menu { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; }
  .workspace-mobile-header__title { flex: 1; color: var(--color-text-primary); font-size: 14px; font-weight: 700; }
  .workspace-mobile-header__user { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; color: var(--color-primary); background: var(--color-info-wash); font-size: 12px; font-weight: 800; }
}
</style>
