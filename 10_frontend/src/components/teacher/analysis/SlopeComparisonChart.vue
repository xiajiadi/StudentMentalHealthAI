<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts/core'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import {
  escapeAnalysisText,
  formatAnalysisPercent,
  formatPercentagePoints,
  isUsableVerifiedTaskPair,
  type VerifiedTaskPair,
} from '@/utils/teacher-analysis-aggregations'

const props = defineProps<{
  pairs: VerifiedTaskPair[]
  selectedPairKey?: string
}>()

const emit = defineEmits<{
  select: [pairKey: string]
}>()

const usablePairs = computed(() => props.pairs.filter(isUsableVerifiedTaskPair))
const reducedMotion = typeof window !== 'undefined'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const cleanVisibleLabel = (label: string) => label.replaceAll('\u00b7', '：')
const cleanTaskLabel = (label: string) => cleanVisibleLabel(label.replace(/\s*[（(]合成示例[）)]\s*$/, '').trim())

const themeColor = (name: string, fallback: string) => {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

const lineColors = computed(() => [
  themeColor('--color-primary-active', '#008eb5'),
  themeColor('--color-chart-teal', '#0f766e'),
  themeColor('--color-chart-blue', '#2563eb'),
  themeColor('--color-chart-amber', '#b7791f'),
  themeColor('--color-chart-sky', '#53a9cf'),
  themeColor('--color-chart-violet', '#817bd1'),
  themeColor('--color-chart-rose', '#d46a7e'),
])
const legendItems = computed(() => usablePairs.value.map((pair, index) => ({
  key: pair.key,
  taskLabel: cleanTaskLabel(pair.taskLabel),
  color: lineColors.value[index % lineColors.value.length],
})))
const yScale = computed(() => {
  const rates = usablePairs.value.flatMap((pair) => [pair.classA.completionRate, pair.classB.completionRate])
  if (!rates.length) return { min: 0, max: 100, interval: 25 }

  const dataMin = Math.min(...rates)
  const dataMax = Math.max(...rates)
  const padding = Math.max(5, (dataMax - dataMin) * 0.18)
  let min = Math.max(0, Math.floor((dataMin - padding) / 10) * 10)
  let max = Math.min(100, Math.ceil((dataMax + padding) / 10) * 10)

  if (max - min < 30) {
    const center = (dataMin + dataMax) / 2
    min = Math.max(0, Math.floor((center - 15) / 10) * 10)
    max = Math.min(100, Math.ceil((center + 15) / 10) * 10)
    if (max - min < 30) {
      if (min === 0) max = 30
      else min = 70
    }
  }

  return { min, max, interval: max - min <= 50 ? 10 : 20 }
})

const option = computed<EChartsOption>(() => {
  const gridColor = themeColor('--color-chart-grid', '#e4e7ec')
  const textColor = themeColor('--color-text-primary', '#1e1d29')
  const mutedColor = themeColor('--color-text-muted', '#656b76')
  const borderColor = themeColor('--color-border-strong', 'rgb(0 0 0 / 12%)')
  const surfaceColor = themeColor('--color-surface', '#ffffff')
  const pairsByKey = new Map(usablePairs.value.map((pair) => [pair.key, pair]))
  const firstPair = usablePairs.value[0]

  return {
    animation: !reducedMotion,
    animationDuration: 260,
    animationDurationUpdate: 180,
    animationEasingUpdate: 'cubicOut',
    grid: { left: 36, right: 36, top: 24, bottom: 50, containLabel: true },
    tooltip: {
      trigger: 'item',
      confine: true,
      transitionDuration: 0.12,
      backgroundColor: surfaceColor,
      borderColor,
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: textColor, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:var(--shadow-raised);',
      formatter: (params) => {
        const first = Array.isArray(params) ? params[0] : params
        const data = first?.data
        const key = typeof data === 'object' && data !== null && 'taskRef' in data
          ? data.taskRef
          : undefined
        const pair = typeof key === 'string' ? pairsByKey.get(key) : undefined
        if (!pair) return ''

        const side = (classLabel: string, completed: number, active: number, rate: number) =>
          '<div style="display:flex;justify-content:space-between;gap:18px;margin-top:7px">'
          + '<span>' + escapeAnalysisText(cleanVisibleLabel(classLabel)) + '</span><strong>'
          + formatAnalysisPercent(rate) + '（' + completed + ' / ' + active + ' 人次）</strong></div>'

        return '<div style="min-width:235px"><strong>' + escapeAnalysisText(cleanTaskLabel(pair.taskLabel)) + '</strong>'
          + '<div style="margin-top:4px;color:' + mutedColor + ';font-size:11px">共同定义 '
          + escapeAnalysisText(cleanVisibleLabel(pair.taskDefinitionRef)) + '，版本 '
          + escapeAnalysisText(cleanVisibleLabel(pair.taskDefinitionVersion)) + '</div>'
          + side(pair.classA.classLabel, pair.classA.completedCount, pair.classA.activeCount, pair.classA.completionRate)
          + side(pair.classB.classLabel, pair.classB.completedCount, pair.classB.activeCount, pair.classB.completionRate)
          + '<div style="margin-top:8px;padding-top:7px;border-top:1px solid ' + borderColor + '">完成率差异（B − A）：<strong>'
          + escapeAnalysisText(formatPercentagePoints(pair.differencePp)) + '</strong></div></div>'
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 4,
      axisLabel: {
        formatter: (value) => {
          if (Number(value) === 8) return cleanVisibleLabel(firstPair?.classA.classLabel ?? '')
          if (Number(value) === 92) return cleanVisibleLabel(firstPair?.classB.classLabel ?? '')
          return ''
        },
        color: mutedColor,
        fontSize: 12,
        hideOverlap: true,
        overflow: 'truncate',
        width: 150,
      },
      axisLine: { lineStyle: { color: gridColor } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: yScale.value.min,
      max: yScale.value.max,
      interval: yScale.value.interval,
      name: '任务完成率',
      nameTextStyle: { color: mutedColor, fontSize: 11 },
      axisLabel: { formatter: '{value}%', color: mutedColor, fontSize: 12 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: gridColor } },
    },
    series: usablePairs.value.map((pair, index) => {
      const selected = pair.key === props.selectedPairKey
      const color = lineColors.value[index % lineColors.value.length]
      return {
        id: pair.key,
        name: cleanTaskLabel(pair.taskLabel),
        type: 'line',
        data: [
          { value: [8, pair.classA.completionRate], taskRef: pair.key },
          { value: [92, pair.classB.completionRate], taskRef: pair.key },
        ],
        showSymbol: true,
        symbol: 'circle',
        symbolSize: selected ? 15 : 11,
        smooth: false,
        connectNulls: false,
        lineStyle: { color, width: selected ? 4.5 : 2.7, opacity: props.selectedPairKey && !selected ? 0.32 : 0.92 },
        itemStyle: { color, borderColor: '#ffffff', borderWidth: 2.5, opacity: props.selectedPairKey && !selected ? 0.45 : 1 },
        emphasis: {
          focus: 'series',
          scale: true,
          lineStyle: { width: 5.5, opacity: 1 },
          itemStyle: { color, borderColor: '#ffffff', borderWidth: 3, opacity: 1 },
        },
        blur: { lineStyle: { opacity: 0.16 }, itemStyle: { opacity: 0.18 } },
        z: selected ? 20 : index + 1,
      }
    }),
  }
})

</script>

<template>
  <div v-if="usablePairs.length" class="slope-chart">
    <TeacherProgressChart
      :option="option"
      :height="Math.min(560, Math.max(430, 360 + usablePairs.length * 22))"
      :label="`双班任务完成率斜率对照图，纵轴当前范围 ${yScale.min}% 到 ${yScale.max}%`"
      interactive
      @select="emit('select', $event)"
    />
    <div class="slope-chart__footer">
      <span class="slope-chart__axis-range">纵轴范围 {{ yScale.min }}%–{{ yScale.max }}%</span>
      <div class="slope-chart__legend" role="group" aria-label="共同任务图例">
        <button
          v-for="item in legendItems"
          :key="item.key"
          type="button"
          :style="{ '--legend-color': item.color }"
          :title="item.taskLabel"
          :aria-label="`突出显示任务：${item.taskLabel}`"
          :aria-pressed="item.key === selectedPairKey"
          @click="emit('select', item.key)"
        >
          <i aria-hidden="true"></i>
          <span>{{ item.taskLabel }}</span>
        </button>
      </div>
    </div>
  </div>
  <div v-else class="slope-chart-empty" role="status">暂无可比较的共同任务</div>
</template>

<style scoped>
.slope-chart { min-width: 0; }
.slope-chart__footer { display: grid; gap: 8px; margin-top: 12px; }
.slope-chart__axis-range { color: var(--color-text-muted); font-size: 11px; text-align: right; }
.slope-chart__legend { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin: 0; padding: 0; }
.slope-chart__legend button { display: inline-flex; width: 100%; min-width: 0; min-height: 32px; align-items: center; gap: 8px; padding: 4px 9px; overflow: hidden; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-secondary); background: var(--color-surface); font: inherit; font-size: 12px; text-align: left; cursor: pointer; transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.slope-chart__legend button:hover,.slope-chart__legend button[aria-pressed="true"] { border-color: var(--color-primary); background: var(--color-surface-blue); }
.slope-chart__legend button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.slope-chart__legend i { position: relative; width: 20px; height: 3px; flex: 0 0 auto; border-radius: 99px; background: var(--legend-color); }
.slope-chart__legend i::after { position: absolute; top: 50%; left: 50%; width: 8px; height: 8px; border: 1.5px solid var(--color-surface); border-radius: 50%; background: var(--legend-color); content: ''; transform: translate(-50%, -50%); }
.slope-chart__legend span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slope-chart-empty { display: grid; min-height: 180px; place-content: center; gap: 6px; border: 1px dashed var(--color-border-strong); border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 13px; text-align: center; }
@media (max-width: 560px) {
  .slope-chart__legend { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px; }
  .slope-chart__legend button { font-size: 11px; }
}
@media (max-width: 360px) {
  .slope-chart__legend { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .slope-chart__legend button { transition: none; }
}
</style>
