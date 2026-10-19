<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AnalysisTimeWindow } from '@/utils/teacher-analysis-aggregations'
import {
  coverageAt,
  filterTeacherAnalysisRows,
  formatAnalysisPercent,
  formatPercentagePointMagnitude,
  formatPercentagePoints,
  inspectAnalysisCountAnomalies,
  isUsableVerifiedTaskPair,
  toAnalysisTasks,
  validAnalysisTasks,
  type VerifiedTaskPair,
} from '@/utils/teacher-analysis-aggregations'
import { taskProgressCount, teacherClassDisplayLabel } from '@/utils/teacher-task-progress'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import TeacherClassSelect from '@/components/teacher/TeacherClassSelect.vue'
import CoverageCurveChart from '@/components/teacher/analysis/CoverageCurveChart.vue'
import SlopeComparisonChart from '@/components/teacher/analysis/SlopeComparisonChart.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import {
  createTeacherAnalyticsDemoDataset,
  createTeacherAnalyticsDemoPairs,
} from '@/data/teacher-analytics-demo-fixture'

type AnalysisMode = 'comparison' | 'coverage'

const { state, rows: sourceRows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })
const analyticsDemo = isDemo ? createTeacherAnalyticsDemoDataset() : null
const rows = computed(() => analyticsDemo?.rows ?? sourceRows.value)
const mode = ref<AnalysisMode>('coverage')
let analysisCanvasResizeObserver: ResizeObserver | undefined
const selectedClass = ref('')
const comparisonClass = ref('')
const selectedPairKey = ref('')
const timeWindow = ref<AnalysisTimeWindow>('all')
const threshold = 75
const timeOptions: { value: AnalysisTimeWindow; label: string }[] = [
  { value: 'all', label: '全部时间' },
  { value: '30', label: '近 30 天' },
  { value: '90', label: '近 90 天' },
  { value: '365', label: '近一年' },
]

const syncAnalysisInspectorHeight = () => {
  analysisCanvasResizeObserver?.disconnect()
  analysisCanvasResizeObserver = undefined
  const page = document.querySelector<HTMLElement>('.teacher-analytics')
  const canvas = page?.querySelector<HTMLElement>('.analysis-canvas')
  const inspector = page?.querySelector<HTMLElement>('.analysis-inspector')
  if (!canvas || !inspector) return

  const syncHeight = () => {
    const height = canvas.getBoundingClientRect().height
    if (height > 0) inspector.style.setProperty('--analysis-canvas-height', `${height}px`)
  }

  syncHeight()
  analysisCanvasResizeObserver = new ResizeObserver(syncHeight)
  analysisCanvasResizeObserver.observe(canvas)
}

onBeforeUnmount(() => analysisCanvasResizeObserver?.disconnect())

const classRefs = computed(() => [...new Set(rows.value.map((row) => row.class_ref))]
  .sort((first, second) => first.localeCompare(second, 'zh-CN')))
const cleanVisibleLabel = (value: string) => value.replaceAll('\u00b7', '：')
const classOptions = computed(() => classRefs.value.map((classRef) => ({
  value: classRef,
  label: cleanVisibleLabel(teacherClassDisplayLabel(classRef, rows.value)),
})))
const comparisonOptions = computed(() => classOptions.value.filter((option) => option.value !== selectedClass.value))
const cleanTaskLabel = (label: string) => cleanVisibleLabel(label.replace(/\s*[（(]合成示例[）)]\s*$/, '').trim())
const selectedClassLabel = computed(() => cleanVisibleLabel(selectedClass.value
  ? teacherClassDisplayLabel(selectedClass.value, rows.value)
  : '观察班级'))
const comparisonClassLabel = computed(() => cleanVisibleLabel(comparisonClass.value
  ? teacherClassDisplayLabel(comparisonClass.value, rows.value)
  : '对照班级'))

const reconcileClasses = () => {
  const available = classRefs.value
  if (!available.includes(selectedClass.value)) selectedClass.value = available[0] ?? ''
  if (!available.includes(comparisonClass.value) || comparisonClass.value === selectedClass.value) {
    comparisonClass.value = available.find((classRef) => classRef !== selectedClass.value) ?? ''
  }
}
watch(classRefs, reconcileClasses, { immediate: true })
watch(selectedClass, (value) => {
  if (comparisonClass.value === value) {
    comparisonClass.value = classRefs.value.find((classRef) => classRef !== value) ?? ''
  }
})

const filteredRows = computed(() => filterTeacherAnalysisRows(rows.value, timeWindow.value))
watch([state, filteredRows], syncAnalysisInspectorHeight, { flush: 'post', immediate: true })
const analysisTasks = computed(() => toAnalysisTasks(filteredRows.value))
const validOverallTasks = computed(() => validAnalysisTasks(analysisTasks.value))
const selectedClassRows = computed(() => filteredRows.value.filter((row) => row.class_ref === selectedClass.value))
const selectedClassTasks = computed(() => toAnalysisTasks(selectedClassRows.value))
const validSelectedClassTasks = computed(() => validAnalysisTasks(selectedClassTasks.value))
const countAnomalies = computed(() => inspectAnalysisCountAnomalies(filteredRows.value))
const currentCoverage = computed(() => coverageAt(validSelectedClassTasks.value, threshold))
const overallCoverage = computed(() => coverageAt(validOverallTasks.value, threshold))
const coverageDifference = computed(() => currentCoverage.value && overallCoverage.value
  ? currentCoverage.value.percent - overallCoverage.value.percent
  : null)
const belowThresholdTasks = computed(() => validSelectedClassTasks.value
  .filter((task) => task.completionRate < threshold)
  .sort((first, second) => first.completionRate - second.completionRate
    || first.taskLabel.localeCompare(second.taskLabel, 'zh-CN')
    || first.taskRef.localeCompare(second.taskRef)))
const selectedZeroDenominatorCount = computed(() => selectedClassRows.value
  .filter((row) => taskProgressCount(row, 'active_enrollment_count') === 0).length)
const filteredDemoTaskKeys = computed(() => new Set(filteredRows.value.map((row) =>
  JSON.stringify([row.class_ref, row.task_ref]))))
const comparisonPairs = computed<VerifiedTaskPair[]>(() => {
  if (!isDemo || !analyticsDemo) return []

  const visibleAssignments = analyticsDemo.assignments.filter((assignment) =>
    filteredDemoTaskKeys.value.has(JSON.stringify([assignment.row.class_ref, assignment.row.task_ref])))
  return createTeacherAnalyticsDemoPairs(visibleAssignments, selectedClass.value, comparisonClass.value)
})
const usableComparisonPairs = computed(() => comparisonPairs.value.filter(isUsableVerifiedTaskPair))
const rejectedComparisonPairCount = computed(() => comparisonPairs.value.length - usableComparisonPairs.value.length)
const orderedComparisonPairs = computed(() => [...usableComparisonPairs.value]
  .sort((first, second) => Math.abs(second.differencePp) - Math.abs(first.differencePp)
    || first.taskLabel.localeCompare(second.taskLabel, 'zh-CN')))
const focusedComparisonPair = computed(() => orderedComparisonPairs.value.find((pair) => pair.key === selectedPairKey.value)
  ?? orderedComparisonPairs.value[0]
  ?? null)
const comparisonTaskColors = [
  'var(--color-primary-active)',
  'var(--color-chart-teal)',
  'var(--color-chart-blue)',
  'var(--color-chart-amber)',
  'var(--color-chart-sky)',
  'var(--color-chart-violet)',
  'var(--color-chart-rose)',
]
const comparisonTaskColor = (pairKey: string) => {
  const index = usableComparisonPairs.value.findIndex((pair) => pair.key === pairKey)
  return comparisonTaskColors[Math.max(0, index) % comparisonTaskColors.length]
}
watch(orderedComparisonPairs, (pairs) => {
  if (!pairs.some((pair) => pair.key === selectedPairKey.value)) {
    selectedPairKey.value = pairs[0]?.key ?? ''
  }
}, { immediate: true })

const swapDirection = ref(false)
const swapClasses = () => {
  if (!selectedClass.value || !comparisonClass.value) return
  const current = selectedClass.value
  selectedClass.value = comparisonClass.value
  comparisonClass.value = current
  swapDirection.value = !swapDirection.value
}
</script>

<template>
  <main class="teacher-analytics content-wrap">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="数据分析" />

    <AppCard class="analysis-filter-card">
      <div class="analysis-filter-heading">
        <div
          class="analysis-mode-switch"
          :class="{ 'analysis-mode-switch--coverage': mode === 'coverage' }"
          role="tablist"
          aria-label="数据分析模式"
        >
          <span class="analysis-mode-switch__thumb" aria-hidden="true"></span>
          <button
            id="analysis-tab-comparison"
            type="button"
            role="tab"
            :aria-selected="mode === 'comparison'"
            aria-controls="analysis-workspace-panel"
            @click="mode = 'comparison'"
          >
            双班对照
          </button>
          <button
            id="analysis-tab-coverage"
            type="button"
            role="tab"
            :aria-selected="mode === 'coverage'"
            aria-controls="analysis-workspace-panel"
            @click="mode = 'coverage'"
          >
            完成率覆盖
          </button>
        </div>
        <div class="analysis-filter-actions">
          <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh">刷新数据</AppButton>
        </div>
      </div>

      <div class="analysis-filter-grid" :class="{ 'analysis-filter-grid--comparison': mode === 'comparison' }">
        <div class="analysis-filter-field">
          <label for="analysis-class-a">{{ mode === 'comparison' ? '对照班级 A' : '观察班级' }}</label>
          <TeacherClassSelect
            id="analysis-class-a"
            v-model="selectedClass"
            :options="classOptions"
            aria-label="选择观察班级"
            :disabled="state !== 'ready' || !classOptions.length"
            searchable
          />
        </div>

        <button
          v-if="mode === 'comparison'"
          class="analysis-class-swap"
          :class="{ 'analysis-class-swap--reversed': swapDirection }"
          type="button"
          aria-label="交换观察班级和对照班级"
          title="交换班级"
          :disabled="!selectedClass || !comparisonClass"
          @click="swapClasses"
        >
          <span class="analysis-class-swap__arrow analysis-class-swap__arrow--top" aria-hidden="true">⟵</span>
          <span class="analysis-class-swap__arrow analysis-class-swap__arrow--bottom" aria-hidden="true">⟶</span>
        </button>

        <div v-if="mode === 'comparison'" class="analysis-filter-field">
          <label for="analysis-class-b">对照班级 B</label>
          <TeacherClassSelect
            id="analysis-class-b"
            v-model="comparisonClass"
            :options="comparisonOptions"
            aria-label="选择对照班级"
            :disabled="state !== 'ready' || !comparisonOptions.length"
            searchable
          />
        </div>

        <div class="analysis-filter-field">
          <label for="analysis-time-window">开放时间范围</label>
          <TeacherClassSelect
            id="analysis-time-window"
            v-model="timeWindow"
            :options="timeOptions"
            aria-label="选择开放时间范围"
            :disabled="state !== 'ready' || !rows.length"
          />
        </div>
      </div>
    </AppCard>

    <div v-if="state === 'loading'" class="analytics-state" aria-busy="true" aria-live="polite">正在读取任务汇总数据…</div>
    <div v-else-if="state === 'error'" class="analytics-state analytics-state--error" role="alert">
      <p>{{ cleanVisibleLabel(errorMessage) }}</p>
      <AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton>
    </div>
    <AppCard v-else-if="!rows.length" class="analytics-state" role="status">当前没有可用于分析的班级任务汇总</AppCard>
    <AppCard v-else-if="!filteredRows.length" class="analytics-state" role="status">
      所选开放时间范围内没有任务汇总记录，请调整筛选范围
    </AppCard>

    <AppCard
      v-else
      id="analysis-workspace-panel"
      class="analysis-workspace-card"
      role="tabpanel"
      :aria-labelledby="mode === 'comparison' ? 'analysis-tab-comparison' : 'analysis-tab-coverage'"
    >
      <p
        v-if="countAnomalies.completedAboveActiveCount || countAnomalies.completedWithNoActiveCount"
        class="analysis-data-quality-note"
        role="status"
      >
        <strong>任务计数需核对</strong>
        <span v-if="countAnomalies.completedAboveActiveCount">
          {{ countAnomalies.completedAboveActiveCount }} 项已完成人次超过有效报名人次；当前仍按既有口径将完成率上限计为 100%，并纳入可统计任务
        </span>
        <span v-if="countAnomalies.completedWithNoActiveCount">
          {{ countAnomalies.completedWithNoActiveCount }} 项分母为 0 但存在已完成人次；当前仍从覆盖率中排除
        </span>
        <span>请核对汇总数据</span>
      </p>
      <div class="analysis-workspace">
        <section class="analysis-canvas">
          <header class="analysis-canvas-heading">
            <h1>{{ mode === 'comparison' ? '班级完成差异' : '任务完成率覆盖' }}</h1>
          </header>

          <template v-if="mode === 'comparison'">
            <div v-if="usableComparisonPairs.length" class="comparison-chart-region">
              <SlopeComparisonChart
                :pairs="usableComparisonPairs"
                :selected-pair-key="selectedPairKey"
                @select="selectedPairKey = $event"
              />
            </div>
            <div v-else-if="!comparisonClass" class="analysis-empty-state analysis-empty-state--comparison" role="group" aria-labelledby="comparison-empty-title">
              <div class="analysis-empty-mark" aria-hidden="true"><span>A</span><i></i><span>B</span></div>
              <h2 id="comparison-empty-title">需要至少两个授权班级</h2>
              <p>当前授权范围内只有一个班级，暂时不能进行双班对照</p>
              <AppButton variant="secondary" size="sm" @click="mode = 'coverage'">查看完成率覆盖</AppButton>
            </div>
            <div v-else class="analysis-empty-state analysis-empty-state--comparison" role="group" aria-labelledby="comparison-empty-title">
              <div class="analysis-empty-mark" aria-hidden="true"><span>A</span><i></i><span>B</span></div>
              <h2 id="comparison-empty-title">暂无可比较的共同任务</h2>
              <p>当前数据缺少经过验证的共同任务定义与版本关联。</p>
              <p v-if="rejectedComparisonPairCount" class="analysis-empty-state__detail">
                {{ rejectedComparisonPairCount }} 条配对数据未通过计数校验，未绘图，请核对来源
              </p>
              <AppButton variant="secondary" size="sm" @click="mode = 'coverage'">查看完成率覆盖</AppButton>
            </div>
          </template>

          <template v-else>
            <div v-if="validOverallTasks.length" class="coverage-chart-region">
              <div class="coverage-legend" aria-label="图例">
                <span><i class="coverage-legend__current" aria-hidden="true"></i>{{ selectedClassLabel }}</span>
                <span><i class="coverage-legend__overall" aria-hidden="true"></i>全部授权班级（含本班）</span>
              </div>
              <CoverageCurveChart
                :current-tasks="validSelectedClassTasks"
                :overall-tasks="validOverallTasks"
                :current-class-label="selectedClassLabel"
                :threshold="threshold"
              />
            </div>
            <div v-else class="analysis-empty-state coverage-empty-state" role="status">
              <h2>当前范围没有可计算的任务</h2>
              <p>有效报名人次为 0 的班级—任务组合不计入可统计任务分母</p>
            </div>

          </template>
        </section>

        <aside class="analysis-inspector" aria-live="polite">
          <template v-if="mode === 'comparison'">
            <section v-if="focusedComparisonPair" class="inspector-focus">
              <div class="inspector-focus__lead">
                <div>
                  <span>{{ selectedPairKey ? '当前任务差异' : '最大任务差异' }}</span>
                  <strong>{{ formatPercentagePointMagnitude(Math.abs(focusedComparisonPair.differencePp)) }}</strong>
                </div>
                  <b>{{ cleanTaskLabel(focusedComparisonPair.taskLabel) }}</b>
              </div>
              <div class="inspector-focus__values">
                <div>
                  <span><i class="comparison-class-key comparison-class-key--a" aria-hidden="true"></i>A：{{ selectedClassLabel }}</span>
                  <strong>{{ formatAnalysisPercent(focusedComparisonPair.classA.completionRate) }}</strong>
                </div>
                <span class="inspector-focus__arrow" aria-hidden="true">→</span>
                <div>
                  <span><i class="comparison-class-key comparison-class-key--b" aria-hidden="true"></i>B：{{ comparisonClassLabel }}</span>
                  <strong>{{ formatAnalysisPercent(focusedComparisonPair.classB.completionRate) }}</strong>
                </div>
              </div>
            </section>
            <section v-if="orderedComparisonPairs.length" class="comparison-pairs">
              <div class="comparison-pairs__heading">
                <h2>共同任务</h2>
                <button
                  type="button"
                  class="comparison-pairs__all"
                  :aria-pressed="!selectedPairKey"
                  @click="selectedPairKey = ''"
                >
                  全部
                </button>
              </div>
              <div class="comparison-pairs__series-legend" aria-label="班级完成率图例">
                <span><i class="comparison-class-key comparison-class-key--a" aria-hidden="true"></i>A：{{ selectedClassLabel }}</span>
                <span><i class="comparison-class-key comparison-class-key--b" aria-hidden="true"></i>B：{{ comparisonClassLabel }}</span>
              </div>
              <ul
                class="comparison-pairs__list"
                tabindex="0"
                aria-label="共同任务完成率差异列表，可使用滚轮或方向键浏览"
              >
                <li v-for="pair in orderedComparisonPairs" :key="pair.key">
                  <button
                    type="button"
                    :style="{ '--task-color': comparisonTaskColor(pair.key) }"
                    :aria-pressed="selectedPairKey === pair.key"
                    :class="{ 'is-selected': selectedPairKey === pair.key }"
                    @click="selectedPairKey = pair.key"
                  >
                    <span class="comparison-pair__heading">
                      <i aria-hidden="true"></i>
                      <strong>{{ cleanTaskLabel(pair.taskLabel) }}</strong>
                      <b>{{ formatPercentagePoints(pair.differencePp) }}</b>
                    </span>
                    <span class="comparison-pair__rate">
                      <span>A</span>
                      <span class="comparison-pair__track" aria-hidden="true"><i class="comparison-pair__track-fill comparison-pair__track-fill--a" :style="{ width: pair.classA.completionRate + '%' }"></i></span>
                      <strong>{{ formatAnalysisPercent(pair.classA.completionRate) }}</strong>
                    </span>
                    <span class="comparison-pair__rate">
                      <span>B</span>
                      <span class="comparison-pair__track" aria-hidden="true"><i class="comparison-pair__track-fill comparison-pair__track-fill--b" :style="{ width: pair.classB.completionRate + '%' }"></i></span>
                      <strong>{{ formatAnalysisPercent(pair.classB.completionRate) }}</strong>
                    </span>
                  </button>
                </li>
              </ul>
            </section>
            <p v-else class="inspector-empty">暂无共同任务可供对比</p>
          </template>

          <template v-else>
            <section class="coverage-kpi" aria-label="本班任务覆盖率">
              <div class="coverage-kpi__topline">
                <span>达到 {{ threshold }}% 观察线的任务</span>
                <strong>{{ currentCoverage ? formatAnalysisPercent(currentCoverage.percent) : '—' }}</strong>
              </div>
              <div class="coverage-kpi__count">
                <b v-if="currentCoverage">{{ currentCoverage.reachedCount }}<small> / {{ currentCoverage.totalCount }}</small></b>
                <b v-else>—</b>
                <span>项达到门槛</span>
              </div>
              <div class="coverage-kpi__track" aria-hidden="true">
                <span :style="{ width: (currentCoverage?.percent ?? 0) + '%' }"></span>
              </div>
            </section>

            <dl class="coverage-summary">
              <div>
                <dt>全部授权班级</dt>
                <dd>{{ overallCoverage ? formatAnalysisPercent(overallCoverage.percent) : '—' }}</dd>
              </div>
              <div>
                <dt>与整体差距</dt>
                <dd>{{ coverageDifference === null ? '—' : formatPercentagePoints(coverageDifference) }}</dd>
              </div>
              <div>
                <dt>可统计任务</dt>
                <dd>{{ currentCoverage ? currentCoverage.totalCount : 0 }} / {{ overallCoverage ? overallCoverage.totalCount : 0 }}</dd>
              </div>
            </dl>

            <section class="below-threshold">
              <div class="below-threshold__heading">
                <div>
                  <h2>低于观察线</h2>
                </div>
                <span>{{ belowThresholdTasks.length }}</span>
              </div>

              <p v-if="!currentCoverage" class="inspector-empty">本班没有有效报名任务，暂时无法计算</p>
              <p v-else-if="!belowThresholdTasks.length" class="inspector-empty">本班所有可统计任务均达到当前观察线</p>
              <ul v-else class="below-threshold__list">
                <li
                  v-for="task in belowThresholdTasks"
                  :key="task.key"
                  :aria-label="`${cleanTaskLabel(task.taskLabel)}：完成率 ${formatAnalysisPercent(task.completionRate)}，${task.completedCount} / ${task.activeCount} 人次已完成`"
                >
                  <div class="below-threshold__row">
                    <strong>{{ cleanTaskLabel(task.taskLabel) }}</strong>
                    <b>{{ formatAnalysisPercent(task.completionRate) }}</b>
                  </div>
                  <div class="task-rate-track" aria-hidden="true">
                    <span :style="{ width: task.completionRate + '%' }"></span>
                  </div>
                </li>
              </ul>

              <p v-if="selectedZeroDenominatorCount" class="excluded-note">
                本班另有 {{ selectedZeroDenominatorCount }} 个有效报名为 0 的班级—任务组合，未纳入可统计任务分母
              </p>
            </section>
          </template>
        </aside>
      </div>
    </AppCard>

  </main>
</template>

<style scoped>
.teacher-analytics { display: grid; gap: 14px; padding-top: 0; padding-bottom: 35px; animation: analytics-enter 220ms ease both; min-width: 0; }
.analysis-mode-switch { position: relative; isolation: isolate; display: grid; width: min(100%, 260px); grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; padding: 4px; border: 1px solid var(--color-border); border-radius: 9px; background: var(--color-surface-soft); }
.analysis-mode-switch__thumb { position: absolute; z-index: 0; top: 4px; bottom: 4px; left: 4px; width: calc(50% - 4px); border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface); box-shadow: 0 1px 3px rgb(31 63 78 / 10%); transition: transform 340ms cubic-bezier(.16,1,.3,1); will-change: transform; }
.analysis-mode-switch--coverage .analysis-mode-switch__thumb { transform: translateX(100%); }
.analysis-mode-switch button { position: relative; z-index: 1; display: inline-flex; min-width: 0; min-height: 34px; align-items: center; justify-content: center; padding: 0 10px; border: 0; border-radius: 7px; color: var(--color-text-muted); background: transparent; font: inherit; font-size: 13px; font-weight: 600; white-space: nowrap; cursor: pointer; transition: color 220ms ease; }
.analysis-mode-switch button[aria-selected="true"] { color: var(--color-primary-active); font-weight: 700; }
.analysis-mode-switch button:focus-visible,.analysis-class-swap:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.analysis-filter-card { padding: 18px 20px; }
.analysis-filter-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 15px; }
.analysis-filter-actions { display: flex; min-width: 0; align-items: center; justify-content: flex-end; gap: 14px; }
.analysis-filter-grid { display: grid; grid-template-columns: repeat(2, minmax(220px, 320px)); gap: 14px; align-items: end; justify-content: start; }
.analysis-filter-grid--comparison { grid-template-columns: minmax(0, 1fr) 42px minmax(0, 1fr) minmax(190px, .72fr); }
.analysis-filter-field { display: grid; gap: 6px; min-width: 0; }
.analysis-filter-field > label { color: var(--color-text-muted); font-size: 11px; font-weight: 600; }
.analysis-filter-field :deep(.teacher-class-select__trigger) { min-width: 0; min-height: 38px; border-radius: var(--radius-button); font-size: 11px; }
.analysis-class-swap { display: flex; width: 42px; height: 38px; flex-direction: column; align-items: center; justify-content: center; gap: 0; padding: 0; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-primary-active); background: var(--color-surface); cursor: pointer; transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease, color var(--motion-fast) ease; }
.analysis-class-swap__arrow { display: block; width: 25px; height: 12px; font-size: 17px; font-weight: 600; line-height: 12px; transition: transform 300ms cubic-bezier(.16,1,.3,1); }
.analysis-class-swap--reversed .analysis-class-swap__arrow { transform: scaleX(-1); }
.analysis-class-swap:hover:not(:disabled) { border-color: var(--color-primary); background: var(--color-surface-blue); }
.analysis-class-swap:disabled { color: var(--color-text-muted); cursor: not-allowed; opacity: .5; }
.analytics-state { display: flex; min-height: 130px; align-items: center; justify-content: center; gap: 14px; padding: 20px; color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 13px; text-align: center; }
.analytics-state--error { justify-content: space-between; color: var(--color-attention); background: var(--color-attention-wash); text-align: left; }
.analytics-state--error p { margin: 0; }
.analysis-workspace-card.app-card { min-width: 0; padding: 0; overflow: visible; background: transparent; box-shadow: none; }
.analysis-workspace { display: grid; min-width: 0; grid-template-columns: minmax(0, 1.8fr) minmax(290px, .95fr); align-items: start; gap: 14px; }
.analysis-canvas { min-width: 0; padding: 20px 21px 18px; border-radius: var(--radius-card); background: var(--color-surface); box-shadow: var(--shadow-rest); }
.analysis-canvas-heading { display: flex; align-items: center; justify-content: flex-start; gap: 18px; margin-bottom: 15px; }
.analysis-canvas-heading h1 { margin: 0; color: var(--color-text-primary); font-size: 20px; line-height: 1.3; }
.analysis-data-quality-note { display: grid; gap: 4px; margin: 0 0 14px; padding: 11px 13px; border: 1px solid color-mix(in srgb, var(--color-attention) 24%, transparent); border-radius: 9px; color: var(--color-text-secondary); background: var(--color-attention-wash); font-size: 12px; line-height: 1.55; }
.analysis-data-quality-note strong { color: var(--color-attention); font-size: 12px; }
.analysis-empty-state { display: flex; min-height: 245px; flex-direction: column; align-items: center; justify-content: center; padding: 24px; border: 1px dashed var(--color-border-strong); border-radius: var(--radius-card); background: linear-gradient(135deg, var(--color-surface-soft), var(--color-surface-blue)); text-align: center; }
.analysis-empty-state--comparison { min-height: 218px; padding: 20px; }
.analysis-empty-state--comparison button { margin-top: 11px; }
.analysis-empty-state__detail { color: var(--color-attention) !important; }
.analysis-empty-state h2 { margin: 12px 0 5px; color: var(--color-text-primary); font-size: 15px; }
.analysis-empty-state p { max-width: 460px; margin: 0; color: var(--color-text-muted); font-size: 12px; line-height: 1.65; }
.analysis-empty-mark { display: flex; align-items: center; gap: 9px; color: var(--color-text-secondary); font-size: 13px; font-weight: 700; }
.analysis-empty-mark span { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid var(--color-border-strong); border-radius: 50%; color: var(--color-primary-active); background: var(--color-surface); }
.analysis-empty-mark i { width: 30px; border-top: 1px dashed var(--color-border-strong); }
.coverage-chart-region { display: grid; min-width: 0; gap: 14px; }
.comparison-chart-region { min-width: 0; }
.comparison-inspector__heading { margin-bottom: 13px; }
.inspector-focus { padding: 14px; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); }
.inspector-focus__lead { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.inspector-focus__lead > div { display: grid; min-width: 0; gap: 3px; }
.inspector-focus__lead > div > span { color: var(--color-text-muted); font-size: 12px; }
.inspector-focus__lead strong { color: var(--color-primary-active); font-size: 30px; font-weight: 750; line-height: 1.1; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
.inspector-focus__lead > b { max-width: 52%; padding: 6px 9px; border-radius: 8px; color: var(--color-text-secondary); background: var(--color-surface-blue); font-size: 12px; font-weight: 650; line-height: 1.35; text-align: right; overflow-wrap: anywhere; }
.inspector-focus__values { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) 22px minmax(0, 1fr); align-items: center; gap: 8px; margin-top: 12px; padding-top: 11px; border-top: 1px solid var(--color-border); }
.inspector-focus__values > div { display: grid; min-width: 0; gap: 5px; }
.inspector-focus__values > div:first-child { justify-items: end; text-align: right; }
.inspector-focus__values > div > span { display: flex; min-width: 0; align-items: center; gap: 6px; overflow: hidden; color: var(--color-text-muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.inspector-focus__values > div:first-child > span { justify-content: flex-end; }
.inspector-focus__values strong { color: var(--color-text-primary); font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.inspector-focus__arrow { position: relative; left: -2px; color: var(--color-text-muted); font-size: 16px; text-align: center; }
.comparison-class-key { display: inline-block; width: 9px; height: 9px; flex: 0 0 9px; border-radius: 50%; }
.comparison-class-key--a { background: var(--color-primary-active); }
.comparison-class-key--b { background: var(--color-chart-sky); }
.comparison-pairs { display: flex; min-height: 0; flex: 1 1 auto; flex-direction: column; margin-top: 13px; }
.comparison-pairs__heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.comparison-pairs h2 { margin: 0; color: var(--color-text-primary); font-size: 15px; font-weight: 700; }
.comparison-pairs__all { min-height: 30px; padding: 0 11px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-secondary); background: var(--color-surface); font: inherit; font-size: 12px; font-weight: 600; cursor: pointer; transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease, background var(--motion-fast) ease; }
.comparison-pairs__all:hover,.comparison-pairs__all[aria-pressed="true"] { border-color: var(--color-primary); color: var(--color-primary-active); background: var(--color-surface-blue); }
.comparison-pairs__all:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.comparison-pairs__series-legend { display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 10px 0 7px; color: var(--color-text-secondary); font-size: 11px; }
.comparison-pairs__series-legend span { display: inline-flex; min-width: 0; align-items: center; gap: 6px; }
.comparison-pairs__list { display: grid; min-height: 0; flex: 1 1 0; gap: 7px; overflow-y: auto; overscroll-behavior-y: contain; scroll-behavior: smooth; scroll-snap-type: y proximity; margin: 0; padding: 2px 3px 2px 0; list-style: none; scrollbar-width: none; }
.comparison-pairs__list::-webkit-scrollbar { display: none; }
.comparison-pairs__list li { min-width: 0; scroll-snap-align: start; scroll-margin-block: 3px; }
.comparison-pairs__list:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; border-radius: 9px; }
.comparison-pairs__list button { display: grid; width: 100%; gap: 7px; padding: 10px 11px; border: 1px solid var(--color-border); border-radius: 10px; color: var(--color-text-secondary); background: var(--color-surface); text-align: left; cursor: pointer; transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.comparison-pairs__list button:hover,.comparison-pairs__list button.is-selected { border-color: var(--task-color); background: var(--color-surface); box-shadow: 0 0 0 2px color-mix(in srgb, var(--task-color) 12%, transparent); }
.comparison-pairs__list button:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.comparison-pair__heading { display: grid; min-width: 0; grid-template-columns: 9px minmax(0, 1fr) auto; align-items: center; gap: 7px; }
.comparison-pair__heading > i { width: 9px; height: 9px; border-radius: 50%; background: var(--task-color); }
.comparison-pair__heading > strong { overflow: hidden; color: var(--color-text-primary); font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.comparison-pair__heading > b { color: var(--color-primary-active); font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.comparison-pair__rate { display: grid; grid-template-columns: 12px minmax(0, 1fr) 45px; align-items: center; gap: 8px; color: var(--color-text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.comparison-pair__rate > strong { color: var(--color-text-secondary); font-size: 12px; font-weight: 650; text-align: right; }
.comparison-pair__track { height: 6px; overflow: hidden; border-radius: 99px; background: var(--color-surface-muted); }
.comparison-pair__track-fill { display: block; height: 100%; border-radius: inherit; transition: width var(--motion-normal) ease; }
.comparison-pair__track-fill--a { background: var(--color-primary-active); }
.comparison-pair__track-fill--b { background: var(--color-chart-sky); }
.coverage-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; margin: 0 0 0 10px; color: var(--color-text-secondary); font-size: 12px; }
.coverage-legend span { display: inline-flex; align-items: center; gap: 6px; }
.coverage-legend i { display: inline-block; width: 19px; height: 3px; border-radius: 99px; }
.coverage-legend__current { background: var(--color-primary-active); }
.coverage-legend__overall { height: 0 !important; border-top: 2px dashed var(--color-sidebar-label); }
.coverage-empty-state { min-height: 230px; }
.analysis-inspector { display: flex; min-width: 0; min-height: 0; height: var(--analysis-canvas-height, auto); flex-direction: column; overflow: hidden; padding: 18px 18px 16px; border-radius: var(--radius-card); background: var(--color-surface-soft); box-shadow: var(--shadow-rest); }
.inspector-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 18px; }
.inspector-heading > span { color: var(--color-text-primary); font-size: 15px; font-weight: 720; }
.inspector-heading small { color: var(--color-text-muted); font-size: 12px; text-align: right; }
.coverage-kpi { display: grid; gap: 5px; padding: 12px 13px 11px; border: 1px solid var(--color-border); border-radius: 11px; background: var(--color-surface); }
.coverage-kpi__topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.coverage-kpi__topline > span,.coverage-kpi__count > span { color: var(--color-text-muted); font-size: 11px; }
.coverage-kpi__topline > strong { color: var(--color-primary-active); font-size: 14px; font-weight: 750; font-variant-numeric: tabular-nums; }
.coverage-kpi__count { display: flex; align-items: baseline; gap: 8px; }
.coverage-kpi__count > b { color: var(--color-text-primary); font-size: 24px; font-weight: 750; line-height: 1.05; font-variant-numeric: tabular-nums; }
.coverage-kpi__count > b small { color: var(--color-text-muted); font-size: 14px; font-weight: 550; }
.coverage-kpi__track { height: 6px; overflow: hidden; margin-top: 3px; border-radius: 99px; background: var(--color-surface-muted); }
.coverage-kpi__track > span { display: block; height: 100%; border-radius: inherit; background: var(--color-primary-active); transition: width var(--motion-normal) ease; }
.coverage-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin: 7px 0 0; }
.coverage-summary > div { display: grid; min-width: 0; min-height: 62px; align-content: start; gap: 5px; padding: 8px; border: 1px solid var(--color-border); border-radius: 9px; background: var(--color-surface); }
.coverage-summary dt { color: var(--color-text-muted); font-size: 11px; line-height: 1.3; }
.coverage-summary dd { margin: 0; color: var(--color-text-primary); font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.below-threshold { display: flex; min-height: 0; flex: 1 1 auto; flex-direction: column; margin-top: 12px; }
.below-threshold__heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.below-threshold__heading h2 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.below-threshold__heading > span { display: grid; min-width: 27px; height: 27px; place-items: center; padding: 0 6px; border-radius: 999px; color: var(--color-primary-active); background: #e6f6f9; font-size: 12px; font-weight: 700; }
.below-threshold__list { display: grid; min-height: 0; flex: 1 1 auto; gap: 0; overflow-y: auto; overscroll-behavior-y: contain; margin: 6px 0 0; padding: 0; list-style: none; scrollbar-width: none; }
.below-threshold__list::-webkit-scrollbar { display: none; }
.below-threshold__list li { padding: 6px 0; border-bottom: 1px solid var(--color-border); }
.below-threshold__row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.below-threshold__row strong { overflow: hidden; color: var(--color-text-secondary); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.below-threshold__row b { flex: 0 0 auto; color: var(--color-primary-active); font-size: 12px; }
.task-rate-track { height: 4px; overflow: hidden; margin-top: 5px; border-radius: 99px; background: var(--color-surface-muted); }
.task-rate-track span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--color-primary-hover), var(--color-primary-active)); transition: width var(--motion-normal) ease; }
.inspector-empty { margin: 11px 0 0; padding: 12px; border-radius: 9px; color: var(--color-text-muted); background: #f0f6f8; font-size: 12px; line-height: 1.55; }
.excluded-note { margin: 10px 0 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.5; }
@keyframes analytics-enter { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 1100px) {
  .analysis-filter-grid:not(.analysis-filter-grid--comparison) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .analysis-filter-grid--comparison { grid-template-columns: minmax(0, 1fr) 38px minmax(0, 1fr); }
  .analysis-filter-grid--comparison .analysis-filter-field:last-child { grid-column: 1 / -1; }
  .analysis-workspace { grid-template-columns: minmax(0, 1fr); }
  .analysis-inspector { height: auto; border-top: 0; border-left: 0; overflow: visible; }
  .comparison-pairs { flex: initial; }
  .comparison-pairs__list { max-height: none; flex: initial; overflow: visible; scroll-snap-type: none; }
  .below-threshold { flex: initial; }
  .below-threshold__list { flex: initial; overflow: visible; }
}
@media (max-width: 680px) {
  .analysis-filter-card { padding: 16px; }
  .analysis-filter-heading { align-items: stretch; flex-direction: column; gap: 10px; }
  .analysis-mode-switch { width: 100%; max-width: 260px; }
  .analysis-filter-actions { width: 100%; justify-content: flex-end; gap: 8px; }
  .analysis-filter-grid,.analysis-filter-grid--comparison { grid-template-columns: minmax(0, 1fr); }
  .analysis-filter-grid:not(.analysis-filter-grid--comparison) { grid-template-columns: minmax(0, 1fr); }
  .analysis-filter-grid--comparison .analysis-filter-field:last-child { grid-column: auto; }
  .analysis-class-swap { width: 42px; height: 38px; justify-self: center; }
  .analysis-canvas { padding: 17px 14px 14px; }
  .analysis-canvas-heading { align-items: flex-start; }
  .analysis-canvas-heading h1 { font-size: 19px; }
  .analysis-workspace-card.app-card { overflow: visible; }
  .analysis-inspector { height: auto; padding: 16px 15px; }
  .analysis-empty-state--comparison { min-height: 190px; }
}
@media (prefers-reduced-motion: reduce) {
  .teacher-analytics,.analysis-mode-switch__thumb,.analysis-mode-switch button,.analysis-class-swap,.analysis-class-swap__arrow,.coverage-kpi__track > span,.task-rate-track span,.comparison-pair__track-fill,.comparison-pairs__list button,.comparison-pairs__all { animation: none !important; transition: none !important; }
  .comparison-pairs__list { scroll-behavior: auto; scroll-snap-type: none; }
}
</style>
