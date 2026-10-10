<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, CircleHelp, LogOut, Menu, Search, X } from '@lucide/vue'
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import AppLogo from '@/components/app/AppLogo.vue'
import RoleSidebar from '@/components/shell/RoleSidebar.vue'
import { roleHomes, roleLabels, workspaceConfig } from '@/components/shell/navigation'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'
import type { Role } from '@/types/contracts'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const sidebarOpen = ref(false)
const helpOpen = ref(false)
const searchOpen = ref(false)
const query = ref('')
const logoutError = ref('')
const isLoggingOut = ref(false)

const currentRole = computed<Role>(() => {
  const pathRole: Array<[string, Role]> = [
    ['/student', 'student'], ['/teacher', 'teacher'], ['/specialist', 'psychological_specialist'], ['/admin', 'school_admin'], ['/reviewer', 'reviewer'],
  ]
  return pathRole.find(([prefix]) => route.path === prefix || route.path.startsWith(`${prefix}/`))?.[1] ?? session.role ?? 'student'
})
const canSwitchWorkspace = computed(() => Boolean(session.user?.authorizedRoles && session.user.authorizedRoles.length > 1))
const allowedWorkspaces = computed(() => (session.user?.authorizedRoles ?? []).filter((role) => roleHomes[role]))
const navItems = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return (workspaceConfig[currentRole.value]?.items ?? []).filter((item) => !term || item.label.toLocaleLowerCase().includes(term))
})
const roleHome = (role: Role) => roleHomes[role]

const switchWorkspace = async (role: Role) => {
  if (!allowedWorkspaces.value.includes(role)) return
  const path = roleHome(role)
  if (path) await router.push(path)
}

const logout = async () => {
  if (isLoggingOut.value) return
  logoutError.value = ''
  isLoggingOut.value = true
  try {
    await frontendApi.logout()
    session.signOut()
    await router.replace('/login')
  } catch (error) {
    const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code) : ''
    if (code === 'auth_session_expired' || code === 'auth_session_revoked') {
      session.signOut()
      await router.replace('/login')
      return
    }
    logoutError.value = '暂时无法退出，请检查连接后重试。'
  } finally { isLoggingOut.value = false }
}

const openFirstResult = async () => {
  if (navItems.value[0]) {
    await router.push(navItems.value[0].to)
    searchOpen.value = false
  }
}
</script>

<template>
  <div class="workspace-shell app-shell">
    <header class="workspace-topbar">
      <button class="workspace-topbar__menu" type="button" aria-label="打开工作区导航" @click="sidebarOpen = true"><Menu :size="19" aria-hidden="true" /></button>
      <RouterLink class="workspace-topbar__brand" :to="roleHome(currentRole) || '/login'"><AppLogo /></RouterLink>
      <div class="workspace-search-wrap">
        <label class="workspace-search"><Search :size="16" aria-hidden="true" /><input v-model="query" type="search" aria-label="搜索当前工作区导航" placeholder="搜索当前工作区" @focus="searchOpen = true" @keydown.enter.prevent="openFirstResult" @keydown.esc="searchOpen = false" /><button v-if="query" type="button" aria-label="清除搜索" @click="query = ''; searchOpen = true">×</button></label>
        <div v-if="searchOpen && query" class="workspace-search__results" role="listbox" aria-label="导航搜索结果">
          <RouterLink v-for="item in navItems" :key="item.to + item.label" :to="item.to" role="option" @click="query = ''; searchOpen = false"><component :is="item.icon" :size="16" aria-hidden="true" /><span>{{ item.label }}</span></RouterLink>
          <span v-if="!navItems.length" class="workspace-search__empty">没有匹配的导航</span>
        </div>
      </div>
      <div class="workspace-topbar__actions">
        <button class="workspace-help" type="button" aria-label="帮助" @click="helpOpen = true"><CircleHelp :size="18" /><span>帮助</span></button>
        <details class="account-menu">
          <summary :aria-label="`账号菜单，${session.user?.displayName || '当前账号'}`"><span class="account-menu__avatar" aria-hidden="true">{{ session.user?.initials || '用' }}</span><span class="account-menu__copy"><strong>{{ session.user?.displayName || '当前账号' }}</strong><small>{{ roleLabels[currentRole] }}</small></span><ChevronDown :size="15" /></summary>
          <div class="account-menu__panel">
            <span class="account-menu__heading">当前账号</span>
            <strong class="account-menu__name">{{ session.user?.displayName || '当前账号' }}</strong>
            <span class="account-menu__role">{{ roleLabels[currentRole] }}</span>
            <template v-if="canSwitchWorkspace">
              <span class="account-menu__heading account-menu__heading--spaced">可访问的工作区</span>
              <button v-for="role in allowedWorkspaces" :key="role" class="account-menu__switch" type="button" :disabled="role === currentRole" @click="switchWorkspace(role)">{{ roleLabels[role] }}</button>
            </template>
            <button class="account-menu__logout" type="button" :disabled="isLoggingOut" @click="logout"><LogOut :size="16" />退出登录</button>
          </div>
        </details>
      </div>
    </header>
    <RoleSidebar v-model:mobile-open="sidebarOpen" :role="currentRole" />
    <main class="workspace-main">
      <div v-if="logoutError" class="workspace-error" role="alert">{{ logoutError }}</div>
      <slot />
    </main>
    <DialogRoot :open="helpOpen" @update:open="helpOpen = $event">
      <DialogPortal>
        <DialogOverlay class="workspace-dialog__overlay" />
        <DialogContent class="workspace-dialog__content">
          <DialogClose as-child><button class="workspace-dialog__dismiss" type="button" aria-label="关闭帮助"><X :size="18" aria-hidden="true" /></button></DialogClose>
          <div class="workspace-dialog__inner">
            <DialogTitle class="workspace-dialog__title">帮助</DialogTitle>
            <DialogDescription class="workspace-dialog__description">请使用学校提供的账号和密码。如无法登录或访问工作区，请联系学校信息管理员。可访问的工作区由服务端账号权限决定。</DialogDescription>
            <DialogClose as-child><button class="workspace-dialog__close" type="button">知道了</button></DialogClose>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </div>
</template>

<style scoped>
.workspace-topbar { position: fixed; z-index: 40; inset: 0 0 auto; display: flex; align-items: center; gap: 28px; height: var(--layout-topbar); padding: 0 34px; border-bottom: 1px solid var(--color-border); background: var(--color-surface); }
.workspace-topbar__brand { display: inline-flex; align-items: center; min-width: var(--layout-sidebar); color: var(--color-text-primary); }
.workspace-search-wrap { position: relative; width: min(36vw, 370px); }
.workspace-search { display: flex; align-items: center; gap: 9px; width: 100%; height: 40px; padding: 0 11px; border: 1px solid #e7eaee; border-radius: 8px; color: #99a0a8; background: #fafbfc; }
.workspace-search:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(0 177 226 / 12%); }
.workspace-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font-size: 12px; }
.workspace-search input::placeholder { color: #9ba2aa; }
.workspace-search button { border: 0; color: var(--color-text-muted); background: transparent; cursor: pointer; font-size: 20px; }
.workspace-search__results { position: absolute; z-index: 45; top: calc(100% + 6px); right: 0; left: 0; display: grid; gap: 3px; padding: 6px; border: 1px solid var(--color-border); border-radius: 9px; background: white; box-shadow: 0 12px 28px rgb(16 24 40 / 12%); }
.workspace-search__results a { display: flex; align-items: center; gap: 9px; min-height: 38px; padding: 0 9px; border-radius: 6px; color: var(--color-text-secondary); font-size: 12px; }
.workspace-search__results a:hover { color: var(--color-primary); background: #f2fbfe; }
.workspace-search__empty { padding: 11px 9px; color: var(--color-text-muted); font-size: 11px; }
.workspace-topbar__actions { display: flex; align-items: center; gap: 18px; margin-left: auto; }
.workspace-help { display: inline-flex; align-items: center; gap: 7px; min-height: 40px; border: 0; color: var(--color-text-secondary); background: transparent; cursor: pointer; font-size: 12px; }
.workspace-help:hover { color: var(--color-primary); }
.account-menu { position: relative; }
.account-menu summary { display: flex; align-items: center; gap: 9px; list-style: none; cursor: pointer; }
.account-menu summary::-webkit-details-marker { display: none; }
.account-menu summary > svg { color: #9299a1; }
.account-menu__avatar { display: inline-grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; color: #1683a5; background: #e6f8fd; font-size: 13px; font-weight: 700; }
.account-menu__copy { display: grid; gap: 3px; }
.account-menu__copy strong { max-width: 140px; overflow: hidden; color: var(--color-text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.account-menu__copy small { color: var(--color-text-muted); font-size: 10px; }
.account-menu__panel { position: absolute; top: calc(100% + 14px); right: 0; display: grid; min-width: 225px; padding: 14px; border: 1px solid var(--color-border); border-radius: 10px; background: white; box-shadow: 0 12px 32px rgb(16 24 40 / 12%); }
.account-menu__heading { color: var(--color-text-muted); font-size: 10px; font-weight: 700; }
.account-menu__heading--spaced { margin-top: 16px; }
.account-menu__name { margin-top: 6px; color: var(--color-text-primary); font-size: 13px; }
.account-menu__role { margin-top: 3px; color: var(--color-text-secondary); font-size: 11px; }
.account-menu__switch, .account-menu__logout { display: flex; align-items: center; gap: 9px; min-height: 37px; border: 0; border-radius: 6px; color: var(--color-text-secondary); background: white; cursor: pointer; text-align: left; font-size: 12px; }
.account-menu__switch { padding: 0 8px; }
.account-menu__switch:hover:not(:disabled), .account-menu__logout:hover:not(:disabled) { color: var(--color-primary); background: #f2fbfe; }
.account-menu__switch:disabled { color: var(--color-primary); }
.account-menu__logout { margin-top: 12px; padding: 9px 8px 0; border-top: 1px solid var(--color-border); border-radius: 0; }
.account-menu__logout:disabled { opacity: .55; cursor: wait; }
.workspace-main { min-height: 100vh; margin-left: var(--layout-sidebar); padding-top: var(--layout-topbar); background: var(--color-canvas); }
.workspace-error { margin: 16px 28px 0; padding: 10px 13px; border: 1px solid rgb(180 35 24 / 22%); border-radius: 8px; color: #8f1d14; background: #fff3f1; font-size: 12px; }
.workspace-dialog__overlay { position: fixed; z-index: 100; inset: 0; background: rgb(0 0 0 / 80%); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); }
.workspace-dialog__content { position: fixed; z-index: 101; top: 50%; left: 50%; width: min(580px, calc(100vw - 32px)); min-height: 300px; padding: 60px 30px 30px; border: 0; border-radius: 12px; outline: none; background: #fff; box-shadow: none; transform: translate(-50%, -50%); }
.workspace-dialog__dismiss { position: absolute; top: 15px; right: 15px; display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; padding: 11px; border: 0; border-radius: 50%; color: #1e1d29; background: transparent; cursor: pointer; transition: all .2s ease-in-out; }
.workspace-dialog__inner { display: grid; width: 100%; min-height: 210px; grid-template-rows: auto minmax(0, 1fr) auto; gap: 30px; }
.workspace-dialog__title { display: block; margin: 0; color: #1e1d29; font-size: 24px; font-weight: 600; line-height: 1.3; text-align: center; }
.workspace-dialog__description { display: flex; align-items: center; margin: 0; color: #3f424a; font-size: 16px; font-weight: 500; line-height: 1.6; }
.workspace-dialog__close { display: flex; width: 100%; min-height: 0; align-items: center; justify-content: center; padding: 10px 15px; border: 1px solid transparent; border-radius: 8px; color: #fff; background: #00b1e2; cursor: pointer; font: inherit; font-size: 14px; font-weight: 600; line-height: 1.3; transition: all .2s ease-in-out; }
.workspace-dialog__close:hover { background: #33c1e8; }
.workspace-dialog__close:active { background: #008eb5; }
.workspace-dialog__dismiss:focus-visible, .workspace-dialog__close:focus-visible { outline: 2px solid #3f424a; outline-offset: 1px; }
.workspace-topbar__menu { display: none; }
@media (max-width: 1023px) { .workspace-topbar { gap: 14px; height: 62px; padding: 0 16px; }.workspace-topbar__menu { display: inline-grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-secondary); background: white; cursor: pointer; }.workspace-topbar__brand { min-width: 0; }.workspace-search-wrap { width: min(34vw, 260px); margin-left: 12px; }.workspace-main { margin-left: 0; padding-top: 62px; } }
@media (max-width: 620px) { .workspace-topbar { gap: 10px; padding: 0 12px; }.workspace-topbar__brand :deep(.app-logo__wordmark small) { display: none; }.workspace-search-wrap { width: 38px; flex: 0 1 38px; margin-left: auto; }.workspace-search { width: 38px; padding: 0 10px; border-color: transparent; background: transparent; }.workspace-search:focus-within { width: min(42vw, 200px); background: white; }.workspace-search input { width: 0; padding: 0; }.workspace-search:focus-within input { width: auto; }.workspace-search button { display: none; }.workspace-topbar__actions { gap: 8px; margin-left: 0; }.workspace-help { width: 36px; justify-content: center; }.workspace-help span, .account-menu__copy, .account-menu summary > svg { display: none; }.account-menu__avatar { width: 32px; height: 32px; }.workspace-main :deep(.content-wrap), .workspace-main :deep(.content-wrap--student) { width: min(100% - 28px, var(--layout-content-max)); } }
</style>
