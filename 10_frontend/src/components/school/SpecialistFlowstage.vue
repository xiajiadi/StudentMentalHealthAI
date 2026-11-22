<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, watch } from 'vue'
import type { Component } from 'vue'
import { ArrowDown, ArrowUp, CornerDownLeft, Search, X } from '@lucide/vue'
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
  TabsContent,
  TabsIndicator,
  TabsList,
  TabsRoot,
  TabsTrigger,
} from 'reka-ui'
import type {
  SpecialistFlowstageBridge,
  SpecialistWorkflowKey,
} from '@/views/specialist/specialist-workflow-flowstage'
import { isSpecialistWorkflowKey, specialistWorkflowDefinitions } from '@/views/specialist/specialist-workflow-flowstage'

type PaletteCommand = Readonly<{
  id: string
  kind: 'workflow' | 'record'
  label: string
  description: string
  workflow: SpecialistWorkflowKey
  icon: Component
  itemKey?: string
}>

const props = defineProps<{
  workflow: SpecialistWorkflowKey
  workflowComponent: Component
  scopeKey: string
}>()

const emit = defineEmits<{
  'update:workflow': [value: SpecialistWorkflowKey]
}>()

const businessPanel = ref<HTMLElement | null>(null)
const paletteOpen = ref(false)
const paletteQuery = ref('')
const paletteActiveIndex = ref(0)
const paletteInput = ref<HTMLInputElement | null>(null)
const bridgeInstances = shallowReactive(new Map<SpecialistWorkflowKey, SpecialistFlowstageBridge>())

const activeDefinition = computed(() => specialistWorkflowDefinitions.find((item) => item.key === props.workflow) ?? specialistWorkflowDefinitions[0])
const currentBridge = computed(() => bridgeInstances.get(props.workflow) ?? null)
const filmstripItems = computed(() => currentBridge.value?.flowstageItems ?? [])
const paletteCommands = computed<PaletteCommand[]>(() => [
  ...specialistWorkflowDefinitions.map((workflow) => ({
    id: `workflow-${workflow.key}`,
    kind: 'workflow' as const,
    label: workflow.label,
    description: workflow.description,
    workflow: workflow.key,
    icon: workflow.icon,
  })),
  ...filmstripItems.value.map((item, index) => ({
    id: `record-${props.workflow}-${index}`,
    kind: 'record' as const,
    label: item.label,
    description: [item.status, item.meta, activeDefinition.value.label].filter(Boolean).join(' · '),
    workflow: props.workflow,
    icon: activeDefinition.value.icon,
    itemKey: item.key,
  })),
])

const filteredCommands = computed(() => {
  const search = paletteQuery.value.trim().toLocaleLowerCase('zh-CN')
  if (!search) return paletteCommands.value
  return paletteCommands.value.filter((command) =>
    [command.label, command.description, specialistWorkflowDefinitions.find((item) => item.key === command.workflow)?.english]
      .filter(Boolean)
      .join(' ')
      .toLocaleLowerCase('zh-CN')
      .includes(search),
  )
})

const activeCommand = computed(() => filteredCommands.value[paletteActiveIndex.value] ?? null)

watch(filteredCommands, () => { paletteActiveIndex.value = 0 })
watch(() => props.scopeKey, () => { bridgeInstances.clear() }, { flush: 'sync' })
watch(paletteOpen, (open) => {
  if (!open) {
    paletteQuery.value = ''
    paletteActiveIndex.value = 0
  }
})

function setBusinessInstance(workflow: SpecialistWorkflowKey, instance: unknown) {
  if (instance) bridgeInstances.set(workflow, instance as SpecialistFlowstageBridge)
  else bridgeInstances.delete(workflow)
}

function selectWorkflow(value: string) {
  if (isSpecialistWorkflowKey(value)) emit('update:workflow', value)
}

function commandDomId(command: PaletteCommand) {
  return `specialist-flowstage-command-${command.id}`
}

function openPalette() {
  paletteQuery.value = ''
  paletteActiveIndex.value = 0
  paletteOpen.value = true
}

function closePalette() {
  paletteOpen.value = false
}

function focusPaletteInput(event: Event) {
  event.preventDefault()
  requestAnimationFrame(() => paletteInput.value?.focus())
}

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable
    || Boolean(target.closest('input, textarea, select, [role="combobox"], [role="textbox"], [contenteditable="true"]'))
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if (paletteOpen.value || event.defaultPrevented || event.altKey
    || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k'
    || isEditableTarget(event.target)) return
  event.preventDefault()
  openPalette()
}

function movePaletteSelection(direction: -1 | 1) {
  const length = filteredCommands.value.length
  if (!length) return
  paletteActiveIndex.value = (paletteActiveIndex.value + direction + length) % length
}

async function enterBusiness() {
  await nextTick()
  const panel = businessPanel.value
  if (!panel) return
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  panel.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
  panel.focus({ preventScroll: true })
}

async function activateCommand(command: PaletteCommand) {
  closePalette()
  if (command.kind === 'workflow') {
    emit('update:workflow', command.workflow)
    await enterBusiness()
    return
  }
  if (command.itemKey) await currentBridge.value?.selectFlowstageItem(command.itemKey)
  await enterBusiness()
}

function handlePaletteKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    movePaletteSelection(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    movePaletteSelection(-1)
  } else if (event.key === 'Enter' && activeCommand.value) {
    event.preventDefault()
    void activateCommand(activeCommand.value)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    closePalette()
  }
}

onMounted(() => document.addEventListener('keydown', handleGlobalKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', handleGlobalKeydown))
</script>

<template>
  <section class="specialist-flowstage" aria-label="专业工作事项">
    <h1 class="specialist-flowstage__sr-only">专业工作事项</h1>
    <header class="specialist-flowstage__page-heading">
      <button class="specialist-flowstage__quick-trigger" type="button" @click="openPalette">
        <Search :size="16" aria-hidden="true" />
        <span>快速定位</span>
        <kbd>Ctrl / ⌘ K</kbd>
      </button>
    </header>

    <section class="specialist-flowstage__canvas" aria-label="专业工作流画布">
      <TabsRoot :model-value="workflow" class="specialist-flowstage__tabs" activation-mode="automatic" @update:model-value="selectWorkflow">
        <TabsList class="specialist-flowstage__dock" aria-label="心理专业工作流">
          <TabsIndicator class="specialist-flowstage__dock-indicator" aria-hidden="true" />
          <TabsTrigger
            v-for="definition in specialistWorkflowDefinitions"
            :key="definition.key"
            class="specialist-flowstage__dock-tab"
            :class="`specialist-flowstage__dock-tab--${definition.tone}`"
            :value="definition.key"
          >
            <span class="specialist-flowstage__dock-icon">
              <component :is="definition.icon" :size="20" stroke-width="1.8" aria-hidden="true" />
            </span>
            <span class="specialist-flowstage__dock-label">{{ definition.label }}</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent :value="workflow" class="specialist-flowstage__panel">
          <section ref="businessPanel" class="specialist-flowstage__business" tabindex="-1" aria-label="当前工作流">
            <KeepAlive :key="scopeKey" :max="5">
              <component
                :is="workflowComponent"
                :key="workflow"
                :ref="(instance: unknown) => setBusinessInstance(workflow, instance)"
              />
            </KeepAlive>
          </section>
        </TabsContent>
      </TabsRoot>
    </section>

    <DialogRoot :open="paletteOpen" @update:open="paletteOpen = $event">
      <DialogPortal>
        <DialogOverlay class="specialist-flowstage__command-overlay" />
        <DialogContent class="specialist-flowstage__command-dialog" @open-auto-focus="focusPaletteInput">
          <div class="specialist-flowstage__command-search">
            <Search :size="18" aria-hidden="true" />
            <input
              id="specialist-flowstage-command-input"
              ref="paletteInput"
              v-model="paletteQuery"
              type="search"
              role="combobox"
              aria-label="搜索工作流或当前已加载事项"
              aria-autocomplete="list"
              aria-controls="specialist-flowstage-command-results"
              :aria-expanded="paletteOpen"
              :aria-activedescendant="activeCommand ? commandDomId(activeCommand) : undefined"
              placeholder="搜索工作流或当前事项…"
              autocomplete="off"
              @keydown="handlePaletteKeydown"
            >
            <kbd>ESC</kbd>
            <button type="button" aria-label="关闭快速定位" @click="closePalette"><X :size="17" aria-hidden="true" /></button>
          </div>
          <DialogTitle class="specialist-flowstage__command-title">快速定位</DialogTitle>
          <DialogDescription class="specialist-flowstage__command-description">搜索五条工作流，或当前流程已加载的授权事项。</DialogDescription>
          <div id="specialist-flowstage-command-results" class="specialist-flowstage__command-results" role="listbox" aria-label="快速定位结果">
            <button
              v-for="(command, index) in filteredCommands"
              :id="commandDomId(command)"
              :key="command.id"
              type="button"
              role="option"
              :aria-selected="index === paletteActiveIndex"
              class="specialist-flowstage__command-result"
              :class="{ 'specialist-flowstage__command-result--active': index === paletteActiveIndex }"
              @mouseenter="paletteActiveIndex = index"
              @click="activateCommand(command)"
            >
              <span class="specialist-flowstage__command-result-icon"><component :is="command.icon" :size="17" aria-hidden="true" /></span>
              <span class="specialist-flowstage__command-result-copy">
                <strong>{{ command.label }}</strong>
                <small>{{ command.description }}</small>
              </span>
            </button>
            <p v-if="!filteredCommands.length" class="specialist-flowstage__command-empty" role="status">没有匹配的工作流或已加载事项。</p>
          </div>
          <div class="specialist-flowstage__command-footer" aria-hidden="true">
            <span><ArrowUp :size="12" /><ArrowDown :size="12" />选择</span>
            <span><CornerDownLeft :size="12" />进入</span>
            <span>Tab 切换焦点</span>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </section>
</template>

<style scoped>
.specialist-flowstage { display: grid; gap: 16px; min-width: 0; color: var(--color-text-primary); }
.specialist-flowstage__sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; clip-path: inset(50%); }
.specialist-flowstage__page-heading { display: flex; align-items: center; justify-content: flex-end; }
.specialist-flowstage__quick-trigger { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; padding: 7px 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-secondary); background: var(--color-surface); font: inherit; font-size: 12px; font-weight: 650; cursor: pointer; transition: color var(--motion-fast), border-color var(--motion-fast), box-shadow var(--motion-fast); }
.specialist-flowstage__quick-trigger > svg { color: var(--color-primary-active); }
.specialist-flowstage__quick-trigger:hover { border-color: var(--color-primary); color: var(--color-primary-active); box-shadow: 0 0 0 3px color-mix(in srgb,var(--color-primary) 7%,transparent); }
.specialist-flowstage__quick-trigger:focus-visible,.specialist-flowstage__dock-tab:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.specialist-flowstage__quick-trigger kbd { padding: 3px 5px; border: 1px solid var(--color-border); border-radius: 4px; color: var(--color-text-muted); background: var(--color-surface-soft); font: inherit; font-size: 11px; }
.specialist-flowstage__canvas { min-width: 0; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); box-shadow: var(--shadow-rest); }
.specialist-flowstage__tabs { display: block; min-width: 0; }
.specialist-flowstage__dock { position: relative; display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 3px; margin: 0 14px; padding: 5px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface-soft); isolation: isolate; }
.specialist-flowstage__dock-indicator { position: absolute; z-index: 0; top: 5px; left: 0; width: var(--reka-tabs-indicator-size,0px); height: var(--reka-tabs-indicator-thickness,0px); border: 1px solid var(--color-border); border-radius: var(--radius-button); background: var(--color-surface); box-shadow: 0 1px 3px color-mix(in srgb,var(--color-text-primary) 5%,transparent); transform: translateX(var(--reka-tabs-indicator-position,0px)); transition: transform var(--motion-normal) cubic-bezier(.2,.8,.2,1); pointer-events: none; }
.specialist-flowstage__dock-tab { --flow-accent: var(--color-primary-active); --flow-wash: color-mix(in srgb,var(--color-primary-active) 8%,var(--color-surface)); position: relative; z-index: 1; display: grid; grid-template-columns: 36px minmax(0,1fr); grid-template-rows: auto auto; align-items: center; gap: 2px 9px; min-width: 0; min-height: 58px; padding: 6px 8px; border: 0; border-radius: var(--radius-button); color: var(--color-text-secondary); background: transparent; text-align: left; cursor: pointer; transition: color var(--motion-fast), transform var(--motion-fast), background-color var(--motion-fast); }
.specialist-flowstage__dock-tab--violet { --flow-accent: var(--color-chart-violet); --flow-wash: color-mix(in srgb,var(--color-chart-violet) 8%,var(--color-surface)); }
.specialist-flowstage__dock-tab--mint { --flow-accent: var(--color-support); --flow-wash: var(--color-support-wash); }
.specialist-flowstage__dock-tab--purple { --flow-accent: var(--color-chart-violet); --flow-wash: color-mix(in srgb,var(--color-chart-violet) 6%,var(--color-surface)); }
.specialist-flowstage__dock-tab--amber { --flow-accent: var(--color-attention); --flow-wash: var(--color-attention-wash); }
.specialist-flowstage__dock-tab:hover { transform: translateY(-1px); }
.specialist-flowstage__dock-tab[data-state="active"] { color: var(--flow-accent); }
.specialist-flowstage__dock-icon { display: grid; width: 34px; height: 34px; grid-column: 1; grid-row: 1 / 3; place-items: center; border: 1px solid color-mix(in srgb,var(--flow-accent) 17%,transparent); border-radius: var(--radius-button); color: var(--flow-accent); background: color-mix(in srgb,var(--flow-accent) 8%,var(--color-surface)); transition: transform var(--motion-fast), background-color var(--motion-fast), color var(--motion-fast); }
.specialist-flowstage__dock-tab[data-state="active"] .specialist-flowstage__dock-icon { transform: translateY(-1px) rotate(-2deg); background: color-mix(in srgb,var(--flow-accent) 13%,var(--color-surface)); }
.specialist-flowstage__dock-label { grid-column: 2; grid-row: 1; overflow: hidden; color: var(--color-text-primary); font-size: 13px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__dock-tab[data-state="active"] .specialist-flowstage__dock-label { color: var(--flow-accent); }
.specialist-flowstage__panel { min-width: 0; }
.specialist-flowstage__panel[data-state="inactive"] { display: none; }
.specialist-flowstage__business { min-width: 0; padding: 14px 18px 18px; border-top: 1px solid var(--color-border); scroll-margin-top: calc(var(--layout-topbar) + 12px); }
.specialist-flowstage__business:focus:not(:focus-visible) { outline: none; }
.specialist-flowstage__business:focus-visible { outline: 1px solid color-mix(in srgb,var(--color-primary-active) 55%,var(--color-border)); outline-offset: -1px; border-radius: var(--radius-card); box-shadow: inset 0 0 0 3px color-mix(in srgb,var(--color-primary-active) 5%,transparent); }
.specialist-flowstage__command-overlay { position: fixed; inset: 0; z-index: 120; background: color-mix(in srgb,var(--color-text-primary) 42%,transparent); backdrop-filter: blur(3px); }
.specialist-flowstage__command-dialog { position: fixed; top: 50%; left: 50%; z-index: 130; display: grid; grid-template-rows: auto auto auto minmax(0,1fr) auto; width: min(590px,calc(100vw - 32px)); max-height: min(590px,calc(100vh - 40px)); overflow: hidden; padding: 14px; border: 1px solid var(--color-border); border-radius: var(--radius-dialog); background: var(--color-surface); box-shadow: var(--shadow-raised); transform: translate(-50%,-50%); }
.specialist-flowstage__command-search { display: flex; align-items: center; gap: 10px; min-height: 47px; padding: 0 10px; border: 1px solid color-mix(in srgb,var(--color-primary) 45%,var(--color-border)); border-radius: var(--radius-button); color: var(--color-primary-active); background: var(--color-surface-soft); box-shadow: 0 0 0 3px color-mix(in srgb,var(--color-primary) 5%,transparent); }
.specialist-flowstage__command-search input { width: 100%; min-width: 0; height: 44px; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 14px; }
.specialist-flowstage__command-search input::placeholder { color: var(--color-text-muted); }
.specialist-flowstage__command-search kbd { flex: 0 0 auto; color: var(--color-text-muted); font: inherit; font-size: 11px; }
.specialist-flowstage__command-search button { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border: 0; border-radius: var(--radius-control); color: var(--color-text-muted); background: transparent; cursor: pointer; }
.specialist-flowstage__command-search button:hover { color: var(--color-text-primary); background: var(--color-surface-muted); }
.specialist-flowstage__command-title { margin: 15px 7px 0; color: var(--color-text-primary); font-size: 14px; font-weight: 700; }
.specialist-flowstage__command-description { margin: 4px 7px 10px; color: var(--color-text-muted); font-size: 12px; line-height: 1.5; }
.specialist-flowstage__command-results { min-height: 70px; overflow-y: auto; overscroll-behavior: contain; padding: 3px; }
.specialist-flowstage__command-result { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 48px; padding: 7px 8px; border: 0; border-radius: 8px; color: var(--color-text-secondary); background: transparent; text-align: left; cursor: pointer; }
.specialist-flowstage__command-result:hover,.specialist-flowstage__command-result--active { background: var(--color-info-wash); }
.specialist-flowstage__command-result:focus-visible { outline: 2px solid var(--color-primary-active); outline-offset: -2px; }
.specialist-flowstage__command-result-icon { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border: 1px solid var(--color-border); border-radius: var(--radius-button); color: var(--color-primary-active); background: var(--color-surface); }
.specialist-flowstage__command-result-copy { display: grid; flex: 1; gap: 3px; min-width: 0; }
.specialist-flowstage__command-result-copy strong { overflow: hidden; color: var(--color-text-primary); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__command-result-copy small { overflow: hidden; color: var(--color-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__command-empty { padding: 24px 10px; color: var(--color-text-muted); font-size: 12px; text-align: center; }
.specialist-flowstage__command-footer { display: flex; align-items: center; gap: 14px; padding: 9px 7px 2px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 11px; }
.specialist-flowstage__command-footer span { display: inline-flex; align-items: center; gap: 3px; }
.specialist-flowstage__dock { margin-block: 10px; }
.specialist-flowstage__dock-tab { display: flex; align-items: center; gap: 8px; }
.specialist-flowstage__dock-icon { flex: none; }
@media (max-width: 760px) {
  .specialist-flowstage__dock { margin-inline: 8px; }
  .specialist-flowstage__dock-tab { flex-direction: column; justify-content: center; padding: 6px 2px; gap: 4px; }
  .specialist-flowstage__dock-icon { width: 27px; height: 27px; }
  .specialist-flowstage__dock-label { font-size: 11px; }
  .specialist-flowstage__business { padding: 12px 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .specialist-flowstage__dock-indicator, .specialist-flowstage__dock-tab { transition: none; }
}
</style>
