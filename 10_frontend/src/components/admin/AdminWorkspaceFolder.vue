<script setup lang="ts">
/* global HTMLButtonElement */
import { computed, ref } from 'vue'
import type { FolderOrigin } from './admin-workspace-preview'
import type { AdminWorkspaceFolder } from './admin-workspace-actions'

const props = defineProps<{
  folder: AdminWorkspaceFolder
  active?: boolean
  stacked?: boolean
  activePaperIndex?: number | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  open: [folder: AdminWorkspaceFolder, source: HTMLButtonElement, papers: FolderOrigin[], selectedPaperIndex: number]
}>()

type LayerPosition = { x: number; y: number; width: number; height: number; rotation: number }
type StackState = 0 | 1 | 2

const hovered = ref(false)
const focused = ref(false)
const stackState = computed<StackState>(() => props.active || props.stacked || hovered.value || focused.value ? 1 : 0)

// Vue adaptation of OpenSourceUI's POSITION_LAYOUT / STACK_ORDER approach.
const POSITION_LAYOUT: Record<StackState, LayerPosition[]> = {
  0: [
    { x: 4, y: 7, width: 91, height: 88, rotation: -2.1 },
    { x: 7, y: 3, width: 91, height: 91, rotation: 1.5 },
    { x: 0, y: 8, width: 100, height: 92, rotation: 0 },
  ],
  1: [
    { x: 2, y: 5, width: 93, height: 91, rotation: -2.8 },
    { x: 9, y: 1, width: 90, height: 93, rotation: 2.1 },
    { x: 0, y: 5, width: 100, height: 95, rotation: 0 },
  ],
  2: [
    { x: 1, y: 5, width: 94, height: 91, rotation: -2.5 },
    { x: 10, y: 0, width: 88, height: 93, rotation: 2.3 },
    { x: 0, y: 3, width: 100, height: 97, rotation: 0 },
  ],
}

const STACK_ORDER: Record<StackState, number[]> = {
  0: [0, 1, 2],
  1: [1, 0, 2],
  2: [2, 1, 0],
}

const positionForLayer = (index: number) => {
  const position = POSITION_LAYOUT[stackState.value][index]
  return {
    left: `${position.x}%`,
    top: `${position.y}%`,
    width: `${position.width}%`,
    height: `${position.height}%`,
    zIndex: STACK_ORDER[stackState.value].indexOf(index) + 1,
    transform: `rotate(${position.rotation}deg)`,
  }
}

const accessibleName = computed(() => `${props.folder.title}。${props.folder.description}`)
const paperOffsets = [-68, -23, 23, 68]
const paperRotations = [-9, -3, 4, 9]
const paperTops = [-30, -26, -28, -24]

const paperStyle = (index: number) => ({
  left: `calc(50% + ${paperOffsets[index]}px)`,
  top: `${paperTops[index]}px`,
  transform: `translateX(-50%) rotate(${paperRotations[index]}deg)`,
  zIndex: index + 5,
})

const getPaperOrigins = (source: HTMLButtonElement): FolderOrigin[] => {
  const coverTop = source.querySelector<HTMLElement>('.workspace-folder__cover')?.getBoundingClientRect().top
  return [...source.querySelectorAll<HTMLElement>('[data-folder-paper]')].map((paper) => {
    const bounds = paper.getBoundingClientRect()
    const coverOcclusion = coverTop === undefined ? 0 : Math.min(1, Math.max(0, (bounds.bottom - coverTop) / bounds.height))
    return {
      x: bounds.left + bounds.width / 2,
      y: bounds.top + bounds.height / 2,
      width: bounds.width,
      height: bounds.height,
      coverOcclusion,
    }
  })
}

const requestOpen = (event: MouseEvent) => {
  if (props.disabled) return
  const source = event.currentTarget as HTMLButtonElement
  const clickedPaper = (event.target as HTMLElement).closest<HTMLElement>('[data-folder-paper-index]')
  const clickedIndex = Number(clickedPaper?.dataset.folderPaperIndex)
  const selectedPaperIndex = Number.isInteger(clickedIndex) && clickedIndex >= 0 && clickedIndex < 4 ? clickedIndex : 2
  emit('open', props.folder, source, getPaperOrigins(source), selectedPaperIndex)
}
</script>

<template>
  <button
    class="workspace-folder"
    :class="[`workspace-folder--${folder.tone}`, { 'workspace-folder--active': active }]"
    type="button"
    :disabled="disabled"
    :aria-label="accessibleName"
    aria-haspopup="dialog"
    :aria-expanded="active ? 'true' : 'false'"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
    @focusin="focused = true"
    @focusout="focused = false"
    @click="requestOpen"
  >
    <span v-for="layer in [0, 1, 2]" :key="layer" class="workspace-folder__layer" :style="positionForLayer(layer)" aria-hidden="true">
      <span v-if="layer === 2" class="workspace-folder__papers">
        <span
          v-for="index in 4"
          :key="index"
          class="workspace-folder__paper"
          :class="[`workspace-folder__paper--${index}`, { 'workspace-folder__paper--selected': active && activePaperIndex === index - 1 }]"
          :style="paperStyle(index - 1)"
          data-folder-paper
          :data-folder-paper-index="index - 1"
        >
          <span class="workspace-folder__paper-mark" />
          <span class="workspace-folder__paper-lines"><i /><i /></span>
        </span>
      </span>
    </span>
    <span class="workspace-folder__cover">
      <span class="workspace-folder__head">
        <span class="workspace-folder__icon"><component :is="folder.icon" :size="23" stroke-width="1.8" aria-hidden="true" /></span>
        <span class="workspace-folder__category">{{ folder.category }}</span>
      </span>
      <span class="workspace-folder__copy">
        <span class="workspace-folder__title">{{ folder.title }}</span>
        <span class="workspace-folder__description">{{ folder.description }}</span>
      </span>
    </span>
  </button>
</template>

<style scoped>
.workspace-folder {
  --folder-accent: var(--color-primary-active);
  --folder-surface: #e1f4f7;
  --folder-tab: #d3edf1;
  position: relative;
  display: block;
  width: 100%;
  min-width: 0;
  min-height: 184px;
  padding: 0;
  border: 0;
  border-radius: 24px;
  color: var(--color-text-primary);
  background: transparent;
  text-align: left;
  cursor: pointer;
  isolation: isolate;
  -webkit-tap-highlight-color: transparent;
}
.workspace-folder--lavender { --folder-accent: #657bd6; --folder-surface: #e8edfb; --folder-tab: #dfe6f9; }
.workspace-folder--sage { --folder-accent: #3d8a77; --folder-surface: #e8f3ed; --folder-tab: #dcefe4; }
.workspace-folder--sand { --folder-accent: #ae7a3a; --folder-surface: #f8efe4; --folder-tab: #f2e5d6; }
.workspace-folder__layer { position: absolute; display: block; border: 1px solid rgb(145 169 182 / 15%); border-radius: 23px; background: var(--folder-tab); box-shadow: 0 12px 26px rgb(46 72 89 / 5%); pointer-events: none; transition: left 260ms cubic-bezier(.22, 1, .36, 1), top 260ms cubic-bezier(.22, 1, .36, 1), width 260ms cubic-bezier(.22, 1, .36, 1), height 260ms cubic-bezier(.22, 1, .36, 1), transform 260ms cubic-bezier(.22, 1, .36, 1), box-shadow 260ms ease; }
.workspace-folder__layer::before { position: absolute; top: -21px; left: 9%; width: 46%; height: 28px; border: 1px solid rgb(145 169 182 / 15%); border-bottom: 0; border-radius: 14px 14px 0 0; background: inherit; content: ''; }
.workspace-folder__layer:nth-of-type(2) { background: #fff; border-color: rgb(145 169 182 / 17%); box-shadow: 0 14px 30px rgb(46 72 89 / 7%); }
.workspace-folder__layer:nth-of-type(2)::before { left: 24%; width: 48%; background: #fff; }
.workspace-folder__layer:nth-of-type(3) { background: var(--folder-tab); opacity: .92; }
.workspace-folder__layer:nth-of-type(3)::before { left: 38%; width: 45%; }
.workspace-folder__papers { position: absolute; z-index: 5; inset: 0; pointer-events: none; }
.workspace-folder__paper { position: absolute; display: flex; width: 42px; height: 32px; flex-direction: column; gap: 4px; padding: 5px 6px; border: 1px solid rgb(103 138 154 / 19%); border-radius: 7px; background: var(--paper-surface, #fff); box-shadow: 0 5px 10px rgb(46 72 89 / 9%); cursor: pointer; pointer-events: auto; transition: opacity 120ms ease; }
.workspace-folder__paper--1 { --paper-surface: #fff; --paper-ink: #169bb7; }.workspace-folder__paper--2 { --paper-surface: #fdfefe; --paper-ink: #7abfce; }.workspace-folder__paper--3 { --paper-surface: var(--folder-tab); --paper-ink: var(--folder-accent); }.workspace-folder__paper--4 { --paper-surface: #fff; --paper-ink: #a9cdd5; }
.workspace-folder__paper-mark { width: 11px; height: 3px; flex: 0 0 3px; border-radius: 3px; background: var(--paper-ink); }.workspace-folder__paper-lines { display: grid; gap: 3px; }.workspace-folder__paper-lines i { display: block; width: 100%; height: 2px; border-radius: 3px; background: color-mix(in srgb, var(--paper-ink) 24%, white); }.workspace-folder__paper-lines i:last-child { width: 68%; }
.workspace-folder__cover { position: absolute; inset: 8px 0 0; z-index: 4; display: flex; flex-direction: column; justify-content: space-between; min-height: 176px; padding: 17px 20px; overflow: hidden; border: 1px solid rgb(68 104 124 / 9%); border-radius: 22px; background: var(--folder-surface); box-shadow: 0 14px 28px rgb(46 72 89 / 6%); transition: transform 260ms cubic-bezier(.22, 1, .36, 1), box-shadow 260ms ease, border-color 260ms ease; }
.workspace-folder__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.workspace-folder__icon { display: grid; width: 48px; height: 48px; flex: 0 0 48px; place-items: center; border-radius: 14px; color: var(--folder-accent); background: rgb(255 255 255 / 55%); }
.workspace-folder__category { padding: 7px 11px; border-radius: 999px; color: color-mix(in srgb, var(--folder-accent) 80%, #526677); background: rgb(255 255 255 / 64%); font-size: 13px; line-height: 1.35; }
.workspace-folder__copy { display: grid; gap: 8px; margin: 0; }
.workspace-folder__title { color: #203949; font-size: clamp(19px, 1.7vw, 23px); font-weight: 720; letter-spacing: -.025em; line-height: 1.3; }
.workspace-folder__description { color: #6d8796; font-size: 14px; line-height: 1.55; }
.workspace-folder:hover .workspace-folder__cover { border-color: color-mix(in srgb, var(--folder-accent) 25%, transparent); box-shadow: 0 18px 34px rgb(46 72 89 / 12%); }
.workspace-folder__paper--selected { opacity: 0; }
.workspace-folder--active .workspace-folder__cover { border-color: color-mix(in srgb, var(--folder-accent) 25%, transparent); }
.workspace-folder:disabled { opacity: .58; cursor: not-allowed; }
.workspace-folder:focus-visible { outline: 3px solid color-mix(in srgb, var(--folder-accent) 70%, white); outline-offset: 5px; }
.workspace-folder:focus-visible .workspace-folder__cover { box-shadow: 0 0 0 3px rgb(255 255 255 / 85%), 0 14px 28px rgb(46 72 89 / 8%); }
@media (prefers-reduced-motion: reduce) { .workspace-folder__layer, .workspace-folder__cover { transition-duration: 1ms; } }
@media (max-width: 720px) { .workspace-folder { min-height: 164px; }.workspace-folder__cover { min-height: 156px; padding: 15px 16px; }.workspace-folder__icon { width: 40px; height: 40px; flex-basis: 40px; }.workspace-folder__title { font-size: 20px; } }
</style>
