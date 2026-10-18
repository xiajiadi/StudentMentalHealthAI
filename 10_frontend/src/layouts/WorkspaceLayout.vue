<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, ChevronDown, CircleHelp, LogOut, Menu, Search, UserRound, X } from '@lucide/vue'
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
const accountMenu = ref<HTMLDetailsElement | null>(null)
const notificationMenu = ref<HTMLDetailsElement | null>(null)
const searchOpen = ref(false)
const searchInputFocusedByTab = ref(false)
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
const currentWorkspaceTitle = computed(() => workspaceConfig[currentRole.value]?.title ?? 'Student Workspace')
const navItems = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return (workspaceConfig[currentRole.value]?.items ?? []).filter((item) => !term || item.label.toLocaleLowerCase().includes(term))
})
const roleHome = (role: Role) => roleHomes[role]

const closeAccountMenu = () => {
  if (accountMenu.value) accountMenu.value.open = false
}

const openHelp = () => {
  closeAccountMenu()
  helpOpen.value = true
}

const handleShellPointerdown = (event: PointerEvent) => {
  searchInputFocusedByTab.value = false
  if (!(event.target instanceof Node)) return
  if (accountMenu.value && !accountMenu.value.contains(event.target)) accountMenu.value.open = false
  if (notificationMenu.value && !notificationMenu.value.contains(event.target)) notificationMenu.value.open = false
}

const switchWorkspace = async (role: Role) => {
  if (!allowedWorkspaces.value.includes(role)) return
  const path = roleHome(role)
  closeAccountMenu()
  if (path) await router.push(path)
}

const logout = async () => {
  if (isLoggingOut.value) return
  closeAccountMenu()
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
  <div class="workspace-shell app-shell" @keydown.capture.tab="searchInputFocusedByTab = true" @pointerdown.capture="handleShellPointerdown">
    <header class="workspace-topbar">
      <RouterLink class="workspace-topbar__brand" :to="roleHome(currentRole) || '/login'">
        <AppLogo compact />
        <span class="workspace-topbar__title">{{ currentWorkspaceTitle }}</span>
      </RouterLink>
      <div class="workspace-search-wrap">
        <label class="workspace-search"><Search :size="16" aria-hidden="true" /><input v-model="query" :class="{ 'search-input-focused-by-tab': searchInputFocusedByTab }" type="search" aria-label="Search" placeholder="Search" @focus="searchOpen = true" @keydown.enter.prevent="openFirstResult" @keydown.esc="searchOpen = false" /><button v-if="query" type="button" aria-label="清除搜索" @click="query = ''; searchOpen = true">×</button></label>
        <div v-if="searchOpen && query" class="workspace-search__results" role="listbox" aria-label="导航搜索结果">
          <RouterLink v-for="item in navItems" :key="item.to + item.label" :to="item.to" role="option" @click="query = ''; searchOpen = false"><component :is="item.icon" :size="16" aria-hidden="true" /><span>{{ item.label }}</span></RouterLink>
          <span v-if="!navItems.length" class="workspace-search__empty">没有匹配的导航</span>
        </div>
      </div>
      <div class="workspace-topbar__actions">
        <details ref="notificationMenu" class="notification-menu">
          <summary aria-label="Notification" title="Notification"><Bell :size="18" aria-hidden="true" /></summary>
          <section class="notification-menu__panel" role="dialog" aria-label="Notification">
            <header class="notification-menu__header">
              <h2>Notification</h2>
              <span class="notification-menu__indicator" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="m4 12 3 3 5-6" />
                  <path d="M14 7h6M14 12h6M14 17h6" />
                </svg>
              </span>
            </header>
            <div class="notification-menu__empty" role="status" aria-live="polite">
              <img class="notification-menu__empty-art" src="/assets/psynova/notification-empty.svg" alt="" aria-hidden="true" />
              <strong>You have no new notification</strong>
            </div>
          </section>
        </details>
        <details ref="accountMenu" class="account-menu">
          <summary :aria-label="`账号菜单，${session.user?.displayName || '当前账号'}`"><span class="account-menu__avatar" aria-hidden="true"><template v-if="session.user?.initials">{{ session.user.initials }}</template><UserRound v-else :size="18" /></span><span class="account-menu__copy"><strong>{{ session.user?.displayName || '当前账号' }}</strong><small>{{ currentWorkspaceTitle }}</small></span><ChevronDown :size="15" aria-hidden="true" /></summary>
          <div class="account-menu__panel">
            <div class="account-menu__profile">
              <span class="account-menu__avatar account-menu__avatar--large" aria-hidden="true"><template v-if="session.user?.initials">{{ session.user.initials }}</template><UserRound v-else :size="20" /></span>
              <span class="account-menu__profile-copy">
                <strong>{{ session.user?.displayName || '当前账号' }}</strong>
                <small>{{ currentWorkspaceTitle }}</small>
              </span>
            </div>
            <div class="account-menu__rule"></div>
            <RouterLink v-for="item in workspaceConfig[currentRole]?.items ?? []" :key="item.to + item.label" class="account-menu__item" :to="item.to" @click="closeAccountMenu"><component :is="item.icon" :size="17" aria-hidden="true" /><span>{{ item.label }}</span></RouterLink>
            <template v-if="canSwitchWorkspace">
              <button v-for="role in allowedWorkspaces" :key="role" class="account-menu__item" type="button" :disabled="role === currentRole" @click="switchWorkspace(role)"><component :is="workspaceConfig[role]?.items[0]?.icon" :size="17" aria-hidden="true" /><span>{{ workspaceConfig[role]?.title ?? roleLabels[role] }}</span></button>
            </template>
            <div class="account-menu__rule"></div>
            <button class="account-menu__item" type="button" @click="openHelp"><CircleHelp :size="17" aria-hidden="true" /><span>帮助</span></button>
            <button class="account-menu__item account-menu__logout" type="button" :disabled="isLoggingOut" @click="logout"><LogOut :size="17" aria-hidden="true" /><span>退出登录</span></button>
          </div>
        </details>
        <button class="workspace-topbar__menu" type="button" aria-label="打开工作区导航" title="打开工作区导航" @click="sidebarOpen = true"><Menu :size="19" aria-hidden="true" /></button>
      </div>
    </header>
    <RoleSidebar v-model:mobile-open="sidebarOpen" :role="currentRole" />
    <main class="workspace-main" :class="{ 'workspace-main--teacher-overview': route.name === 'teacher-overview' }">
      <div v-if="logoutError" class="workspace-error" role="alert">{{ logoutError }}</div>
      <slot />
      <footer class="workspace-footer">
        <nav class="workspace-footer__links" aria-label="页面底部">
          <button type="button" @click="openHelp">使用手册</button>
          <span>隐私政策</span>
          <span>平台规范</span>
          <span class="workspace-footer__choices"><span>数据选择</span><svg class="workspace-footer__choice-mark" xmlns="http://www.w3.org/2000/svg" width="30" height="14" viewBox="0 0 30 14" fill="none" aria-hidden="true" focusable="false">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M7.00313 12.7992H13.8031L16.9031 1.19922H7.00313C3.80313 1.19922 1.20312 3.79922 1.20312 6.99922C1.20312 10.1992 3.80313 12.7992 7.00313 12.7992Z" fill="white" />
            <path fill-rule="evenodd" clip-rule="evenodd" d="M22.2 0H7C3.1 0 0 3.1 0 7C0 10.9 3.1 14 7 14H22.2C26.1 14 29.2 10.9 29.2 7C29.2 3.1 26 0 22.2 0ZM1.2 7C1.2 3.8 3.8 1.2 7 1.2H16.9L13.8 12.8H7C3.8 12.8 1.2 10.2 1.2 7Z" fill="currentColor" />
            <path d="M24.1969 3.99961C24.3969 4.19961 24.3969 4.59961 24.1969 4.79961L22.0969 6.99961L24.2969 9.19961C24.4969 9.39961 24.4969 9.79961 24.2969 9.99961C24.0969 10.1996 23.6969 10.1996 23.4969 9.99961L21.2969 7.79961L19.0969 9.99961C18.8969 10.1996 18.4969 10.1996 18.2969 9.99961C18.0969 9.79961 18.0969 9.39961 18.2969 9.19961L20.3969 6.99961L18.1969 4.79961C17.9969 4.59961 17.9969 4.19961 18.1969 3.99961C18.3969 3.79961 18.7969 3.79961 18.9969 3.99961L21.1969 6.19961L23.3969 3.99961C23.5969 3.79961 23.9969 3.79961 24.1969 3.99961Z" fill="white" />
            <path d="M12.3016 4.09922C12.5016 4.29922 12.6016 4.69922 12.4016 4.89922L8.20156 9.79922C8.10156 9.89922 8.00156 9.99922 7.90156 9.99922C7.70156 10.0992 7.40156 10.0992 7.20156 9.89922L5.00156 7.69922C4.80156 7.49922 4.80156 7.09922 5.00156 6.89922C5.20156 6.69922 5.60156 6.69922 5.80156 6.89922L7.60156 8.59922L11.4016 4.09922C11.6016 3.89922 12.0016 3.89922 12.3016 4.09922Z" fill="currentColor" />
          </svg></span>
        </nav>
        <button class="workspace-footer__help" type="button" aria-label="帮助" title="帮助" @click="openHelp"><CircleHelp :size="20" aria-hidden="true" /></button>
      </footer>
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
.workspace-shell { background: var(--color-canvas); }
.workspace-topbar { position: fixed; z-index: 40; inset: 0 0 auto; display: flex; align-items: center; gap: 15px; width: 100%; max-width: 1907px; height: var(--layout-topbar); margin: 0 auto; padding: 0 20px; background: rgb(247 247 247 / 88%); backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px); }
.workspace-topbar__brand { display: inline-flex; align-items: center; gap: 15px; flex: 0 0 auto; min-width: 0; color: var(--color-text-primary); }
.workspace-topbar__title { overflow: hidden; max-width: min(34vw, 360px); color: var(--color-text-primary); font-size: 16px; font-weight: 500; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; }
.workspace-search-wrap { position: relative; z-index: 45; width: 144px; height: 42px; flex: 0 0 144px; margin-left: auto; }
.workspace-search { display: flex; align-items: center; gap: 5px; width: 144px; height: 42px; padding: 0 10px; border: 1px solid transparent; border-radius: 6px; color: #a0a3ab; background: rgb(24 26 31 / 7%); transition: all 300ms ease-in-out; }
.workspace-search:focus-within { border-color: #3f424a; }
.workspace-search:focus-within > svg { color: #3f424a; }
.workspace-search:has(.search-input-focused-by-tab):focus-within { outline: 2px solid #3f424a; outline-offset: 1px; }
.workspace-search > svg { flex: 0 0 auto; }
.workspace-search input { min-width: 0; width: 84px; flex: 1; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font-size: 14px; font-weight: 500; line-height: 1.3; }
.workspace-search input::placeholder { color: #a0a3ab; opacity: 1; }
.workspace-search input::-webkit-search-cancel-button { appearance: none; }
.workspace-search button { display: inline-grid; place-items: center; width: 18px; height: 18px; flex: 0 0 auto; padding: 0; border: 0; color: var(--color-text-muted); background: transparent; cursor: pointer; font-size: 18px; line-height: 1; }
.workspace-search__results { position: absolute; z-index: 50; top: calc(100% + 8px); right: 0; left: 0; display: grid; gap: 2px; padding: 6px; border: 0; border-radius: 8px; background: #ffffff; box-shadow: var(--shadow-raised); }
.workspace-search__results a { display: flex; align-items: center; gap: 9px; min-height: 40px; padding: 0 10px; border-radius: 6px; color: var(--color-text-secondary); font-size: 14px; font-weight: 500; }
.workspace-search__results a:hover, .workspace-search__results a:focus-visible { color: var(--color-primary); background: var(--color-surface-muted); }
.workspace-search__empty { padding: 12px 10px; color: var(--color-text-muted); font-size: 12px; }
.workspace-topbar__actions { display: flex; align-items: center; gap: 5px; flex: 0 0 auto; margin-left: 0; }
.workspace-help, .notification-menu summary, .account-menu summary, .workspace-topbar__menu { display: inline-flex; align-items: center; justify-content: center; min-width: 40px; min-height: 40px; padding: 0 8px; border: 0; border-radius: 6px; color: var(--color-text-secondary); background: transparent; cursor: pointer; transition: color var(--motion-fast), background var(--motion-fast); }
.workspace-help { gap: 5px; font-size: 12px; font-weight: 500; }
.workspace-help:hover, .notification-menu summary:hover, .account-menu summary:hover, .workspace-topbar__menu:hover { color: var(--color-primary); background: var(--color-surface-muted); }
.notification-menu, .account-menu { position: relative; }
.notification-menu summary, .account-menu summary { list-style: none; }
.notification-menu summary::-webkit-details-marker, .account-menu summary::-webkit-details-marker { display: none; }
.notification-menu__panel { position: absolute; z-index: 100; top: calc(100% + 8px); right: 0; display: flex; flex-direction: column; width: min(448px, calc(100vw - 24px)); height: min(496px, calc(100dvh - var(--layout-topbar) - 20px)); min-height: 260px; border-radius: 10px; background: #ffffff; box-shadow: 0 14px 38px rgb(27 31 44 / 16%), 0 2px 8px rgb(27 31 44 / 7%); }
.notification-menu__panel::before { position: absolute; top: -7px; right: 14px; width: 14px; height: 14px; border-radius: 2px; background: #ffffff; content: ""; transform: rotate(45deg); }
.notification-menu__header { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between; min-height: 62px; flex: 0 0 62px; padding: 0 18px; border-bottom: 1px solid #e5e7eb; background: #ffffff; border-radius: 10px 10px 0 0; }
.notification-menu__header h2 { margin: 0; color: var(--color-text-primary); font-size: 16px; font-weight: 600; line-height: 1.3; }
.notification-menu__indicator { display: inline-grid; place-items: center; width: 24px; height: 24px; color: #687080; }
.notification-menu__indicator svg { width: 21px; height: 21px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; }
.notification-menu__empty { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 0; padding: 24px; text-align: center; }
.notification-menu__empty-art { display: block; width: 168px; height: 156px; flex: 0 0 auto; object-fit: contain; }
.notification-menu__empty strong { color: #626978; font-size: 16px; font-weight: 500; line-height: 1.4; }
.account-menu summary { gap: 8px; min-width: 0; padding: 0 5px; }
.account-menu summary > svg { color: #656b76; }
.account-menu__avatar { display: inline-grid; place-items: center; width: 34px; height: 34px; flex: 0 0 34px; overflow: hidden; border-radius: 50%; color: #1e1d29; background: #e6e6e8; font-size: 13px; font-weight: 600; }
.account-menu__copy { display: grid; gap: 2px; min-width: 0; }
.account-menu__copy strong { max-width: 132px; overflow: hidden; color: var(--color-text-primary); font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.account-menu__copy small { max-width: 150px; overflow: hidden; color: var(--color-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.account-menu__copy, .account-menu summary > svg { display: none; }
.account-menu__panel { position: absolute; z-index: 100; top: calc(100% + 10px); right: 0; display: grid; width: min(328px, calc(100vw - 24px)); padding: 14px 18px 10px; border: 1px solid rgb(31 35 45 / 5%); border-radius: 10px; background: #ffffff; box-shadow: 0 14px 38px rgb(27 31 44 / 16%), 0 2px 8px rgb(27 31 44 / 7%); }
.account-menu__panel::before { position: absolute; top: -7px; right: 16px; width: 14px; height: 14px; border-radius: 2px; background: #ffffff; content: ""; transform: rotate(45deg); }
.account-menu__profile { position: relative; z-index: 1; display: flex; align-items: center; gap: 14px; min-height: 74px; padding: 0 0 12px; }
.account-menu__avatar--large { width: 54px; height: 54px; flex-basis: 54px; border: 1px solid #7b8190; color: #3e4350; background: #f8f9fb; font-size: 17px; }
.account-menu__profile-copy { display: grid; gap: 5px; min-width: 0; }
.account-menu__profile-copy strong { overflow: hidden; color: #191923; font-size: 14px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.account-menu__profile-copy small { overflow: hidden; color: #5f6572; font-size: 11px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.account-menu__item { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; min-width: 0; min-height: 52px; padding: 0; border: 0; border-bottom: 1px solid #e4e6ea; border-radius: 0; color: #191923; background: transparent; cursor: pointer; text-align: left; font: inherit; font-size: 14px; font-weight: 450; text-decoration: none; }
.account-menu__item svg { flex: 0 0 18px; color: #4f5562; }
.account-menu__item:hover:not(:disabled), .account-menu__item.router-link-active { color: var(--color-primary); background: transparent; }
.account-menu__item:hover:not(:disabled) svg { color: var(--color-primary); }
.account-menu__item:disabled { color: var(--color-primary); cursor: default; }
.account-menu__item:disabled svg { color: var(--color-primary); }
.account-menu__rule { height: 1px; margin: 0 -18px; background: #e4e6ea; }
.account-menu__logout { min-height: 48px; border-bottom: 0; }
.account-menu__logout:disabled { opacity: .55; cursor: wait; }
.workspace-topbar__menu { display: none; }
.workspace-main { display: flex; flex-direction: column; width: calc(100% - var(--layout-sidebar)); max-width: var(--layout-content-max); min-height: 100vh; margin-left: var(--layout-sidebar); padding-top: var(--layout-topbar); background: transparent; }
.workspace-error { width: calc(100% - 30px); max-width: var(--layout-content-max); margin: 16px 30px 0 0; padding: 12px 14px; border: 0; border-radius: 8px; color: #8f1d14; background: #fff3f1; font-size: 13px; }
.workspace-footer { display: flex; align-items: center; justify-content: flex-end; gap: clamp(26px, 4vw, 52px); width: 100%; max-width: var(--layout-content-max); margin-top: auto; padding: 70px 30px 30px 0; color: #656b76; font-size: 14px; font-weight: 500; }
.workspace-main--teacher-overview .workspace-footer { padding-top: 35px; }
.workspace-footer__links { display: flex; align-items: center; justify-content: flex-end; gap: clamp(14px, 2vw, 26px); }
.workspace-footer__links button, .workspace-footer__help { display: inline-flex; align-items: center; justify-content: center; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; font: inherit; font-size: inherit; white-space: nowrap; }
.workspace-footer__links button:hover, .workspace-footer__help:hover { color: var(--color-primary); }
.workspace-footer__choices { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.workspace-footer__choice-mark { display: block; width: 30px; height: 14px; flex: 0 0 30px; color: #00b1e2; }
.workspace-footer__help { width: 22px; height: 24px; flex: 0 0 22px; }
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
@media (max-width: 1200px) {
  .workspace-topbar { padding-right: 24px; padding-left: 24px; }
  .workspace-topbar__menu { display: inline-grid; place-items: center; }
  .workspace-main { width: 100%; max-width: none; margin-left: 0; }
  .workspace-error { width: calc(100% - 60px); margin-right: 30px; margin-left: 30px; }
  .workspace-footer { width: 100%; max-width: none; padding-right: 30px; padding-left: 30px; }
}
@media (max-width: 767px) {
  .workspace-topbar { gap: 10px; padding-right: 16px; padding-left: 16px; }
  .workspace-topbar__title { max-width: 30vw; }
  .workspace-search-wrap { width: 42px; flex-basis: 42px; }
  .workspace-search { width: 42px; padding: 0 10px; border-color: transparent; background: transparent; }
  .workspace-search-wrap:focus-within { width: min(44vw, 210px); flex-basis: min(44vw, 210px); }
  .workspace-search-wrap:focus-within .workspace-search { width: 100%; }
  .workspace-search input { display: none; }
  .workspace-search-wrap:focus-within input { display: block; }
  .workspace-search button { display: none; }
  .workspace-topbar__actions { gap: 2px; }
  .workspace-help { width: 38px; min-width: 38px; padding: 0; }
  .account-menu summary { padding: 0; }
  .account-menu__avatar { width: 32px; height: 32px; flex-basis: 32px; }
  .account-menu__panel { position: fixed; top: calc(var(--layout-topbar) - 2px); right: 12px; width: min(328px, calc(100vw - 24px)); }
  .account-menu__panel::before { right: 57px; }
  .workspace-error { width: calc(100% - 36px); margin: 14px 18px 0; }
  .workspace-footer { align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 14px 24px; padding: 34px 18px 22px; font-size: 11px; }
  .workspace-main--teacher-overview .workspace-footer { padding-top: 17px; }
  .workspace-footer__links { justify-content: flex-end; flex-wrap: wrap; gap: 12px 16px; }
  .workspace-footer__help { margin-left: 0; }
  .notification-menu__panel { position: fixed; top: calc(var(--layout-topbar) - 8px); right: 12px; width: min(448px, calc(100vw - 24px)); height: min(496px, calc(100dvh - var(--layout-topbar) - 16px)); }
  .notification-menu__panel::before { right: 93px; }
}
@media (max-width: 860px) {
  .workspace-dialog__content { min-height: 0; padding: 60px 20px 24px; }
  .workspace-dialog__inner { min-height: 190px; gap: 24px; }
}
@media (max-width: 575px) {
  .workspace-topbar { padding-right: 12px; padding-left: 12px; }
  .workspace-topbar__title { display: none; }
  .workspace-search-wrap { margin-left: auto; }
  .notification-menu__panel { right: 12px; }
  .notification-menu__panel::before { right: 89px; }
  .workspace-dialog__content { padding: 26px 20px 20px; }
  .workspace-dialog__content :deep([data-slot="dialog-title"]) { font-size: 20px; }
  .workspace-footer { column-gap: 12px; }
  .workspace-footer__links { flex: 1 1 calc(100% - 38px); justify-content: flex-end; gap: 10px 14px; }
}
</style>
