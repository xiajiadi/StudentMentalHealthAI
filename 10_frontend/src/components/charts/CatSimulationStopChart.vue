<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsOption } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

export type CatStoppingReasonRow = {
  reason: string
  label: string
  count: number
}

const props = defineProps<{
  rows: readonly CatStoppingReasonRow[]
}>()

const root = ref<HTMLElement | null>(null)
const reducedMotion = ref(false)
const fontFamily = ref('sans-serif')
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let mediaQuery: MediaQueryList | null = null

const formatCount = (value: number) => new Intl.NumberFormat('zh-CN', {
  maximumFractionDigits: 0,
}).format(value)

const option = computed<EChartsOption>(() => ({
  animation: !reducedMotion.value,
  animationDuration: 320,
  animationDurationUpdate: 220,
  animationEasing: 'cubicOut',
  textStyle: { fontFamily: fontFamily.value },
  grid: { top: 8, right: 36, bottom: 25, left: 136, containLabel: false },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    confine: true,
    backgroundColor: '#ffffff',
    borderColor: '#dbe7ec',
    borderWidth: 1,
    padding: [9, 11],
    textStyle: { color: '#344b57', fontFamily: fontFamily.value, fontSize: 12 },
    extraCssText: 'border-radius: 8px; box-shadow: 0 8px 22px rgba(34,67,83,.12);',
    formatter: '{b}<br/>样本数：{c}',
  },
  xAxis: {
    type: 'value',
    min: 0,
    name: '样本数',
    nameLocation: 'end',
    nameGap: 7,
    nameTextStyle: { color: '#7b8990', fontSize: 10, fontFamily: fontFamily.value },
    axisLabel: { color: '#7b8990', fontSize: 10, fontFamily: fontFamily.value },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { show: true, lineStyle: { color: '#e9eef1', width: 1 } },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: props.rows.map((row) => row.label),
    axisLabel: { color: '#536772', fontSize: 11, fontFamily: fontFamily.value, margin: 12 },
    axisLine: { show: false },
    axisTick: { show: false },
  },
  series: [{
    type: 'bar',
    data: props.rows.map((row) => ({ name: row.label, value: row.count })),
    barMaxWidth: 20,
    barCategoryGap: '42%',
    itemStyle: { color: '#00b1e2', borderRadius: [0, 7, 7, 0] },
    emphasis: { focus: 'self', itemStyle: { color: '#008eb5' } },
    label: {
      show: true,
      position: 'right',
      distance: 7,
      color: '#3e5a67',
      fontSize: 11,
      fontFamily: fontFamily.value,
      formatter: ({ value }) => typeof value === 'number' ? formatCount(value) : '',
    },
  }],
}))

function render() {
  chart?.setOption(option.value, { notMerge: true })
}

function onReducedMotionChange(event: MediaQueryListEvent) {
  reducedMotion.value = event.matches
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  if (!root.value) return
  fontFamily.value = getComputedStyle(root.value).fontFamily || 'sans-serif'
  mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  reducedMotion.value = mediaQuery.matches
  mediaQuery.addEventListener?.('change', onReducedMotionChange)
  chart = echarts.init(root.value, undefined, { renderer: 'canvas' })
  render()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(root.value)
  } else {
    window.addEventListener('resize', resize)
  }
})

watch(option, render, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  mediaQuery?.removeEventListener?.('change', onReducedMotionChange)
  window.removeEventListener('resize', resize)
  chart?.dispose()
  resizeObserver = null
  mediaQuery = null
  chart = null
})
</script>

<template>
  <figure class="cat-stop-chart">
    <div ref="root" class="cat-stop-chart__canvas" role="img" aria-label="停止原因分布；按原因显示本次模拟样本数" />
    <figcaption class="sr-only">停止原因分布。<ul><li v-for="row in rows" :key="row.reason">{{ row.label }}：{{ formatCount(row.count) }} 个样本</li></ul></figcaption>
  </figure>
</template>

<style scoped>
.cat-stop-chart { width: 100%; min-width: 0; margin: 0; }
.cat-stop-chart__canvas { width: 100%; height: 286px; min-height: 240px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; clip-path: inset(50%); }

@media (max-width: 560px) {
  .cat-stop-chart__canvas { height: 254px; }
}
</style>
