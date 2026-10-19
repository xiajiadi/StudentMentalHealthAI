<script setup lang="ts">
/* global HTMLCanvasElement, HTMLButtonElement, CanvasRenderingContext2D, performance, MediaQueryListEvent */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { SchoolClass, SchoolMember, SchoolOperationsAuditEvent } from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { readDependencyHealth } from '@/views/admin/health'
import type { EChartsOption } from 'echarts/core'
import AdminCommandPalette from './AdminCommandPalette.vue'
import AdminWorkspaceDrawer from './AdminWorkspaceDrawer.vue'
import AdminWorkspaceFolder from './AdminWorkspaceFolder.vue'
import type { AdminPreviewSummary, AdminPreviewState, FolderOrigin, FolderOrigins } from './admin-workspace-preview'
import {
  adminWorkspaceActions,
  adminWorkspaceFolders,
  getFolderActions,
  type AdminWorkspaceAction,
  type AdminFolderId,
  type AdminWorkspaceFolder as WorkspaceFolder,
} from './admin-workspace-actions'

const router = useRouter()
const activeFolderId = ref<AdminFolderId | null>(null)
const stackedFolderId = ref<AdminFolderId | null>(null)
const drawerOpen = ref(false)
const drawerClosing = ref(false)
const previewState = ref<AdminPreviewState>('loading')
const previewSummary = ref<AdminPreviewSummary | null>(null)
const previewError = ref('')
const previewOrigin = ref<FolderOrigin | null>(null)
const previewPaperOrigins = ref<FolderOrigins>([])
const previewPaperIndex = ref(2)
const fieldRoot = ref<HTMLElement | null>(null)
const dotCanvas = ref<HTMLCanvasElement | null>(null)
const sourceElement = ref<HTMLButtonElement | null>(null)
let previewRequestGeneration = 0
let closeTimer: number | undefined
let closeAfterAnimation: (() => void) | undefined
let previewScrollPosition = { x: 0, y: 0 }

type Dot = { x: number; y: number; phase: number }

let dots: Dot[] = []
let dotContext: CanvasRenderingContext2D | null = null
let fieldWidth = 0
let fieldHeight = 0
let pixelRatio = 1
let pointerX = 0
let pointerY = 0
let pointerActive = false
let pointerExitedAt = 0
let animationFrame = 0
let reducedMotion = false
let resizeObserver: ResizeObserver | null = null
let resizeFallbackActive = false
let motionPreference: MediaQueryList | null = null

const seededPhase = (x: number, y: number) => {
  const value = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453
  return (value - Math.floor(value)) * Math.PI * 2
}

const scheduleDotFrame = () => {
  if (!animationFrame && !reducedMotion) {
    animationFrame = window.requestAnimationFrame((now) => {
      animationFrame = 0
      drawDots(now)
    })
  }
}

const drawDots = (now = performance.now()) => {
  const context = dotContext
  if (!context) return

  context.clearRect(0, 0, fieldWidth, fieldHeight)
  const fade = pointerActive ? 1 : pointerExitedAt ? Math.max(0, 1 - (now - pointerExitedAt) / 680) : 0
  const radius = 142

  for (const dot of dots) {
    let proximity = 0
    let x = dot.x
    let y = dot.y

    if (fade > 0) {
      const dx = dot.x - pointerX
      const dy = dot.y - pointerY
      const distance = Math.hypot(dx, dy)
      proximity = Math.max(0, 1 - distance / radius) * fade

      if (proximity > 0) {
        const angle = distance > 0 ? Math.atan2(dy, dx) : dot.phase
        const wave = Math.sin(distance * 0.028 - now * 0.0021 + dot.phase)
        const orbit = Math.cos(now * 0.00135 + dot.phase)
        const radial = wave * 2.8 * proximity
        const tangent = orbit * 1.7 * proximity
        x += Math.cos(angle) * radial - Math.sin(angle) * tangent
        y += Math.sin(angle) * radial + Math.cos(angle) * tangent
      }
    }

    context.beginPath()
    context.fillStyle = `rgba(180, 211, 221, ${0.72 + proximity * 0.24})`
    context.arc(x, y, 0.85 + proximity * 0.55, 0, Math.PI * 2)
    context.fill()
  }

  if (!reducedMotion && (pointerActive || fade > 0)) {
    scheduleDotFrame()
  } else if (!pointerActive) {
    pointerExitedAt = 0
  }
}

const resizeDotCanvas = () => {
  const canvas = dotCanvas.value
  const field = fieldRoot.value
  if (!canvas || !field) return

  const bounds = field.getBoundingClientRect()
  fieldWidth = bounds.width
  fieldHeight = bounds.height
  pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(fieldWidth * pixelRatio)
  canvas.height = Math.round(fieldHeight * pixelRatio)
  dotContext = canvas.getContext('2d')
  dotContext?.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)

  const spacing = typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 720px)').matches ? 26 : 30
  dots = []
  let row = 0
  for (let y = 12; y < fieldHeight; y += spacing, row += 1) {
    for (let x = 12; x < fieldWidth; x += spacing) {
      dots.push({ x, y, phase: seededPhase(x, y + row * 0.37) })
    }
  }
  drawDots()
}

const onFieldPointerMove = (event: PointerEvent) => {
  if (reducedMotion || event.pointerType === 'touch') return
  const bounds = fieldRoot.value?.getBoundingClientRect()
  if (!bounds) return
  pointerX = event.clientX - bounds.left
  pointerY = event.clientY - bounds.top
  pointerActive = true
  pointerExitedAt = 0
  scheduleDotFrame()
}

const onFieldPointerLeave = () => {
  if (reducedMotion || !pointerActive) return
  pointerActive = false
  pointerExitedAt = performance.now()
  scheduleDotFrame()
}

const onMotionPreferenceChange = (event: MediaQueryListEvent) => {
  reducedMotion = event.matches
  if (reducedMotion) {
    pointerActive = false
    pointerExitedAt = 0
    if (animationFrame) window.cancelAnimationFrame(animationFrame)
    animationFrame = 0
  }
  drawDots()
}

onMounted(() => {
  const field = fieldRoot.value
  if (!field) return

  if (typeof window.matchMedia === 'function') {
    motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotion = motionPreference.matches
    motionPreference.addEventListener('change', onMotionPreferenceChange)
  }
  field.addEventListener('pointermove', onFieldPointerMove, { passive: true })
  field.addEventListener('pointerleave', onFieldPointerLeave, { passive: true })
  if (typeof ResizeObserver === 'function') {
    resizeObserver = new ResizeObserver(resizeDotCanvas)
    resizeObserver.observe(field)
  } else {
    window.addEventListener('resize', resizeDotCanvas)
    resizeFallbackActive = true
  }
  resizeDotCanvas()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeFallbackActive) window.removeEventListener('resize', resizeDotCanvas)
  resizeFallbackActive = false
  motionPreference?.removeEventListener('change', onMotionPreferenceChange)
  motionPreference = null
  fieldRoot.value?.removeEventListener('pointermove', onFieldPointerMove)
  fieldRoot.value?.removeEventListener('pointerleave', onFieldPointerLeave)
  if (animationFrame) window.cancelAnimationFrame(animationFrame)
  animationFrame = 0
  if (closeTimer !== undefined) window.clearTimeout(closeTimer)
  closeAfterAnimation = undefined
  previewScrollPosition = { x: 0, y: 0 }
  previewRequestGeneration += 1
})

const activeFolder = computed(() => adminWorkspaceFolders.find((folder) => folder.id === activeFolderId.value) ?? null)
const currentActions = computed(() => getFolderActions(activeFolder.value))

const formatCount = (value: number) => new Intl.NumberFormat('zh-CN').format(Math.max(0, Number.isFinite(value) ? value : 0))

const isLocalAdminPreview = () => import.meta.env.DEV
  && typeof window !== 'undefined'
  && ['127.0.0.1', 'localhost'].includes(window.location.hostname)
  && window.location.port === '4206'

const loadAdminOverviewDemoData = async () => {
  const { createAdminOverviewDemoData } = await import('@/data/admin-overview-demo-data')
  return createAdminOverviewDemoData()
}

const adminTooltipStyle = {
  backgroundColor: 'rgba(255, 255, 255, 0.98)',
  borderColor: '#dce8ed',
  borderWidth: 1,
  borderRadius: 10,
  confine: true,
  padding: [10, 12],
  textStyle: {
    color: '#6f8191',
    fontFamily: 'var(--font-sans)',
    fontSize: 13,
    fontWeight: 400,
    lineHeight: 20,
  },
  extraCssText: 'box-shadow: 0 8px 22px rgba(52, 80, 96, 0.14);',
}

const chartShadowPointer = {
  type: 'shadow' as const,
  shadowStyle: {
    shadowBlur: 8,
    shadowColor: 'rgba(52, 80, 96, 0.08)',
    color: 'rgba(117, 132, 142, 0.13)',
  },
}

const makeHorizontalChart = (labels: string[], values: number[], color = '#00a1c5'): EChartsOption => ({
  animation: !reducedMotion,
  animationDuration: 420,
  grid: { left: 8, right: 30, top: 10, bottom: 10, containLabel: true },
  tooltip: { ...adminTooltipStyle, trigger: 'axis', axisPointer: chartShadowPointer },
  xAxis: {
    type: 'value',
    min: 0,
    axisLabel: { color: '#8295a0', fontSize: 10 },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: '#e8eef1' } },
  },
  yAxis: {
    type: 'category',
    data: labels,
    axisLabel: { color: '#536a78', fontSize: 11 },
    axisLine: { show: false },
    axisTick: { show: false },
  },
  series: [{
    type: 'bar',
    data: values,
    barMaxWidth: 19,
    showBackground: true,
    backgroundStyle: { color: '#eff3f5', borderRadius: 6 },
    itemStyle: { color, borderRadius: 6 },
    emphasis: { focus: 'series', itemStyle: { color: '#16a5bf' } },
    label: { show: true, position: 'right', color: '#536a78', fontSize: 11, formatter: '{c}' },
  }],
})

const makeClassChart = (classes: Array<{ label: string; students: number; teachers: number }>): EChartsOption => ({
  animation: !reducedMotion,
  animationDuration: 420,
  color: ['#009fbe', '#7abfce'],
  legend: { top: 0, left: 4, itemWidth: 10, itemHeight: 8, textStyle: { color: '#6d8390', fontSize: 11 } },
  grid: { left: 28, right: 14, top: 31, bottom: 50, containLabel: true },
  tooltip: {
    ...adminTooltipStyle,
    trigger: 'axis',
    axisPointer: chartShadowPointer,
    formatter: (params) => {
      const point = Array.isArray(params) ? params[0] : params
      const row = classes[Number(point?.dataIndex)]
      return row ? `${row.label}<br/>学生：${row.students}<br/>教师：${row.teachers}` : ''
    },
  },
  xAxis: {
    type: 'category',
    data: classes.map((item) => item.label),
    axisLabel: { color: '#8295a0', fontSize: 10, interval: 0, rotate: classes.length > 6 ? 20 : 0, hideOverlap: true },
    axisLine: { lineStyle: { color: '#e2e8ee' } },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    min: 0,
    minInterval: 1,
    axisLabel: { color: '#8295a0', fontSize: 10 },
    axisLine: { lineStyle: { color: '#e2e8ee' } },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: '#e8eef1' } },
  },
  series: [
    { type: 'bar', name: '学生', stack: 'members', data: classes.map((item) => item.students), barMaxWidth: 28, itemStyle: { color: '#129db9' } },
    {
      type: 'bar', name: '教师', stack: 'members', data: classes.map((item) => item.teachers), barMaxWidth: 28,
      itemStyle: { color: '#7abfce', borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top', color: '#536a78', fontSize: 10, formatter: (params) => formatCount((classes[params.dataIndex]?.students ?? 0) + Number(params.value ?? 0)) },
    },
  ],
})

const formatDayLabel = (date: Date) => `${date.getMonth() + 1}/${date.getDate()}`
const dateAtOffset = (offset: number) => {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offset)
  return date
}

const makeOperationsLineChart = (days: Array<{ label: string; accounts: number; tasks: number; classes: number }>): EChartsOption => ({
  animation: !reducedMotion,
  animationDuration: 460,
  color: ['#009fbe', '#7e83ca', '#53a58b'],
  grid: { left: 28, right: 13, top: 34, bottom: 22, containLabel: true },
  tooltip: {
    ...adminTooltipStyle,
    trigger: 'axis',
    axisPointer: { type: 'line', lineStyle: { color: '#aebdc4', width: 1, type: 'dashed' } },
    formatter: (params) => {
      const items = Array.isArray(params) ? params : [params]
      const day = days[Number(items[0]?.dataIndex)]
      return day ? `${day.label}<br/>账号变更：${day.accounts}<br/>任务发布：${day.tasks}<br/>班级调整：${day.classes}` : ''
    },
  },
  legend: { top: 0, left: 2, itemWidth: 9, itemHeight: 9, textStyle: { color: '#6d8390', fontSize: 10 } },
  xAxis: {
    type: 'category', data: days.map((item) => item.label), boundaryGap: false,
    axisTick: { show: false }, axisLine: { lineStyle: { color: '#e2e8ee' } },
    axisLabel: { color: '#8295a0', fontSize: 9, hideOverlap: true },
  },
  yAxis: {
    type: 'value', min: 0, minInterval: 1,
    axisLabel: { color: '#8295a0', fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false },
    splitLine: { lineStyle: { color: '#e8eef1' } },
  },
  series: [
    { name: '账号变更', type: 'line', data: days.map((item) => item.accounts), smooth: false, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2.5 }, itemStyle: { borderColor: '#fff', borderWidth: 1.5 } },
    { name: '任务发布', type: 'line', data: days.map((item) => item.tasks), smooth: false, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2.5 }, itemStyle: { borderColor: '#fff', borderWidth: 1.5 } },
    { name: '班级调整', type: 'line', data: days.map((item) => item.classes), smooth: false, symbol: 'circle', symbolSize: 5, lineStyle: { width: 2.5 }, itemStyle: { borderColor: '#fff', borderWidth: 1.5 } },
  ],
})

const summarizeClasses = async (): Promise<AdminPreviewSummary> => {
  let rows: Array<{ label: string; students: number; teachers: number; isActive: boolean }>
  if (isLocalAdminPreview()) {
    rows = (await loadAdminOverviewDemoData()).classes
  } else {
    if (!frontendApi.listSchoolClasses) throw new Error('unavailable')
    const result = await frontendApi.listSchoolClasses()
    if (!Array.isArray(result.data)) throw new Error('invalid_response')
    rows = result.data.map((item: SchoolClass, index) => ({
      label: item.display_name?.trim() || `班级 ${index + 1}`,
      students: Math.max(0, Number(item.active_student_count) || 0),
      teachers: Math.max(0, Number(item.active_teacher_count) || 0),
      isActive: item.status.toUpperCase() === 'ACTIVE',
    }))
  }

  const ranked = [...rows].sort((a, b) => b.students + b.teachers - (a.students + a.teachers)).slice(0, 8)
  const studentCount = rows.reduce((sum, item) => sum + item.students, 0)
  const teacherCount = rows.reduce((sum, item) => sum + item.teachers, 0)
  const hasMemberCounts = ranked.some((item) => item.students + item.teachers > 0)

  return {
    presentation: 'chart',
    headlineLabel: '本校班级',
    headlineValue: formatCount(rows.length),
    metrics: [
      { label: '启用班级', value: formatCount(rows.filter((item) => item.isActive).length) },
      { label: '学生人数', value: formatCount(studentCount) },
      { label: '教师人数', value: formatCount(teacherCount) },
    ],
    chartTitle: '各班成员人数',
    chartLabel: '按班级显示的学生与教师人数',
    chartEmptyMessage: rows.length ? '当前没有班级成员数据' : '本校暂无班级',
    chartOption: hasMemberCounts ? makeClassChart(ranked) : null,
  }
}

const summarizeAccounts = async (): Promise<AdminPreviewSummary> => {
  let studentCount: number
  let teacherCount: number
  let pendingCount: number
  if (isLocalAdminPreview()) {
    const data = await loadAdminOverviewDemoData()
    studentCount = data.accounts.students
    teacherCount = data.accounts.teachers
    pendingCount = data.accounts.pendingActivation
  } else {
    if (!frontendApi.listSchoolMembers) throw new Error('unavailable')
    const [studentResult, teacherResult] = await Promise.all([
      frontendApi.listSchoolMembers('student'),
      frontendApi.listSchoolMembers('teacher'),
    ])
    if (!Array.isArray(studentResult.data) || !Array.isArray(teacherResult.data)) throw new Error('invalid_response')
    const students = studentResult.data as SchoolMember[]
    const teachers = teacherResult.data as SchoolMember[]
    const allMembers = [...students, ...teachers]
    studentCount = students.length
    teacherCount = teachers.length
    pendingCount = allMembers.filter((member) => member.provisioning_status?.toUpperCase() === 'PENDING_ACTIVATION').length
  }
  const total = studentCount + teacherCount

  return {
    presentation: 'chart',
    headlineLabel: '本校账号',
    headlineValue: formatCount(total),
    metrics: [
      { label: '学生账号', value: formatCount(studentCount) },
      { label: '教师账号', value: formatCount(teacherCount) },
      { label: '待激活', value: formatCount(pendingCount) },
    ],
    chartTitle: '账号角色分布',
    chartLabel: '学生账号与教师账号数量',
    chartEmptyMessage: '本校暂无账号',
    chartOption: total ? makeHorizontalChart(['学生账号', '教师账号'], [studentCount, teacherCount]) : null,
  }
}

const summarizeOperationsFromDemo = async (): Promise<AdminPreviewSummary> => {
  const { operations } = await loadAdminOverviewDemoData()
  const days = operations.map((item) => ({ label: formatDayLabel(dateAtOffset(item.offset)), ...item }))
  const accountCount = days.reduce((sum, item) => sum + item.accounts, 0)
  const taskCount = days.reduce((sum, item) => sum + item.tasks, 0)
  const classCount = days.reduce((sum, item) => sum + item.classes, 0)

  return {
    presentation: 'chart',
    headlineLabel: '近14天操作',
    headlineValue: formatCount(accountCount + taskCount + classCount),
    metrics: [
      { label: '账号变更', value: formatCount(accountCount) },
      { label: '任务发布', value: formatCount(taskCount) },
      { label: '班级调整', value: formatCount(classCount) },
    ],
    chartTitle: '每日操作趋势',
    chartLabel: '近14天账号变更、任务发布与班级调整次数',
    chartEmptyMessage: '暂无操作记录',
    chartOption: makeOperationsLineChart(days),
  }
}

const summarizeOperations = async (): Promise<AdminPreviewSummary> => {
  if (isLocalAdminPreview()) return summarizeOperationsFromDemo()
  if (!frontendApi.listSchoolOperationsAudit) throw new Error('unavailable')
  const result = await frontendApi.listSchoolOperationsAudit({ offset: 0, limit: 25, category: null })
  const events: SchoolOperationsAuditEvent[] = result.data.items
  const operationDays = new Map<string, { accounts: number; tasks: number; classes: number }>()
  for (const event of events) {
    const dateKey = event.created_at.slice(0, 10)
    const counts = operationDays.get(dateKey) ?? { accounts: 0, tasks: 0, classes: 0 }
    if (event.resource_category === 'task') counts.tasks += 1
    else if (event.resource_category === 'class' || event.resource_category === 'organization') counts.classes += 1
    else counts.accounts += 1
    operationDays.set(dateKey, counts)
  }
  const days = [...operationDays.entries()].sort(([first], [second]) => first.localeCompare(second)).map(([date, counts]) => ({
    label: formatDayLabel(new Date(`${date}T12:00:00`)),
    ...counts,
  }))
  const accountCount = days.reduce((sum, item) => sum + item.accounts, 0)
  const taskCount = days.reduce((sum, item) => sum + item.tasks, 0)
  const classCount = days.reduce((sum, item) => sum + item.classes, 0)

  return {
    presentation: 'chart',
    headlineLabel: '近期操作',
    headlineValue: formatCount(events.length),
    metrics: [
      { label: '账号变更', value: formatCount(accountCount) },
      { label: '任务发布', value: formatCount(taskCount) },
      { label: '班级调整', value: formatCount(classCount) },
    ],
    chartTitle: '操作趋势',
    chartLabel: '按日期统计账号变更、任务发布与班级调整次数',
    chartEmptyMessage: '暂无操作记录',
    chartOption: days.length ? makeOperationsLineChart(days) : null,
  }
}

const dependencyNames: Record<string, string> = {
  cat: 'CAT 测评',
  rag: 'RAG 检索',
  llm_runtime: 'LLM 运行时',
  safety: '安全校验',
  post_assessment_worker: '测后处理',
  research_education_worker: '研究教育任务',
  research_programme_worker: '研究项目任务',
  research_general_education_draft_worker: '通用教育草稿',
}

const connectionNames: Record<string, string> = {
  REAL_HTTP: 'HTTP 服务',
  LOCAL_OUTBOX: '本地队列',
  RESEARCH_OUTBOX: '研究队列',
  RESEARCH_STAFF_PROGRAMME_OUTBOX: '项目队列',
  RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX: '草稿队列',
}

const summarizeSystem = async (): Promise<AdminPreviewSummary> => {
  const result = await readDependencyHealth()
  if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('invalid_response')
  const dependencyRows = Object.entries(result).map(([name, value]) => ({
    name: dependencyNames[name] ?? name.replaceAll('_', ' '),
    connection: connectionNames[value.integration] ?? value.integration ?? '—',
    status: value.status,
  }))

  return {
    presentation: 'table',
    tableLabel: '服务接入方式和运行状态',
    dependencyRows,
  }
}

const previewErrorFor = (folderId: AdminFolderId) => {
  if (folderId === 'classes') return '暂时无法读取班级信息，请刷新后重试。'
  if (folderId === 'accounts') return '暂时无法读取账号信息，请刷新后重试。'
  if (folderId === 'operations') return '暂时无法读取运营记录，请刷新后重试。'
  return '暂时无法读取服务状态，请刷新后重试。'
}

const loadPreview = async (folderId: AdminFolderId) => {
  const generation = ++previewRequestGeneration
  previewState.value = 'loading'
  previewSummary.value = null
  previewError.value = ''
  try {
    const summary = folderId === 'classes'
      ? await summarizeClasses()
      : folderId === 'accounts'
        ? await summarizeAccounts()
        : folderId === 'operations'
          ? await summarizeOperations()
          : await summarizeSystem()
    if (generation !== previewRequestGeneration || activeFolderId.value !== folderId) return
    previewSummary.value = summary
    previewState.value = 'ready'
  } catch {
    if (generation !== previewRequestGeneration || activeFolderId.value !== folderId) return
    previewError.value = previewErrorFor(folderId)
    previewState.value = 'error'
  }
}

const measurePaperOrigins = (source: HTMLButtonElement | null): FolderOrigins => {
  if (!source) return []
  const coverTop = source.querySelector<HTMLElement>('.workspace-folder__cover')?.getBoundingClientRect().top
  return [...source.querySelectorAll<HTMLElement>('[data-folder-paper]')].map((paper) => {
    const bounds = paper.getBoundingClientRect()
    return {
      x: bounds.left + bounds.width / 2,
      y: bounds.top + bounds.height / 2,
      width: bounds.width,
      height: bounds.height,
      coverOcclusion: coverTop === undefined ? 0 : Math.min(1, Math.max(0, (bounds.bottom - coverTop) / bounds.height)),
    }
  })
}

const updateOrigin = (source: HTMLButtonElement | null, origins?: FolderOrigins) => {
  const measured = origins?.length ? origins : measurePaperOrigins(source)
  previewPaperOrigins.value = measured
  previewOrigin.value = {
    x: window.innerWidth / 2,
    y: window.innerHeight / 2,
    width: 42,
    height: 32,
  }
}

const openFolder = (folder: WorkspaceFolder, source: HTMLButtonElement, papers: FolderOrigins, selectedPaperIndex: number) => {
  if (drawerClosing.value) return
  sourceElement.value = source
  previewPaperIndex.value = selectedPaperIndex
  previewScrollPosition = { x: window.scrollX, y: window.scrollY }
  updateOrigin(source, papers)
  stackedFolderId.value = folder.id
  activeFolderId.value = folder.id
  drawerClosing.value = false
  drawerOpen.value = true
  void loadPreview(folder.id)
}

const finishPreviewClose = async () => {
  if (!drawerClosing.value) return

  if (closeTimer !== undefined) {
    window.clearTimeout(closeTimer)
    closeTimer = undefined
  }

  const returnFocusTo = sourceElement.value
  const closingFolderId = activeFolderId.value
  const afterClose = closeAfterAnimation
  closeAfterAnimation = undefined

  drawerOpen.value = false
  drawerClosing.value = false
  activeFolderId.value = null
  sourceElement.value = null
  previewOrigin.value = null
  previewPaperOrigins.value = []
  previewPaperIndex.value = 2
  previewSummary.value = null
  previewState.value = 'loading'
  previewError.value = ''

  await nextTick()
  // Reka UI releases its body scroll lock when the portal overlay is removed.
  // Wait for that cleanup before restoring the page's saved scroll position.
  await new Promise<void>((resolve) => {
    const startedAt = performance.now()
    const waitForOverlayRemoval = () => {
      if (!document.querySelector('.admin-drawer__overlay') || performance.now() - startedAt > 500) {
        resolve()
        return
      }
      window.requestAnimationFrame(waitForOverlayRemoval)
    }
    window.requestAnimationFrame(waitForOverlayRemoval)
  })
  window.scrollTo(previewScrollPosition.x, previewScrollPosition.y)
  if (returnFocusTo?.isConnected) {
    returnFocusTo.focus({ preventScroll: true })
    await nextTick()
  }

  previewScrollPosition = { x: 0, y: 0 }
  if (stackedFolderId.value === closingFolderId) stackedFolderId.value = null
  afterClose?.()
}

const closePreview = (afterClose?: () => void) => {
  if (!drawerOpen.value || drawerClosing.value) return
  drawerClosing.value = true
  closeAfterAnimation = afterClose
  updateOrigin(sourceElement.value)
  previewRequestGeneration += 1
  // Let the paper finish its CSS return animation before unmounting it. The
  // fallback covers reduced motion and browsers that cancel animation events.
  closeTimer = window.setTimeout(() => { void finishPreviewClose() }, reducedMotion ? 1 : 1000)
}

const setDrawerOpen = (value: boolean) => {
  if (!value) closePreview()
}

const refreshPreview = () => {
  if (activeFolderId.value && !drawerClosing.value) void loadPreview(activeFolderId.value)
}

const navigateFromPreview = (action: AdminWorkspaceAction) => {
  closePreview(() => { void router.push(action.to) })
}

</script>

<template>
  <section class="operations-desk" aria-label="学校运营工作区">
    <AdminCommandPalette :actions="adminWorkspaceActions" @activate="setDrawerOpen(false)" />

    <div ref="fieldRoot" class="operations-desk__field">
      <canvas ref="dotCanvas" class="operations-desk__dots" aria-hidden="true" />
      <svg class="operations-desk__orbit" viewBox="0 0 1200 560" preserveAspectRatio="none" aria-hidden="true">
        <circle cx="600" cy="280" r="108" />
        <circle cx="600" cy="280" r="188" />
        <path d="M178 138 506 258M1022 138 694 258M178 421 506 302M1022 421 694 302" />
      </svg>
      <div class="operations-desk__field-label"><span>工作领域</span><span class="operations-desk__field-line" /></div>

      <div class="operations-desk__grid">
        <AdminWorkspaceFolder
          v-for="folder in adminWorkspaceFolders"
          :key="folder.id"
          class="operations-desk__folder"
          :class="`operations-desk__folder--${folder.id}`"
          :folder="folder"
          :active="activeFolderId === folder.id && drawerOpen"
          :stacked="stackedFolderId === folder.id"
          :active-paper-index="activeFolderId === folder.id && drawerOpen ? previewPaperIndex : null"
          @open="openFolder"
        />

        <div class="operations-desk__core" role="group" aria-label="PsyNova 学校运营中心">
          <div class="operations-desk__core-mark"><img src="/assets/psynova/mark.png" alt="PsyNova" /></div>
          <img class="operations-desk__core-wordmark" src="/assets/psynova/wordmark.png" alt="" aria-hidden="true" />
          <span class="operations-desk__core-caption">学校运营中心</span>
        </div>
      </div>

      <div class="operations-desk__field-foot"><span class="operations-desk__field-dot" aria-hidden="true" />选择文件夹，查看本校数据概览</div>
    </div>

    <AdminWorkspaceDrawer
      :open="drawerOpen"
      :closing="drawerClosing"
      :folder="activeFolder"
      :actions="currentActions"
      :state="previewState"
      :summary="previewSummary"
      :error-message="previewError"
      :origin="previewOrigin"
      :paper-origins="previewPaperOrigins"
      :selected-paper-index="previewPaperIndex"
      @update:open="setDrawerOpen"
      @return-complete="finishPreviewClose"
      @refresh="refreshPreview"
      @navigate="navigateFromPreview"
    />
  </section>
</template>

<style scoped>
.operations-desk { min-width: 0; }
.operations-desk__field { position: relative; isolation: isolate; display: grid; grid-template-rows: auto 1fr auto; gap: 10px; min-height: 480px; padding: 20px 22px 16px; overflow: hidden; border: 1px solid #e1e9ed; border-radius: 23px; background: #fbfcfd; box-shadow: inset 0 0 0 1px rgb(255 255 255 / 64%); }
.operations-desk__dots { position: absolute; z-index: -1; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.operations-desk__orbit { position: absolute; z-index: -1; inset: 0; width: 100%; height: 100%; fill: none; stroke: #dcecf0; stroke-width: 1.25; pointer-events: none; }
.operations-desk__orbit circle:first-of-type { stroke: #cde8ee; }.operations-desk__orbit path { stroke: #b9dfe7; stroke-dasharray: 5 10; }
.operations-desk__field-label { display: flex; align-items: center; gap: 13px; color: #748c99; font-size: 12px; font-weight: 650; letter-spacing: .02em; }.operations-desk__field-line { width: 46px; height: 1px; background: #c9dce3; }
.operations-desk__grid { position: relative; display: grid; grid-template-columns: minmax(0, 1fr) clamp(112px, 15vw, 174px) minmax(0, 1fr); grid-template-rows: repeat(2, minmax(184px, 1fr)); grid-template-areas: 'classes core accounts' 'operations core system'; align-items: center; gap: 30px 14px; min-height: 420px; }
.operations-desk__folder--classes { grid-area: classes; }.operations-desk__folder--accounts { grid-area: accounts; }.operations-desk__folder--operations { grid-area: operations; }.operations-desk__folder--system { grid-area: system; }
.operations-desk__core { z-index: 2; grid-area: core; display: flex; flex-direction: column; align-items: center; justify-content: center; justify-self: center; width: 158px; height: 158px; border: 1px solid #d6ebef; border-radius: 50%; background: rgb(255 255 255 / 90%); box-shadow: 0 0 0 18px rgb(255 255 255 / 30%), 0 17px 44px rgb(33 98 119 / 9%); text-align: center; }
.operations-desk__core-mark { display: grid; width: 56px; height: 56px; place-items: center; }.operations-desk__core-mark img { display: block; width: 52px; height: 52px; object-fit: contain; transform: translateX(-3px); }
.operations-desk__core-wordmark { display: block; width: 78px; height: 39px; margin-top: 1px; object-fit: contain; }
.operations-desk__core-caption { margin-top: 3px; color: #8da4af; font-size: 10px; }
.operations-desk__field-foot { display: flex; align-items: center; gap: 8px; color: #8aa0aa; font-size: 11px; line-height: 1.4; }.operations-desk__field-dot { width: 6px; height: 6px; border-radius: 50%; background: #70b8ca; }
@media (max-width: 1100px) and (min-width: 721px) {
  .operations-desk__field { min-height: 0; }
  .operations-desk__orbit { opacity: .6; }
  .operations-desk__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: repeat(3, minmax(176px, auto)); grid-template-areas: 'classes accounts' 'core core' 'operations system'; gap: 26px 22px; min-height: 0; padding: 8px 8px 2px; }
  .operations-desk__core { width: 124px; height: 124px; }.operations-desk__core-mark, .operations-desk__core-mark img { width: 44px; height: 44px; }.operations-desk__core-caption { margin-top: 3px; }
}
@media (max-width: 720px) {
  .operations-desk__field { min-height: 0; padding: 16px 14px 14px; border-radius: 18px; }
  .operations-desk__orbit { display: none; }
  .operations-desk__grid { grid-template-columns: minmax(0, 1fr); grid-template-rows: repeat(4, minmax(164px, auto)) auto; grid-template-areas: 'classes' 'accounts' 'operations' 'system' 'core'; gap: 24px; min-height: 0; padding: 3px 2px 4px; }
  .operations-desk__core { width: 106px; height: 106px; margin-top: 5px; box-shadow: 0 0 0 10px rgb(255 255 255 / 35%), 0 12px 30px rgb(33 98 119 / 8%); }.operations-desk__core-mark, .operations-desk__core-mark img { width: 36px; height: 36px; }.operations-desk__core-wordmark { width: 58px; height: 28px; margin-top: 0; }.operations-desk__core-caption { margin-top: 0; font-size: 9px; }
  .operations-desk__field-foot { padding-left: 2px; font-size: 10px; }
}
</style>
