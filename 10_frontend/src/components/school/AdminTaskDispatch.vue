<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CalendarDays, ChevronLeft, ChevronRight, Clock3, ListChecks, Plus, RefreshCw, Search, X } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import WorkspaceTabs from '@/components/workspace/WorkspaceTabs.vue'
import TeacherClassSelect, { type TeacherClassOption } from '@/components/teacher/TeacherClassSelect.vue'
import AdminProfessionalAssignments from '@/components/school/AdminProfessionalAssignments.vue'
import type { SchoolClass, SchoolTask, SchoolTaskEnrollment } from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { schoolCatActivations, type CatActivationMetadata } from '@/services/school-cat-activations'
import { dateFromKey, localDateKey } from '@/utils/teacher-assessment-planner'

type LoadState = 'loading' | 'ready' | 'error'
type WindowState = 'open' | 'upcoming' | 'ended' | 'cancelled' | 'unknown'
type ViewMode = 'timeline' | 'calendar'
type TaskEntry = { key: string; task: SchoolTask; classLabel: string }
type DayTask = { entry: TaskEntry; opens: boolean; due: boolean }
type EnrollmentState = { state: LoadState; items: SchoolTaskEnrollment[]; message: string }

const classes = ref<SchoolClass[]>([])
const entries = ref<TaskEntry[]>([])
const failedClassRefs = ref<string[]>([])
const pageState = ref<LoadState>('loading')
const listError = ref('')
const notice = ref('')
const operationError = ref('')
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const classFilter = ref('all')
const statusFilter = ref<WindowState | 'all'>('all')
const viewMode = ref<ViewMode>('timeline')
const selectedTaskKey = ref('')
const detailTab = ref('overview')
const clockNow = ref(Date.now())
const today = new Date()
const todayKey = localDateKey(today)
const selectedDate = ref(todayKey)
const monthCursor = ref(new Date(today.getFullYear(), today.getMonth(), 1))
const enrollmentViews = ref<Record<string, EnrollmentState>>({})
const revokeTarget = ref<{ taskRef: string; enrollmentRef: string } | null>(null)
const revokePending = ref(false)

const publishOpen = ref(false)
const publishStep = ref(0)
const publishPending = ref(false)
const publishError = ref('')
const publishClassRef = ref('')
const bindingMode = ref<'FIXTURE' | 'SAVED_VERSION'>('FIXTURE')
const selectedActivationRef = ref('')
const activations = ref<CatActivationMetadata[]>([])
const activationState = ref<'idle' | LoadState>('idle')
const activationError = ref('')
const activationHasMore = ref(false)
const activationSkip = ref(0)
const opensAt = ref('')
const dueAt = ref('')

let taskLoadGeneration = 0
let activationLoadGeneration = 0
let enrollmentLoadGeneration = 0
let clockTimer: number | undefined
let disposed = false

const detailTabs = [
  { value: 'overview', label: '任务概况' },
  { value: 'enrollments', label: '报名记录' },
  { value: 'assignments', label: '专业分配' },
] as const
const publishSteps = ['选择配置', '开放时间', '确认发布']
const weekdays = ['一', '二', '三', '四', '五', '六', '日']
const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

const shortRef = (value: string) => value.slice(-6)
const classLabel = (item: SchoolClass) => item.display_name?.trim() || `班级 ${shortRef(item.class_ref)}`
const entryKey = (task: SchoolTask) => JSON.stringify([task.class_ref, task.task_ref])
const taskTitle = (entry: TaskEntry) => entry.task.plan_name?.trim() || `${entry.classLabel} · 任务 ${shortRef(entry.task.task_ref)}`
const taskConfiguration = (task: SchoolTask) => task.plan_name?.trim()
  ? `${task.plan_name} v${task.plan_version_number ?? '—'}`
  : task.instrument_version ? `方案版本 ${task.instrument_version}` : '服务端未提供配置版本'
const formatDate = (value: string | null | undefined, empty = '未设置') => {
  if (!value) return empty
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间待确认' : dateTimeFormatter.format(parsed)
}
const formatLocalDraft = (value: string) => value ? formatDate(new Date(value).toISOString()) : '未设置截止时间'
const windowState = (task: SchoolTask, now = clockNow.value): WindowState => {
  const status = task.status.toUpperCase()
  if (['REVOKED', 'CANCELLED', 'CANCELED'].includes(status)) return 'cancelled'
  const opens = Date.parse(task.opens_at)
  if (!Number.isFinite(opens)) return 'unknown'
  if (opens > now) return 'upcoming'
  const due = task.due_at ? Date.parse(task.due_at) : Number.NaN
  if (Number.isFinite(due) && due <= now) return 'ended'
  return 'open'
}
const windowStateLabel = (state: WindowState) => ({
  open: '开放中', upcoming: '即将开放', ended: '已截止', cancelled: '已撤销', unknown: '时间待确认',
}[state])
const serverStatusLabel = (status: string) => ({
  PUBLISHED: '已发布', ACTIVE: '有效', REVOKED: '已撤销', CANCELLED: '已取消', COMPLETED: '已完成',
}[status.toUpperCase()] ?? status) || '状态待确认'
const enrollmentStatusLabel = (status: string) => ({
  ACTIVE: '有效', ENROLLED: '有效', REVOKED: '已撤销', CANCELLED: '已取消',
}[status.toUpperCase()] ?? status) || '状态待确认'
const statusTone = (state: WindowState) => `task-state--${state}`
const isEnrollmentRevoked = (status: string) => ['REVOKED', 'CANCELLED'].includes(status.toUpperCase())

const classOptions = computed<TeacherClassOption[]>(() => [
  { value: 'all', label: '全部班级' },
  ...[...classes.value].sort((first, second) => classLabel(first).localeCompare(classLabel(second), 'zh-CN'))
    .map((item) => ({ value: item.class_ref, label: classLabel(item) })),
])
const statusOptions = computed<TeacherClassOption[]>(() => {
  const options: TeacherClassOption[] = [
    { value: 'all', label: '全部状态' },
    { value: 'open', label: '开放中' },
    { value: 'upcoming', label: '即将开放' },
    { value: 'ended', label: '已截止' },
    { value: 'cancelled', label: '已撤销' },
  ]
  if (entries.value.some((entry) => windowState(entry.task) === 'unknown')) options.push({ value: 'unknown', label: '时间待确认' })
  return options
})
const statusFilterModel = computed<string>({
  get: () => statusFilter.value,
  set: (value) => {
    if (['all', 'open', 'upcoming', 'ended', 'cancelled', 'unknown'].includes(value)) {
      statusFilter.value = value as WindowState | 'all'
    }
  },
})

const orderedEntries = computed(() => [...entries.value].sort((first, second) => {
  const firstTime = Date.parse(first.task.opens_at)
  const secondTime = Date.parse(second.task.opens_at)
  return (Number.isFinite(firstTime) ? firstTime : Number.POSITIVE_INFINITY)
    - (Number.isFinite(secondTime) ? secondTime : Number.POSITIVE_INFINITY)
    || first.classLabel.localeCompare(second.classLabel, 'zh-CN')
    || first.task.task_ref.localeCompare(second.task.task_ref)
}))
const visibleEntries = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return orderedEntries.value.filter((entry) => {
    const state = windowState(entry.task)
    if (classFilter.value !== 'all' && entry.task.class_ref !== classFilter.value) return false
    if (statusFilter.value !== 'all' && state !== statusFilter.value) return false
    if (!query) return true
    const searchable = [taskTitle(entry), entry.classLabel, entry.task.task_ref, entry.task.plan_name ?? '', entry.task.instrument_id, entry.task.instrument_version]
      .join(' ').toLocaleLowerCase()
    return searchable.includes(query)
  })
})
const selectedEntry = computed(() => visibleEntries.value.find((entry) => entry.key === selectedTaskKey.value)
  ?? visibleEntries.value[0]
  ?? null)
const selectedTask = computed(() => selectedEntry.value?.task ?? null)
const hasActiveFilters = computed(() => Boolean(searchQuery.value.trim()) || classFilter.value !== 'all' || statusFilter.value !== 'all')
const summaryCounts = computed(() => ({
  all: entries.value.length,
  open: entries.value.filter((entry) => windowState(entry.task) === 'open').length,
  upcoming: entries.value.filter((entry) => windowState(entry.task) === 'upcoming').length,
  ended: entries.value.filter((entry) => windowState(entry.task) === 'ended').length,
}))
const classScopeNote = computed(() => {
  if (pageState.value === 'loading') return '正在读取本校班级任务'
  if (pageState.value === 'error') return entries.value.length
    ? '列表读取失败；当前仅显示服务端已确认的任务记录'
    : '任务统计暂不可用'
  if (!classes.value.length) return '本校暂无可读取的班级'
  const loaded = classes.value.length - failedClassRefs.value.length
  return failedClassRefs.value.length
    ? `已读取 ${loaded}/${classes.value.length} 个班级，统计仅包含已读取任务`
    : `覆盖 ${classes.value.length} 个服务端返回的本校班级`
})
const selectedState = computed(() => selectedTask.value ? windowState(selectedTask.value) : 'unknown')
const totalEnrollmentBreakdown = computed(() => selectedTask.value
  ? selectedTask.value.active_enrollment_count + selectedTask.value.revoked_enrollment_count
  : 0)
const enrollmentBreakdownConsistent = computed(() => Boolean(selectedTask.value)
  && totalEnrollmentBreakdown.value === selectedTask.value!.published_enrollment_count)
const enrollmentViewsForSelected = computed(() => selectedTask.value ? enrollmentViews.value[selectedTask.value.task_ref] : undefined)
const assignmentTaskForSelected = computed(() => selectedTask.value ? [selectedTask.value] : [])

watch(visibleEntries, (items) => {
  if (!items.some((entry) => entry.key === selectedTaskKey.value)) selectedTaskKey.value = items[0]?.key ?? ''
}, { immediate: true })
watch(statusOptions, (options) => {
  if (!options.some((option) => option.value === statusFilter.value)) statusFilter.value = 'all'
})

const loadTaskData = async (silent = false): Promise<boolean> => {
  const generation = ++taskLoadGeneration
  const listClasses = frontendApi.listSchoolClasses
  const listTasks = frontendApi.listSchoolTasks
  if (!listClasses || !listTasks) {
    pageState.value = 'error'
    listError.value = '当前运行环境未提供学校任务服务。本页面不会用演示数据替代服务端结果。'
    entries.value = []
    classes.value = []
    return false
  }
  if (!silent) pageState.value = 'loading'
  listError.value = ''
  notice.value = ''
  try {
    const response = await listClasses()
    if (disposed || generation !== taskLoadGeneration) return false
    const classByRef = new Map(response.data.map((item) => [item.class_ref, item]))
    const classRows = [...classByRef.values()]
    classes.value = classRows
    if (classFilter.value !== 'all' && !classByRef.has(classFilter.value)) classFilter.value = 'all'

    const results = await Promise.allSettled(classRows.map(async (classRow) => {
      const tasksResponse = await listTasks(classRow.class_ref)
      if (!Array.isArray(tasksResponse.data) || tasksResponse.data.some((task) => task.class_ref !== classRow.class_ref)) {
        throw new Error('class_scope_mismatch')
      }
      return { classRow, tasks: tasksResponse.data }
    }))
    if (disposed || generation !== taskLoadGeneration) return false
    const loaded: TaskEntry[] = []
    const failures: string[] = []
    for (const result of results) {
      if (result.status === 'rejected') {
        const index = results.indexOf(result)
        const failedClass = classRows[index]
        if (failedClass) failures.push(failedClass.class_ref)
        continue
      }
      for (const task of result.value.tasks) {
        loaded.push({ key: entryKey(task), task, classLabel: classLabel(result.value.classRow) })
      }
    }
    const unique = new Map(loaded.map((entry) => [entry.key, entry]))
    entries.value = [...unique.values()]
    failedClassRefs.value = failures
    listError.value = failures.length
      ? `部分班级任务读取失败；当前统计仅包含 ${classRows.length - failures.length}/${classRows.length} 个班级的结果。`
      : ''
    pageState.value = 'ready'
    return true
  } catch (error) {
    if (disposed || generation !== taskLoadGeneration) return false
    entries.value = []
    failedClassRefs.value = []
    pageState.value = 'error'
    listError.value = requestMessage(error, '暂时无法读取本校班级与测评任务。')
    return false
  }
}

const requestMessage = (error: unknown, fallback: string) => {
  const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
  if (['FORBIDDEN', '403'].includes(code)) return '当前账号暂时没有此项操作权限。'
  if (['AUTH_SESSION_EXPIRED', 'AUTH_SESSION_REVOKED'].includes(code)) return '登录状态已过期，请重新登录后再试。'
  if (['RESOURCE_NOT_FOUND', 'NOT_FOUND', '404'].includes(code)) return '所选内容已不可用，请刷新后重试。'
  if (['WORKFLOW_CONFLICT', 'CONFLICT', '409'].includes(code)) return '数据已发生变化，请刷新后重试。'
  return fallback
}

const clearFilters = () => {
  searchQuery.value = ''
  classFilter.value = 'all'
  statusFilter.value = 'all'
}
const clearSearch = () => {
  searchQuery.value = ''
  void nextTick(() => searchInput.value?.focus())
}
const selectEntry = (entry: TaskEntry) => { selectedTaskKey.value = entry.key }
const setViewMode = (mode: ViewMode) => { viewMode.value = mode }
const localDateKeyForValue = (value: string | null) => {
  if (!value) return ''
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '' : localDateKey(parsed)
}

const eventsByDate = computed(() => {
  const byDate = new Map<string, Array<{ entry: TaskEntry; kind: 'opens' | 'due' }>>()
  const add = (dateKey: string, event: { entry: TaskEntry; kind: 'opens' | 'due' }) => {
    if (!dateKey) return
    const values = byDate.get(dateKey) ?? []
    values.push(event)
    byDate.set(dateKey, values)
  }
  for (const entry of visibleEntries.value) {
    if (windowState(entry.task) === 'cancelled') continue
    add(localDateKeyForValue(entry.task.opens_at), { entry, kind: 'opens' })
    add(localDateKeyForValue(entry.task.due_at), { entry, kind: 'due' })
  }
  return byDate
})
const calendarCells = computed(() => {
  const year = monthCursor.value.getFullYear()
  const month = monthCursor.value.getMonth()
  const firstOfMonth = new Date(year, month, 1)
  const mondayOffset = (firstOfMonth.getDay() + 6) % 7
  const firstCell = new Date(year, month, 1 - mondayOffset)
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(firstCell.getFullYear(), firstCell.getMonth(), firstCell.getDate() + index)
    const key = localDateKey(date)
    const events = eventsByDate.value.get(key) ?? []
    return {
      key,
      day: date.getDate(),
      inMonth: date.getMonth() === month,
      isToday: key === localDateKey(new Date(clockNow.value)),
      isSelected: key === selectedDate.value,
      opensCount: events.filter((event) => event.kind === 'opens').length,
      dueCount: events.filter((event) => event.kind === 'due').length,
      eventCount: events.length,
    }
  })
})
const monthLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long' }).format(monthCursor.value))
const selectedDateLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(dateFromKey(selectedDate.value)))
const selectedDateTasks = computed<DayTask[]>(() => {
  const grouped = new Map<string, DayTask>()
  for (const event of eventsByDate.value.get(selectedDate.value) ?? []) {
    const item = grouped.get(event.entry.key) ?? { entry: event.entry, opens: false, due: false }
    if (event.kind === 'opens') item.opens = true
    else item.due = true
    grouped.set(event.entry.key, item)
  }
  return [...grouped.values()].sort((first, second) => Date.parse(first.entry.task.opens_at) - Date.parse(second.entry.task.opens_at))
})
const selectDate = (key: string) => {
  selectedDate.value = key
  const date = dateFromKey(key)
  if (date.getFullYear() !== monthCursor.value.getFullYear() || date.getMonth() !== monthCursor.value.getMonth()) {
    monthCursor.value = new Date(date.getFullYear(), date.getMonth(), 1)
  }
}
const changeMonth = (offset: number) => {
  const currentDay = dateFromKey(selectedDate.value).getDate()
  const next = new Date(monthCursor.value.getFullYear(), monthCursor.value.getMonth() + offset, 1)
  const lastDay = new Date(next.getFullYear(), next.getMonth() + 1, 0).getDate()
  monthCursor.value = next
  selectedDate.value = localDateKey(new Date(next.getFullYear(), next.getMonth(), Math.min(currentDay, lastDay)))
}
const goToToday = () => {
  const now = new Date(clockNow.value)
  monthCursor.value = new Date(now.getFullYear(), now.getMonth(), 1)
  selectedDate.value = localDateKey(now)
}
const dayAriaLabel = (cell: (typeof calendarCells.value)[number]) => {
  const date = dateFromKey(cell.key)
  const counts = [cell.opensCount ? `开放 ${cell.opensCount} 项` : '', cell.dueCount ? `截止 ${cell.dueCount} 项` : ''].filter(Boolean).join('，')
  return `${new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' }).format(date)}${counts ? `，${counts}` : '，无任务日期'}`
}

const loadEnrollments = async (taskRef: string, force = false): Promise<boolean> => {
  const cached = enrollmentViews.value[taskRef]
  if (!force && cached?.state === 'ready') return true
  const generation = ++enrollmentLoadGeneration
  const listEnrollments = frontendApi.listSchoolTaskEnrollments
  if (!listEnrollments) {
    enrollmentViews.value = { ...enrollmentViews.value, [taskRef]: { state: 'error', items: [], message: '当前运行环境未提供报名记录服务。' } }
    return false
  }
  enrollmentViews.value = { ...enrollmentViews.value, [taskRef]: { state: 'loading', items: cached?.items ?? [], message: '' } }
  try {
    const result = await listEnrollments(taskRef)
    if (disposed || generation !== enrollmentLoadGeneration) return false
    enrollmentViews.value = { ...enrollmentViews.value, [taskRef]: { state: 'ready', items: result.data, message: '' } }
    return true
  } catch (error) {
    if (disposed || generation !== enrollmentLoadGeneration) return false
    enrollmentViews.value = { ...enrollmentViews.value, [taskRef]: { state: 'error', items: cached?.items ?? [], message: requestMessage(error, '暂时无法读取报名记录。') } }
    return false
  }
}

watch(() => [detailTab.value, selectedTask.value?.task_ref] as const, ([tab, taskRef]) => {
  if (tab === 'enrollments' && taskRef) void loadEnrollments(taskRef)
})

const openRevokeDialog = (taskRef: string, enrollmentRef: string) => {
  operationError.value = ''
  revokeTarget.value = { taskRef, enrollmentRef }
}
const setRevokeOpen = (open: boolean) => {
  if (revokePending.value && !open) return
  if (!open) revokeTarget.value = null
}
const confirmRevoke = async () => {
  const target = revokeTarget.value
  const revoke = frontendApi.revokeSchoolTaskEnrollment
  if (!target || revokePending.value || !revoke) return
  revokePending.value = true
  operationError.value = ''
  notice.value = ''
  try {
    await revoke(target.taskRef, target.enrollmentRef)
    revokeTarget.value = null
    const refreshed = await loadEnrollments(target.taskRef, true)
    await loadTaskData(true)
    notice.value = refreshed ? '报名已撤销，列表已从服务端刷新。' : '服务端已确认撤销，但报名列表暂时无法刷新。'
  } catch (error) {
    operationError.value = requestMessage(error, '报名暂时无法撤销。')
  } finally {
    revokePending.value = false
  }
}

const openPublish = () => {
  publishError.value = ''
  publishStep.value = 0
  publishClassRef.value = classFilter.value !== 'all' ? classFilter.value : classes.value[0]?.class_ref ?? ''
  bindingMode.value = 'FIXTURE'
  selectedActivationRef.value = ''
  activations.value = []
  activationState.value = 'idle'
  activationHasMore.value = false
  activationSkip.value = 0
  opensAt.value = ''
  dueAt.value = ''
  publishOpen.value = true
}
const setPublishOpen = (open: boolean) => {
  if (publishPending.value && !open) return
  publishOpen.value = open
  if (!open) {
    publishError.value = ''
    activationLoadGeneration += 1
  }
}
const loadActivations = async (reset = true) => {
  const generation = ++activationLoadGeneration
  const skip = reset ? 0 : activationSkip.value
  if (reset) {
    activations.value = []
    activationSkip.value = 0
    activationHasMore.value = false
    selectedActivationRef.value = ''
  }
  activationState.value = 'loading'
  activationError.value = ''
  try {
    const page = await schoolCatActivations.list({ skip, limit: 30 })
    if (disposed || generation !== activationLoadGeneration || !publishOpen.value || bindingMode.value !== 'SAVED_VERSION') return
    const all = reset ? [] : activations.value
    const byRef = new Map(all.map((item) => [item.activation_ref, item]))
    for (const item of page.items) if (item.status === 'ACTIVE') byRef.set(item.activation_ref, item)
    activations.value = [...byRef.values()]
    activationSkip.value = skip + page.items.length
    activationHasMore.value = page.has_more
    activationState.value = 'ready'
  } catch (error) {
    if (disposed || generation !== activationLoadGeneration) return
    activations.value = []
    selectedActivationRef.value = ''
    activationHasMore.value = false
    activationState.value = 'error'
    activationError.value = requestMessage(error, '暂时无法读取已启用的测评版本。')
  }
}
const chooseBindingMode = (mode: 'FIXTURE' | 'SAVED_VERSION') => {
  if (publishPending.value || mode === bindingMode.value) return
  bindingMode.value = mode
  selectedActivationRef.value = ''
  activationError.value = ''
  if (mode === 'SAVED_VERSION') void loadActivations(true)
  else {
    activationLoadGeneration += 1
    activationState.value = 'idle'
    activationHasMore.value = false
  }
}
const selectedActivation = computed(() => activations.value.find((item) =>
  item.activation_ref === selectedActivationRef.value && item.status === 'ACTIVE',
) ?? null)
const publishStepCanContinue = computed(() => {
  if (publishStep.value === 0) return Boolean(publishClassRef.value)
    && (bindingMode.value === 'FIXTURE' || (activationState.value === 'ready' && Boolean(selectedActivation.value)))
  if (publishStep.value === 1) {
    if (!opensAt.value) return false
    const opens = new Date(opensAt.value)
    const due = dueAt.value ? new Date(dueAt.value) : null
    return !Number.isNaN(opens.getTime()) && (!due || (!Number.isNaN(due.getTime()) && due.getTime() >= opens.getTime()))
  }
  return publishStep.value === 2 && Boolean(publishClassRef.value && opensAt.value)
})
const publishStepHint = computed(() => {
  if (publishStep.value === 0) {
    if (!publishClassRef.value) return '请选择班级。'
    if (bindingMode.value === 'SAVED_VERSION' && activationState.value === 'loading') return '正在读取已启用版本。'
    if (bindingMode.value === 'SAVED_VERSION' && activationState.value === 'error') return activationError.value || '版本列表暂不可用。'
    if (bindingMode.value === 'SAVED_VERSION' && !selectedActivation.value) return '请选择服务端返回的已启用版本。'
  }
  if (publishStep.value === 1) {
    if (!opensAt.value) return '请设置开放时间。'
    const opens = new Date(opensAt.value)
    const due = dueAt.value ? new Date(dueAt.value) : null
    if (Number.isNaN(opens.getTime()) || (due && (Number.isNaN(due.getTime()) || due.getTime() < opens.getTime()))) return '截止时间不能早于开放时间。'
  }
  return ''
})
const publishClass = computed(() => classes.value.find((item) => item.class_ref === publishClassRef.value) ?? null)
const publishTask = async () => {
  const publish = frontendApi.publishSchoolTask
  if (publishStep.value !== 2 || !publishStepCanContinue.value || publishPending.value || !publishClassRef.value || !publish) return
  const activation = bindingMode.value === 'SAVED_VERSION' ? selectedActivation.value : null
  if (bindingMode.value === 'SAVED_VERSION' && (activationState.value !== 'ready' || !activation)) {
    publishError.value = '可用版本列表尚未读取成功。请重新读取后再发布。'
    return
  }
  const opens = new Date(opensAt.value)
  const due = dueAt.value ? new Date(dueAt.value) : null
  if (Number.isNaN(opens.getTime()) || (due && (Number.isNaN(due.getTime()) || due < opens))) {
    publishError.value = '截止时间不能早于开放时间。'
    return
  }
  publishPending.value = true
  publishError.value = ''
  notice.value = ''
  try {
    const result = activation
      ? await publish(publishClassRef.value, opens.toISOString(), due?.toISOString() ?? null, activation.activation_ref)
      : await publish(publishClassRef.value, opens.toISOString(), due?.toISOString() ?? null)
    const created = result.data
    publishOpen.value = false
    publishStep.value = 0
    classFilter.value = classes.value.some((item) => item.class_ref === created.class_ref) ? created.class_ref : 'all'
    statusFilter.value = 'all'
    searchQuery.value = ''
    detailTab.value = 'overview'
    const refreshed = await loadTaskData(true)
    if (!entries.value.some((entry) => entry.task.task_ref === created.task_ref && entry.task.class_ref === created.class_ref)) {
      const createdClass = classes.value.find((item) => item.class_ref === created.class_ref)
      entries.value = [...entries.value, {
        key: entryKey(created), task: created,
        classLabel: createdClass ? classLabel(createdClass) : `班级 ${shortRef(created.class_ref)}`,
      }]
    }
    selectedTaskKey.value = entryKey(created)
    notice.value = refreshed
      ? '服务端已确认发布，任务列表已更新。'
      : '服务端已确认发布；列表刷新暂不可用，已保留发布接口返回的任务记录。'
  } catch (error) {
    publishError.value = requestMessage(error, '任务暂时无法发布。服务端未确认前不会显示成功。')
  } finally {
    publishPending.value = false
  }
}

const ratioWidth = (value: number) => totalEnrollmentBreakdown.value > 0
  ? `${Math.min(100, Math.max(0, value / totalEnrollmentBreakdown.value * 100))}%`
  : '0%'

onMounted(() => {
  void loadTaskData()
  clockTimer = window.setInterval(() => { clockNow.value = Date.now() }, 60_000)
})
onBeforeUnmount(() => {
  disposed = true
  taskLoadGeneration += 1
  activationLoadGeneration += 1
  enrollmentLoadGeneration += 1
  if (clockTimer !== undefined) window.clearInterval(clockTimer)
})
</script>

<template>
  <section class="admin-task-page" aria-labelledby="admin-task-page-title" :aria-busy="pageState === 'loading'">
    <header class="task-page-heading">
      <div>
        <h1 id="admin-task-page-title">测评任务</h1>
        <p>班级测评发布与开放时间管理</p>
      </div>
      <AppButton variant="primary" :disabled="pageState !== 'ready' || !classes.length || publishPending" @click="openPublish">
        <Plus :size="16" aria-hidden="true" />发布测评
      </AppButton>
    </header>

    <AppStatusCallout v-if="listError && pageState !== 'error'" tone="attention" title="任务列表未完整更新" :body="listError" role="status" />
    <AppStatusCallout v-if="pageState === 'error'" tone="critical" title="任务列表不可用" :body="listError" role="alert" />
    <AppStatusCallout v-if="notice" tone="info" title="服务端已确认" :body="notice" role="status" />
    <AppStatusCallout v-if="operationError && !revokeTarget" tone="critical" title="操作未完成" :body="operationError" role="alert" />

    <AppCard class="task-summary" aria-label="任务概况">
      <div class="task-summary__scope"><span>任务概况</span><small>{{ classScopeNote }}</small></div>
      <dl class="task-summary__metrics">
        <div><dt>全部任务</dt><dd>{{ pageState === 'ready' ? summaryCounts.all : '—' }}</dd></div>
        <div><dt>开放中</dt><dd>{{ pageState === 'ready' ? summaryCounts.open : '—' }}</dd></div>
        <div><dt>即将开放</dt><dd>{{ pageState === 'ready' ? summaryCounts.upcoming : '—' }}</dd></div>
        <div><dt>已截止</dt><dd>{{ pageState === 'ready' ? summaryCounts.ended : '—' }}</dd></div>
      </dl>
    </AppCard>

    <AppCard class="task-filterbar" aria-label="任务筛选与视图切换">
      <div class="task-search">
        <label for="admin-task-search" class="sr-only">搜索测评、班级或编号</label>
        <Search :size="16" aria-hidden="true" />
        <input id="admin-task-search" ref="searchInput" v-model="searchQuery" type="search" autocomplete="off" placeholder="搜索测评、班级或编号">
        <button v-if="searchQuery" type="button" aria-label="清除搜索" @click="clearSearch"><X :size="14" aria-hidden="true" /></button>
      </div>
      <TeacherClassSelect v-model="classFilter" :options="classOptions" aria-label="按班级筛选" :disabled="pageState !== 'ready' || !classes.length" />
      <TeacherClassSelect v-model="statusFilterModel" :options="statusOptions" aria-label="按任务状态筛选" :disabled="pageState !== 'ready' || !entries.length" />
      <div class="task-view-switch" role="group" aria-label="任务视图" :class="`task-view-switch--${viewMode}`">
        <span class="task-view-switch__indicator" aria-hidden="true" />
        <button type="button" :aria-pressed="viewMode === 'timeline'" @click="setViewMode('timeline')"><ListChecks :size="14" aria-hidden="true" />时间轴</button>
        <button type="button" :aria-pressed="viewMode === 'calendar'" @click="setViewMode('calendar')"><CalendarDays :size="14" aria-hidden="true" />日历</button>
      </div>
      <button v-if="hasActiveFilters" class="task-filterbar__clear" type="button" @click="clearFilters">清除筛选</button>
    </AppCard>

    <AppCard class="task-workbench" aria-label="测评任务工作台">
      <header class="task-workbench__header">
        <div><h2>{{ viewMode === 'timeline' ? '任务时间轴' : '任务日历' }}</h2><p>{{ viewMode === 'timeline' ? '按开放时间排序' : '查看任务开放与截止日期' }}</p></div>
        <button class="task-refresh" type="button" :disabled="pageState === 'loading'" @click="loadTaskData()"><RefreshCw :size="15" aria-hidden="true" />刷新</button>
      </header>

      <div v-if="pageState === 'loading'" class="task-workbench__state" role="status" aria-live="polite" aria-busy="true">
        <span class="task-skeleton" aria-hidden="true" />正在读取本校班级任务
      </div>
      <div v-else-if="pageState === 'error'" class="task-workbench__state task-workbench__state--error" role="alert">{{ listError }}</div>
      <div v-else class="task-workbench__body">
        <section class="task-workbench__list" aria-label="任务列表">
          <template v-if="viewMode === 'timeline'">
            <ol v-if="visibleEntries.length" class="task-timeline">
              <li v-for="entry in visibleEntries" :key="entry.key" class="task-timeline__item">
                <div class="task-timeline__date"><span>{{ entry.task.opens_at ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric' }).format(new Date(entry.task.opens_at)) : '—' }}</span><strong>{{ entry.task.opens_at ? new Intl.DateTimeFormat('zh-CN', { day: '2-digit' }).format(new Date(entry.task.opens_at)) : '—' }}</strong></div>
                <button type="button" class="task-ticket" :class="{ 'task-ticket--selected': selectedEntry?.key === entry.key }" :aria-pressed="selectedEntry?.key === entry.key" @click="selectEntry(entry)">
                  <span class="task-ticket__title-row"><strong>{{ taskTitle(entry) }}</strong><span class="task-state" :class="statusTone(windowState(entry.task))">{{ windowStateLabel(windowState(entry.task)) }}</span></span>
                  <span class="task-ticket__meta">{{ entry.classLabel }}<template v-if="entry.task.plan_name"> · {{ taskConfiguration(entry.task) }}</template><template v-else-if="entry.task.instrument_version"> · {{ taskConfiguration(entry.task) }}</template></span>
                  <span class="task-ticket__times"><span><Clock3 :size="13" aria-hidden="true" />{{ formatDate(entry.task.opens_at) }}</span><span aria-hidden="true">→</span><span>{{ formatDate(entry.task.due_at, '无截止时间') }}</span></span>
                  <span class="task-ticket__footer"><span>报名 {{ entry.task.active_enrollment_count }}<template v-if="entry.task.revoked_enrollment_count"> · 已撤销 {{ entry.task.revoked_enrollment_count }}</template></span><span>编号 {{ shortRef(entry.task.task_ref) }}</span></span>
                </button>
              </li>
            </ol>
            <div v-else class="task-list-empty"><span class="task-list-empty__icon"><ListChecks :size="20" aria-hidden="true" /></span><strong>{{ entries.length ? '没有符合条件的任务' : failedClassRefs.length === classes.length && classes.length ? '班级任务暂时不可用' : '当前没有可显示的任务' }}</strong><p>{{ entries.length ? '调整搜索内容或筛选条件' : failedClassRefs.length === classes.length && classes.length ? '请稍后刷新本校班级任务' : '服务端返回的班级中暂无测评任务' }}</p><button v-if="hasActiveFilters" type="button" @click="clearFilters">清除筛选</button></div>
          </template>

          <section v-else class="task-calendar" aria-label="测评任务日历">
            <header class="task-calendar__navigation">
              <div><strong>{{ monthLabel }}</strong><button type="button" class="task-calendar__today" @click="goToToday">回到本月</button></div>
              <div><button type="button" aria-label="上个月" @click="changeMonth(-1)"><ChevronLeft :size="16" aria-hidden="true" /></button><button type="button" aria-label="下个月" @click="changeMonth(1)"><ChevronRight :size="16" aria-hidden="true" /></button></div>
            </header>
            <div class="task-calendar__grid" role="grid" aria-label="周一至周日">
              <span v-for="day in weekdays" :key="day" class="task-calendar__weekday" role="columnheader">{{ day }}</span>
              <button v-for="cell in calendarCells" :key="cell.key" type="button" class="task-calendar__day" :class="{ 'task-calendar__day--outside': !cell.inMonth, 'task-calendar__day--today': cell.isToday, 'task-calendar__day--selected': cell.isSelected, 'task-calendar__day--has-events': cell.eventCount }" role="gridcell" :aria-label="dayAriaLabel(cell)" :aria-pressed="cell.isSelected" @click="selectDate(cell.key)">
                <span>{{ cell.day }}</span>
                <span v-if="cell.eventCount" class="task-calendar__markers" aria-hidden="true"><i v-if="cell.opensCount" class="task-calendar__marker task-calendar__marker--opens" /><i v-if="cell.dueCount" class="task-calendar__marker task-calendar__marker--due" /><small>{{ cell.eventCount }}</small></span>
              </button>
            </div>
            <section class="task-calendar__agenda" aria-live="polite">
              <header><div><strong>{{ selectedDateLabel }}</strong><span>{{ selectedDateTasks.length }} 项</span></div><div class="task-calendar__legend"><span><i class="task-calendar__marker--opens" />开放</span><span><i class="task-calendar__marker--due" />截止</span></div></header>
              <div v-if="selectedDateTasks.length" class="task-calendar__agenda-list">
                <button v-for="item in selectedDateTasks" :key="item.entry.key" type="button" class="task-calendar__agenda-item" :class="{ 'task-calendar__agenda-item--selected': selectedEntry?.key === item.entry.key }" @click="selectEntry(item.entry)">
                  <span class="task-calendar__agenda-markers"><i v-if="item.opens" class="task-calendar__marker--opens" /><i v-if="item.due" class="task-calendar__marker--due" /></span>
                  <span><strong>{{ taskTitle(item.entry) }}</strong><small>{{ item.entry.classLabel }} · {{ item.opens ? '开放' : '' }}{{ item.opens && item.due ? '、' : '' }}{{ item.due ? '截止' : '' }}</small></span>
                  <ChevronRight :size="15" aria-hidden="true" />
                </button>
              </div>
              <p v-else class="task-calendar__empty">当天没有开放或截止事件</p>
            </section>
          </section>
        </section>

        <aside class="task-workbench__detail" aria-label="任务详情">
          <template v-if="selectedEntry && selectedTask">
            <header class="task-detail__heading">
              <div><span>任务详情</span><h3>{{ taskTitle(selectedEntry) }}</h3><code>{{ selectedTask.task_ref }}</code></div>
              <span class="task-state" :class="statusTone(selectedState)">{{ windowStateLabel(selectedState) }}</span>
            </header>
            <div class="task-detail__server-status"><span>服务端状态</span><strong>{{ serverStatusLabel(selectedTask.status) }}</strong></div>
            <WorkspaceTabs v-model="detailTab" id="admin-task-detail-tabs" label="任务详情分区" :tabs="detailTabs">
              <template #panel="{ tab }">
                <section v-if="tab.value === 'overview'" class="task-detail__overview" aria-label="任务概况">
                  <dl class="task-detail__facts">
                    <div><dt>所属班级</dt><dd>{{ selectedEntry.classLabel }}</dd></div>
                    <div><dt>测评版本</dt><dd>{{ taskConfiguration(selectedTask) }}</dd></div>
                    <div><dt>开放时间</dt><dd>{{ formatDate(selectedTask.opens_at) }}</dd></div>
                    <div><dt>截止时间</dt><dd>{{ formatDate(selectedTask.due_at, '未设置') }}</dd></div>
                  </dl>
                  <section class="task-detail__enrollment-summary" aria-label="报名汇总">
                    <h4>报名记录</h4>
                    <dl><div><dt>报名条目</dt><dd>{{ selectedTask.published_enrollment_count }}</dd></div><div><dt>当前有效</dt><dd>{{ selectedTask.active_enrollment_count }}</dd></div><div><dt>已撤销</dt><dd>{{ selectedTask.revoked_enrollment_count }}</dd></div></dl>
                    <div v-if="enrollmentBreakdownConsistent && totalEnrollmentBreakdown" class="task-detail__ratio" role="img" :aria-label="`有效报名 ${selectedTask.active_enrollment_count}，已撤销 ${selectedTask.revoked_enrollment_count}`"><span :style="{ width: ratioWidth(selectedTask.active_enrollment_count) }" /><i :style="{ width: ratioWidth(selectedTask.revoked_enrollment_count) }" /></div>
                    <p v-else-if="selectedTask.published_enrollment_count" class="task-detail__ratio-note">报名分类与总数不一致，按服务端原值显示</p>
                  </section>
                  <p class="task-detail__privacy-note">此处仅显示任务与报名编号，不展示学生身份、心理内容或测评结果</p>
                </section>

                <section v-else-if="tab.value === 'enrollments'" class="task-detail__enrollments" aria-label="报名记录">
                  <header><div><h4>报名记录</h4><p>仅显示服务端返回的编号与状态</p></div><button type="button" :disabled="enrollmentViewsForSelected?.state === 'loading'" @click="loadEnrollments(selectedTask.task_ref, true)"><RefreshCw :size="14" aria-hidden="true" />刷新</button></header>
                  <div v-if="enrollmentViewsForSelected?.state === 'loading'" class="task-detail__tab-state" role="status" aria-busy="true">正在读取报名记录</div>
                  <div v-else-if="enrollmentViewsForSelected?.state === 'error'" class="task-detail__tab-state task-detail__tab-state--error" role="alert">{{ enrollmentViewsForSelected.message }}<button type="button" @click="loadEnrollments(selectedTask.task_ref, true)">重新读取</button></div>
                  <div v-else-if="!enrollmentViewsForSelected || enrollmentViewsForSelected.state !== 'ready'" class="task-detail__tab-state" role="status">正在读取报名记录</div>
                  <div v-else-if="!enrollmentViewsForSelected.items.length" class="task-detail__tab-state">当前没有可显示的报名记录</div>
                  <ul v-else class="task-enrollment-list">
                    <li v-for="enrollment in enrollmentViewsForSelected.items" :key="enrollment.enrollment_ref">
                      <div><span class="task-enrollment-list__ref">{{ shortRef(enrollment.enrollment_ref) }}</span><span class="task-enrollment-list__status" :class="{ 'task-enrollment-list__status--revoked': isEnrollmentRevoked(enrollment.status) }">{{ enrollmentStatusLabel(enrollment.status) }}</span></div>
                      <AppButton v-if="!isEnrollmentRevoked(enrollment.status)" variant="quiet" size="sm" :disabled="revokePending" @click="openRevokeDialog(selectedTask.task_ref, enrollment.enrollment_ref)">撤销报名</AppButton>
                    </li>
                  </ul>
                </section>

                <section v-else class="task-detail__assignments" aria-label="专业人员分配">
                  <AdminProfessionalAssignments v-if="assignmentTaskForSelected.length" :key="selectedTaskKey" :tasks="assignmentTaskForSelected" />
                  <div v-else class="task-detail__tab-state">暂无可显示的分配信息</div>
                </section>
              </template>
            </WorkspaceTabs>
          </template>
          <div v-else class="task-detail-empty"><span><ListChecks :size="20" aria-hidden="true" /></span><strong>{{ visibleEntries.length ? '选择一项任务' : '暂无任务详情' }}</strong><p>{{ visibleEntries.length ? '选择左侧任务查看概况、报名记录和专业分配' : '调整筛选条件或等待服务端返回任务' }}</p></div>
        </aside>
      </div>
    </AppCard>

    <AppDialog :open="publishOpen" title="发布测评" description="选择班级和测评配置，设置开放时间后确认发布" @update:open="setPublishOpen">
      <div class="publish-dialog">
        <ol class="publish-steps" aria-label="发布测评步骤">
          <li v-for="(step, index) in publishSteps" :key="step" :class="{ 'publish-steps__item--active': publishStep === index, 'publish-steps__item--done': publishStep > index }" :aria-current="publishStep === index ? 'step' : undefined"><span>{{ publishStep > index ? '✓' : index + 1 }}</span><strong>{{ step }}</strong></li>
        </ol>
        <section v-if="publishStep === 0" class="publish-step-panel">
          <label for="admin-publish-class">目标班级</label>
          <select id="admin-publish-class" v-model="publishClassRef" :disabled="publishPending || !classes.length"><option value="" disabled>请选择班级</option><option v-for="item in classes" :key="item.class_ref" :value="item.class_ref">{{ classLabel(item) }}</option></select>
          <span class="publish-step-panel__label">测评配置</span>
          <div class="publish-config-choice" role="group" aria-label="测评配置来源">
            <button type="button" :aria-pressed="bindingMode === 'FIXTURE'" :disabled="publishPending" @click="chooseBindingMode('FIXTURE')"><strong>默认工程模板</strong><small>使用当前服务端默认配置</small></button>
            <button type="button" :aria-pressed="bindingMode === 'SAVED_VERSION'" :disabled="publishPending" @click="chooseBindingMode('SAVED_VERSION')"><strong>已启用版本</strong><small>选择本校服务端启用记录</small></button>
          </div>
          <template v-if="bindingMode === 'SAVED_VERSION'">
            <label for="admin-publish-activation">测评版本</label>
            <select id="admin-publish-activation" v-model="selectedActivationRef" :disabled="activationState !== 'ready' || !activations.length || publishPending"><option value="">请选择已启用版本</option><option v-for="item in activations" :key="item.activation_ref" :value="item.activation_ref">{{ item.plan_name }} v{{ item.plan_version_number }} · {{ item.bank_name }} v{{ item.bank_version_number }}</option></select>
            <div v-if="activationState === 'loading'" class="publish-step-panel__message" role="status" aria-busy="true">正在读取已启用版本</div>
            <div v-else-if="activationState === 'error'" class="publish-step-panel__message publish-step-panel__message--error" role="alert">{{ activationError }}<button type="button" @click="loadActivations(true)">重新读取</button></div>
            <div v-else-if="activationState === 'ready' && !activations.length" class="publish-step-panel__message">当前没有可用的已启用版本</div>
            <button v-if="activationHasMore" class="publish-load-more" type="button" :disabled="activationState === 'loading'" @click="loadActivations(false)">加载更多版本</button>
          </template>
        </section>
        <section v-else-if="publishStep === 1" class="publish-step-panel">
          <label for="admin-publish-opens">开放时间（本地时间）</label><input id="admin-publish-opens" v-model="opensAt" type="datetime-local" :disabled="publishPending" required>
          <label for="admin-publish-due">截止时间（可选，本地时间）</label><input id="admin-publish-due" v-model="dueAt" type="datetime-local" :disabled="publishPending">
          <p>截止时间可留空；如填写，不能早于开放时间</p>
        </section>
        <section v-else class="publish-step-panel">
          <dl class="publish-summary">
            <div><dt>目标班级</dt><dd>{{ publishClass ? classLabel(publishClass) : '未选择' }}</dd></div>
            <div><dt>测评配置</dt><dd>{{ selectedActivation ? `${selectedActivation.plan_name} v${selectedActivation.plan_version_number} · ${selectedActivation.bank_name} v${selectedActivation.bank_version_number}` : '默认工程模板' }}</dd></div>
            <div><dt>开放时间</dt><dd>{{ opensAt ? formatLocalDraft(opensAt) : '未设置' }}</dd></div>
            <div><dt>截止时间</dt><dd>{{ dueAt ? formatLocalDraft(dueAt) : '未设置' }}</dd></div>
          </dl>
          <p>任务发布后以服务端返回记录为准</p>
        </section>
        <p v-if="publishStepHint" class="publish-hint" role="status">{{ publishStepHint }}</p>
        <p v-if="publishError" class="publish-error" role="alert">{{ publishError }}</p>
        <div class="publish-dialog__actions">
          <AppButton variant="secondary" :disabled="publishPending" @click="publishStep === 0 ? setPublishOpen(false) : publishStep -= 1">{{ publishStep === 0 ? '取消' : '上一步' }}</AppButton>
          <AppButton v-if="publishStep < 2" variant="primary" :disabled="publishPending || !publishStepCanContinue" @click="publishStep += 1">下一步<ChevronRight :size="15" aria-hidden="true" /></AppButton>
          <AppButton v-else variant="primary" :disabled="publishPending || !publishStepCanContinue" :loading="publishPending" @click="publishTask">确认发布</AppButton>
        </div>
      </div>
    </AppDialog>

    <AppDialog :open="Boolean(revokeTarget)" title="撤销报名" description="撤销后该报名将不能继续访问对应任务。" @update:open="setRevokeOpen">
      <div class="revoke-dialog">
        <p>报名编号 · {{ revokeTarget ? shortRef(revokeTarget.enrollmentRef) : '' }}</p>
        <p v-if="operationError" class="publish-error" role="alert">{{ operationError }}</p>
        <div class="publish-dialog__actions"><AppButton variant="secondary" :disabled="revokePending" @click="setRevokeOpen(false)">取消</AppButton><AppButton variant="primary" :disabled="revokePending" :loading="revokePending" @click="confirmRevoke">确认撤销</AppButton></div>
      </div>
    </AppDialog>
  </section>
</template>

<style scoped>
.admin-task-page { display: grid; gap: 16px; min-width: 0; padding: 2px 0 34px; color: var(--color-text-primary); }
.task-page-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.task-page-heading h1 { margin: 0; color: var(--color-text-primary); font-size: 24px; font-weight: 730; letter-spacing: -.025em; }
.task-page-heading p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 13px; }
.task-summary { display: grid; grid-template-columns: minmax(140px,.75fr) minmax(0,3fr); align-items: center; gap: 14px; padding: 14px 18px; }
.task-summary__scope { display: grid; gap: 5px; min-width: 0; }
.task-summary__scope > span { color: #355060; font-size: 13px; font-weight: 700; }
.task-summary__scope small { color: var(--color-text-muted); font-size: 10px; line-height: 1.45; }
.task-summary__metrics { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); margin: 0; }
.task-summary__metrics > div { min-width: 0; padding: 2px 16px; border-left: 1px solid #edf0f2; }
.task-summary__metrics dt { color: var(--color-text-muted); font-size: 11px; }
.task-summary__metrics dd { margin: 4px 0 0; color: #293f4d; font-size: 21px; font-weight: 730; font-variant-numeric: tabular-nums; }
.task-summary__metrics > div:nth-child(2) dd { color: #168a78; }
.task-summary__metrics > div:nth-child(3) dd { color: #418eae; }
.task-summary__metrics > div:nth-child(4) dd { color: #7d8891; }
.task-filterbar { display: grid; grid-template-columns: minmax(220px,1.4fr) minmax(150px,.85fr) minmax(135px,.72fr) auto; align-items: center; gap: 9px; padding: 11px 12px; }
.task-search { position: relative; display: flex; min-width: 0; min-height: 38px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-muted); background: var(--color-surface); transition: border-color 160ms ease, box-shadow 160ms ease; }
.task-search:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(0 177 226 / 12%); }
.task-search > svg { flex: 0 0 auto; color: #78909d; }
.task-search input { width: 100%; min-width: 0; height: 34px; padding: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 12px; }
.task-search input::placeholder { color: #94a1a9; }
.task-search input:focus-visible { outline: none; }
.task-search input::-webkit-search-cancel-button { display: none; }
.task-search > button { display: grid; width: 24px; height: 24px; flex: 0 0 24px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: #7d8e98; background: transparent; cursor: pointer; }
.task-search > button:hover { color: var(--color-primary-active); background: var(--color-surface-blue); }
.task-view-switch { position: relative; display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); min-height: 38px; padding: 3px; border: 1px solid #e5edf0; border-radius: var(--radius-button); background: var(--color-surface-blue); isolation: isolate; }
.task-view-switch__indicator { position: absolute; z-index: 0; top: 3px; bottom: 3px; left: 3px; width: calc((100% - 6px) / 2); border: 1px solid #e1e9ed; border-radius: 6px; background: #fff; box-shadow: 0 1px 4px rgb(31 63 78 / 10%); transition: transform 200ms cubic-bezier(.22,1,.36,1); pointer-events: none; }
.task-view-switch--calendar .task-view-switch__indicator { transform: translateX(100%); }
.task-view-switch button { position: relative; z-index: 1; display: flex; min-width: 0; align-items: center; justify-content: center; gap: 5px; padding: 0 8px; border: 0; border-radius: 6px; color: #687e8b; background: transparent; font: inherit; font-size: 11px; cursor: pointer; }
.task-view-switch button[aria-pressed='true'] { color: var(--color-primary-active); font-weight: 680; }
.task-filterbar__clear { grid-column: 1 / -1; justify-self: end; padding: 1px 4px; border: 0; color: var(--color-primary-active); background: transparent; font: inherit; font-size: 11px; cursor: pointer; }
.task-workbench { overflow: hidden; }
.task-workbench__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 17px 19px; border-bottom: 1px solid #edf0f2; }
.task-workbench__header h2 { margin: 0; color: #294554; font-size: 16px; font-weight: 720; }
.task-workbench__header p { margin: 4px 0 0; color: var(--color-text-muted); font-size: 11px; }
.task-refresh { display: inline-flex; min-height: 34px; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid var(--color-border); border-radius: var(--radius-button); color: var(--color-text-secondary); background: #fff; font: inherit; font-size: 11px; cursor: pointer; }
.task-refresh:hover:not(:disabled) { border-color: #a8d4df; color: var(--color-primary-active); background: #f8fcfd; }
.task-refresh:disabled { opacity: .55; cursor: wait; }
.task-workbench__body { display: grid; grid-template-columns: minmax(0,1.04fr) minmax(0,.96fr); min-height: 510px; }
.task-workbench__list { min-width: 0; padding: 16px; border-right: 1px solid #edf0f2; }
.task-workbench__detail { min-width: 0; padding: 18px; background: #fff; }
.task-timeline { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.task-timeline__item { display: grid; grid-template-columns: 44px minmax(0,1fr); gap: 10px; align-items: stretch; }
.task-timeline__date { display: grid; align-content: start; justify-items: center; gap: 1px; padding-top: 13px; color: #758b96; font-size: 10px; }
.task-timeline__date strong { color: #344f5e; font-size: 17px; font-variant-numeric: tabular-nums; }
.task-ticket { display: grid; gap: 7px; width: 100%; min-width: 0; padding: 12px 13px; border: 1px solid #e6edf0; border-radius: 10px; color: inherit; background: #fff; text-align: left; cursor: pointer; transition: border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease; }
.task-ticket:hover { border-color: #b7dce5; background: #fbfeff; }
.task-ticket--selected { border-color: #77c9dc; background: #f1fbfd; box-shadow: inset 3px 0 #35b6d1; }
.task-ticket:focus-visible,.task-calendar__day:focus-visible,.task-calendar__agenda-item:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.task-ticket__title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; min-width: 0; }
.task-ticket__title-row > strong { overflow: hidden; color: #2e4a5a; font-size: 13px; font-weight: 700; text-overflow: ellipsis; }
.task-state { display: inline-flex; flex: 0 0 auto; align-items: center; padding: 3px 7px; border-radius: 999px; font-size: 10px; font-weight: 700; line-height: 1.3; white-space: nowrap; }
.task-state--open { color: #247765; background: #eaf5f1; }
.task-state--upcoming { color: #397a97; background: #eaf5f9; }
.task-state--ended { color: #697782; background: #eef1f3; }
.task-state--cancelled { color: #8f6a48; background: #f7f0e8; }
.task-state--unknown { color: #8b6a2d; background: #faf4e7; }
.task-ticket__meta { overflow: hidden; color: #748995; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.task-ticket__times { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; color: #556d7a; font-size: 10px; }
.task-ticket__times > span:first-child { display: inline-flex; align-items: center; gap: 4px; }
.task-ticket__times svg { color: #78919c; }
.task-ticket__footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 5px 10px; padding-top: 6px; border-top: 1px solid #f0f3f5; color: #7f919a; font-size: 10px; }
.task-list-empty,.task-detail-empty { display: grid; min-height: 270px; align-content: center; justify-items: center; gap: 9px; padding: 25px; color: var(--color-text-secondary); text-align: center; }
.task-list-empty__icon,.task-detail-empty > span { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 13px; color: var(--color-primary-active); background: #eaf7fa; }
.task-list-empty strong,.task-detail-empty strong { color: #3d5967; font-size: 13px; }
.task-list-empty p,.task-detail-empty p { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.55; }
.task-list-empty button { border: 0; color: var(--color-primary-active); background: transparent; font: inherit; font-size: 11px; cursor: pointer; }
.task-detail__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid #edf0f2; }
.task-detail__heading > div { min-width: 0; }
.task-detail__heading > div > span { color: #72909e; font-size: 10px; font-weight: 680; }
.task-detail__heading h3 { overflow: hidden; margin: 4px 0; color: #294655; font-size: 16px; font-weight: 720; text-overflow: ellipsis; }
.task-detail__heading code { display: block; overflow-wrap: anywhere; color: #96a2a8; font-family: var(--font-mono); font-size: 9px; }
.task-detail__server-status { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0 12px; color: #82939a; font-size: 11px; }
.task-detail__server-status strong { color: #506977; font-size: 11px; font-weight: 680; }
.task-detail__overview { display: grid; gap: 15px; padding-top: 13px; }
.task-detail__facts { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 1px; overflow: hidden; margin: 0; border: 1px solid #e8eef1; border-radius: 10px; background: #e8eef1; }
.task-detail__facts > div { display: grid; gap: 5px; min-width: 0; padding: 11px 12px; background: #fff; }
.task-detail__facts dt,.task-detail__enrollment-summary dt { color: #86969d; font-size: 10px; }
.task-detail__facts dd { overflow: hidden; margin: 0; color: #425b68; font-size: 12px; font-weight: 650; text-overflow: ellipsis; }
.task-detail__enrollment-summary { display: grid; gap: 10px; }
.task-detail__enrollment-summary h4,.task-detail__enrollments h4 { margin: 0; color: #3c5664; font-size: 13px; }
.task-detail__enrollment-summary dl { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; margin: 0; }
.task-detail__enrollment-summary dl > div { display: grid; gap: 5px; padding: 10px; border: 1px solid #e9eef0; border-radius: 9px; background: #fbfcfd; }
.task-detail__enrollment-summary dd { margin: 0; color: #314e5c; font-size: 17px; font-weight: 720; font-variant-numeric: tabular-nums; }
.task-detail__ratio { display: flex; height: 6px; overflow: hidden; border-radius: 999px; background: #eef2f4; }
.task-detail__ratio span { background: #26a9c5; }.task-detail__ratio i { background: #e5aa6f; }
.task-detail__ratio-note,.task-detail__privacy-note { margin: 0; color: #83939a; font-size: 10px; line-height: 1.5; }
.task-detail__privacy-note { padding-top: 10px; border-top: 1px solid #edf0f2; }
.task-detail__enrollments { display: grid; gap: 12px; padding-top: 13px; }
.task-detail__enrollments > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.task-detail__enrollments > header p { margin: 4px 0 0; color: #84949c; font-size: 10px; }
.task-detail__enrollments > header button { display: inline-flex; min-height: 30px; align-items: center; gap: 5px; padding: 0 8px; border: 1px solid #e3eaed; border-radius: 7px; color: #5c7581; background: #fff; font: inherit; font-size: 10px; cursor: pointer; }
.task-detail__enrollments > header button:disabled { opacity: .55; cursor: wait; }
.task-enrollment-list { display: grid; gap: 7px; max-height: 310px; overflow-y: auto; margin: 0; padding: 0 2px 0 0; list-style: none; }
.task-enrollment-list li { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-width: 0; padding: 8px 10px; border: 1px solid #e8edf0; border-radius: 8px; }
.task-enrollment-list li > div { display: flex; align-items: center; gap: 9px; min-width: 0; }
.task-enrollment-list__ref { color: #526d7a; font-family: var(--font-mono); font-size: 11px; }
.task-enrollment-list__status { color: #25826f; font-size: 10px; font-weight: 700; }
.task-enrollment-list__status--revoked { color: #8b969c; }
.task-detail__tab-state { display: grid; min-height: 150px; align-content: center; justify-items: center; gap: 8px; padding: 18px; border: 1px dashed #dce7eb; border-radius: 9px; color: #71858f; background: #fbfcfd; font-size: 11px; text-align: center; }
.task-detail__tab-state--error { color: #8d6427; background: #fcf8ef; }
.task-detail__tab-state button { border: 0; color: var(--color-primary-active); background: transparent; font: inherit; cursor: pointer; }
.task-detail__assignments { padding-top: 12px; }
.task-detail__assignments :deep(.professional-assignments) { padding: 0; border: 0; box-shadow: none; }
.task-detail__assignments :deep(.professional-assignments__title) { color: var(--color-primary-active); }
.task-detail__assignments :deep(.professional-assignments__title p) { display: none; }
.task-detail__assignments :deep(.professional-assignments__form) { grid-template-columns: 92px minmax(0,1fr); gap: 8px; max-width: none; }
.task-detail__assignments :deep(.professional-assignments__form label) { font-size: 11px; }
.task-detail__assignments :deep(.professional-assignments__form select) { min-height: 36px; font-size: 11px; }
.task-detail__assignments :deep(.professional-assignments__row) { padding: 8px 10px; }
.task-detail__assignments :deep(.professional-assignments__row p) { font-size: 10px; }
.task-calendar { min-width: 0; }
.task-calendar__navigation { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 0 10px; }
.task-calendar__navigation > div { display: flex; align-items: center; gap: 7px; }
.task-calendar__navigation strong { color: #35515f; font-size: 15px; }
.task-calendar__today { padding: 4px 7px; border: 1px solid #e4ebee; border-radius: 6px; color: #54717e; background: #fff; font: inherit; font-size: 10px; cursor: pointer; }
.task-calendar__navigation > div:last-child button { display: grid; width: 29px; height: 29px; place-items: center; border: 1px solid #e4ebee; border-radius: 7px; color: #617984; background: #fff; cursor: pointer; }
.task-calendar__grid { display: grid; grid-template-columns: repeat(7,minmax(0,1fr)); border-top: 1px solid #edf1f3; border-left: 1px solid #edf1f3; }
.task-calendar__weekday { display: grid; min-height: 30px; place-items: center; border-right: 1px solid #edf1f3; border-bottom: 1px solid #edf1f3; color: #83939a; font-size: 10px; }
.task-calendar__day { display: flex; min-width: 0; min-height: 54px; flex-direction: column; align-items: flex-start; justify-content: space-between; padding: 6px 7px; border: 0; border-right: 1px solid #edf1f3; border-bottom: 1px solid #edf1f3; color: #526a76; background: #fff; text-align: left; font: inherit; font-size: 11px; cursor: pointer; transition: background-color 160ms ease, box-shadow 160ms ease; }
.task-calendar__day:hover { background: #f5fbfd; }
.task-calendar__day--outside { color: #acb7bc; background: #fbfcfd; }
.task-calendar__day--today > span:first-child { display: grid; width: 21px; height: 21px; place-items: center; border-radius: 50%; color: #fff; background: var(--color-primary-active); }
.task-calendar__day--selected { position: relative; z-index: 1; outline: 1px solid #5bb8cd; outline-offset: -1px; background: #eef9fc; }
.task-calendar__markers { display: flex; align-items: center; gap: 3px; color: #82949b; font-size: 9px; }
.task-calendar__markers small { font-size: 9px; }
.task-calendar__marker--opens { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #28a7c1; }
.task-calendar__marker--due { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #d9a369; }
.task-calendar__agenda { display: grid; gap: 9px; margin-top: 15px; }
.task-calendar__agenda > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.task-calendar__agenda > header > div:first-child { display: flex; align-items: baseline; gap: 8px; }
.task-calendar__agenda > header strong { color: #3b5866; font-size: 12px; }
.task-calendar__agenda > header span { color: #87979e; font-size: 10px; }
.task-calendar__legend { display: flex; gap: 10px; }
.task-calendar__legend span { display: inline-flex; align-items: center; gap: 4px; color: #819199; font-size: 9px; }
.task-calendar__agenda-list { display: grid; gap: 6px; }
.task-calendar__agenda-item { display: grid; grid-template-columns: 14px minmax(0,1fr) auto; align-items: center; gap: 7px; min-width: 0; padding: 8px 9px; border: 1px solid #e8eef0; border-radius: 8px; color: inherit; background: #fff; text-align: left; cursor: pointer; transition: border-color 160ms ease, background-color 160ms ease; }
.task-calendar__agenda-item--selected { border-color: #8acbda; background: #f2fbfd; }
.task-calendar__agenda-markers { display: grid; gap: 4px; }
.task-calendar__agenda-item > span:nth-child(2) { display: grid; gap: 3px; min-width: 0; }
.task-calendar__agenda-item strong { overflow: hidden; color: #435d6a; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.task-calendar__agenda-item small { color: #81929a; font-size: 9px; }
.task-calendar__agenda-item > svg { color: #82949b; }
.task-calendar__empty { margin: 0; padding: 14px; border-radius: 8px; color: #819199; background: #f8fafb; font-size: 10px; text-align: center; }
.task-workbench__state { display: flex; min-height: 300px; align-items: center; justify-content: center; gap: 10px; padding: 22px; color: #71858f; font-size: 12px; }
.task-workbench__state--error { color: #8d3b34; }
.task-skeleton { width: 17px; height: 17px; border: 2px solid #e5eff2; border-top-color: #21a5c1; border-radius: 50%; animation: task-spin 900ms linear infinite; }
.publish-dialog { display: grid; gap: 14px; }
.publish-steps { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 6px; margin: 0; padding: 0; list-style: none; }
.publish-steps__item { display: flex; align-items: center; gap: 6px; min-width: 0; color: #89989f; }
.publish-steps__item > span { display: grid; width: 23px; height: 23px; flex: 0 0 23px; place-items: center; border: 1px solid #dfe8eb; border-radius: 50%; color: #748892; background: #fff; font-size: 10px; font-weight: 700; }
.publish-steps__item strong { overflow: hidden; font-size: 10px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.publish-steps__item--active { color: var(--color-primary-active); }.publish-steps__item--active > span,.publish-steps__item--done > span { border-color: var(--color-primary-active); color: #fff; background: var(--color-primary-active); }.publish-steps__item--done { color: #4b8b7d; }
.publish-step-panel { display: grid; gap: 9px; padding: 14px; border: 1px solid #e7eef1; border-radius: 10px; background: #fbfcfd; }
.publish-step-panel > label,.publish-step-panel__label { margin-top: 2px; color: #536c78; font-size: 11px; font-weight: 680; }
.publish-step-panel > select,.publish-step-panel > input { width: 100%; min-height: 39px; padding: 7px 10px; border: 1px solid #dce6ea; border-radius: 8px; color: #354e5b; background: #fff; font: inherit; font-size: 12px; }
.publish-step-panel > select:focus-visible,.publish-step-panel > input:focus-visible { outline: 2px solid rgb(0 177 226 / 27%); border-color: var(--color-primary); }
.publish-config-choice { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 7px; }
.publish-config-choice button { display: grid; gap: 4px; min-width: 0; padding: 9px; border: 1px solid #e4ebee; border-radius: 8px; color: #526a76; background: #fff; text-align: left; cursor: pointer; }
.publish-config-choice button[aria-pressed='true'] { border-color: #82c7d6; color: #297b91; background: #f0fafc; box-shadow: inset 0 0 0 1px rgb(50 167 194 / 9%); }
.publish-config-choice button strong { font-size: 11px; }.publish-config-choice button small { color: #84949b; font-size: 9px; line-height: 1.4; }
.publish-step-panel__message { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; padding: 9px; border-radius: 7px; color: #687f89; background: #f2f6f8; font-size: 10px; }
.publish-step-panel__message--error { color: #8a642b; background: #fbf5e8; }
.publish-step-panel__message button,.publish-load-more { border: 0; color: var(--color-primary-active); background: transparent; font: inherit; font-size: 10px; cursor: pointer; }
.publish-load-more { justify-self: start; }
.publish-step-panel > p { margin: 0; color: #84949b; font-size: 10px; }
.publish-summary { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 1px; overflow: hidden; margin: 0; border: 1px solid #e4ecef; border-radius: 8px; background: #e4ecef; }
.publish-summary > div { display: grid; gap: 5px; min-width: 0; padding: 9px 10px; background: #fff; }
.publish-summary dt { color: #84949b; font-size: 9px; }.publish-summary dd { overflow-wrap: anywhere; margin: 0; color: #415b68; font-size: 11px; font-weight: 650; }
.publish-hint { margin: 0; color: #748a94; font-size: 10px; }.publish-error { margin: 0; padding: 9px 10px; border-radius: 8px; color: #953f35; background: #fdf0ee; font-size: 11px; line-height: 1.5; }
.publish-dialog__actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 5px; border-top: 1px solid #edf0f2; }
.revoke-dialog { display: grid; gap: 15px; }.revoke-dialog > p:first-child { margin: 0; color: #566e7a; font-family: var(--font-mono); font-size: 12px; }

:deep(.workspace-tabs) { border-color: #e4edf0; background: #f4f8fa; }
:deep(.workspace-tabs__indicator) { border-color: #e4ecef; }
:deep(.workspace-tabs__tab[data-state='active']) { color: var(--color-primary-active); }

@keyframes task-spin { to { transform: rotate(360deg); } }
@media (max-width: 1000px) {
  .task-filterbar { grid-template-columns: minmax(180px,1fr) minmax(140px,.7fr) minmax(130px,.65fr); }
  .task-view-switch { grid-column: 1 / -1; justify-self: end; width: min(220px,100%); }
  .task-filterbar__clear { grid-column: 1 / -1; }
  .task-workbench__body { grid-template-columns: minmax(0,1fr); }
  .task-workbench__list { border-right: 0; border-bottom: 1px solid #edf0f2; }
  .task-workbench__detail { min-height: 390px; }
}
@media (max-width: 660px) {
  .admin-task-page { gap: 12px; }
  .task-page-heading { align-items: flex-start; }
  .task-page-heading h1 { font-size: 21px; }
  .task-page-heading p { max-width: 220px; font-size: 11px; line-height: 1.45; }
  .task-page-heading :deep(.app-button) { min-height: 36px; padding-inline: 10px; font-size: 11px; }
  .task-summary { grid-template-columns: minmax(0,1fr); gap: 11px; padding: 12px; }
  .task-summary__metrics > div { padding-inline: 9px; }
  .task-summary__metrics > div:first-child { border-left: 0; padding-left: 0; }
  .task-summary__metrics dt { font-size: 9px; }
  .task-summary__metrics dd { font-size: 18px; }
  .task-filterbar { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; padding: 10px; }
  .task-search { grid-column: 1 / -1; }
  .task-filterbar > :deep(.teacher-class-select) { grid-column: span 1; }
  .task-view-switch { grid-column: 1 / -1; justify-self: stretch; width: 100%; }
  .task-workbench__header { padding: 14px; }
  .task-workbench__list,.task-workbench__detail { padding: 12px; }
  .task-timeline__item { grid-template-columns: 36px minmax(0,1fr); gap: 7px; }
  .task-timeline__date strong { font-size: 15px; }
  .task-ticket { padding: 10px; }
  .task-ticket__title-row { flex-direction: column; gap: 6px; }
  .task-ticket__title-row > strong { white-space: normal; }
  .task-ticket__times { font-size: 9px; }
  .task-detail__facts { grid-template-columns: minmax(0,1fr); }
  .task-detail__enrollment-summary dl { gap: 5px; }
  .task-detail__enrollment-summary dl > div { padding: 8px 6px; }
  .task-calendar__day { min-height: 47px; padding: 5px; }
  .task-detail__assignments :deep(.professional-assignments__form) { grid-template-columns: 1fr; }
  .publish-steps { gap: 3px; }
  .publish-steps__item { gap: 4px; }
  .publish-steps__item > span { width: 21px; height: 21px; flex-basis: 21px; }
  .publish-steps__item strong { font-size: 9px; }
  .publish-step-panel { padding: 11px; }
  .publish-summary { grid-template-columns: minmax(0,1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .task-view-switch__indicator,.task-ticket,.task-calendar__day,.task-calendar__agenda-item,.task-search { transition: none; }
  .task-skeleton { animation: none; }
}
</style>
