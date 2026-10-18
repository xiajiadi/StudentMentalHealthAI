<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsOption } from 'echarts/core'
import { BarChart, HeatmapChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, HeatmapChart, PieChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  option: EChartsOption
  label: string
  summary: string
  height?: number
}>(), { height: 270 })

const root = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const render = () => {
  if (chart) chart.setOption(props.option, true)
}

onMounted(() => {
  if (!root.value) return
  chart = echarts.init(root.value, undefined, { renderer: 'canvas' })
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(root.value)
})

watch(() => props.option, render, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  resizeObserver = null
  chart = null
})
</script>

<template>
  <div class="teacher-chart">
    <div ref="root" class="teacher-chart__canvas" :style="{ height: `${height}px` }" role="img" :aria-label="label"></div>
    <p class="teacher-chart__summary">{{ summary }}</p>
  </div>
</template>

<style scoped>
.teacher-chart { min-width: 0; }
.teacher-chart__canvas { width: 100%; min-height: 220px; }
.teacher-chart__summary { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@media (max-width: 560px) { .teacher-chart__canvas { min-height: 200px; } }
</style>
