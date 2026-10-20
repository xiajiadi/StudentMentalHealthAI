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
    <section class="cat-lab__banner" aria-label="CAT 实验室介绍">
      <div class="cat-lab__banner-copy">
        <p class="cat-lab__eyebrow">COMPUTERIZED ADAPTIVE TESTING / LAB</p>
        <h2>从测评配置，到可解释的模拟结果</h2>
        <p>一个工作台完成配置、模拟与结果检查。</p>
      </div>
      <div class="cat-lab__instrument" aria-hidden="true">
        <span class="cat-lab__instrument-ring" />
        <span class="cat-lab__instrument-orbit" />
        <span class="cat-lab__instrument-needle" />
        <span class="cat-lab__instrument-ticks" />
        <i />
      </div>
    </section>

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
.cat-lab__banner { position: relative; display: flex; align-items: center; min-height: 122px; overflow: hidden; padding: 22px 26px; border: 1px solid #dce9ee; border-radius: var(--radius-card); background: linear-gradient(108deg, #fafdfe 0%, #f4fafc 68%, #edf7fa 100%); }
.cat-lab__banner::before { position: absolute; inset: 0; background-image: radial-gradient(#b9d7e0 0.7px, transparent 0.7px); background-size: 17px 17px; opacity: .28; content: ''; mask-image: linear-gradient(90deg, transparent 0%, #000 66%); }
.cat-lab__banner-copy { position: relative; z-index: 1; }
.cat-lab__eyebrow { margin: 0 0 8px; color: #1886a2; font-size: 10px; font-weight: 760; letter-spacing: .13em; }
.cat-lab__banner h2 { margin: 0; color: #2d4956; font-size: clamp(18px, 1.9vw, 22px); font-weight: 720; letter-spacing: -.025em; }
.cat-lab__banner-copy > p:last-child { margin: 6px 0 0; color: #6d8189; font-size: 12px; line-height: 1.5; }
.cat-lab__instrument { position: absolute; top: 50%; right: clamp(22px, 7vw, 92px); width: 110px; height: 82px; transform: translateY(-50%); }
.cat-lab__instrument-ring,.cat-lab__instrument-orbit { position: absolute; inset: 8px 21px; border: 1px solid rgb(0 142 181 / 18%); border-radius: 50%; transform: rotate(-24deg); }
.cat-lab__instrument-orbit { inset: 2px 12px; border-style: dashed; opacity: .7; transform: rotate(38deg); }
.cat-lab__instrument-needle { position: absolute; top: 15px; left: 53px; width: 2px; height: 26px; border-radius: 2px; background: #00a4cc; transform: rotate(27deg); transform-origin: 50% 100%; }
.cat-lab__instrument-ticks { position: absolute; inset: 1px 13px; border: 1px solid transparent; border-top-color: rgb(0 142 181 / 27%); border-bottom-color: rgb(0 142 181 / 27%); border-radius: 50%; transform: rotate(-13deg); }
.cat-lab__instrument i { position: absolute; top: 39px; left: 50px; width: 7px; height: 7px; border: 2px solid white; border-radius: 50%; background: #00a4cc; box-shadow: 0 0 0 1px #00a4cc; }
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
@media (max-width: 700px) { .cat-lab { gap: 13px; }.cat-lab__banner { min-height: 112px; padding: 18px 20px; }.cat-lab__instrument { right: 18px; transform: translateY(-50%) scale(.78); transform-origin: right center; }.cat-lab__panel { padding: 12px; } }
@media (max-width: 480px) { .cat-lab__banner { min-height: 118px; padding-right: 18px; }.cat-lab__instrument { right: 4px; opacity: .35; }.cat-lab__tabs-list { padding-inline: 7px; }.cat-lab__tab { padding-inline: 5px; font-size: 12px; } }
@media (prefers-reduced-motion: reduce) { .cat-lab__tabs-indicator,.cat-lab__tab { transition-duration: .01ms; } }
</style>
