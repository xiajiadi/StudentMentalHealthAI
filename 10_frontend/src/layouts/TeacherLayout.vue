<script setup lang="ts">
import { Menu } from '@lucide/vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import RoleSidebar from '@/components/shell/RoleSidebar.vue'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const session = useSessionStore()
const sidebarOpen = ref(false)
const logoutError = ref('')
const isLoggingOut = ref(false)

const logout = async () => {
  if (isLoggingOut.value) return
  logoutError.value = ''
  isLoggingOut.value = true
  try {
    await frontendApi.logout()
    session.signOut()
    await router.replace('/login')
  } catch (error) {
    const code = typeof error === 'object' && error !== null && 'code' in error
      ? String(error.code)
      : ''
    if (code === 'auth_session_expired' || code === 'auth_session_revoked') {
      session.signOut()
      await router.replace('/login')
      return
    }
    logoutError.value = '暂时无法退出，请检查连接后重试。'
  } finally {
    isLoggingOut.value = false
  }
}
</script>

<template>
  <div class="workspace-layout app-shell">
    <RoleSidebar v-model:mobile-open="sidebarOpen" role="teacher" :user="session.user" @logout="logout" />
    <header class="workspace-mobile-header">
      <button class="workspace-mobile-header__menu" type="button" aria-label="打开工作区导航" @click="sidebarOpen = true">
        <Menu :size="20" aria-hidden="true" />
      </button>
      <span class="workspace-mobile-header__title">教师支持工作区</span>
      <span class="workspace-mobile-header__user">{{ session.user?.initials || '师' }}</span>
    </header>
    <main class="app-main">
      <div v-if="logoutError" class="workspace-logout-error" role="alert">{{ logoutError }}</div>
      <slot />
    </main>
  </div>
</template>

<style scoped>
.workspace-mobile-header { display: none; }
.workspace-logout-error { margin: 12px 22px 0; padding: 10px 13px; border: 1px solid rgb(180 35 24 / 22%); border-radius: 7px; color: #8f1d14; background: #fff3f1; font-size: 12px; }
@media (max-width: 1023px) {
  .workspace-mobile-header { position: sticky; z-index: 35; top: 0; display: flex; align-items: center; gap: 12px; min-height: 60px; padding: 0 16px; border-bottom: 1px solid var(--color-border); background: rgb(247 248 250 / 94%); backdrop-filter: blur(12px); }
  .workspace-mobile-header__menu { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; }
  .workspace-mobile-header__title { flex: 1; color: var(--color-text-primary); font-size: 14px; font-weight: 700; }
  .workspace-mobile-header__user { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; color: var(--color-primary); background: var(--color-info-wash); font-size: 12px; font-weight: 800; }
}
</style>
