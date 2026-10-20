<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowReactive, watch } from 'vue'
import type { Component } from 'vue'
import { ArrowDown, ArrowRight, ArrowUp, CornerDownLeft, Search, ShieldCheck, X } from '@lucide/vue'
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
const stripTrack = ref<HTMLElement | null>(null)
const paletteOpen = ref(false)
const paletteQuery = ref('')
const paletteActiveIndex = ref(0)
const paletteInput = ref<HTMLInputElement | null>(null)
const bridgeInstances = shallowReactive(new Map<SpecialistWorkflowKey, SpecialistFlowstageBridge>())

const activeDefinition = computed(() => specialistWorkflowDefinitions.find((item) => item.key === props.workflow) ?? specialistWorkflowDefinitions[0])
const currentBridge = computed(() => bridgeInstances.get(props.workflow) ?? null)
const filmstripItems = computed(() => currentBridge.value?.flowstageItems ?? [])
const filmstripState = computed(() => currentBridge.value?.flowstageState ?? 'loading')
const filmstripCount = computed(() => currentBridge.value?.flowstageCountLabel ?? '')
const activeItemKey = computed(() => currentBridge.value?.flowstageSelectedKey ?? '')
const activeItem = computed(() => filmstripItems.value.find((item) => item.key === activeItemKey.value) ?? null)
const stageTitle = computed(() => activeItem.value?.label ?? activeDefinition.value.label)

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

function selectFilmstripItem(key: string) {
  void currentBridge.value?.selectFlowstageItem(key)
}

function handleFilmstripKeydown(event: KeyboardEvent, currentIndex: number) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  const buttons = stripTrack.value?.querySelectorAll<HTMLButtonElement>('[data-flowstage-item]')
  if (!buttons?.length) return
  event.preventDefault()
  const delta = event.key === 'ArrowRight' ? 1 : -1
  const nextIndex = (currentIndex + delta + buttons.length) % buttons.length
  buttons[nextIndex]?.focus()
}

onMounted(() => document.addEventListener('keydown', handleGlobalKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', handleGlobalKeydown))
</script>

<template>
  <section class="specialist-flowstage" aria-label="专业工作事项 Flowstage">
    <h1 class="specialist-flowstage__sr-only">专业工作事项</h1>
    <header class="specialist-flowstage__page-heading">
      <button class="specialist-flowstage__quick-trigger" type="button" @click="openPalette">
        <Search :size="16" aria-hidden="true" />
        <span>快速定位</span>
        <kbd>Ctrl / ⌘ K</kbd>
      </button>
    </header>

    <section class="specialist-flowstage__canvas" aria-label="专业工作流画布">
      <header class="specialist-flowstage__canvas-heading">
        <span>切换工作流</span>
      </header>

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
            <span class="specialist-flowstage__dock-english">{{ definition.english }}</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent :value="workflow" force-mount class="specialist-flowstage__panel">
          <Transition name="flowstage-stage" mode="out-in">
            <section :key="workflow" class="specialist-flowstage__stage" :class="`specialist-flowstage__stage--${activeDefinition.tone}`">
              <div class="specialist-flowstage__stage-copy">
                <h2>{{ stageTitle }}</h2>
                <p class="specialist-flowstage__stage-description">{{ activeDefinition.description }}</p>
                <div class="specialist-flowstage__areas" aria-label="当前工作区包含">
                  <span class="specialist-flowstage__areas-label">工作区</span>
                  <span v-for="area in activeDefinition.areas" :key="area">{{ area }}</span>
                </div>
                <button class="specialist-flowstage__enter" type="button" @click="enterBusiness">
                  进入此工作
                </button>
              </div>

              <div class="specialist-flowstage__visual" aria-hidden="true">
                <svg class="specialist-flowstage__orbit" viewBox="0 0 360 250" fill="none">
                  <ellipse class="specialist-flowstage__orbit-ring specialist-flowstage__orbit-ring--outer" cx="180" cy="125" rx="152" ry="88" />
                  <ellipse class="specialist-flowstage__orbit-ring specialist-flowstage__orbit-ring--middle" cx="180" cy="125" rx="124" ry="72" />
                  <ellipse class="specialist-flowstage__orbit-ring specialist-flowstage__orbit-ring--inner" cx="180" cy="125" rx="92" ry="53" />
                  <path class="specialist-flowstage__orbit-track" d="M34 162C84 45 238 36 322 97" />
                  <circle class="specialist-flowstage__orbit-point" cx="322" cy="97" r="4" />
                </svg>
                <span class="specialist-flowstage__visual-index">{{ activeDefinition.code }}</span>
                <span class="specialist-flowstage__visual-icon">
                  <component :is="activeDefinition.icon" :size="34" stroke-width="1.65" />
                </span>
              </div>
            </section>
          </Transition>

          <div class="specialist-flowstage__scope" :class="`specialist-flowstage__scope--${activeDefinition.tone}`">
            <span class="specialist-flowstage__scope-icon"><ShieldCheck :size="17" aria-hidden="true" /></span>
            <div class="specialist-flowstage__scope-copy">
              <strong>授权范围</strong>
              <p>{{ activeDefinition.scope }}</p>
            </div>
            <span v-if="filmstripCount" class="specialist-flowstage__scope-count">{{ filmstripCount }}</span>
            <span v-else class="specialist-flowstage__scope-count">以当前服务端返回为准</span>
          </div>

          <section class="specialist-flowstage__filmstrip" aria-labelledby="specialist-flowstage-items-title">
            <header class="specialist-flowstage__filmstrip-heading">
              <div>
                <h3 id="specialist-flowstage-items-title">当前事项</h3>
              </div>
              <span>按当前流程加载</span>
            </header>

            <div v-if="filmstripState === 'loading' || filmstripState === 'idle'" class="specialist-flowstage__filmstrip-state" role="status" aria-busy="true">
              <span class="specialist-flowstage__state-pulse" aria-hidden="true" />正在读取此工作流的授权事项…
            </div>
            <div v-else-if="filmstripState === 'error'" class="specialist-flowstage__filmstrip-state" role="status">
              当前列表暂不可用；下方业务工作区会显示原有错误状态与重试入口。
            </div>
            <div v-else-if="!filmstripItems.length" class="specialist-flowstage__filmstrip-state">
              {{ currentBridge?.flowstageEmptyMessage || '当前工作流暂无服务端返回的事项。' }}
            </div>
            <div v-else ref="stripTrack" class="specialist-flowstage__filmstrip-viewport" tabindex="0" aria-label="当前工作流事项，可横向滚动">
              <ul class="specialist-flowstage__filmstrip-track">
                <li v-for="(item, index) in filmstripItems" :key="item.key" class="specialist-flowstage__filmstrip-item">
                  <button
                    :id="`specialist-flowstage-item-${index}`"
                    type="button"
                    data-flowstage-item
                    class="specialist-flowstage__filmstrip-button"
                    :class="{ 'specialist-flowstage__filmstrip-button--active': item.key === activeItemKey }"
                    :aria-pressed="item.key === activeItemKey"
                    @click="selectFilmstripItem(item.key)"
                    @keydown="handleFilmstripKeydown($event, index)"
                  >
                    <span class="specialist-flowstage__item-order">{{ String(index + 1).padStart(2, '0') }}</span>
                    <span class="specialist-flowstage__item-copy">
                      <span class="specialist-flowstage__item-title">{{ item.label }}</span>
                      <span v-if="item.status" class="specialist-flowstage__item-status">{{ item.status }}</span>
                      <span v-if="item.meta" class="specialist-flowstage__item-meta">{{ item.meta }}</span>
                    </span>
                    <ArrowRight :size="15" class="specialist-flowstage__item-arrow" aria-hidden="true" />
                  </button>
                </li>
              </ul>
            </div>
          </section>
        </TabsContent>
      </TabsRoot>

      <section ref="businessPanel" class="specialist-flowstage__business" tabindex="-1" aria-label="当前工作流业务操作">
        <header class="specialist-flowstage__business-heading">
          <span>业务操作</span>
        </header>
        <KeepAlive :key="scopeKey" :max="5">
          <component
            :is="workflowComponent"
            :key="workflow"
            :ref="(instance: unknown) => setBusinessInstance(workflow, instance)"
          />
        </KeepAlive>
      </section>
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
              <ArrowRight :size="15" class="specialist-flowstage__command-result-arrow" aria-hidden="true" />
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
.specialist-flowstage__quick-trigger:focus-visible,.specialist-flowstage__dock-tab:focus-visible,.specialist-flowstage__enter:focus-visible,.specialist-flowstage__filmstrip-button:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.specialist-flowstage__quick-trigger kbd { padding: 3px 5px; border: 1px solid var(--color-border); border-radius: 4px; color: var(--color-text-muted); background: var(--color-surface-soft); font: inherit; font-size: 11px; }
.specialist-flowstage__canvas { min-width: 0; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); box-shadow: var(--shadow-rest); }
.specialist-flowstage__canvas-heading { display: flex; align-items: center; justify-content: flex-end; padding: 14px 21px 8px; }
.specialist-flowstage__canvas-heading > span { color: var(--color-text-muted); font-size: 12px; }
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
.specialist-flowstage__dock-english { grid-column: 2; grid-row: 2; color: var(--color-text-muted); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.specialist-flowstage__panel { min-width: 0; }
.specialist-flowstage__panel[data-state="inactive"] { display: none; }
.specialist-flowstage__stage { --flow-accent: var(--color-primary-active); --flow-wash: color-mix(in srgb,var(--color-primary-active) 6%,var(--color-surface)); display: grid; grid-template-columns: minmax(0,1.18fr) minmax(250px,.82fr); align-items: center; gap: 20px; min-height: 250px; margin: 12px 14px 0; padding: 24px 27px; overflow: hidden; border: 1px solid color-mix(in srgb,var(--flow-accent) 12%,var(--color-border)); border-radius: var(--radius-card); background: linear-gradient(105deg,var(--color-surface) 0%,var(--flow-wash) 100%); }
.specialist-flowstage__stage--violet { --flow-accent: var(--color-chart-violet); --flow-wash: color-mix(in srgb,var(--color-chart-violet) 7%,var(--color-surface)); }
.specialist-flowstage__stage--mint { --flow-accent: var(--color-support); --flow-wash: color-mix(in srgb,var(--color-support) 6%,var(--color-surface)); }
.specialist-flowstage__stage--purple { --flow-accent: var(--color-chart-violet); --flow-wash: color-mix(in srgb,var(--color-chart-violet) 5%,var(--color-surface)); }
.specialist-flowstage__stage--amber { --flow-accent: var(--color-attention); --flow-wash: color-mix(in srgb,var(--color-attention) 7%,var(--color-surface)); }
.specialist-flowstage__stage-copy { min-width: 0; }
.specialist-flowstage__stage h2 { margin: 0; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(23px,2.3vw,28px); font-weight: 720; letter-spacing: -.035em; line-height: 1.25; overflow-wrap: anywhere; }
.specialist-flowstage__stage-description { max-width: 540px; margin: 8px 0 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.specialist-flowstage__areas { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 13px; }
.specialist-flowstage__areas-label { margin-right: 2px; color: var(--color-text-muted); font-size: 11px; }
.specialist-flowstage__areas > span:not(:first-child) { padding: 4px 7px; border: 1px solid color-mix(in srgb,var(--flow-accent) 15%,transparent); border-radius: 999px; color: color-mix(in srgb,var(--flow-accent) 82%,var(--color-text-primary)); background: color-mix(in srgb,var(--flow-accent) 6%,var(--color-surface)); font-size: 11px; line-height: 1.2; }
.specialist-flowstage__enter { display: inline-flex; align-items: center; gap: 8px; min-height: 36px; margin-top: 16px; padding: 8px 12px; border: 0; border-radius: var(--radius-button); color: var(--color-text-inverse); background: var(--flow-accent); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; transition: filter var(--motion-fast), transform var(--motion-fast); }
.specialist-flowstage__enter:hover { filter: brightness(.96); transform: translateY(-1px); }
.specialist-flowstage__visual { position: relative; display: grid; min-height: 198px; place-items: center; color: var(--flow-accent); }
.specialist-flowstage__orbit { position: absolute; width: min(100%,340px); height: 100%; overflow: visible; }
.specialist-flowstage__orbit-ring { stroke: color-mix(in srgb,var(--flow-accent) 13%,transparent); stroke-width: 1; }
.specialist-flowstage__orbit-ring--outer { stroke-dasharray: 2 6; }
.specialist-flowstage__orbit-ring--middle { stroke-dasharray: 1 4; }
.specialist-flowstage__orbit-ring--inner { stroke: color-mix(in srgb,var(--flow-accent) 18%,transparent); }
.specialist-flowstage__orbit-track { stroke: color-mix(in srgb,var(--flow-accent) 46%,transparent); stroke-dasharray: 3 8; stroke-linecap: round; stroke-width: 1.2; animation: specialist-flowstage-track 12s linear infinite; }
.specialist-flowstage__orbit-point { fill: var(--flow-accent); stroke: var(--color-surface); stroke-width: 3; }
.specialist-flowstage__visual-index { position: absolute; right: 4%; bottom: 0; color: color-mix(in srgb,var(--flow-accent) 9%,transparent); font-family: var(--font-display); font-size: clamp(76px,9vw,112px); font-weight: 760; letter-spacing: -.08em; line-height: .9; }
.specialist-flowstage__visual-icon { position: relative; display: grid; width: 76px; height: 76px; place-items: center; border: 1px solid color-mix(in srgb,var(--flow-accent) 24%,transparent); border-radius: var(--radius-card); color: var(--flow-accent); background: color-mix(in srgb,var(--flow-accent) 7%,var(--color-surface)); box-shadow: 0 12px 30px color-mix(in srgb,var(--flow-accent) 10%,transparent),inset 0 1px var(--color-surface); animation: specialist-flowstage-float 5s ease-in-out infinite; }
.flowstage-stage-enter-active,.flowstage-stage-leave-active { transition: opacity var(--motion-normal), transform var(--motion-normal); }
.flowstage-stage-enter-from { opacity: 0; transform: translateY(5px); }
.flowstage-stage-leave-to { opacity: 0; transform: translateY(-4px); }
.specialist-flowstage__scope { display: flex; align-items: center; gap: 10px; margin: 0 14px; padding: 12px 8px; border-bottom: 1px solid var(--color-border); }
.specialist-flowstage__scope-icon { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border-radius: 9px; color: var(--color-primary-active); background: var(--color-info-wash); }
.specialist-flowstage__scope--violet .specialist-flowstage__scope-icon { color: var(--color-chart-violet); background: color-mix(in srgb,var(--color-chart-violet) 8%,var(--color-surface)); }
.specialist-flowstage__scope--mint .specialist-flowstage__scope-icon { color: var(--color-support); background: var(--color-support-wash); }
.specialist-flowstage__scope--purple .specialist-flowstage__scope-icon { color: var(--color-chart-violet); background: color-mix(in srgb,var(--color-chart-violet) 6%,var(--color-surface)); }
.specialist-flowstage__scope--amber .specialist-flowstage__scope-icon { color: var(--color-attention); background: var(--color-attention-wash); }
.specialist-flowstage__scope-copy { min-width: 0; }
.specialist-flowstage__scope-copy strong { color: var(--color-text-primary); font-size: 12px; font-weight: 690; }
.specialist-flowstage__scope-copy p { margin: 2px 0 0; color: var(--color-text-muted); font-size: 12px; line-height: 1.5; }
.specialist-flowstage__scope-count { flex: 0 0 auto; margin-left: auto; padding-left: 8px; color: var(--color-text-muted); font-size: 11px; text-align: right; }
.specialist-flowstage__filmstrip { min-width: 0; padding: 13px 21px 17px; }
.specialist-flowstage__filmstrip-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-bottom: 5px; }
.specialist-flowstage__filmstrip-heading h3 { margin: 0; color: var(--color-text-primary); font-size: 17px; font-weight: 700; }
.specialist-flowstage__filmstrip-heading > span { color: var(--color-text-muted); font-size: 15px; }
.specialist-flowstage__filmstrip-viewport { overflow-x: auto; overscroll-behavior-inline: contain; scroll-behavior: smooth; scrollbar-color: var(--color-border-strong) transparent; scrollbar-width: thin; }
.specialist-flowstage__filmstrip-viewport:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; border-radius: 7px; }
.specialist-flowstage__filmstrip-track { display: flex; min-width: max-content; margin: 0; padding: 4px 0 8px; list-style: none; }
.specialist-flowstage__filmstrip-item { width: min(234px,68vw); min-width: 190px; border-right: 1px solid var(--color-border); }
.specialist-flowstage__filmstrip-item:first-child { border-left: 1px solid var(--color-border); }
.specialist-flowstage__filmstrip-button { position: relative; display: grid; grid-template-columns: 27px minmax(0,1fr) 16px; align-items: start; gap: 8px; width: 100%; min-height: 72px; padding: 13px 11px 9px; border: 0; color: var(--color-text-secondary); background: transparent; text-align: left; cursor: pointer; transition: background-color var(--motion-fast),color var(--motion-fast); }
.specialist-flowstage__filmstrip-button::before { position: absolute; inset: 0 0 auto; height: 2px; background: transparent; content: ''; transition: background-color var(--motion-fast); }
.specialist-flowstage__filmstrip-button:hover { background: var(--color-surface-soft); }
.specialist-flowstage__filmstrip-button--active { background: color-mix(in srgb,var(--flow-accent) 5%,var(--color-surface)); }
.specialist-flowstage__filmstrip-button--active::before { background: var(--flow-accent); }
.specialist-flowstage__item-order { color: var(--color-text-muted); font-family: var(--font-mono); font-size: 11px; font-variant-numeric: tabular-nums; }
.specialist-flowstage__item-copy { display: grid; gap: 4px; min-width: 0; }
.specialist-flowstage__item-title { overflow: hidden; color: var(--color-text-secondary); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__filmstrip-button--active .specialist-flowstage__item-title { color: var(--color-text-primary); }
.specialist-flowstage__item-status { width: fit-content; color: var(--flow-accent); font-size: 11px; font-weight: 620; }
.specialist-flowstage__item-meta { overflow: hidden; color: var(--color-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__item-arrow { margin-top: 1px; color: var(--color-text-muted); }
.specialist-flowstage__filmstrip-state { display: flex; align-items: center; gap: 8px; min-height: 55px; padding: 8px 11px; color: var(--color-text-muted); font-size: 12px; }
.specialist-flowstage__state-pulse { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: var(--color-primary); box-shadow: 0 0 0 3px color-mix(in srgb,var(--color-primary) 10%,transparent); animation: specialist-flowstage-pulse 1.6s ease-in-out infinite; }
.specialist-flowstage__business { min-width: 0; padding: 14px 18px 18px; border-top: 1px solid var(--color-border); scroll-margin-top: calc(var(--layout-topbar) + 12px); }
.specialist-flowstage__business:focus { outline: 2px solid var(--color-focus-ring); outline-offset: -2px; border-radius: 8px; }
.specialist-flowstage__business-heading { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.specialist-flowstage__business-heading span { color: var(--color-primary-active); font-size: 15px; font-weight: 730; letter-spacing: .11em; }
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
.specialist-flowstage__command-result-copy { display: grid; gap: 3px; min-width: 0; }
.specialist-flowstage__command-result-copy strong { overflow: hidden; color: var(--color-text-primary); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__command-result-copy small { overflow: hidden; color: var(--color-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.specialist-flowstage__command-result-arrow { flex: 0 0 auto; margin-left: auto; color: var(--color-text-muted); }
.specialist-flowstage__command-empty { padding: 24px 10px; color: var(--color-text-muted); font-size: 12px; text-align: center; }
.specialist-flowstage__command-footer { display: flex; align-items: center; gap: 14px; padding: 9px 7px 2px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 11px; }
.specialist-flowstage__command-footer span { display: inline-flex; align-items: center; gap: 3px; }
@keyframes specialist-flowstage-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
@keyframes specialist-flowstage-track { to { stroke-dashoffset: -66; } }
@keyframes specialist-flowstage-pulse { 50% { opacity: .45; box-shadow: 0 0 0 5px color-mix(in srgb,var(--color-primary) 5%,transparent); } }
@media (max-width: 1000px) { .specialist-flowstage__dock-english { display: none; }.specialist-flowstage__dock-tab { grid-template-rows: auto; }.specialist-flowstage__dock-icon { grid-row: 1; } }
@media (max-width: 760px) { .specialist-flowstage { gap: 13px; }.specialist-flowstage__canvas-heading { align-items: center; justify-content: flex-end; padding: 12px 15px 7px; }.specialist-flowstage__dock { margin-inline: 9px; padding: 4px; }.specialist-flowstage__dock-tab { display: flex; min-height: 53px; flex-direction: column; justify-content: center; gap: 3px; padding: 5px 2px; text-align: center; }.specialist-flowstage__dock-icon { width: 30px; height: 30px; }.specialist-flowstage__dock-icon svg { width: 17px; height: 17px; }.specialist-flowstage__dock-label { max-width: 100%; font-size: 11px; }.specialist-flowstage__stage { grid-template-columns: minmax(0,1fr) 160px; gap: 9px; margin: 9px; padding: 18px 16px; }.specialist-flowstage__visual { min-height: 160px; }.specialist-flowstage__visual-icon { width: 62px; height: 62px; border-radius: 20px; }.specialist-flowstage__visual-icon svg { width: 28px; height: 28px; }.specialist-flowstage__orbit { width: 190px; }.specialist-flowstage__visual-index { font-size: 68px; }.specialist-flowstage__scope { align-items: flex-start; margin-inline: 10px; }.specialist-flowstage__scope-count { max-width: 130px; line-height: 1.4; }.specialist-flowstage__filmstrip { padding-inline: 13px; }.specialist-flowstage__filmstrip-heading > span { display: none; }.specialist-flowstage__business { padding: 12px 10px 14px; } }
@media (max-width: 500px) { .specialist-flowstage__page-heading { align-items: center; justify-content: flex-end; }.specialist-flowstage__quick-trigger { min-height: 34px; }.specialist-flowstage__stage { grid-template-columns: minmax(0,1fr); }.specialist-flowstage__visual { min-height: 118px; max-height: 118px; }.specialist-flowstage__orbit { width: 210px; }.specialist-flowstage__visual-index { right: 3%; font-size: 58px; }.specialist-flowstage__visual-icon { width: 54px; height: 54px; border-radius: 18px; }.specialist-flowstage__stage h2 { font-size: 23px; }.specialist-flowstage__scope { gap: 8px; padding: 10px 2px; }.specialist-flowstage__scope-count { max-width: 100px; font-size: 10px; }.specialist-flowstage__business-heading { align-items: flex-start; flex-direction: column; gap: 3px; }.specialist-flowstage__command-footer { flex-wrap: wrap; gap: 8px 12px; } }
@media (prefers-reduced-motion: reduce) { .specialist-flowstage__dock-indicator,.specialist-flowstage__dock-tab,.specialist-flowstage__dock-icon,.specialist-flowstage__enter,.specialist-flowstage__filmstrip-button,.specialist-flowstage__filmstrip-button::before,.specialist-flowstage__quick-trigger { transition-duration: .01ms; }.specialist-flowstage__orbit-track,.specialist-flowstage__visual-icon,.specialist-flowstage__state-pulse { animation: none; }.specialist-flowstage__filmstrip-viewport { scroll-behavior: auto; }.flowstage-stage-enter-active,.flowstage-stage-leave-active { transition-duration: .01ms; } }
</style>
