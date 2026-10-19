<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsOption } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([PieChart, CanvasRenderer])

const props = withDefaults(defineProps<{
  rate: number | null
  label: string
  size?: number
  valueSize?: number
}>(), { size: 58, valueSize: 14 })

const root = ref<HTMLDivElement | null>(null)
const chartHost = ref<HTMLDivElement | null>(null)
const centerLabel = computed(() => props.rate === null ? '—' : `${Math.round(Math.max(0, Math.min(100, props.rate)))}%`)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const render = () => {
  if (!chart || !chartHost.value) return
  const styles = getComputedStyle(chartHost.value)
  const primary = styles.getPropertyValue('--color-primary').trim() || '#00b1e2'
  const track = styles.getPropertyValue('--color-surface-skeleton').trim() || '#e9edf2'
  const rate = props.rate === null ? 0 : Math.max(0, Math.min(100, props.rate))
  const option: EChartsOption = {
    animation: false,
    tooltip: { show: false },
    series: [{
      type: 'pie',
      radius: ['76%', '94%'],
      startAngle: 90,
      clockwise: true,
      avoidLabelOverlap: false,
      hoverOffset: 0,
      silent: true,
      label: { show: false },
      labelLine: { show: false },
      itemStyle: { borderWidth: 0 },
      emphasis: { disabled: true },
      data: [
        { value: rate, name: '已完成', itemStyle: { color: primary } },
        { value: Math.max(0, 100 - rate), name: '尚未完成', itemStyle: { color: track } },
      ],
    }],
  }
  chart.setOption(option, true)
}

watch(() => [props.rate, props.size], render)

onMounted(() => {
  if (!chartHost.value) return
  chart = echarts.init(chartHost.value, undefined, { renderer: 'canvas' })
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartHost.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  resizeObserver = null
  chart = null
})
</script>

<template>
  <div ref="root" class="task-progress-ring" :style="{ width: `${size}px`, height: `${size}px`, '--task-progress-ring-value-size': `${valueSize}px` }" role="img" :aria-label="`${label}：${centerLabel}`">
    <div ref="chartHost" class="task-progress-ring__chart" aria-hidden="true"></div>
    <span class="task-progress-ring__value" aria-hidden="true">{{ centerLabel }}</span>
  </div>
</template>

<style scoped>
.task-progress-ring { position: relative; flex: 0 0 auto; }
.task-progress-ring__chart { position: absolute; inset: 0; }
.task-progress-ring__value { position: absolute; inset: 0; display: grid; place-items: center; color: var(--color-primary-active); font-size: var(--task-progress-ring-value-size); font-weight: 700; font-variant-numeric: tabular-nums; pointer-events: none; }
</style>
