<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts/core'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import {
  coverageAt,
  coverageCurvePoints,
  escapeAnalysisText,
  formatAnalysisPercent,
  type AnalysisTask,
} from '@/utils/teacher-analysis-aggregations'

const props = defineProps<{
  currentTasks: AnalysisTask[]
  overallTasks: AnalysisTask[]
  currentClassLabel: string
  threshold: number
}>()

const reducedMotion = typeof window !== 'undefined'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const themeColor = (name: string, fallback: string) => {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

const option = computed<EChartsOption>(() => {
  const currentColor = themeColor('--color-primary-active', '#008eb5')
  const overallColor = themeColor('--color-sidebar-label', '#a0a3ab')
  const gridColor = themeColor('--color-chart-grid', '#e4e7ec')
  const textColor = themeColor('--color-text-primary', '#1e1d29')
  const mutedColor = themeColor('--color-text-muted', '#656b76')
  const borderColor = themeColor('--color-border-strong', 'rgb(0 0 0 / 12%)')
  const surfaceColor = themeColor('--color-surface', '#ffffff')
  const currentLabel = props.currentClassLabel
  const overallLabel = '全部授权班级（含本班）'
  const currentPoints = coverageCurvePoints(props.currentTasks)
  const overallPoints = coverageCurvePoints(props.overallTasks)

  return {
    animation: !reducedMotion,
    animationDuration: 280,
    animationDurationUpdate: 260,
    animationEasingUpdate: 'cubicOut',
    grid: { left: 20, right: 18, top: 20, bottom: 42, containLabel: true },
    tooltip: {
      trigger: 'axis',
      confine: true,
      transitionDuration: 0.12,
      backgroundColor: surfaceColor,
      borderColor,
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: textColor, fontSize: 12 },
      extraCssText: 'border-radius:10px;box-shadow:var(--shadow-raised);',
      axisPointer: { type: 'line', lineStyle: { color: currentColor, width: 1, type: 'dashed' } },
      formatter: (params) => {
        const first = Array.isArray(params) ? params[0] : params
        const threshold = Number(first?.axisValue)
        if (!Number.isFinite(threshold)) return ''

        const current = coverageAt(props.currentTasks, threshold)
        const overall = coverageAt(props.overallTasks, threshold)
        const row = (label: string, color: string, value: ReturnType<typeof coverageAt>) => {
          const safeLabel = escapeAnalysisText(label)
          const result = value
            ? formatAnalysisPercent(value.percent) + '（达到 ' + value.reachedCount + ' / ' + value.totalCount + ' 项可统计任务）'
            : '暂无可统计任务'
          return '<div style="display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:7px">'
            + '<span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + color + ';margin-right:7px"></i>'
            + safeLabel + '</span><strong>' + result + '</strong></div>'
        }

        return '<div style="min-width:220px"><strong>完成率门槛 ' + threshold + '%</strong>'
          + row(currentLabel, currentColor, current)
          + row(overallLabel, overallColor, overall)
          + '</div>'
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 20,
      name: '完成率观察门槛',
      nameLocation: 'middle',
      nameGap: 29,
      nameTextStyle: { color: mutedColor, fontSize: 11 },
      axisLabel: { formatter: '{value}%', color: mutedColor, fontSize: 11 },
      axisLine: { lineStyle: { color: gridColor } },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      interval: 25,
      name: '达到门槛的任务',
      nameTextStyle: { color: mutedColor, fontSize: 10 },
      axisLabel: { formatter: '{value}%', color: mutedColor, fontSize: 11 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: gridColor } },
    },
    series: [
      {
        name: currentLabel,
        type: 'line',
        data: currentPoints,
        step: 'end',
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: currentColor, width: 3 },
        areaStyle: { color: currentColor, opacity: 0.08 },
        emphasis: { focus: 'series', lineStyle: { width: 4 } },
        z: 3,
      },
      {
        name: overallLabel,
        type: 'line',
        data: overallPoints,
        step: 'end',
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: overallColor, width: 2.5, type: 'dashed' },
        emphasis: { focus: 'series', lineStyle: { width: 3 } },
        z: 2,
      },
      {
        name: '观察线',
        type: 'line',
        data: [[props.threshold, 0], [props.threshold, 100]],
        symbol: 'none',
        lineStyle: { color: currentColor, width: 1.5, type: 'dashed', opacity: 0.72 },
        silent: true,
        tooltip: { show: false },
        z: 1,
      },
      {
        name: '本班门槛位置',
        type: 'scatter',
        data: props.currentTasks.length
          ? [[props.threshold, coverageAt(props.currentTasks, props.threshold)?.percent ?? 0]]
          : [],
        symbolSize: 12,
        itemStyle: { color: currentColor, borderColor: '#ffffff', borderWidth: 2 },
        silent: true,
        tooltip: { show: false },
        z: 5,
      },
      {
        name: '整体门槛位置',
        type: 'scatter',
        data: props.overallTasks.length
          ? [[props.threshold, coverageAt(props.overallTasks, props.threshold)?.percent ?? 0]]
          : [],
        symbolSize: 10,
        itemStyle: { color: overallColor, borderColor: '#ffffff', borderWidth: 2 },
        silent: true,
        tooltip: { show: false },
        z: 4,
      },
    ],
  }
})
</script>

<template>
  <TeacherProgressChart
    :option="option"
    :height="300"
    label="完成率覆盖阶梯曲线，横轴为完成率门槛，纵轴为达到门槛的任务比例"
  />
</template>
