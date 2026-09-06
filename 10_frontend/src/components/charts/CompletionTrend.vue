<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsOption } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  data: Array<{ date: string; completed: number; supported: number }>
}>()

const root = ref<HTMLElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const token = (name: string) => {
  if (typeof window === 'undefined') return 'transparent'
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || 'transparent'
}

const render = () => {
  if (!chart) return
  const option: EChartsOption = {
    animation: true,
    animationDuration: 260,
    color: [token('--color-chart-blue'), token('--color-chart-teal')],
    tooltip: {
      trigger: 'axis',
      backgroundColor: token('--color-sidebar'),
      borderWidth: 0,
      textStyle: { color: token('--color-text-inverse'), fontSize: 12 },
    },
    legend: { bottom: 0, icon: 'roundRect', itemWidth: 16, itemHeight: 4, textStyle: { color: token('--color-text-secondary'), fontSize: 11 } },
    grid: { top: 18, right: 10, bottom: 38, left: 37 },
    xAxis: { type: 'category', boundaryGap: false, data: props.data.map((item) => item.date), axisLine: { lineStyle: { color: token('--color-chart-grid') } }, axisTick: { show: false }, axisLabel: { color: token('--color-text-muted'), fontSize: 11 } },
    yAxis: { type: 'value', splitNumber: 3, min: 0, axisLabel: { color: token('--color-text-muted'), fontSize: 10 }, splitLine: { lineStyle: { color: token('--color-chart-grid'), type: 'dashed' } }, axisLine: { show: false }, axisTick: { show: false } },
    series: [
      { name: '已完成', type: 'line', smooth: 0.22, symbol: 'circle', symbolSize: 6, data: props.data.map((item) => item.completed), lineStyle: { width: 2 }, areaStyle: { opacity: 0.08 } },
      { name: '进入支持流程', type: 'line', smooth: 0.22, symbol: 'circle', symbolSize: 6, data: props.data.map((item) => item.supported), lineStyle: { width: 2 } },
    ],
  }
  chart.setOption(option, true)
}

onMounted(() => {
  if (!root.value) return
  chart = echarts.init(root.value, undefined, { renderer: 'canvas' })
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(root.value)
})

watch(() => props.data, render, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  resizeObserver = null
  chart = null
})
</script>

<template>
  <div>
    <div ref="root" class="trend-chart" aria-label="合成案例一周完成与支持流程趋势图"></div>
    <p class="trend-alt">文字摘要：完成记录在本周末为 {{ data.at(-1)?.completed ?? 0 }} 条，进入支持流程为 {{ data.at(-1)?.supported ?? 0 }} 条。数据为合成演示。</p>
  </div>
</template>

<style scoped>
.trend-chart { width: 100%; height: 300px; }
.trend-alt { margin: -4px 0 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@media (max-width: 560px) { .trend-chart { height: 260px; } }
</style>
