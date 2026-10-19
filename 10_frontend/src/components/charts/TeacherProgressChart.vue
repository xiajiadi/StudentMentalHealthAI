<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsOption } from 'echarts/core'
import { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, HeatmapChart, LineChart, PieChart, ScatterChart, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  option: EChartsOption
  label: string
  summary?: string
  height?: number
  interactive?: boolean
}>(), { height: 270, interactive: false })

const emit = defineEmits<{
  select: [taskRef: string]
}>()

const root = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const render = () => {
  if (chart) chart.setOption(props.option, true)
}

const onChartClick = (event: unknown) => {
  if (!props.interactive || typeof event !== 'object' || event === null || !('data' in event)) return
  const data = event.data
  if (typeof data !== 'object' || data === null || !('taskRef' in data)) return
  const taskRef = data.taskRef
  if (typeof taskRef === 'string') emit('select', taskRef)
}

onMounted(() => {
  if (!root.value) return
  chart = echarts.init(root.value, undefined, { renderer: 'canvas' })
  chart.on('click', onChartClick)
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
    <p v-if="summary" class="teacher-chart__summary">{{ summary }}</p>
  </div>
</template>

<style scoped>
.teacher-chart { min-width: 0; }
.teacher-chart__canvas { width: 100%; min-height: 220px; }
.teacher-chart__summary { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@media (max-width: 560px) { .teacher-chart__canvas { min-height: 200px; } }
</style>
