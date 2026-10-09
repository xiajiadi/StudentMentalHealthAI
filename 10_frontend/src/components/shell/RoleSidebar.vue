<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ShieldCheck, X } from '@lucide/vue'
import { DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle } from 'reka-ui'
import AppLogo from '@/components/app/AppLogo.vue'
import { workspaceConfig } from '@/components/shell/navigation'
import type { Role } from '@/types/contracts'

const props = defineProps<{ role: Role; mobileOpen: boolean }>()
const emit = defineEmits<{ 'update:mobileOpen': [value: boolean] }>()
const route = useRoute()

const config = computed(() => workspaceConfig[props.role] ?? workspaceConfig.student!)
const isActive = (to: string) => route.path === to || route.path.startsWith(`${to}/`)
const closeMobile = () => emit('update:mobileOpen', false)
</script>

<template>
  <aside class="role-sidebar" aria-label="主要导航">
    <div class="role-sidebar__heading"><span class="role-sidebar__section">工作空间</span><strong>{{ config.title }}</strong></div>
    <nav class="role-sidebar__nav" aria-label="工作区导航">
      <RouterLink v-for="item in config.items" :key="item.to + item.label" :to="item.to" class="role-sidebar__link" :class="{ 'role-sidebar__link--active': isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined" @click="closeMobile">
        <component :is="item.icon" :size="18" stroke-width="1.7" aria-hidden="true" /><span>{{ item.label }}</span>
      </RouterLink>
    </nav>
    <div class="role-sidebar__foot"><span class="role-sidebar__foot-icon"><ShieldCheck :size="15" aria-hidden="true" /></span><span>仅显示当前账号可访问的功能</span></div>
  </aside>

  <DialogRoot :open="mobileOpen" @update:open="emit('update:mobileOpen', $event)">
    <DialogPortal>
      <DialogOverlay class="role-sidebar__overlay" />
      <DialogContent class="role-sidebar__mobile-panel">
        <DialogTitle class="sr-only">{{ config.title }}</DialogTitle><DialogDescription class="sr-only">移动端工作区导航</DialogDescription>
        <div class="role-sidebar__mobile-head"><RouterLink :to="config.home" @click="closeMobile"><AppLogo /></RouterLink><DialogClose as-child><button class="role-sidebar__mobile-close" type="button" aria-label="关闭导航"><X :size="18" /></button></DialogClose></div>
        <div class="role-sidebar__mobile-title">{{ config.title }}</div>
        <nav class="role-sidebar__nav role-sidebar__nav--mobile" aria-label="移动端工作区导航">
          <RouterLink v-for="item in config.items" :key="item.to + item.label" :to="item.to" class="role-sidebar__link" :class="{ 'role-sidebar__link--active': isActive(item.to) }" :aria-current="isActive(item.to) ? 'page' : undefined" @click="closeMobile"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span></RouterLink>
        </nav>
        <div class="role-sidebar__foot"><span class="role-sidebar__foot-icon"><ShieldCheck :size="15" /></span><span>仅显示当前账号可访问的功能</span></div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.role-sidebar { position: fixed; z-index: 30; top: var(--layout-topbar); bottom: 0; left: 0; display: flex; flex-direction: column; width: var(--layout-sidebar); padding: 26px 16px 18px; border-right: 1px solid var(--color-border); background: var(--color-sidebar); }
.role-sidebar__heading { display: grid; gap: 7px; padding: 0 12px 23px; border-bottom: 1px solid var(--color-border); }
.role-sidebar__heading strong { color: var(--color-text-primary); font-size: 14px; font-weight: 700; }
.role-sidebar__section { color: var(--color-text-muted); font-size: 10px; font-weight: 700; letter-spacing: .1em; }
.role-sidebar__nav { display: grid; align-content: start; gap: 5px; padding: 18px 0; overflow-y: auto; }
.role-sidebar__link { display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 0 12px; border-radius: 8px; color: var(--color-text-secondary); font-size: 13px; font-weight: 600; transition: color var(--motion-fast), background var(--motion-fast); }
.role-sidebar__link svg { color: #8a929b; }
.role-sidebar__link:hover { color: var(--color-primary); background: #f2fbfe; }
.role-sidebar__link--active { color: var(--color-primary); background: #e9f9fe; }
.role-sidebar__link--active svg { color: var(--color-primary); }
.role-sidebar__foot { display: flex; align-items: center; gap: 9px; margin-top: auto; padding: 15px 9px 0; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.role-sidebar__foot-icon { display: inline-flex; color: var(--color-primary); }
.role-sidebar__overlay { position: fixed; inset: 0; z-index: 50; background: rgb(23 32 51 / 38%); }
.role-sidebar__mobile-panel { position: fixed; z-index: 60; inset: 0 auto 0 0; display: flex; flex-direction: column; width: min(86vw, 312px); padding: 20px 16px 18px; border: 0; background: var(--color-sidebar); box-shadow: 18px 0 35px rgb(23 32 51 / 16%); }
.role-sidebar__mobile-head { display: flex; align-items: center; justify-content: space-between; padding: 0 7px 18px; border-bottom: 1px solid var(--color-border); }
.role-sidebar__mobile-close { display: inline-grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-secondary); background: white; cursor: pointer; }
.role-sidebar__mobile-title { padding: 18px 8px 5px; color: var(--color-text-secondary); font-size: 12px; font-weight: 700; }
.role-sidebar__nav--mobile { flex: 1; }
@media (max-width: 1023px) { .role-sidebar { display: none; } }
</style>
