<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsOption } from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  dimensions: Array<{ label: string; value: number }>
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
    animationDuration: 240,
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const value = Array.isArray(params) ? params[0]?.value : params.value
        return `<strong>合成结构</strong><br/>数值：${Array.isArray(value) ? value.join('、') : value}`
      },
    },
    radar: {
      center: ['50%', '50%'],
      radius: '63%',
      splitNumber: 4,
      indicator: props.dimensions.map((dimension) => ({ name: dimension.label, max: 100 })),
      axisName: { color: token('--color-text-secondary'), fontSize: 11 },
      axisLine: { lineStyle: { color: token('--color-chart-grid') } },
      splitLine: { lineStyle: { color: token('--color-chart-grid') } },
      splitArea: { areaStyle: { color: [token('--color-surface-raised'), token('--color-surface-chart-alt')] } },
    },
    series: [{
      type: 'radar',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { color: token('--color-chart-blue'), width: 2 },
      itemStyle: { color: token('--color-chart-blue') },
      areaStyle: { opacity: 0.12 },
      data: [{ value: props.dimensions.map((dimension) => dimension.value), name: '合成结构' }],
    }],
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

watch(() => props.dimensions, render, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  resizeObserver = null
  chart = null
})
</script>

<template>
  <div class="radar-wrap">
    <div ref="root" class="radar-chart" aria-label="合成测评结构雷达图"></div>
    <p class="radar-alt">文字摘要：{{ dimensions.map((item) => `${item.label} ${item.value}`).join('；') }}。图表仅作结构展示，不代表心理学评分。</p>
  </div>
</template>

<style scoped>
.radar-wrap { min-width: 0; }
.radar-chart { width: 100%; height: 330px; }
.radar-alt { margin: -4px 0 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@media (max-width: 560px) { .radar-chart { height: 280px; } }
</style>
