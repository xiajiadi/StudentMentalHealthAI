<script setup lang="ts">
/* global Event, HTMLInputElement */
import { computed, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import { hasFormulaRegion, type FormulaRegion } from '@/services/workspace-formula-region'

const props = defineProps<{ source: string; editing: boolean; disabled: boolean; suggestions?: FormulaRegion[] }>()
const region = defineModel<FormulaRegion>({ required: true })
type Point = { x: number; y: number }
const drag = ref<{ pointer: number; anchor: Point; current: Point }>()
const edges = [
  { name: 'left', label: '左边界' },
  { name: 'top', label: '上边界' },
  { name: 'right', label: '右边界' },
  { name: 'bottom', label: '下边界' },
] as const

function rectangle(anchor: Point, current: Point): FormulaRegion {
  return {
    left: Math.min(anchor.x, current.x),
    top: Math.min(anchor.y, current.y),
    right: Math.max(anchor.x, current.x),
    bottom: Math.max(anchor.y, current.y),
  }
}

function placement(bounds: FormulaRegion) {
  return {
    left: `${bounds.left}%`,
    top: `${bounds.top}%`,
    width: `${bounds.right - bounds.left}%`,
    height: `${bounds.bottom - bounds.top}%`,
  }
}

function isCurrent(candidate: FormulaRegion) {
  return edges.every(({ name }) => region.value[name] === candidate[name])
}

const outline = computed(() => {
  const bounds = drag.value ? rectangle(drag.value.anchor, drag.value.current) : region.value
  return props.editing && hasFormulaRegion(bounds) ? placement(bounds) : undefined
})

function findPoint(event: PointerEvent, stage: HTMLElement): Point {
  const bounds = stage.getBoundingClientRect()
  const percent = (offset: number, size: number) => Math.round(Math.max(0, Math.min(100, offset / size * 100)) * 10) / 10
  return { x: percent(event.clientX - bounds.left, bounds.width), y: percent(event.clientY - bounds.top, bounds.height) }
}

function start(event: PointerEvent) {
  if (!props.editing || props.disabled || drag.value || !event.isPrimary || event.button !== 0) return
  const stage = event.currentTarget as HTMLElement
  const anchor = findPoint(event, stage)
  stage.setPointerCapture(event.pointerId)
  drag.value = { pointer: event.pointerId, anchor, current: anchor }
}

function move(event: PointerEvent) {
  if (drag.value?.pointer !== event.pointerId) return
  drag.value.current = findPoint(event, event.currentTarget as HTMLElement)
}

function finish(event: PointerEvent) {
  if (drag.value?.pointer !== event.pointerId) return
  move(event)
  const { anchor, current } = drag.value
  const selected = rectangle(anchor, current)
  drag.value = undefined
  if (hasFormulaRegion(selected)) {
    region.value = selected
  } else if (Math.abs(anchor.x - current.x) < 1 && Math.abs(anchor.y - current.y) < 1) {
    const candidate = props.suggestions?.find(({ left, top, right, bottom }) =>
      current.x >= left && current.x <= right && current.y >= top && current.y <= bottom)
    if (candidate) region.value = { ...candidate }
  }
}

function cancel(event: PointerEvent) {
  if (drag.value?.pointer === event.pointerId) drag.value = undefined
}

function setEdge(edge: keyof FormulaRegion, event: Event) {
  const input = event.target as HTMLInputElement
  if (Number.isFinite(input.valueAsNumber)) {
    region.value = { ...region.value, [edge]: Math.max(0, Math.min(100, input.valueAsNumber)) }
  }
  input.value = String(region.value[edge])
}

watch(() => [props.editing, props.disabled], () => { drag.value = undefined })
</script>

<template>
  <details v-if="!editing">
    <summary>查看原图</summary>
    <img class="formula-image" :src="source" alt="所选图片原图" loading="lazy">
  </details>
  <section v-else class="formula-region" aria-label="公式选区">
    <p>{{ suggestions?.length ? '选一个候选框，或自己拖出矩形。学校服务只接收选中的图片' : '拖出一个矩形，框住一道公式。学校服务只接收框内的图片' }}</p>
    <div
      class="formula-region__stage" :class="{ 'formula-region__stage--disabled': disabled }"
      @pointerdown="start" @pointermove="move" @pointerup="finish"
      @pointercancel="cancel" @lostpointercapture="cancel"
    >
      <img class="formula-image" :src="source" alt="在原图上框选公式" draggable="false">
      <template v-for="(candidate, index) in suggestions" :key="index">
        <span v-if="!drag && !isCurrent(candidate)" class="formula-region__candidate" :style="placement(candidate)" aria-hidden="true">{{ index + 1 }}</span>
      </template>
      <span v-if="outline" class="formula-region__outline" :style="outline" aria-hidden="true"></span>
    </div>
    <div v-if="suggestions?.length" class="formula-region__choices" role="group" aria-label="候选公式">
      <AppButton
        v-for="(candidate, index) in suggestions" :key="index" variant="secondary" size="sm"
        :disabled="disabled" :aria-pressed="isCurrent(candidate)" @click="region = { ...candidate }"
      >第 {{ index + 1 }} 处</AppButton>
    </div>
    <fieldset class="formula-region__edges" :disabled="disabled">
      <legend>选区边界（%）</legend>
      <label v-for="edge in edges" :key="edge.name">
        {{ edge.label }}
        <input type="number" min="0" max="100" step="0.1" :value="region[edge.name]" @change="setEdge(edge.name, $event)">
      </label>
    </fieldset>
  </section>
</template>

<style scoped>
.formula-image { display: block; width: auto; height: auto; max-width: 100%; max-height: min(45vh, 360px); }
details > .formula-image { margin-top: 8px; max-height: min(38vh, 260px); }
.formula-region { display: grid; gap: 9px; justify-items: start; margin-block: 8px 12px; }
.formula-region p { margin: 0; color: var(--color-text-secondary); font-size: 13px; }
.formula-region__stage { position: relative; max-width: 100%; overflow: hidden; border-radius: 4px; background: var(--color-surface-muted); box-shadow: 0 0 0 1px var(--color-border); touch-action: none; user-select: none; cursor: crosshair; }
.formula-region__stage--disabled { cursor: wait; }
.formula-region__stage img { pointer-events: none; }
.formula-region__candidate { position: absolute; border: 1px dashed #1c5e6e; color: #fff; background: rgb(42 128 151 / 10%); text-shadow: 0 1px 3px #0a3242, 0 0 2px #0a3242; padding-inline: 4px; font-size: 12px; font-weight: 700; pointer-events: none; }
.formula-region__outline { position: absolute; border: 2px solid var(--color-primary-active); box-shadow: 0 0 0 1px #fff, 0 0 0 1000px rgb(21 35 50 / 28%); pointer-events: none; }
.formula-region__choices { display: flex; flex-wrap: wrap; gap: 6px; }
.formula-region__choices :deep([aria-pressed="true"]) { border-color: var(--color-primary-active); color: var(--color-primary-active); }
.formula-region__edges { display: grid; width: 100%; min-width: 0; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0; border: 0; }
.formula-region__edges legend,.formula-region__edges label { color: var(--color-text-secondary); font-size: 12px; }
.formula-region__edges legend { padding: 0 0 5px; }
.formula-region__edges input { display: block; width: 100%; min-height: 36px; margin-top: 3px; padding: 4px 6px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-text-primary); font: inherit; }
.formula-region__edges input:focus-visible { outline: 2px solid var(--color-primary-active); outline-offset: 1px; }
</style>
