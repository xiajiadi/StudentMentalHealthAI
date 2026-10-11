<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { X } from '@lucide/vue'
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
    <div class="role-sidebar__foot" role="img" aria-label="Powered by PsyNova">
      <span>Powered by</span><img src="/assets/psynova/wordmark.png" alt="" aria-hidden="true">
    </div>
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
        <div class="role-sidebar__foot" role="img" aria-label="Powered by PsyNova">
          <span>Powered by</span><img src="/assets/psynova/wordmark.png" alt="" aria-hidden="true">
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.role-sidebar { position: fixed; z-index: 30; top: var(--layout-topbar); bottom: 0; left: 0; display: flex; flex-direction: column; width: var(--layout-sidebar); padding: 0 0 10px; background: transparent; }
.role-sidebar__heading { display: none; }
.role-sidebar__nav { display: grid; align-content: start; gap: 0; padding: 10px 30px; overflow-y: auto; }
.role-sidebar__link { display: flex; align-items: center; gap: 5px; min-height: 42px; padding: 10px 0; color: #656b76; font-size: 16px; font-weight: 500; line-height: 1.3; transition: color var(--motion-fast); }
.role-sidebar__link svg { flex: 0 0 auto; color: inherit; }
.role-sidebar__link:hover, .role-sidebar__link--active { color: var(--color-primary); background: transparent; }
.role-sidebar__foot { display: flex; align-items: center; gap: 3px; width: fit-content; min-height: 28px; margin: auto 18px 0; padding: 0; border-radius: 6px; color: #a0a3ab; font-size: 10px; line-height: 12px; }
.role-sidebar__foot img { display: block; width: 64px; height: 32px; object-fit: contain; }
.role-sidebar__foot:focus-visible { outline: 2px solid #3f424a; outline-offset: 1px; }
.role-sidebar__overlay { position: fixed; inset: 0; z-index: 50; background: rgb(24 26 31 / 38%); }
.role-sidebar__mobile-panel { position: fixed; z-index: 60; inset: 0 auto 0 0; display: flex; flex-direction: column; width: min(86vw, 312px); padding: 16px 18px 10px; border: 0; background: #f7f7f7; box-shadow: 18px 0 35px rgb(0 0 0 / 12%); }
.role-sidebar__mobile-head { display: flex; align-items: center; justify-content: space-between; padding: 0 2px 12px; }
.role-sidebar__mobile-close { display: inline-grid; place-items: center; width: 38px; height: 38px; border: 0; border-radius: 6px; color: var(--color-text-secondary); background: transparent; cursor: pointer; }
.role-sidebar__mobile-close:hover { color: var(--color-primary); background: var(--color-surface-muted); }
.role-sidebar__mobile-title { padding: 16px 0 5px; color: var(--color-text-secondary); font-size: 14px; font-weight: 600; }
.role-sidebar__nav--mobile { flex: 1; padding: 10px 0; }
@media (max-width: 1200px) { .role-sidebar { display: none; } }
</style>
