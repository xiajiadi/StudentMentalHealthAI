<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { BarChart3 } from '@lucide/vue'
import { ClipboardCheck } from '@lucide/vue'
import { FileCheck2 } from '@lucide/vue'
import { LifeBuoy } from '@lucide/vue'
import { LogOut } from '@lucide/vue'
import { PanelLeft } from '@lucide/vue'
import { UsersRound } from '@lucide/vue'
import { X } from '@lucide/vue'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import AppLogo from '@/components/app/AppLogo.vue'
import type { SessionUser } from '@/types/view-models'

const props = defineProps<{
  role: 'teacher' | 'reviewer'
  user: SessionUser | null
  mobileOpen: boolean
}>()

const emit = defineEmits<{
  'update:mobileOpen': [value: boolean]
  logout: []
}>()

const route = useRoute()

const roleLabel = computed(() => props.role === 'teacher' ? '教师支持工作区' : '安全复核工作区')
const navItems = computed(() => props.role === 'teacher'
  ? [
      { label: '工作概览', to: '/teacher/overview', icon: BarChart3 },
      { label: '学生支持', to: '/teacher/students', icon: UsersRound },
    ]
  : [
      { label: '复核队列', to: '/reviewer/queue', icon: FileCheck2 },
    ])

const secondaryItems = computed(() => props.role === 'teacher'
  ? [{ label: '测评记录', to: '/teacher/students', icon: ClipboardCheck }]
  : [{ label: '工作边界', to: '/reviewer/queue', icon: LifeBuoy }])

const isActive = (to: string) => route.path === to || route.path.startsWith(`${to}/`)

const closeMobile = () => emit('update:mobileOpen', false)
const logOut = () => emit('logout')

</script>

<template>
  <aside class="role-sidebar" :data-role="role" aria-label="主要导航">
    <div class="role-sidebar__brand">
      <RouterLink :to="role === 'teacher' ? '/teacher/overview' : '/reviewer/queue'" aria-label="返回工作区首页">
        <AppLogo />
      </RouterLink>
      <span class="role-sidebar__scope">{{ roleLabel }}</span>
    </div>

    <nav class="role-sidebar__nav" aria-label="工作区导航">
      <span class="role-sidebar__section-label">主要功能</span>
      <RouterLink
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="role-sidebar__link"
        :class="{ 'role-sidebar__link--active': isActive(item.to) }"
        :aria-current="isActive(item.to) ? 'page' : undefined"
      >
        <component :is="item.icon" :size="18" stroke-width="1.8" aria-hidden="true" />
        <span>{{ item.label }}</span>
      </RouterLink>

      <span class="role-sidebar__section-label role-sidebar__section-label--secondary">辅助入口</span>
      <RouterLink
        v-for="item in secondaryItems"
        :key="item.to + item.label"
        :to="item.to"
        class="role-sidebar__link"
        :class="{ 'role-sidebar__link--active': role === 'teacher' && isActive(item.to) && route.path === '/teacher/students' }"
        @click="mobile ? closeMobile() : undefined"
      >
        <component :is="item.icon" :size="18" stroke-width="1.8" aria-hidden="true" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="role-sidebar__note">
      <span class="role-sidebar__note-icon"><PanelLeft :size="15" aria-hidden="true" /></span>
      <p>只展示当前角色和安全披露策略允许的内容。</p>
    </div>

    <div class="role-sidebar__account">
      <span class="role-sidebar__avatar" aria-hidden="true">{{ user?.initials || '演' }}</span>
      <div class="role-sidebar__account-copy">
        <strong>{{ user?.displayName || '演示用户' }}</strong>
        <span>合成环境</span>
      </div>
      <button class="role-sidebar__logout" type="button" aria-label="退出演示" @click="logOut">
        <LogOut :size="17" aria-hidden="true" />
      </button>
    </div>
  </aside>

  <DialogRoot :open="mobileOpen" @update:open="emit('update:mobileOpen', $event)">
    <DialogPortal>
      <DialogOverlay class="role-sidebar__overlay" />
      <DialogContent class="role-sidebar__mobile-panel">
        <DialogTitle class="sr-only">{{ roleLabel }}</DialogTitle>
        <DialogDescription class="sr-only">移动端工作区导航</DialogDescription>
        <div class="role-sidebar__mobile-head">
          <AppLogo />
          <DialogClose as-child>
            <button class="role-sidebar__mobile-close" type="button" aria-label="关闭导航">
              <X :size="18" aria-hidden="true" />
            </button>
          </DialogClose>
        </div>
        <nav class="role-sidebar__nav role-sidebar__nav--mobile" aria-label="移动端工作区导航">
          <span class="role-sidebar__section-label">{{ roleLabel }}</span>
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="role-sidebar__link"
            :class="{ 'role-sidebar__link--active': isActive(item.to) }"
            :aria-current="isActive(item.to) ? 'page' : undefined"
            @click="closeMobile"
          >
            <component :is="item.icon" :size="18" stroke-width="1.8" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </RouterLink>
          <span class="role-sidebar__section-label role-sidebar__section-label--secondary">辅助入口</span>
          <RouterLink
            v-for="item in secondaryItems"
            :key="item.to + item.label"
            :to="item.to"
            class="role-sidebar__link"
            @click="closeMobile"
          >
            <component :is="item.icon" :size="18" stroke-width="1.8" aria-hidden="true" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
        <div class="role-sidebar__account role-sidebar__account--mobile">
          <span class="role-sidebar__avatar" aria-hidden="true">{{ user?.initials || '演' }}</span>
          <div class="role-sidebar__account-copy">
            <strong>{{ user?.displayName || '演示用户' }}</strong>
            <span>合成环境</span>
          </div>
          <button class="role-sidebar__logout" type="button" aria-label="退出演示" @click="logOut">
            <LogOut :size="17" aria-hidden="true" />
          </button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.role-sidebar {
  position: fixed;
  z-index: 40;
  top: 0;
  left: 0;
  display: flex;
  flex-direction: column;
  width: var(--layout-sidebar);
  height: 100vh;
  padding: 22px 16px 16px;
  color: var(--color-text-inverse);
  background: var(--color-sidebar);
}

.role-sidebar::after {
  position: absolute;
  top: 0;
  right: 0;
  width: 3px;
  height: 100%;
  content: "";
  background: var(--color-primary);
  opacity: 0.72;
}

.role-sidebar__brand { display: grid; gap: 15px; padding: 0 8px 20px; border-bottom: 1px solid rgb(255 255 255 / 12%); }
.role-sidebar__brand a { width: fit-content; color: var(--color-text-inverse); }
.role-sidebar__brand :deep(.app-logo__wordmark small) { color: var(--color-sidebar-muted); }
.role-sidebar__brand :deep(.app-logo__mark) { color: var(--color-sidebar-mark); }
.role-sidebar__scope { color: var(--color-sidebar-muted); font-size: 11px; line-height: 1.4; }
.role-sidebar__nav { display: flex; flex: 1; flex-direction: column; gap: 5px; overflow-y: auto; padding: 21px 0; }
.role-sidebar__section-label { padding: 0 11px 7px; color: var(--color-sidebar-label); font-size: 10px; font-weight: 800; letter-spacing: 0.13em; text-transform: uppercase; }
.role-sidebar__section-label--secondary { margin-top: 22px; }
.role-sidebar__link { position: relative; display: flex; align-items: center; gap: 11px; min-height: 44px; padding: 0 11px; border-radius: 7px; color: var(--color-sidebar-muted); font-size: 13px; font-weight: 600; transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.role-sidebar__link svg { flex: 0 0 auto; transition: transform var(--motion-fast) ease; }
.role-sidebar__link:hover { color: var(--color-text-inverse); background: rgb(255 255 255 / 8%); }
.role-sidebar__link:hover svg { transform: translateX(2px); }
.role-sidebar__link--active { color: var(--color-text-inverse); background: rgb(37 99 235 / 24%); }
.role-sidebar__link--active::before { position: absolute; left: -16px; width: 3px; height: 22px; border-radius: 0 3px 3px 0; content: ""; background: var(--color-sidebar-active); }
.role-sidebar__note { display: flex; gap: 8px; padding: 12px 10px; border-top: 1px solid rgb(255 255 255 / 10%); border-bottom: 1px solid rgb(255 255 255 / 10%); color: var(--color-sidebar-note); }
.role-sidebar__note-icon { display: inline-flex; align-items: center; justify-content: center; width: 25px; height: 25px; flex: 0 0 25px; border: 1px solid rgb(255 255 255 / 12%); border-radius: 6px; color: var(--color-sidebar-note-icon); }
.role-sidebar__note p { margin: 0; font-size: 11px; line-height: 1.55; }
.role-sidebar__account { display: flex; align-items: center; gap: 10px; padding: 17px 6px 0; }
.role-sidebar__avatar { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; flex: 0 0 32px; border: 1px solid rgb(255 255 255 / 24%); border-radius: 50%; color: var(--color-sidebar-avatar); background: rgb(37 99 235 / 24%); font-size: 13px; font-weight: 800; }
.role-sidebar__account-copy { display: grid; min-width: 0; flex: 1; gap: 3px; }
.role-sidebar__account-copy strong { overflow: hidden; color: var(--color-text-inverse); font-size: 12px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.role-sidebar__account-copy span { color: var(--color-sidebar-account-muted); font-size: 10px; }
.role-sidebar__logout { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border: 0; border-radius: 7px; color: var(--color-sidebar-note); background: transparent; cursor: pointer; }
.role-sidebar__logout:hover { color: var(--color-text-inverse); background: rgb(255 255 255 / 8%); }
.role-sidebar__overlay { position: fixed; inset: 0; z-index: 50; background: rgb(23 32 51 / 52%); }
.role-sidebar__mobile-panel { position: fixed; z-index: 60; top: 0; bottom: 0; left: 0; display: flex; flex-direction: column; width: min(82vw, 300px); padding: 21px 16px 16px; border: 0; color: var(--color-text-inverse); background: var(--color-sidebar); box-shadow: 18px 0 35px rgb(23 32 51 / 16%); }
.role-sidebar__mobile-head { display: flex; align-items: center; justify-content: space-between; padding: 0 8px 20px; border-bottom: 1px solid rgb(255 255 255 / 12%); }
.role-sidebar__mobile-head :deep(.app-logo__wordmark small) { color: var(--color-sidebar-muted); }
.role-sidebar__mobile-head :deep(.app-logo__mark) { color: var(--color-sidebar-mark); }
.role-sidebar__mobile-close { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border: 1px solid rgb(255 255 255 / 16%); border-radius: 7px; color: var(--color-sidebar-close); background: transparent; cursor: pointer; }
.role-sidebar__mobile-close:hover { background: rgb(255 255 255 / 8%); }
.role-sidebar__nav--mobile { padding-top: 24px; }
.role-sidebar__account--mobile { margin-top: auto; }

@media (max-width: 1023px) {
  .role-sidebar { display: none; }
}
</style>
