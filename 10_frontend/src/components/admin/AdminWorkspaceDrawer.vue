<script setup lang="ts">
/* global HTMLButtonElement, Event, AnimationEvent */
import { computed, ref } from 'vue'
import { CircleHelp, LoaderCircle, RefreshCw, X } from '@lucide/vue'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import type { AdminFolderTone, AdminWorkspaceAction, AdminWorkspaceFolder } from './admin-workspace-actions'
import type { AdminPreviewSummary, AdminPreviewState, FolderOrigin, FolderOrigins } from './admin-workspace-preview'

const PAPER_PALETTES: Record<AdminFolderTone, { surface: string; accent: string }> = {
  aqua: { surface: '#d3edf1', accent: '#169bb7' },
  lavender: { surface: '#dfe6f9', accent: '#657bd6' },
  sage: { surface: '#dcefe4', accent: '#3d8a77' },
  sand: { surface: '#f2e5d6', accent: '#ae7a3a' },
}

const props = defineProps<{
  open: boolean
  closing: boolean
  folder: AdminWorkspaceFolder | null
  actions: AdminWorkspaceAction[]
  state: AdminPreviewState
  summary: AdminPreviewSummary | null
  errorMessage: string
  origin: FolderOrigin | null
  paperOrigins: FolderOrigins
  selectedPaperIndex: number
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'return-complete': []
  refresh: []
  navigate: [action: AdminWorkspaceAction]
}>()

const closeButton = ref<HTMLButtonElement | null>(null)

const handleOpenAutoFocus = (event: Event) => {
  event.preventDefault()
  closeButton.value?.focus({ preventScroll: true })
}

const handleCloseAutoFocus = (event: Event) => {
  event.preventDefault()
}

const handlePaperAnimationEnd = (event: AnimationEvent) => {
  if (props.closing && event.target === event.currentTarget) {
    const currentAnimation = getComputedStyle(event.currentTarget as Element).animationName
    if (event.animationName === currentAnimation) emit('return-complete')
  }
}

const viewport = () => ({
  width: typeof window === 'undefined' ? 0 : window.innerWidth,
  height: typeof window === 'undefined' ? 0 : window.innerHeight,
})

const panelStyle = computed(() => {
  const size = viewport()
  const x = props.origin?.x ?? size.width / 2
  const y = props.origin?.y ?? size.height / 2
  const panelWidth = size.width <= 640 ? size.width - 24 : Math.min(780, size.width - 48)
  const cardScale = Math.min(.2, (42 * 1.35) / Math.max(1, panelWidth))
  return {
    '--preview-origin-dx': `${x - size.width / 2}px`,
    '--preview-origin-dy': `${y - size.height / 2}px`,
    '--preview-card-scale': `${cardScale}`,
  }
})

const selectedPaperOrigin = computed(() => props.paperOrigins[props.selectedPaperIndex] ?? props.origin)
const paperPalette = computed(() => PAPER_PALETTES[props.folder?.tone ?? 'aqua'])

const paperStyle = computed(() => {
  const size = viewport()
  const paper = selectedPaperOrigin.value ?? {
    x: size.width / 2,
    y: size.height / 2,
    width: 42,
    height: 32,
    coverOcclusion: 0,
  }
  const left = paper.x - paper.width / 2
  const top = paper.y - paper.height / 2
  const dx = size.width / 2 - paper.x
  const dy = size.height / 2 - paper.y
  const distance = Math.max(1, Math.hypot(dx, dy))
  const bend = Math.min(72, distance * .14)
  const normalX = -dy / distance
  const normalY = dx / distance
  const control1 = { x: dx * .25 + normalX * bend, y: dy * .25 + normalY * bend }
  const control2 = { x: dx * .75 + normalX * bend, y: dy * .75 + normalY * bend }
  const pointOnPath = (progress: number) => {
    const inverse = 1 - progress
    return {
      x: 3 * inverse ** 2 * progress * control1.x + 3 * inverse * progress ** 2 * control2.x + progress ** 3 * dx,
      y: 3 * inverse ** 2 * progress * control1.y + 3 * inverse * progress ** 2 * control2.y + progress ** 3 * dy,
    }
  }
  const trajectory: Record<string, string> = {}
  for (let step = 1; step <= 5; step += 1) {
    const point = pointOnPath(step / 6)
    trajectory[`--paper-p${step}-x`] = `${point.x}px`
    trajectory[`--paper-p${step}-y`] = `${point.y}px`
  }
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${paper.width}px`,
    height: `${paper.height}px`,
    '--paper-dx': `${dx}px`,
    '--paper-dy': `${dy}px`,
    '--paper-cover-occlusion': `${(paper.coverOcclusion ?? 0) * 100}%`,
    '--paper-cover-half-occlusion': `${(paper.coverOcclusion ?? 0) * 50}%`,
    '--paper-surface': paperPalette.value.surface,
    '--paper-accent': paperPalette.value.accent,
    ...trajectory,
  }
})

const dependencyLabel = (status: string) => {
  const value = status.toUpperCase()
  if (value === 'READY' || value === 'AVAILABLE') return '可用'
  if (value === 'UNAVAILABLE') return '不可用'
  if (value === 'DEFERRED') return '未配置'
  if (value === 'DISABLED') return '已关闭'
  return '未知'
}

const dependencyTone = (status: string) => {
  const value = status.toUpperCase()
  if (value === 'READY' || value === 'AVAILABLE') return 'admin-drawer__health-status--ready'
  if (value === 'UNAVAILABLE') return 'admin-drawer__health-status--down'
  return 'admin-drawer__health-status--unknown'
}
</script>

<template>
  <DialogRoot :open="open" @update:open="emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay class="admin-drawer__overlay" :class="{ 'admin-drawer__overlay--opening': open && !closing, 'admin-drawer__overlay--closing': closing }" />

      <div class="admin-drawer__papers" aria-hidden="true">
        <span
          v-if="selectedPaperOrigin"
          :key="selectedPaperIndex"
          class="admin-drawer__paper"
          :class="{ 'admin-drawer__paper--closing': closing }"
          :style="paperStyle"
          @animationend="handlePaperAnimationEnd"
        >
          <i class="admin-drawer__paper-mark" />
          <i class="admin-drawer__paper-line" />
          <i class="admin-drawer__paper-line admin-drawer__paper-line--short" />
        </span>
      </div>

      <DialogContent
        v-if="folder"
        class="admin-drawer__panel"
        :class="[`admin-drawer__panel--${folder.tone}`, { 'admin-drawer__panel--closing': closing }]"
        :style="panelStyle"
        @open-auto-focus="handleOpenAutoFocus"
        @close-auto-focus="handleCloseAutoFocus"
      >
        <header class="admin-drawer__header">
          <span class="admin-drawer__icon"><component :is="folder.icon" :size="21" aria-hidden="true" /></span>
          <div class="admin-drawer__heading">
            <span class="admin-drawer__eyebrow">{{ folder.category }}</span>
            <DialogTitle class="admin-drawer__title">{{ folder.title }}</DialogTitle>
            <DialogDescription class="admin-drawer__description">{{ folder.description }}</DialogDescription>
          </div>
          <button class="admin-drawer__refresh" type="button" :disabled="state === 'loading' || closing" @click="emit('refresh')">
            <LoaderCircle v-if="state === 'loading'" :size="15" class="admin-drawer__spin" aria-hidden="true" />
            <RefreshCw v-else :size="15" aria-hidden="true" />
            <span>{{ state === 'loading' ? '读取中' : '刷新' }}</span>
          </button>
          <DialogClose as-child>
            <button ref="closeButton" class="admin-drawer__close" type="button" aria-label="关闭概览卡片" :disabled="closing"><X :size="18" aria-hidden="true" /></button>
          </DialogClose>
        </header>

        <div class="admin-drawer__body">
          <div v-if="state === 'loading'" class="admin-drawer__message" role="status" aria-live="polite">
            <LoaderCircle :size="17" class="admin-drawer__spin" aria-hidden="true" />正在读取本校数据…
          </div>
          <div v-else-if="state === 'error'" class="admin-drawer__message admin-drawer__message--error" role="status">
            <CircleHelp :size="18" aria-hidden="true" /><span>{{ errorMessage }}</span>
          </div>
          <template v-else-if="summary?.presentation === 'table'">
            <div class="admin-drawer__table-wrap">
              <table class="admin-drawer__table" :aria-label="summary.tableLabel">
                <thead>
                  <tr><th scope="col">服务</th><th scope="col">接入方式</th><th scope="col">状态</th></tr>
                </thead>
                <tbody>
                  <tr v-for="item in summary.dependencyRows" :key="item.name">
                    <th scope="row">{{ item.name }}</th>
                    <td>{{ item.connection }}</td>
                    <td><span class="admin-drawer__health-status" :class="dependencyTone(item.status)"><i aria-hidden="true" />{{ dependencyLabel(item.status) }}</span></td>
                  </tr>
                  <tr v-if="!summary.dependencyRows.length">
                    <td colspan="3" class="admin-drawer__table-empty">暂无服务条目</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <template v-else-if="summary?.presentation === 'chart'">
            <section class="admin-drawer__stats" aria-label="数据摘要">
              <div class="admin-drawer__stat admin-drawer__stat--headline">
                <span>{{ summary.headlineLabel }}</span>
                <strong>{{ summary.headlineValue }}</strong>
              </div>
              <div v-for="metric in summary.metrics" :key="metric.label" class="admin-drawer__stat">
                <span>{{ metric.label }}</span>
                <strong>{{ metric.value }}</strong>
              </div>
            </section>

            <section class="admin-drawer__chart-card" :aria-label="summary.chartTitle">
              <h3 class="admin-drawer__chart-title">{{ summary.chartTitle }}</h3>
              <TeacherProgressChart
                v-if="summary.chartOption"
                :option="summary.chartOption"
                :label="summary.chartLabel"
                :height="240"
              />
              <div v-else class="admin-drawer__chart-empty" role="status">{{ summary.chartEmptyMessage }}</div>
            </section>
          </template>
        </div>

        <footer v-if="actions.length" class="admin-drawer__footer">
          <div class="admin-drawer__actions" aria-label="打开详细页面">
            <button v-for="action in actions" :key="action.id" type="button" @click="emit('navigate', action)">{{ action.label }}</button>
          </div>
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<style scoped>
.admin-drawer__overlay { position: fixed; z-index: 80; inset: 0; opacity: 0; background: rgb(24 42 53 / 18%); backdrop-filter: blur(0); }
.admin-drawer__overlay--opening { animation: preview-overlay-in 180ms ease both; }
.admin-drawer__overlay--closing { animation: preview-overlay-out 380ms ease both; }
.admin-drawer__papers { position: fixed; z-index: 92; inset: 0; overflow: hidden; pointer-events: none; }
.admin-drawer__paper { position: fixed; display: flex; flex-direction: column; gap: 4px; padding: 5px 6px; border: 1px solid color-mix(in srgb, var(--paper-accent, #169bb7) 24%, white); border-radius: 7px; opacity: .92; background: var(--paper-surface, #fff); box-shadow: 0 7px 16px rgb(37 69 85 / 14%); transform-origin: center; animation: folder-paper-fly 460ms linear both; }
.admin-drawer__paper--closing { animation-name: folder-paper-return; animation-duration: 460ms; animation-delay: 330ms; animation-timing-function: linear; }
.admin-drawer__paper-mark { width: 11px; height: 3px; flex: 0 0 3px; border-radius: 3px; background: var(--paper-accent, #169bb7); }.admin-drawer__paper-line { display: block; width: 100%; height: 2px; border-radius: 3px; background: color-mix(in srgb, var(--paper-accent, #169bb7) 24%, white); }.admin-drawer__paper-line--short { width: 68%; }
.admin-drawer__panel { --drawer-accent: var(--color-primary-active); position: fixed; z-index: 90; top: 50%; left: 50%; display: flex; width: min(780px, calc(100vw - 48px)); max-height: min(86dvh, 760px); flex-direction: column; overflow: hidden; border: 1px solid #dfe8ed; border-radius: 23px; outline: none; color: var(--color-text-primary); background: #fff; box-shadow: 0 28px 84px rgb(25 50 66 / 25%); transform: translate(-50%, -50%); transform-origin: center; animation: folder-preview-open 560ms cubic-bezier(.4, 0, .2, 1) 420ms both; }
.admin-drawer__panel--lavender { --drawer-accent: #657bd6; }.admin-drawer__panel--sage { --drawer-accent: #3d8a77; }.admin-drawer__panel--sand { --drawer-accent: #ae7a3a; }
.admin-drawer__panel--closing { animation-direction: reverse; animation-duration: 330ms; animation-delay: 0ms; animation-timing-function: cubic-bezier(.4, 0, .2, 1); }
.admin-drawer__header { display: flex; flex: 0 0 auto; align-items: center; gap: 13px; padding: 20px 22px 17px; border-bottom: 1px solid #e9eef1; }
.admin-drawer__icon { display: grid; width: 44px; height: 44px; flex: 0 0 44px; place-items: center; border-radius: 13px; color: var(--drawer-accent); background: color-mix(in srgb, var(--drawer-accent) 10%, white); }
.admin-drawer__heading { min-width: 0; flex: 1; }.admin-drawer__eyebrow { display: block; margin-bottom: 3px; color: var(--drawer-accent); font-size: 11px; font-weight: 700; }.admin-drawer__title { margin: 0; color: #223a49; font-size: 21px; font-weight: 740; line-height: 1.25; }.admin-drawer__description { display: block; margin-top: 4px; color: #718692; font-size: 12px; line-height: 1.5; }
.admin-drawer__refresh,.admin-drawer__close { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 36px; border: 1px solid #e2e9ed; border-radius: 9px; color: #607783; background: #fff; cursor: pointer; }
.admin-drawer__refresh { padding: 0 10px; font-size: 12px; }.admin-drawer__close { width: 36px; flex: 0 0 36px; padding: 0; }.admin-drawer__refresh:hover,.admin-drawer__close:hover { border-color: #bcdde5; color: var(--drawer-accent); background: #f6fbfc; }.admin-drawer__refresh:disabled,.admin-drawer__close:disabled { opacity: .55; cursor: wait; }
.admin-drawer__body { display: grid; min-height: 0; flex: 1 1 auto; gap: 14px; padding: 18px 22px; overflow-y: auto; overscroll-behavior: contain; }
.admin-drawer__stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }.admin-drawer__stat { display: grid; min-height: 72px; align-content: center; gap: 5px; padding: 11px 13px; border: 1px solid #e7edf0; border-radius: 12px; background: #fbfcfd; }.admin-drawer__stat span { color: #7d909b; font-size: 11px; line-height: 1.35; }.admin-drawer__stat strong { color: #263d4b; font-size: 20px; font-weight: 730; font-variant-numeric: tabular-nums; line-height: 1.1; }.admin-drawer__stat--headline { border-color: color-mix(in srgb, var(--drawer-accent) 23%, white); background: color-mix(in srgb, var(--drawer-accent) 7%, white); }.admin-drawer__stat--headline strong { color: var(--drawer-accent); font-size: 25px; }
.admin-drawer__chart-card { min-width: 0; padding: 15px 16px 12px; border: 1px solid #e6edf0; border-radius: 15px; background: #fcfdfd; }.admin-drawer__chart-title { margin: 0 0 4px; color: #314a59; font-size: 13px; font-weight: 700; }.admin-drawer__chart-empty { display: grid; min-height: 220px; place-items: center; color: #788d98; font-size: 12px; }
.admin-drawer__table-wrap { min-width: 0; overflow-x: auto; border: 1px solid #e6edf0; border-radius: 14px; background: #fff; }.admin-drawer__table { width: 100%; border-collapse: collapse; text-align: left; }.admin-drawer__table thead { color: #8496a0; background: #f7f9fa; font-size: 11px; }.admin-drawer__table th,.admin-drawer__table td { min-height: 44px; padding: 11px 15px; border-bottom: 1px solid #edf1f3; }.admin-drawer__table tbody tr:last-child th,.admin-drawer__table tbody tr:last-child td { border-bottom: 0; }.admin-drawer__table tbody th { color: #425a68; font-size: 12px; font-weight: 650; }.admin-drawer__table tbody td { color: #788d98; font-size: 11px; }.admin-drawer__table-empty { height: 150px; color: #788d98; text-align: center; }
.admin-drawer__health-status { display: inline-flex; align-items: center; gap: 6px; padding: 5px 8px; border-radius: 99px; color: #92722f; background: #fbf5e7; font-size: 10px; font-weight: 700; white-space: nowrap; }.admin-drawer__health-status i { width: 6px; height: 6px; border-radius: 50%; background: currentcolor; }.admin-drawer__health-status--ready { color: #317b68; background: #e9f5f0; }.admin-drawer__health-status--down { color: #a23f38; background: #fbefed; }
.admin-drawer__message { display: flex; min-height: 220px; align-items: center; justify-content: center; gap: 9px; padding: 20px; border: 1px dashed #d8e4e9; border-radius: 14px; color: #6d838f; background: #fafcfd; font-size: 13px; text-align: center; }.admin-drawer__message--error { color: #846e3e; background: #fcfaf4; }
.admin-drawer__footer { display: flex; flex: 0 0 auto; justify-content: flex-end; gap: 10px; padding: 13px 22px 16px; border-top: 1px solid #e9eef1; }.admin-drawer__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; }.admin-drawer__actions button { display: inline-flex; min-height: 34px; align-items: center; justify-content: center; padding: 0 12px; border: 1px solid color-mix(in srgb, var(--drawer-accent) 30%, #e2e9ed); border-radius: 8px; color: var(--drawer-accent); background: #fff; cursor: pointer; font: inherit; font-size: 11px; font-weight: 680; white-space: nowrap; }.admin-drawer__actions button:hover { background: color-mix(in srgb, var(--drawer-accent) 7%, white); }.admin-drawer__actions button:focus-visible,.admin-drawer__refresh:focus-visible,.admin-drawer__close:focus-visible { outline: 2px solid color-mix(in srgb, var(--drawer-accent) 65%, white); outline-offset: 2px; }
.admin-drawer__spin { animation: preview-spin 1.1s linear infinite; }
@keyframes preview-overlay-in { from { opacity: 0; backdrop-filter: blur(0); } to { opacity: 1; backdrop-filter: blur(5px); } }
@keyframes preview-overlay-out { from { opacity: 1; backdrop-filter: blur(5px); } to { opacity: 0; backdrop-filter: blur(0); } }
@keyframes folder-preview-open { from { opacity: 0; border-radius: 7px; transform: translate(-50%, -50%) scale(var(--preview-card-scale, .073)) rotate(24deg); } to { opacity: 1; border-radius: 23px; transform: translate(-50%, -50%) scale(1) rotate(0); } }
@keyframes folder-paper-fly {
  0% { opacity: .95; clip-path: inset(0 0 var(--paper-cover-occlusion, 0%) 0); transform: translate(0, 0) scale(1) rotate(0); }
  16.666% { clip-path: inset(0); transform: translate(var(--paper-p1-x), var(--paper-p1-y)) scale(1.05) rotate(4deg); }
  33.333% { transform: translate(var(--paper-p2-x), var(--paper-p2-y)) scale(1.1) rotate(8deg); }
  50% { transform: translate(var(--paper-p3-x), var(--paper-p3-y)) scale(1.17) rotate(12deg); }
  66.666% { transform: translate(var(--paper-p4-x), var(--paper-p4-y)) scale(1.23) rotate(16deg); }
  83.333% { transform: translate(var(--paper-p5-x), var(--paper-p5-y)) scale(1.3) rotate(20deg); }
  100% { opacity: 0; transform: translate(var(--paper-dx), var(--paper-dy)) scale(1.35) rotate(24deg); }
}
@keyframes folder-paper-return {
  0% { opacity: 0; clip-path: inset(0); transform: translate(var(--paper-dx), var(--paper-dy)) scale(1.35) rotate(24deg); }
  16.666% { opacity: .95; transform: translate(var(--paper-p5-x), var(--paper-p5-y)) scale(1.3) rotate(20deg); }
  33.333% { opacity: .95; transform: translate(var(--paper-p4-x), var(--paper-p4-y)) scale(1.23) rotate(16deg); }
  50% { opacity: .95; transform: translate(var(--paper-p3-x), var(--paper-p3-y)) scale(1.17) rotate(12deg); }
  66.666% { opacity: .95; transform: translate(var(--paper-p2-x), var(--paper-p2-y)) scale(1.1) rotate(8deg); }
  83.333% { opacity: .95; clip-path: inset(0); transform: translate(var(--paper-p1-x), var(--paper-p1-y)) scale(1.05) rotate(4deg); }
  91.666% { opacity: .6; clip-path: inset(0 0 var(--paper-cover-half-occlusion, 0%) 0); }
  100% { opacity: 0; clip-path: inset(0 0 var(--paper-cover-occlusion, 0%) 0); transform: translate(0, 0) scale(1) rotate(0); }
}
@keyframes preview-spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) {
  .admin-drawer__panel { width: calc(100vw - 24px); max-height: calc(100dvh - 24px); border-radius: 17px; }
  .admin-drawer__header { gap: 9px; padding: 14px 13px 12px; }.admin-drawer__icon { width: 38px; height: 38px; flex-basis: 38px; }.admin-drawer__title { font-size: 18px; }.admin-drawer__description { font-size: 11px; }
  .admin-drawer__refresh { width: 35px; padding: 0; }.admin-drawer__refresh span { display: none; }.admin-drawer__close { width: 34px; flex-basis: 34px; }
  .admin-drawer__body { gap: 10px; padding: 12px; }.admin-drawer__stats { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }.admin-drawer__stat { min-height: 63px; padding: 9px 10px; }.admin-drawer__stat strong { font-size: 18px; }.admin-drawer__stat--headline strong { font-size: 23px; }
  .admin-drawer__chart-card { padding: 12px 10px 9px; }.admin-drawer__footer { padding: 11px 13px 13px; }.admin-drawer__actions { justify-content: flex-start; }.admin-drawer__actions button { min-height: 36px; }
  .admin-drawer__table th,.admin-drawer__table td { padding: 10px 9px; }.admin-drawer__table thead { font-size: 10px; }.admin-drawer__table tbody th,.admin-drawer__table tbody td { font-size: 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .admin-drawer__overlay,.admin-drawer__overlay--opening,.admin-drawer__overlay--closing,.admin-drawer__panel,.admin-drawer__panel--closing,.admin-drawer__paper,.admin-drawer__paper--closing,.admin-drawer__spin { animation-duration: 1ms; animation-iteration-count: 1; }
  .admin-drawer__paper { display: none; }
}
</style>
