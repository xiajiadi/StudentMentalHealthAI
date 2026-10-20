<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TabsContent, TabsIndicator, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import SpecialistCatManagement from '@/components/school/SpecialistCatManagement.vue'
import SpecialistCatAssets from '@/components/school/SpecialistCatAssets.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'

type CatWorkspaceMode = 'simulation' | 'assets' | 'research-management'

const route = useRoute()
const router = useRouter()
const activeMode = ref<CatWorkspaceMode>('simulation')

function routeMode(): CatWorkspaceMode {
  const focus = typeof route.query.focus === 'string' ? route.query.focus : ''
  if (focus === 'research-management') return 'research-management'
  if (focus === 'assets') return 'assets'
  if (!focus && route.hash === '#research') return 'research-management'
  return 'simulation'
}

watch([() => route.query.focus, () => route.hash], () => {
  activeMode.value = routeMode()
}, { immediate: true })

async function selectMode(value: string) {
  if (!['simulation', 'assets', 'research-management'].includes(value)) return
  const mode = value as CatWorkspaceMode
  activeMode.value = mode
  const focus = mode
  const currentFocus = Array.isArray(route.query.focus) ? route.query.focus[0] : route.query.focus
  if (currentFocus === focus && !route.hash) return
  await router.push({ path: route.path, query: { ...route.query, focus }, hash: '' })
}
</script>

<template>
  <section class="cat-lab" aria-label="CAT 实验室">
    <section class="cat-lab__workbench" aria-label="CAT 工作模式">
      <TabsRoot :model-value="activeMode" class="cat-lab__tabs" @update:model-value="selectMode">
        <TabsList class="cat-lab__tabs-list" aria-label="CAT 工作模式">
          <TabsIndicator class="cat-lab__tabs-indicator" aria-hidden="true" />
          <TabsTrigger class="cat-lab__tab" value="simulation">工程模拟</TabsTrigger>
          <TabsTrigger class="cat-lab__tab" value="assets">题库与方案</TabsTrigger>
          <TabsTrigger class="cat-lab__tab" value="research-management">研究管理</TabsTrigger>
        </TabsList>

        <TabsContent value="simulation" force-mount class="cat-lab__panel">
          <KeepAlive>
            <SpecialistCatManagement v-if="activeMode === 'simulation'" />
          </KeepAlive>
        </TabsContent>
        <TabsContent value="assets" force-mount class="cat-lab__panel">
          <KeepAlive>
            <SpecialistCatAssets v-if="activeMode === 'assets'" />
          </KeepAlive>
        </TabsContent>
        <TabsContent value="research-management" force-mount class="cat-lab__panel">
          <KeepAlive>
            <SchoolResearchManagement v-if="activeMode === 'research-management'" mode="specialist" />
          </KeepAlive>
        </TabsContent>
      </TabsRoot>
      <p class="cat-lab__boundary">工程模拟指标不等于心理测量学验证结论。</p>
    </section>
  </section>
</template>

<style scoped>
.cat-lab { display: grid; gap: 16px; min-width: 0; color: var(--color-text-primary); }
.cat-lab__workbench { min-width: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface, #fff); box-shadow: var(--shadow-rest); }
.cat-lab__tabs { display: block; min-width: 0; }
.cat-lab__tabs-list { position: relative; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 3px; padding: 8px 12px; border-bottom: 1px solid var(--color-border); background: #fbfdfe; isolation: isolate; }
.cat-lab__tabs-indicator { position: absolute; z-index: 0; top: 8px; left: 0; width: var(--reka-tabs-indicator-size, 0px); height: var(--reka-tabs-indicator-thickness, 0px); border: 1px solid #d8e8ee; border-radius: 9px; background: #fff; box-shadow: 0 1px 3px rgb(29 68 82 / 7%); transform: translateX(var(--reka-tabs-indicator-position, 0px)); transition: transform 190ms cubic-bezier(.2,.8,.2,1); pointer-events: none; }
.cat-lab__tab { position: relative; z-index: 1; display: flex; align-items: center; justify-content: center; min-width: 0; min-height: 38px; padding: 8px 12px; border: 0; border-radius: 8px; color: #657881; background: transparent; font: inherit; font-size: 13px; font-weight: 670; cursor: pointer; transition: color 170ms ease; }
.cat-lab__tab[data-state="active"] { color: #087f9e; }
.cat-lab__tab:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 1px; }
.cat-lab__panel { min-width: 0; padding: 16px; }
.cat-lab__panel[data-state="inactive"] { display: none; }
.cat-lab__boundary { margin: 0; padding: 11px 17px 13px; border-top: 1px solid #eef2f4; color: var(--color-text-muted); font-size: 11px; line-height: 1.5; }
@media (max-width: 700px) { .cat-lab { gap: 13px; }.cat-lab__panel { padding: 12px; } }
@media (max-width: 480px) { .cat-lab__tabs-list { padding-inline: 7px; }.cat-lab__tab { padding-inline: 5px; font-size: 12px; } }
@media (prefers-reduced-motion: reduce) { .cat-lab__tabs-indicator,.cat-lab__tab { transition-duration: .01ms; } }
</style>
