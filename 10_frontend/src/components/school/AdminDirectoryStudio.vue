<script setup lang="ts">
/* global HTMLButtonElement, performance, AnimationEvent, KeyboardEvent, Event, HTMLInputElement */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleHelp,
  FileSpreadsheet,
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  UsersRound,
  X,
} from '@lucide/vue'
import {
  DialogClose as DrawerDialogClose,
  DialogContent as DrawerDialogContent,
  DialogOverlay as DrawerDialogOverlay,
  DialogPortal as DrawerDialogPortal,
  DialogRoot as DrawerDialogRoot,
  DialogTitle as DrawerDialogTitle,
  DialogClose as ActivationDialogClose,
  DialogContent as ActivationDialogContent,
  DialogDescription as ActivationDialogDescription,
  DialogOverlay as ActivationDialogOverlay,
  DialogPortal as ActivationDialogPortal,
  DialogRoot as ActivationDialogRoot,
  DialogTitle as ActivationDialogTitle,
  SelectContent as ImportClassContent,
  SelectItem as ImportClassItem,
  SelectItemIndicator as ImportClassItemIndicator,
  SelectItemText as ImportClassItemText,
  SelectPortal as ImportClassPortal,
  SelectRoot as ImportClassRoot,
  SelectTrigger as ImportClassTrigger,
  SelectValue as ImportClassValue,
  SelectViewport as ImportClassViewport,
} from 'reka-ui'
import { readSheet as readXlsxSheet } from 'read-excel-file/universal'
import { readFirstSheet } from 'xls-reader'
import AppButton from '@/components/app/AppButton.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import AdminWorkspaceFolderCard from '@/components/admin/AdminWorkspaceFolder.vue'
import AdminMemberCombobox from '@/components/school/AdminMemberCombobox.vue'
import type {
  SchoolAccountBatch,
  SchoolAccountImportRow,
  SchoolAccountPreview,
  SchoolClass,
  SchoolDirectory,
  SchoolMember,
} from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { RealApiError } from '@/services/real-api'
import { parseSchoolAccountCsv, type SchoolAccountCsvErrorCode } from '@/utils/school-account-csv'
import type { AdminWorkspaceFolder as AdminWorkspaceFolderData } from '@/components/admin/admin-workspace-actions'

type DirectoryState = 'loading' | 'ready' | 'error'
type DirectoryView = 'members' | 'classes'
type MemberFilter = 'all' | 'student' | 'teacher' | 'pending'
type DirectoryMember = SchoolDirectory['members'][number]
type DirectoryAccount = {
  user_id: string
  display_name: string | null
  role: 'student' | 'teacher'
  account_status?: string
  provisioning_status?: string | null
}
type PendingAccount = {
  user_id: string
  display_name: string
  role: 'student' | 'teacher'
  status: 'PENDING_ACTIVATION'
}

const directory = ref<SchoolDirectory | null>(null)
const directoryState = ref<DirectoryState>('loading')
const directoryStale = ref(false)
const candidatesState = ref<DirectoryState>('loading')
const students = ref<SchoolMember[]>([])
const teachers = ref<SchoolMember[]>([])
const pendingAction = ref('')
const pageError = ref('')
const pageNotice = ref('')
const noticeTone = ref<'success' | 'warning'>('success')
const view = ref<DirectoryView>('members')
const memberFilter = ref<MemberFilter>('all')
const searchTerm = ref('')
const selectedMemberId = ref('')
const selectedClassRef = ref('')
const detailOpen = ref(false)
const drawerExitMessage = ref('')
type DirectoryFlightOrigin = { x: number; y: number; width: number; height: number; coverOcclusion?: number }
const detailPaperOrigins = ref<DirectoryFlightOrigin[]>([])
const selectedPaperIndex = ref(0)
const closingDetail = ref(false)
const detailSourceElement = ref<HTMLButtonElement | null>(null)
const detailScrollPosition = ref({ x: 0, y: 0 })
const memberNameEditing = ref(false)
const memberNameDraft = ref('')
const classNameEditing = ref(false)
const classNameDraft = ref('')
const selectedStudentId = ref('')
const selectedTeacherId = ref('')
const schoolDialogOpen = ref(false)
const schoolNameDraft = ref('')
const createClassDialogOpen = ref(false)
const newClassName = ref('')
const importDialogOpen = ref(false)
const importStage = ref<1 | 2 | 3>(1)
const importClassRef = ref('')
const csvFileName = ref('')
const csvRows = ref<SchoolAccountImportRow[]>([])
const csvClientError = ref('')
const csvPreview = ref<SchoolAccountPreview | null>(null)
const csvPreviewError = ref('')
const csvIdempotencyKey = ref('')
const importedBatch = ref<SchoolAccountBatch | null>(null)
const activationDialogOpen = ref(false)
const activationUserId = ref('')
const newPassword = ref('')
const activationError = ref('')
const activationPending = ref(false)
let directoryRequestGeneration = 0
let candidatesRequestGeneration = 0
let batchRequestGeneration = 0
let isUnmounted = false
let detailCloseTimer: number | undefined
let detailCloseFinalizing = false

const shortRef = (value: string) => value.slice(-6)
const roleLabel = (role: 'student' | 'teacher') => role === 'student' ? '学生' : '教师'
const className = (item: SchoolClass) => item.display_name?.trim() || `班级 ${shortRef(item.class_ref)}`

const apiErrorCode = (error: unknown) => {
  if (error instanceof RealApiError) return error.code.toUpperCase()
  if (typeof error === 'object' && error !== null && 'code' in error) return String(error.code).toUpperCase()
  return ''
}

const requestMessage = (error: unknown, fallback: string) => {
  const code = apiErrorCode(error)
  if (/AUTH_SESSION_(EXPIRED|REVOKED)|UNAUTHORIZED|\b401\b/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'FORBIDDEN' || code === '403') return '当前账号暂时没有此项操作权限。'
  if (/WORKFLOW_CONFLICT|CONFLICT|\b409\b/.test(code)) return '数据已发生变化，请刷新后重试。'
  if (/RESOURCE_NOT_FOUND|NOT_FOUND|\b404\b/.test(code)) return '所选内容已不可用，请刷新后重试。'
  if (code === 'CSRF_FAILED') return '安全校验未通过，请刷新页面后重试。'
  return fallback
}

const accountStatus = (status: string | undefined) => {
  switch (status?.toUpperCase()) {
    case 'ACTIVE': return { label: '可用', tone: 'available' }
    case 'SUSPENDED': return { label: '已暂停', tone: 'paused' }
    case 'DISABLED': return { label: '已停用', tone: 'disabled' }
    default: return { label: '状态待确认', tone: 'unknown' }
  }
}

const provisioningStatus = (status: string | null | undefined) => {
  switch (status?.toUpperCase()) {
    case 'PENDING_ACTIVATION': return { label: '待激活', tone: 'pending' }
    case 'ACTIVE': return { label: '已激活', tone: 'available' }
    case null:
    case undefined: return null
    default: return { label: '开通状态待确认', tone: 'unknown' }
  }
}

const refreshDirectory = async (options: { preserveNotice?: boolean } = {}): Promise<boolean> => {
  const generation = ++directoryRequestGeneration
  directoryState.value = 'loading'
  directoryStale.value = false
  pageError.value = ''
  if (!options.preserveNotice) pageNotice.value = ''
  if (!frontendApi.getSchoolAdminDirectory) {
    directoryState.value = directory.value ? 'ready' : 'error'
    directoryStale.value = Boolean(directory.value)
    pageError.value = '当前运行环境没有提供学校目录服务。'
    return false
  }
  try {
    const result = await frontendApi.getSchoolAdminDirectory()
    if (isUnmounted || generation !== directoryRequestGeneration) return false
    directory.value = result.data
    directoryState.value = 'ready'
    directoryStale.value = false
    if (selectedMemberId.value && !result.data.members.some((member) => member.user_id === selectedMemberId.value)
      && !importedBatch.value?.accounts.some((account) => account.user_id === selectedMemberId.value)) {
      selectedMemberId.value = ''
      detailOpen.value = false
    }
    if (selectedClassRef.value && !result.data.classes.some((item) => item.class_ref === selectedClassRef.value)) {
      selectedClassRef.value = ''
      detailOpen.value = false
    }
    if (!schoolDialogOpen.value) schoolNameDraft.value = result.data.school.display_name ?? ''
    return true
  } catch (error) {
    if (isUnmounted || generation !== directoryRequestGeneration) return false
    directoryState.value = directory.value ? 'ready' : 'error'
    directoryStale.value = Boolean(directory.value)
    pageError.value = directory.value
      ? `${requestMessage(error, '暂时无法刷新当前学校目录。')} 页面保留上次读取结果；刷新成功前不会提交目录变更。`
      : requestMessage(error, '暂时无法读取当前学校目录。')
    return false
  }
}

const refreshCandidates = async (): Promise<boolean> => {
  const generation = ++candidatesRequestGeneration
  candidatesState.value = 'loading'
  if (!frontendApi.listSchoolMembers) {
    students.value = []
    teachers.value = []
    candidatesState.value = 'error'
    return false
  }
  try {
    const [studentResult, teacherResult] = await Promise.all([
      frontendApi.listSchoolMembers('student'),
      frontendApi.listSchoolMembers('teacher'),
    ])
    if (isUnmounted || generation !== candidatesRequestGeneration) return false
    students.value = studentResult.data
    teachers.value = teacherResult.data
    candidatesState.value = 'ready'
    return true
  } catch {
    if (isUnmounted || generation !== candidatesRequestGeneration) return false
    students.value = []
    teachers.value = []
    candidatesState.value = 'error'
    return false
  }
}

const refreshImportedBatch = async (): Promise<boolean> => {
  const batchRef = importedBatch.value?.batch_ref
  if (!batchRef || !frontendApi.getSchoolAccountBatch) return true
  const generation = ++batchRequestGeneration
  try {
    const result = await frontendApi.getSchoolAccountBatch(batchRef)
    if (isUnmounted || generation !== batchRequestGeneration || importedBatch.value?.batch_ref !== batchRef) return false
    importedBatch.value = result.data
    return true
  } catch {
    if (generation === batchRequestGeneration) batchRefreshError.value = true
    return false
  }
}

const batchRefreshError = ref(false)

const refreshAll = async () => {
  pageError.value = ''
  pageNotice.value = ''
  const results = await Promise.all([refreshDirectory(), refreshCandidates(), refreshImportedBatch()])
  if (importedBatch.value && results[2]) batchRefreshError.value = false
}

const pendingAccounts = computed<PendingAccount[]>(() => {
  const found = new Map<string, PendingAccount>()
  for (const member of directory.value?.members ?? []) {
    if (member.provisioning_status === 'PENDING_ACTIVATION') {
      found.set(member.user_id, { user_id: member.user_id, display_name: member.display_name ?? '', role: member.role, status: 'PENDING_ACTIVATION' })
    }
  }
  for (const account of importedBatch.value?.accounts ?? []) {
    if (account.status !== 'PENDING_ACTIVATION') continue
    const currentMember = directory.value?.members.find((member) => member.user_id === account.user_id)
    if (currentMember && currentMember.provisioning_status !== 'PENDING_ACTIVATION') continue
    found.set(account.user_id, { user_id: account.user_id, display_name: account.display_name, role: account.role, status: 'PENDING_ACTIVATION' })
  }
  return [...found.values()]
})

const allMembers = computed(() => directory.value?.members ?? [])
const memberCounts = computed(() => ({
  all: allMembers.value.length,
  student: allMembers.value.filter((member) => member.role === 'student').length,
  teacher: allMembers.value.filter((member) => member.role === 'teacher').length,
  pending: allMembers.value.filter((member) => member.provisioning_status === 'PENDING_ACTIVATION').length,
}))

const filteredMembers = computed(() => {
  const query = searchTerm.value.trim().toLocaleLowerCase()
  return [...allMembers.value]
    .filter((member) => {
      if (memberFilter.value === 'student' && member.role !== 'student') return false
      if (memberFilter.value === 'teacher' && member.role !== 'teacher') return false
      if (memberFilter.value === 'pending' && member.provisioning_status !== 'PENDING_ACTIVATION') return false
      if (!query) return true
      return `${member.display_name ?? ''} ${member.user_id}`.toLocaleLowerCase().includes(query)
    })
    .sort((first, second) => first.role.localeCompare(second.role)
      || (first.display_name ?? '').localeCompare(second.display_name ?? '', 'zh-CN')
      || first.user_id.localeCompare(second.user_id))
})

const sortedClasses = computed(() => [...(directory.value?.classes ?? [])]
  .sort((first, second) => className(first).localeCompare(className(second), 'zh-CN')
    || first.class_ref.localeCompare(second.class_ref)))

const selectedMember = computed<DirectoryAccount | null>(() => {
  const member = directory.value?.members.find((item) => item.user_id === selectedMemberId.value)
  if (member) return member
  const imported = importedBatch.value?.accounts.find((item) => item.user_id === selectedMemberId.value)
  return imported && imported.status === 'PENDING_ACTIVATION'
    ? { user_id: imported.user_id, display_name: imported.display_name, role: imported.role, provisioning_status: imported.status }
    : null
})

const selectedClass = computed(() => directory.value?.classes.find((item) => item.class_ref === selectedClassRef.value) ?? null)
const selectedPaperOrigin = computed(() => detailPaperOrigins.value[selectedPaperIndex.value] ?? null)
const activationAccount = computed(() => pendingAccounts.value.find((account) => account.user_id === activationUserId.value) ?? null)
const roleOptions = computed(() => ({ students: students.value, teachers: teachers.value }))
const route = useRoute()
const router = useRouter()

const captureDetailReturnTarget = (trigger?: HTMLElement) => {
  detailSourceElement.value = trigger instanceof HTMLButtonElement ? trigger : null
  detailScrollPosition.value = { x: window.scrollX, y: window.scrollY }
}

const waitForDetailOverlayRemoval = async () => {
  await nextTick()
  const startedAt = performance.now()
  await new Promise<void>((resolve) => {
    const checkOverlayRemoval = () => {
      if (!document.querySelector('.directory-detail__overlay') || performance.now() - startedAt > 500) {
        resolve()
        return
      }
      window.requestAnimationFrame(checkOverlayRemoval)
    }
    window.requestAnimationFrame(checkOverlayRemoval)
  })
}

const finishDetailClose = async () => {
  if (!closingDetail.value || detailCloseFinalizing) return
  detailCloseFinalizing = true
  if (detailCloseTimer !== undefined) {
    window.clearTimeout(detailCloseTimer)
    detailCloseTimer = undefined
  }
  const returnFocusTo = detailSourceElement.value
  const scrollPosition = detailScrollPosition.value
  detailOpen.value = false
  await waitForDetailOverlayRemoval()
  window.scrollTo(scrollPosition.x, scrollPosition.y)
  if (returnFocusTo?.isConnected) returnFocusTo.focus({ preventScroll: true })
  selectedMemberId.value = ''
  selectedClassRef.value = ''
  selectedPaperIndex.value = 0
  memberNameEditing.value = false
  classNameEditing.value = false
  detailPaperOrigins.value = []
  closingDetail.value = false
  drawerExitMessage.value = ''
  detailSourceElement.value = null
  detailScrollPosition.value = { x: 0, y: 0 }
  detailCloseFinalizing = false
}

const detailPanelStyle = computed(() => {
  const width = typeof window === 'undefined' ? 560 : window.innerWidth <= 560 ? window.innerWidth - 32 : selectedClass.value ? 620 : 520
  const x = selectedPaperOrigin.value?.x ?? (typeof window === 'undefined' ? 0 : window.innerWidth / 2)
  const y = selectedPaperOrigin.value?.y ?? (typeof window === 'undefined' ? 0 : window.innerHeight / 2)
  return {
    '--detail-origin-dx': `${x - (typeof window === 'undefined' ? 0 : window.innerWidth / 2)}px`,
    '--detail-origin-dy': `${y - (typeof window === 'undefined' ? 0 : window.innerHeight / 2)}px`,
    '--detail-card-scale': `${Math.min(.2, (42 * 1.35) / Math.max(1, width))}`,
  }
})

const detailPaperStyle = computed(() => {
  const source = selectedPaperOrigin.value
  if (!source) return {}
  const width = typeof window === 'undefined' ? 0 : window.innerWidth
  const height = typeof window === 'undefined' ? 0 : window.innerHeight
  const dx = width / 2 - source.x
  const dy = height / 2 - source.y
  const distance = Math.max(1, Math.hypot(dx, dy))
  const bend = Math.min(72, distance * .14)
  const normalX = -dy / distance
  const normalY = dx / distance
  const control1 = { x: dx * .25 + normalX * bend, y: dy * .25 + normalY * bend }
  const control2 = { x: dx * .75 + normalX * bend, y: dy * .75 + normalY * bend }
  const trajectory: Record<string, string> = {}
  for (let step = 1; step <= 5; step += 1) {
    const progress = step / 6
    const inverse = 1 - progress
    const point = {
      x: 3 * inverse ** 2 * progress * control1.x + 3 * inverse * progress ** 2 * control2.x + progress ** 3 * dx,
      y: 3 * inverse ** 2 * progress * control1.y + 3 * inverse * progress ** 2 * control2.y + progress ** 3 * dy,
    }
    trajectory[`--directory-paper-p${step}-x`] = `${point.x}px`
    trajectory[`--directory-paper-p${step}-y`] = `${point.y}px`
  }
  return {
    left: `${source.x - source.width / 2}px`,
    top: `${source.y - source.height / 2}px`,
    width: `${source.width}px`,
    height: `${source.height}px`,
    '--directory-paper-dx': `${dx}px`,
    '--directory-paper-dy': `${dy}px`,
    '--directory-paper-occlusion': `${(source.coverOcclusion ?? 0) * 100}%`,
    '--directory-paper-half-occlusion': `${(source.coverOcclusion ?? 0) * 50}%`,
    ...trajectory,
  }
})

const folderForClass = (item: SchoolClass): AdminWorkspaceFolderData => ({
  id: 'classes',
  title: className(item),
  description: `学生 ${item.active_student_count} 人 · 教师 ${item.active_teacher_count} 人`,
  category: '组织目录',
  icon: Building2,
  tone: 'aqua',
  actionIds: [],
})

const detailPalette = computed(() => selectedMember.value?.role === 'teacher'
  ? { surface: '#e5e7f7', accent: '#6e78c4' }
  : { surface: '#dff2f5', accent: '#168fae' })

const handleDetailPaperAnimationEnd = (event: AnimationEvent) => {
  if (!closingDetail.value || event.target !== event.currentTarget) return
  if (event.animationName === getComputedStyle(event.currentTarget as Element).animationName) void finishDetailClose()
}

const handleDetailPanelAnimationEnd = (event: AnimationEvent) => {
  if (!closingDetail.value || selectedPaperOrigin.value || event.target !== event.currentTarget) return
  if (event.animationName === getComputedStyle(event.currentTarget as Element).animationName) void finishDetailClose()
}

const handleViewTabKeydown = (event: KeyboardEvent) => {
  const targetView = event.key === 'Home'
    ? 'members'
    : event.key === 'End'
      ? 'classes'
      : event.key === 'ArrowRight' || event.key === 'ArrowDown'
        ? 'classes'
        : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
          ? 'members'
          : null
  if (!targetView) return
  event.preventDefault()
  view.value = targetView
  void nextTick(() => document.getElementById(targetView === 'members' ? 'directory-members-tab' : 'directory-classes-tab')?.focus())
}

const isMemberNameDirty = computed(() => memberNameEditing.value
  && Boolean(selectedMember.value)
  && memberNameDraft.value.trim() !== (selectedMember.value?.display_name ?? '').trim())
const isClassNameDirty = computed(() => classNameEditing.value
  && Boolean(selectedClass.value)
  && classNameDraft.value.trim() !== (selectedClass.value?.display_name ?? '').trim())

const openMember = (member: DirectoryMember, event?: MouseEvent) => {
  detailCloseFinalizing = false
  closingDetail.value = false
  detailPaperOrigins.value = []
  captureDetailReturnTarget(event?.currentTarget instanceof HTMLElement ? event.currentTarget : undefined)
  drawerExitMessage.value = ''
  selectedClassRef.value = ''
  selectedMemberId.value = member.user_id
  detailOpen.value = true
  memberNameDraft.value = member.display_name ?? ''
  memberNameEditing.value = false
}

const openPendingMember = (account: PendingAccount, event?: MouseEvent) => {
  detailCloseFinalizing = false
  closingDetail.value = false
  detailPaperOrigins.value = []
  captureDetailReturnTarget(event?.currentTarget instanceof HTMLElement ? event.currentTarget : undefined)
  drawerExitMessage.value = ''
  selectedClassRef.value = ''
  selectedMemberId.value = account.user_id
  detailOpen.value = true
  const member = directory.value?.members.find((candidate) => candidate.user_id === account.user_id)
  memberNameDraft.value = member?.display_name ?? account.display_name
  memberNameEditing.value = false
}

const openClass = (item: SchoolClass, editName = false, draft = item.display_name ?? '', source?: HTMLButtonElement) => {
  detailCloseFinalizing = false
  closingDetail.value = false
  captureDetailReturnTarget(source)
  drawerExitMessage.value = ''
  detailPaperOrigins.value = []
  selectedPaperIndex.value = 0
  selectedMemberId.value = ''
  selectedClassRef.value = item.class_ref
  detailOpen.value = true
  classNameDraft.value = draft
  classNameEditing.value = editName
  selectedStudentId.value = ''
  selectedTeacherId.value = ''
}

const handleDetailOpen = (open: boolean) => {
  if (open) return
  if (closingDetail.value) return
  if (pendingAction.value) {
    drawerExitMessage.value = '操作仍在处理中，收到结果后才能关闭。'
    return
  }
  if (isMemberNameDirty.value || isClassNameDirty.value) {
    drawerExitMessage.value = '名称修改尚未保存。保存或取消编辑后再关闭。'
    return
  }
  closingDetail.value = true
  detailCloseTimer = window.setTimeout(() => { void finishDetailClose() }, selectedClass.value ? 0 : selectedPaperOrigin.value ? 900 : 250)
}

const cancelMemberNameEdit = () => {
  memberNameDraft.value = selectedMember.value?.display_name ?? ''
  memberNameEditing.value = false
  drawerExitMessage.value = ''
}

const cancelClassNameEdit = () => {
  classNameDraft.value = selectedClass.value?.display_name ?? ''
  classNameEditing.value = false
  drawerExitMessage.value = ''
}

const validateName = (value: string) => {
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > 120) {
    pageError.value = '名称需为 1 至 120 个字符。'
    return null
  }
  return trimmed
}

const saveMemberName = async () => {
  const account = selectedMember.value
  if (!account || directoryStale.value || pendingAction.value || !frontendApi.updateSchoolMemberDisplayName) return
  const value = validateName(memberNameDraft.value)
  if (!value) return
  pendingAction.value = `member-name-${account.user_id}`
  pageError.value = ''
  pageNotice.value = ''
  try {
    await frontendApi.updateSchoolMemberDisplayName(account.user_id, value)
    memberNameDraft.value = value
    memberNameEditing.value = false
    const refreshed = await refreshDirectory({ preserveNotice: true })
    pageNotice.value = refreshed ? '显示名称已保存。' : '服务端已确认保存，但目录暂时无法刷新；请稍后刷新核对。'
    noticeTone.value = refreshed ? 'success' : 'warning'
  } catch (error) {
    pageError.value = requestMessage(error, '显示名称暂时无法保存，请重试。')
  } finally {
    pendingAction.value = ''
  }
}

const saveClassName = async () => {
  const item = selectedClass.value
  if (!item || directoryStale.value || pendingAction.value || !frontendApi.updateSchoolClassDisplayName) return
  const value = validateName(classNameDraft.value)
  if (!value) return
  pendingAction.value = `class-name-${item.class_ref}`
  pageError.value = ''
  pageNotice.value = ''
  try {
    await frontendApi.updateSchoolClassDisplayName(item.class_ref, value)
    classNameDraft.value = value
    classNameEditing.value = false
    const refreshed = await refreshDirectory({ preserveNotice: true })
    pageNotice.value = refreshed ? '班级名称已保存。' : '服务端已确认保存，但班级目录暂时无法刷新；请稍后刷新核对。'
    noticeTone.value = refreshed ? 'success' : 'warning'
  } catch (error) {
    pageError.value = requestMessage(error, '班级名称暂时无法保存，请重试。')
  } finally {
    pendingAction.value = ''
  }
}

const saveSchoolName = async () => {
  if (directoryStale.value || pendingAction.value || !frontendApi.updateSchoolDisplayName) return
  const value = validateName(schoolNameDraft.value)
  if (!value) return
  pendingAction.value = 'school-name'
  pageError.value = ''
  pageNotice.value = ''
  try {
    await frontendApi.updateSchoolDisplayName(value)
    schoolDialogOpen.value = false
    const refreshed = await refreshDirectory({ preserveNotice: true })
    pageNotice.value = refreshed ? '学校名称已保存。' : '服务端已确认保存，但学校目录暂时无法刷新；请稍后刷新核对。'
    noticeTone.value = refreshed ? 'success' : 'warning'
  } catch (error) {
    pageError.value = requestMessage(error, '学校名称暂时无法保存，请重试。')
  } finally {
    pendingAction.value = ''
  }
}

const createClass = async () => {
  if (!directory.value || directoryState.value !== 'ready' || directoryStale.value || pendingAction.value || !frontendApi.createSchoolClass) return
  const value = validateName(newClassName.value)
  if (!value) return
  const randomId = globalThis.crypto?.randomUUID?.()
  if (!randomId) {
    pageError.value = '当前浏览器无法生成安全的班级编号，请更新浏览器后重试。'
    return
  }
  const classRef = `CLASS_${randomId.replaceAll('-', '')}`
  pendingAction.value = 'create-class'
  pageError.value = ''
  pageNotice.value = ''
  try {
    const created = await frontendApi.createSchoolClass(classRef)
    let renameError: unknown = null
    try {
      if (!frontendApi.updateSchoolClassDisplayName) throw new Error('class rename unavailable')
      await frontendApi.updateSchoolClassDisplayName(created.data.class_ref, value)
    } catch (error) {
      renameError = error
    }
    createClassDialogOpen.value = false
    newClassName.value = ''
    const refreshed = await refreshDirectory({ preserveNotice: true })
    const createdItem = directory.value?.classes.find((item) => item.class_ref === created.data.class_ref)
    if (createdItem) openClass(createdItem, Boolean(renameError), renameError ? value : createdItem.display_name ?? '')
    if (renameError) {
      pageNotice.value = `班级已创建，但名称未保存。${requestMessage(renameError, '请在班级详情里重试。')}`
      noticeTone.value = 'warning'
    } else if (!refreshed) {
      pageNotice.value = '班级与名称已由服务端确认；目录暂时无法刷新，请稍后核对。'
      noticeTone.value = 'warning'
    } else {
      pageNotice.value = `${value}已创建。`
      noticeTone.value = 'success'
    }
  } catch (error) {
    pageError.value = requestMessage(error, '班级暂时无法创建，请重试。')
  } finally {
    pendingAction.value = ''
  }
}

const assignMember = async (role: 'student' | 'teacher') => {
  const classRef = selectedClassRef.value
  const userId = role === 'student' ? selectedStudentId.value : selectedTeacherId.value
  const operation = role === 'student' ? frontendApi.assignSchoolStudent : frontendApi.assignSchoolTeacher
  if (!classRef || !userId || directoryStale.value || pendingAction.value || !operation) return
  pendingAction.value = `assign-${role}`
  pageError.value = ''
  pageNotice.value = ''
  try {
    await operation.call(frontendApi, classRef, userId)
    if (role === 'student') selectedStudentId.value = ''
    else selectedTeacherId.value = ''
    const refreshed = await refreshDirectory({ preserveNotice: true })
    if (!refreshed) {
      pageNotice.value = role === 'student'
        ? '服务端已确认分配学生，但班级人数暂时无法刷新；请稍后核对。'
        : '服务端已确认分配教师，但班级人数暂时无法刷新；请稍后核对。'
      noticeTone.value = 'warning'
    } else {
      pageNotice.value = role === 'student' ? '学生已分配，班级人数已更新。' : '教师已分配，班级人数已更新。'
      noticeTone.value = 'success'
    }
  } catch (error) {
    pageError.value = requestMessage(error, role === 'student' ? '学生暂时无法分配到此班级。' : '教师暂时无法分配到此班级。')
  } finally {
    pendingAction.value = ''
  }
}

const csvErrorText: Record<SchoolAccountCsvErrorCode, string> = {
  CSV_TOO_LARGE: '文件不能超过 500 KiB。',
  CSV_INVALID_UTF8: 'CSV 文件必须使用有效的 UTF-8 编码。',
  CSV_MALFORMED: '表格内容格式无效，请检查逗号、引号或单元格内容。',
  CSV_INVALID_HEADER: '表头必须严格为 login_name、display_name、role。',
  CSV_TOO_MANY_ROWS: '一次最多导入 100 个账号。',
  CSV_INVALID_ROW: '存在列数不一致或空行。',
  LOGIN_NAME_INVALID: '登录名必须符合 SYNTHETIC_ 命名格式。',
  LOGIN_NAME_DUPLICATE: '文件中有重复登录名。',
  DISPLAY_NAME_INVALID: '显示名称不能为空、不能含换行，且不能超过 120 个字符。',
  ROLE_INVALID: '角色只能是 student 或 teacher。',
}

const spreadsheetRowsToCsv = (rows: ReadonlyArray<ReadonlyArray<unknown>>) => rows
  .map((row) => row.map((value) => {
    const text = value instanceof Date
      ? value.toISOString()
      : value === null || value === undefined
        ? ''
        : String(value)
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }).join(','))
  .join('\r\n')

const serverImportErrorText: Record<string, string> = {
  INVALID_ROW_NUMBER: '行号格式无效。',
  DUPLICATE_ROW_NUMBER: '行号重复。',
  INVALID_LOGIN_NAME: '登录名不符合导入规则。',
  BLANK_DISPLAY_NAME: '显示名称不能为空。',
  DUPLICATE_LOGIN_NAME: '登录名重复。',
  LOGIN_UNAVAILABLE: '登录名当前不可用。',
  CLASS_UNAVAILABLE: '目标班级不可用。',
}

const clearServerPreview = () => {
  if (csvIdempotencyKey.value) {
    csvPreviewError.value = '导入结果尚未确认。请使用原文件和班级重试，不能更换内容。'
    return
  }
  csvPreview.value = null
  csvPreviewError.value = ''
  if (importStage.value > 1) importStage.value = 1
}

const acceptCsvFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  if (csvIdempotencyKey.value) {
    input.value = ''
    csvPreviewError.value = '导入结果尚未确认。请使用原文件和班级重试，不能更换内容。'
    return
  }
  clearServerPreview()
  csvRows.value = []
  csvFileName.value = ''
  csvClientError.value = ''
  pageError.value = ''
  pageNotice.value = ''
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  csvFileName.value = file.name
  if (file.size > 500 * 1024) {
    csvClientError.value = csvErrorText.CSV_TOO_LARGE
    return
  }
  const extension = file.name.split('.').pop()?.toLocaleLowerCase()
  if (!extension || !['csv', 'xlsx', 'xls'].includes(extension)) {
    csvClientError.value = '请选择 CSV、XLSX 或 XLS 文件。'
    return
  }
  try {
    let source: string | Uint8Array
    if (extension === 'csv') {
      source = new Uint8Array(await file.arrayBuffer())
    } else if (extension === 'xlsx') {
      source = spreadsheetRowsToCsv(await readXlsxSheet(file, { trim: false }))
    } else {
      const sheet = readFirstSheet(new Uint8Array(await file.arrayBuffer()))
      if (!sheet) {
        csvClientError.value = 'Excel 文件没有可读取的工作表。'
        return
      }
      source = spreadsheetRowsToCsv(sheet.rows)
    }
    const parsed = parseSchoolAccountCsv(source)
    if (!parsed.ok) {
      csvClientError.value = csvErrorText[parsed.code]
      return
    }
    csvRows.value = parsed.rows
  } catch {
    csvClientError.value = extension === 'csv'
      ? csvErrorText.CSV_INVALID_UTF8
      : 'Excel 文件无法读取，请确认文件未加密，并使用第一个工作表。'
  }
}

const openImportWizard = () => {
  pageError.value = ''
  pageNotice.value = ''
  importDialogOpen.value = true
  if (importStage.value === 1 && directory.value && !directory.value.classes.some((item) => item.class_ref === importClassRef.value)) importClassRef.value = ''
}

const closeImportWizard = (open: boolean) => {
  if (!open && pendingAction.value === 'import-accounts') return
  importDialogOpen.value = open
}

const updateImportClass = (value: string) => {
  if (value === importClassRef.value) return
  if (csvIdempotencyKey.value) {
    csvPreviewError.value = '导入结果尚未确认。请使用原文件和班级重试，不能更换内容。'
    return
  }
  importClassRef.value = value
  clearServerPreview()
  pageError.value = ''
}

const clearCsvFile = () => {
  if (csvIdempotencyKey.value) {
    csvPreviewError.value = '导入结果尚未确认。请使用原文件和班级重试，不能更换内容。'
    return
  }
  csvRows.value = []
  csvFileName.value = ''
  csvClientError.value = ''
  csvPreview.value = null
  csvPreviewError.value = ''
  importStage.value = 1
}

const previewImport = async () => {
  if (directoryState.value !== 'ready' || directoryStale.value || pendingAction.value || !csvRows.value.length || !frontendApi.previewSchoolAccountImport) return
  pendingAction.value = 'preview-import'
  pageError.value = ''
  csvPreviewError.value = ''
  csvPreview.value = null
  csvIdempotencyKey.value = ''
  try {
    const result = await frontendApi.previewSchoolAccountImport(importClassRef.value || null, csvRows.value)
    csvPreview.value = result.data
    importStage.value = 2
  } catch (error) {
    csvPreviewError.value = requestMessage(error, '服务端预览失败，账号尚未导入。')
  } finally {
    pendingAction.value = ''
  }
}

const canAdvanceToConfirm = computed(() => Boolean(csvPreview.value?.valid && csvPreview.value.errors.length === 0 && csvRows.value.length))

const importAccounts = async () => {
  if (pendingAction.value || !canAdvanceToConfirm.value || !frontendApi.importSchoolAccounts) return
  if (!csvIdempotencyKey.value) {
    const randomId = globalThis.crypto?.randomUUID?.()
    if (!randomId) {
      pageError.value = '当前浏览器无法生成安全的导入请求编号，请更新浏览器后重试。'
      return
    }
    csvIdempotencyKey.value = `school-account-import-${randomId}`
  }
  pendingAction.value = 'import-accounts'
  pageError.value = ''
  csvPreviewError.value = ''
  try {
    const result = await frontendApi.importSchoolAccounts(importClassRef.value || null, csvRows.value, csvIdempotencyKey.value)
    importedBatch.value = result.data
    batchRefreshError.value = false
    csvIdempotencyKey.value = ''
    csvRows.value = []
    csvPreview.value = null
    csvClientError.value = ''
    const refreshed = await refreshDirectory({ preserveNotice: true })
    importStage.value = 3
    pageNotice.value = refreshed
      ? `服务端已确认创建 ${result.data.created_count} 个账号。待激活账号可在目录中逐个处理。`
      : `服务端已确认创建 ${result.data.created_count} 个账号；目录暂时无法刷新，请稍后核对。`
    noticeTone.value = refreshed ? 'success' : 'warning'
  } catch (error) {
    const rejectedPreview = error instanceof RealApiError && error.code === 'SCHOOL_ACCOUNT_IMPORT_REJECTED'
      ? error.schoolAccountPreview
      : null
    if (rejectedPreview) {
      csvPreview.value = rejectedPreview
      csvIdempotencyKey.value = ''
      importStage.value = 2
      csvPreviewError.value = '服务端发现数据已变化，请重新预览后再导入。'
    } else {
      csvPreviewError.value = '服务器尚未确认导入结果。重试会复用同一请求编号；更换文件或班级后需要重新预览。'
    }
  } finally {
    pendingAction.value = ''
  }
}

const startNewImport = () => {
  importStage.value = 1
  csvFileName.value = ''
  csvRows.value = []
  csvClientError.value = ''
  csvPreview.value = null
  csvPreviewError.value = ''
  csvIdempotencyKey.value = ''
  importClassRef.value = ''
  pageNotice.value = ''
  pageError.value = ''
}

const beginActivation = (userId: string) => {
  const account = pendingAccounts.value.find((item) => item.user_id === userId)
  if (!account || account.status !== 'PENDING_ACTIVATION' || directoryStale.value) return
  activationUserId.value = userId
  newPassword.value = ''
  activationError.value = ''
  activationDialogOpen.value = true
}

const closeActivation = (open: boolean) => {
  if (!open && activationPending.value) return
  activationDialogOpen.value = open
  if (!open) {
    activationUserId.value = ''
    newPassword.value = ''
    activationError.value = ''
  }
}

const activateAccount = async () => {
  const account = activationAccount.value
  if (!account || !newPassword.value || activationPending.value || directoryStale.value || !frontendApi.activateSchoolAccount) return
  const password = newPassword.value
  activationPending.value = true
  activationError.value = ''
  pageError.value = ''
  try {
    await frontendApi.activateSchoolAccount(account.user_id, password)
    newPassword.value = ''
    activationDialogOpen.value = false
    activationUserId.value = ''
    const directoryUpdated = await refreshDirectory({ preserveNotice: true })
    const batchUpdated = await refreshImportedBatch()
    const stillPending = pendingAccounts.value.some((item) => item.user_id === account.user_id)
    if (!directoryUpdated || !batchUpdated) {
      pageNotice.value = '服务端已确认激活；账号目录暂时无法刷新，请稍后核对状态。'
      noticeTone.value = 'warning'
    } else if (stillPending) {
      pageNotice.value = '服务端已确认激活，但最新目录仍标记为待激活。请刷新状态后再处理。'
      noticeTone.value = 'warning'
    } else {
      pageNotice.value = `${account.display_name || `账号 ${shortRef(account.user_id)}`}已激活。`
      noticeTone.value = 'success'
    }
  } catch (error) {
    newPassword.value = ''
    const directoryUpdated = await refreshDirectory({ preserveNotice: true })
    const batchUpdated = await refreshImportedBatch()
    const stillPending = pendingAccounts.value.some((item) => item.user_id === account.user_id)
    if (directoryUpdated && batchUpdated && !stillPending) {
      activationDialogOpen.value = false
      activationUserId.value = ''
      pageNotice.value = `${account.display_name || `账号 ${shortRef(account.user_id)}`}已激活。`
      noticeTone.value = 'success'
    } else {
      activationError.value = requestMessage(error, '没有收到激活成功的确认。请核对账号状态后再试。')
    }
  } finally {
    newPassword.value = ''
    activationPending.value = false
  }
}

const closeSchoolDialog = (open: boolean) => {
  if (!open && pendingAction.value === 'school-name') return
  schoolDialogOpen.value = open
}

const closeCreateClassDialog = (open: boolean) => {
  if (!open && pendingAction.value === 'create-class') return
  createClassDialogOpen.value = open
}

watch(() => route.query.directoryView, (value) => {
  if (value === 'classes') view.value = 'classes'
}, { immediate: true })

watch(() => route.query.directoryAction, (value) => {
  const action = Array.isArray(value) ? value[0] : value
  if (!action) return
  if (action === 'create-class' || action === 'manage-class-people') view.value = 'classes'
  if (action === 'activate-account') {
    view.value = 'members'
    memberFilter.value = 'pending'
  }
  if (action === 'create-class') createClassDialogOpen.value = true
  if (action === 'import-accounts') openImportWizard()
  void router.replace({ query: { ...route.query, directoryAction: undefined } })
}, { immediate: true })

onMounted(() => {
  void refreshDirectory()
  void refreshCandidates()
})

onBeforeUnmount(() => {
  isUnmounted = true
  if (detailCloseTimer !== undefined) window.clearTimeout(detailCloseTimer)
  directoryRequestGeneration += 1
  candidatesRequestGeneration += 1
  batchRequestGeneration += 1
  newPassword.value = ''
  csvRows.value = []
  csvIdempotencyKey.value = ''
})
</script>

<template>
  <section class="directory-studio" aria-label="班级与账号">
    <header class="directory-studio__header">
      <div class="directory-studio__header-actions">
        <button
          type="button"
          class="directory-studio__school-action"
          :disabled="!directory || directoryStale || Boolean(pendingAction) || !frontendApi.updateSchoolDisplayName"
          @click="schoolNameDraft = directory?.school.display_name ?? ''; schoolDialogOpen = true"
        >
          <Building2 :size="15" aria-hidden="true" />
          <span>{{ directory?.school.display_name?.trim() || '学校设置' }}</span>
          <Settings2 :size="14" aria-hidden="true" />
        </button>
        <AppButton variant="primary" size="sm" :disabled="directoryState !== 'ready' || directoryStale || Boolean(pendingAction) || !frontendApi.previewSchoolAccountImport || !frontendApi.importSchoolAccounts" @click="openImportWizard">
          <FileSpreadsheet :size="15" aria-hidden="true" />导入账号
        </AppButton>
      </div>
    </header>

    <div v-if="pageError && directoryState !== 'error'" class="directory-studio__callout directory-studio__callout--error" role="alert">
      <CircleAlert :size="17" aria-hidden="true" /><span>{{ pageError }}</span>
    </div>
    <div v-if="pageNotice" class="directory-studio__callout" :class="noticeTone === 'warning' ? 'directory-studio__callout--warning' : 'directory-studio__callout--success'" role="status" aria-live="polite">
      <Check v-if="noticeTone === 'success'" :size="17" aria-hidden="true" /><CircleHelp v-else :size="17" aria-hidden="true" /><span>{{ pageNotice }}</span>
    </div>

    <div class="directory-studio__toolbar">
      <div class="directory-studio__view-switch" :class="{ 'directory-studio__view-switch--classes': view === 'classes' }" role="tablist" aria-label="目录视图">
        <span class="directory-studio__view-thumb" aria-hidden="true" />
        <button id="directory-members-tab" type="button" role="tab" aria-controls="directory-members-panel" :aria-selected="view === 'members'" :tabindex="view === 'members' ? 0 : -1" @click="view = 'members'" @keydown="handleViewTabKeydown">
          <UsersRound :size="15" aria-hidden="true" />人员目录<span>{{ memberCounts.all }}</span>
        </button>
        <button id="directory-classes-tab" type="button" role="tab" aria-controls="directory-classes-panel" :aria-selected="view === 'classes'" :tabindex="view === 'classes' ? 0 : -1" @click="view = 'classes'" @keydown="handleViewTabKeydown">
          <Building2 :size="15" aria-hidden="true" />班级视图<span>{{ directory?.classes.length ?? 0 }}</span>
        </button>
      </div>
      <div class="directory-studio__tools">
        <label class="directory-studio__search">
          <Search :size="16" aria-hidden="true" />
          <span class="sr-only">搜索姓名或账号编号</span>
          <input v-model="searchTerm" type="search" autocomplete="off" placeholder="搜索姓名或账号编号" aria-label="搜索姓名或账号编号" :disabled="directoryState !== 'ready'" @keydown.esc.prevent="searchTerm = ''">
          <kbd v-if="searchTerm">Esc</kbd>
        </label>
        <AppButton variant="secondary" size="sm" :disabled="directoryState === 'loading' || Boolean(pendingAction)" @click="refreshAll">
          <RefreshCw :size="14" :class="{ 'directory-studio__refresh-icon': directoryState === 'loading' }" aria-hidden="true" />刷新
        </AppButton>
      </div>
    </div>

    <div v-if="view === 'members' && directoryState === 'ready'" class="directory-studio__filter-row" role="group" aria-label="按账号角色筛选">
      <button type="button" :aria-pressed="memberFilter === 'all'" @click="memberFilter = 'all'">全部 <span>{{ memberCounts.all }}</span></button>
      <button type="button" :aria-pressed="memberFilter === 'student'" @click="memberFilter = 'student'">学生 <span>{{ memberCounts.student }}</span></button>
      <button type="button" :aria-pressed="memberFilter === 'teacher'" @click="memberFilter = 'teacher'">教师 <span>{{ memberCounts.teacher }}</span></button>
      <button type="button" :aria-pressed="memberFilter === 'pending'" @click="memberFilter = 'pending'">待激活 <span>{{ memberCounts.pending }}</span></button>
      <span class="directory-studio__filter-spacer" />
      <span class="directory-studio__record-count" v-if="directoryState === 'ready'">{{ filteredMembers.length }} 条记录</span>
    </div>

    <Transition name="directory-view" mode="out-in">
      <section v-if="directoryState === 'loading'" key="loading" class="directory-studio__loading" aria-busy="true" aria-label="正在读取目录">
        <span class="directory-studio__loading-line directory-studio__loading-line--wide" /><span class="directory-studio__loading-line" /><span class="directory-studio__loading-line" />
        <p>正在读取当前学校目录…</p>
      </section>

      <section v-else-if="directoryState === 'error'" key="error" class="directory-studio__empty directory-studio__empty--error" role="status">
        <span class="directory-studio__empty-icon"><CircleHelp :size="20" aria-hidden="true" /></span>
        <h2>目录暂时无法读取</h2>
        <p>{{ pageError || '请检查登录状态后刷新目录。' }}</p>
        <AppButton variant="secondary" size="sm" @click="refreshAll"><RefreshCw :size="14" aria-hidden="true" />重新读取</AppButton>
      </section>

      <section v-else-if="view === 'members'" id="directory-members-panel" key="members" class="directory-studio__table-card" role="tabpanel" aria-labelledby="directory-members-tab">
        <header class="directory-studio__table-heading">
          <div><h2 id="directory-table-title">人员目录</h2><p>本校学生与教师账号</p></div>
          <span class="directory-studio__table-total">{{ filteredMembers.length }} / {{ allMembers.length }}</span>
        </header>
        <div v-if="filteredMembers.length" class="directory-studio__table-wrap">
          <table class="directory-studio__table">
            <thead><tr><th scope="col">学校成员</th><th scope="col">角色</th><th scope="col">账号状态</th><th scope="col" class="directory-studio__action-heading"><span class="sr-only">操作</span></th></tr></thead>
            <tbody>
              <tr v-for="member in filteredMembers" :key="`${member.user_id}:${member.role}`" :class="{ 'directory-studio__row--disabled': directoryStale }">
                <td>
                  <button type="button" class="directory-studio__member-trigger" :disabled="directoryStale" @click="openMember(member, $event)">
                    <span class="directory-studio__avatar" :class="`directory-studio__avatar--${member.role}`">{{ member.display_name?.trim()?.slice(0, 1) || roleLabel(member.role).slice(0, 1) }}</span>
                    <span class="directory-studio__member-copy"><strong>{{ member.display_name?.trim() || `${roleLabel(member.role)}账号` }}</strong><small>账号 · {{ shortRef(member.user_id) }}</small></span>
                  </button>
                </td>
                <td><span class="directory-studio__role" :class="`directory-studio__role--${member.role}`">{{ roleLabel(member.role) }}</span></td>
                <td>
                  <div class="directory-studio__status-stack">
                    <span class="directory-studio__status" :class="`directory-studio__status--${accountStatus(member.account_status).tone}`"><i aria-hidden="true" />{{ accountStatus(member.account_status).label }}</span>
                    <span v-if="provisioningStatus(member.provisioning_status)" class="directory-studio__provisioning" :class="`directory-studio__provisioning--${provisioningStatus(member.provisioning_status)?.tone}`">{{ provisioningStatus(member.provisioning_status)?.label }}</span>
                  </div>
                </td>
                <td class="directory-studio__action-cell"><button type="button" class="directory-studio__row-action" :disabled="directoryStale" :aria-label="`查看${member.display_name?.trim() || roleLabel(member.role) + '账号'}详情`" @click="openMember(member, $event)"><ChevronRight :size="17" aria-hidden="true" /></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="directory-studio__table-empty">
          <span class="directory-studio__empty-icon"><UsersRound :size="19" aria-hidden="true" /></span>
          <strong>{{ allMembers.length ? '没有符合条件的账号' : '当前学校没有人员账号' }}</strong>
          <span>{{ allMembers.length ? '更换搜索内容或筛选条件。' : '导入账号后，人员会显示在这里。' }}</span>
          <button v-if="allMembers.length && (searchTerm || memberFilter !== 'all')" type="button" @click="searchTerm = ''; memberFilter = 'all'">清除筛选</button>
        </div>
      </section>

      <section v-else id="directory-classes-panel" key="classes" class="directory-studio__classes" role="tabpanel" aria-labelledby="directory-classes-tab">
        <header class="directory-studio__classes-heading">
          <AppButton variant="primary" size="sm" :disabled="directoryState !== 'ready' || directoryStale || Boolean(pendingAction) || !frontendApi.createSchoolClass || !frontendApi.updateSchoolClassDisplayName" @click="createClassDialogOpen = true"><Plus :size="15" aria-hidden="true" />创建班级</AppButton>
        </header>
        <div v-if="sortedClasses.length" class="directory-studio__class-grid">
          <AdminWorkspaceFolderCard
            v-for="item in sortedClasses"
            :key="item.class_ref"
            :folder="folderForClass(item)"
            :active="selectedClassRef === item.class_ref"
            :disabled="directoryStale"
            @open="(_folder, source) => openClass(item, false, item.display_name ?? '', source)"
          />
        </div>
        <div v-else class="directory-studio__empty directory-studio__empty--class">
          <span class="directory-studio__empty-icon"><Building2 :size="20" aria-hidden="true" /></span>
          <h2>还没有班级</h2>
          <p>创建班级后，可以查看有效人数并管理人员分配。</p>
          <AppButton variant="secondary" size="sm" :disabled="directoryState !== 'ready' || directoryStale || !frontendApi.createSchoolClass || !frontendApi.updateSchoolClassDisplayName" @click="createClassDialogOpen = true"><Plus :size="14" aria-hidden="true" />创建班级</AppButton>
        </div>
      </section>
    </Transition>

    <section v-if="pendingAccounts.length && directoryState === 'ready'" class="directory-studio__pending-strip" aria-labelledby="directory-pending-title">
      <header><div><span class="directory-studio__pending-icon"><KeyRound :size="16" aria-hidden="true" /></span><div><h2 id="directory-pending-title">待激活账号</h2><p>逐个设置登录密码后激活</p></div></div><span>{{ pendingAccounts.length }}</span></header>
      <div class="directory-studio__pending-list">
        <button v-for="account in pendingAccounts.slice(0, 4)" :key="account.user_id" type="button" :disabled="directoryStale" @click="openPendingMember(account, $event)">
          <span class="directory-studio__pending-avatar" :class="`directory-studio__pending-avatar--${account.role}`">{{ account.display_name.slice(0, 1) || roleLabel(account.role).slice(0, 1) }}</span>
          <span><strong>{{ account.display_name || `${roleLabel(account.role)}账号` }}</strong><small>{{ roleLabel(account.role) }} · {{ shortRef(account.user_id) }}</small></span>
          <ChevronRight :size="15" aria-hidden="true" />
        </button>
        <span v-if="pendingAccounts.length > 4" class="directory-studio__pending-more">还有 {{ pendingAccounts.length - 4 }} 个</span>
      </div>
      <p v-if="batchRefreshError" class="directory-studio__pending-refresh" role="status">最近导入批次状态暂时无法读取，刷新目录后再处理。</p>
    </section>
  </section>

  <DrawerDialogRoot :open="detailOpen" @update:open="handleDetailOpen">
    <DrawerDialogPortal>
      <DrawerDialogOverlay class="directory-detail__overlay" :class="{ 'directory-detail__overlay--opening': !closingDetail, 'directory-detail__overlay--closing': closingDetail, 'directory-detail__overlay--instant': Boolean(selectedClass) }" />
      <span v-if="selectedPaperOrigin" :key="`${selectedMemberId}:${selectedClassRef}:${selectedPaperIndex}`" class="directory-detail__paper" :class="{ 'directory-detail__paper--closing': closingDetail }" :style="{ ...detailPaperStyle, '--paper-surface': detailPalette.surface, '--paper-accent': detailPalette.accent }" aria-hidden="true" @animationend="handleDetailPaperAnimationEnd">
        <i class="directory-detail__paper-mark" /><i class="directory-detail__paper-line" /><i class="directory-detail__paper-line directory-detail__paper-line--short" />
      </span>
      <DrawerDialogContent class="directory-detail__panel" :class="[{ 'directory-detail__panel--member': Boolean(selectedMember), 'directory-detail__panel--class': Boolean(selectedClass) }, { 'directory-detail__panel--closing': closingDetail }]" :style="{ ...detailPanelStyle, '--directory-detail-accent': detailPalette.accent }" :aria-label="selectedMember ? '人员详情卡片' : '班级管理卡片'" @animationend="handleDetailPanelAnimationEnd">
        <header class="directory-drawer__header">
          <div><span class="directory-drawer__eyebrow">{{ selectedMember ? '学校人员' : '组织目录' }}</span><DrawerDialogTitle class="directory-drawer__title">{{ selectedMember ? '账号详情' : selectedClass ? '班级详情' : '详情' }}</DrawerDialogTitle></div>
          <DrawerDialogClose as-child><button type="button" class="directory-drawer__close" aria-label="关闭详情" :disabled="closingDetail"><X :size="18" aria-hidden="true" /></button></DrawerDialogClose>
        </header>
        <div v-if="drawerExitMessage" class="directory-drawer__message" role="status">{{ drawerExitMessage }}</div>
        <div class="directory-drawer__body">
          <template v-if="selectedMember">
            <section class="directory-drawer__identity">
              <span class="directory-drawer__avatar" :class="`directory-drawer__avatar--${selectedMember.role}`"><template v-if="selectedMember.display_name?.trim()">{{ selectedMember.display_name.trim().slice(0, 1) }}</template><UsersRound v-else :size="18" aria-hidden="true" /></span>
              <div><strong>{{ roleLabel(selectedMember.role) }}账号</strong></div>
            </section>
            <dl class="directory-drawer__facts">
              <div><dt>账号编号</dt><dd>…{{ shortRef(selectedMember.user_id) }}</dd></div>
              <div><dt>账号状态</dt><dd><span class="directory-studio__status" :class="`directory-studio__status--${accountStatus(selectedMember.account_status).tone}`"><i aria-hidden="true" />{{ accountStatus(selectedMember.account_status).label }}</span></dd></div>
              <div><dt>开通流程</dt><dd>{{ provisioningStatus(selectedMember.provisioning_status)?.label ?? '未提供' }}</dd></div>
            </dl>

            <section class="directory-drawer__section">
              <header><div><h3>显示名称</h3><p>修改名称会同步到当前学校目录。</p></div><button v-if="!memberNameEditing" type="button" class="directory-drawer__text-action" :disabled="directoryStale || Boolean(pendingAction) || !frontendApi.updateSchoolMemberDisplayName" @click="memberNameDraft = selectedMember?.display_name ?? ''; memberNameEditing = true"><Pencil :size="14" aria-hidden="true" />修改</button></header>
              <form v-if="memberNameEditing" class="directory-drawer__edit-form" @submit.prevent="saveMemberName">
                <label class="sr-only" for="directory-member-name">显示名称</label>
                <input id="directory-member-name" v-model="memberNameDraft" maxlength="120" autocomplete="off" :disabled="Boolean(pendingAction)" aria-describedby="directory-member-name-hint">
                <p id="directory-member-name-hint">1 至 120 个字符</p>
                <div><AppButton type="submit" size="sm" :disabled="!memberNameDraft.trim() || !isMemberNameDirty || directoryStale || !frontendApi.updateSchoolMemberDisplayName" :loading="pendingAction === `member-name-${selectedMember.user_id}`">保存名称</AppButton><AppButton type="button" variant="secondary" size="sm" :disabled="Boolean(pendingAction)" @click="cancelMemberNameEdit">取消</AppButton></div>
              </form>
              <p v-else class="directory-drawer__value">{{ selectedMember.display_name?.trim() || '尚未设置' }}</p>
            </section>

            <section v-if="selectedMember.provisioning_status === 'PENDING_ACTIVATION'" class="directory-drawer__activation-card">
              <span class="directory-drawer__activation-icon"><KeyRound :size="17" aria-hidden="true" /></span>
              <div><strong>账号待激活</strong><p>为此账号设置登录密码后完成激活。</p></div>
              <AppButton variant="secondary" size="sm" :disabled="directoryStale || Boolean(pendingAction) || activationPending || !frontendApi.activateSchoolAccount" @click="beginActivation(selectedMember.user_id)">设置密码</AppButton>
            </section>
          </template>

          <template v-else-if="selectedClass">
            <section class="directory-drawer__class-summary">
              <div class="directory-drawer__class-ref"><Building2 :size="15" aria-hidden="true" />班级编号 <span>{{ selectedClass.class_ref }}</span></div>
              <div class="directory-drawer__class-metrics"><div><span>有效学生</span><strong>{{ selectedClass.active_student_count }}</strong></div><div><span>有效教师</span><strong>{{ selectedClass.active_teacher_count }}</strong></div></div>
            </section>

            <section class="directory-drawer__section">
              <header><div><h3>班级名称</h3><p>名称仅用于本校目录展示。</p></div><button v-if="!classNameEditing" type="button" class="directory-drawer__text-action" :disabled="directoryStale || Boolean(pendingAction) || !frontendApi.updateSchoolClassDisplayName" @click="classNameDraft = selectedClass?.display_name ?? ''; classNameEditing = true"><Pencil :size="14" aria-hidden="true" />修改</button></header>
              <form v-if="classNameEditing" class="directory-drawer__edit-form" @submit.prevent="saveClassName">
                <label class="sr-only" for="directory-class-name">班级名称</label>
                <input id="directory-class-name" v-model="classNameDraft" maxlength="120" autocomplete="off" :disabled="Boolean(pendingAction)" aria-describedby="directory-class-name-hint">
                <p id="directory-class-name-hint">1 至 120 个字符</p>
                <div><AppButton type="submit" size="sm" :disabled="!classNameDraft.trim() || !isClassNameDirty || directoryStale || !frontendApi.updateSchoolClassDisplayName" :loading="pendingAction === `class-name-${selectedClass.class_ref}`">保存名称</AppButton><AppButton type="button" variant="secondary" size="sm" :disabled="Boolean(pendingAction)" @click="cancelClassNameEdit">取消</AppButton></div>
              </form>
              <p v-else class="directory-drawer__value">{{ className(selectedClass) }}</p>
            </section>

            <section class="directory-drawer__section directory-drawer__assignment">
              <header><div><h3>分配学生</h3><p>仅显示服务端返回的本校学生账号。</p></div></header>
              <div v-if="candidatesState === 'loading'" class="directory-drawer__candidate-state" aria-busy="true">正在读取可分配人员…</div>
              <div v-else-if="candidatesState === 'error'" class="directory-drawer__candidate-state directory-drawer__candidate-state--error" role="status">暂时无法读取学生账号。<button type="button" @click="refreshCandidates">重新读取</button></div>
              <div v-else-if="!students.length" class="directory-drawer__candidate-state">当前没有可分配的学生账号。</div>
              <form v-else class="directory-drawer__assign-row" @submit.prevent="assignMember('student')">
                <AdminMemberCombobox v-model="selectedStudentId" role="student" :members="roleOptions.students" :disabled="directoryStale || Boolean(pendingAction)" />
                <AppButton type="submit" variant="secondary" size="sm" :disabled="!selectedStudentId || directoryStale || !frontendApi.assignSchoolStudent" :loading="pendingAction === 'assign-student'">分配</AppButton>
              </form>
            </section>

            <section class="directory-drawer__section directory-drawer__assignment">
              <header><div><h3>分配教师</h3><p>仅显示服务端返回的本校教师账号。</p></div></header>
              <div v-if="candidatesState === 'loading'" class="directory-drawer__candidate-state" aria-busy="true">正在读取可分配人员…</div>
              <div v-else-if="candidatesState === 'error'" class="directory-drawer__candidate-state directory-drawer__candidate-state--error" role="status">暂时无法读取教师账号。<button type="button" @click="refreshCandidates">重新读取</button></div>
              <div v-else-if="!teachers.length" class="directory-drawer__candidate-state">当前没有可分配的教师账号。</div>
              <form v-else class="directory-drawer__assign-row" @submit.prevent="assignMember('teacher')">
                <AdminMemberCombobox v-model="selectedTeacherId" role="teacher" :members="roleOptions.teachers" :disabled="directoryStale || Boolean(pendingAction)" />
                <AppButton type="submit" variant="secondary" size="sm" :disabled="!selectedTeacherId || directoryStale || !frontendApi.assignSchoolTeacher" :loading="pendingAction === 'assign-teacher'">分配</AppButton>
              </form>
            </section>
          </template>
        </div>
      </DrawerDialogContent>
    </DrawerDialogPortal>
  </DrawerDialogRoot>

  <AppDialog :open="schoolDialogOpen" title="学校设置" description="修改当前学校在目录中显示的名称。" @update:open="closeSchoolDialog">
    <form class="directory-dialog-form" @submit.prevent="saveSchoolName">
      <label for="directory-school-name">学校名称</label>
      <input id="directory-school-name" v-model="schoolNameDraft" maxlength="120" autocomplete="organization" :disabled="Boolean(pendingAction)" required>
      <p>最多 120 个字符。</p>
      <div class="directory-dialog-form__actions"><AppButton type="button" variant="secondary" :disabled="Boolean(pendingAction)" @click="schoolDialogOpen = false">取消</AppButton><AppButton type="submit" :disabled="!schoolNameDraft.trim() || directoryStale || !frontendApi.updateSchoolDisplayName" :loading="pendingAction === 'school-name'">保存名称</AppButton></div>
    </form>
  </AppDialog>

  <AppDialog :open="createClassDialogOpen" title="创建班级" description="创建后会保存班级名称，并显示服务端生成的班级编号。" @update:open="closeCreateClassDialog">
    <form class="directory-dialog-form" @submit.prevent="createClass">
      <label for="directory-new-class-name">班级名称</label>
      <input id="directory-new-class-name" v-model="newClassName" maxlength="120" autocomplete="off" placeholder="例如：24级1班" :disabled="Boolean(pendingAction)" required>
      <p>名称需为 1 至 120 个字符。</p>
      <div class="directory-dialog-form__actions"><AppButton type="button" variant="secondary" :disabled="Boolean(pendingAction)" @click="createClassDialogOpen = false">取消</AppButton><AppButton type="submit" :disabled="!newClassName.trim() || directoryState !== 'ready' || directoryStale || !frontendApi.createSchoolClass || !frontendApi.updateSchoolClassDisplayName" :loading="pendingAction === 'create-class'">创建班级</AppButton></div>
    </form>
  </AppDialog>

  <AppDialog :open="importDialogOpen" title="导入账号" description="账号导入分三步完成：选择文件、服务端预览、确认导入。" @update:open="closeImportWizard">
    <div class="directory-import">
      <ol class="directory-import__steps" aria-label="导入步骤">
        <li v-for="(step, index) in ['选择文件', '服务端预览', '确认导入']" :key="step" :class="{ 'directory-import__step--active': importStage === index + 1, 'directory-import__step--done': importStage > index + 1 }">
          <span>{{ importStage > index + 1 ? '✓' : index + 1 }}</span><strong>{{ step }}</strong>
        </li>
      </ol>

      <section v-if="importStage === 1" class="directory-import__stage" aria-labelledby="directory-import-stage-one">
        <h3 id="directory-import-stage-one">选择 CSV 或 Excel 文件</h3>
        <p>支持 CSV、XLSX 和 XLS；CSV 使用 UTF-8，Excel 默认读取第一个工作表。文件不超过 500 KiB，表头须为 login_name、display_name、role，最多导入 100 个账号。</p>
        <label class="directory-import__field" id="directory-import-class-label">关联班级 <span>可选</span></label>
        <ImportClassRoot :model-value="importClassRef || '__no_class__'" :disabled="Boolean(pendingAction) || Boolean(csvIdempotencyKey) || !directory" @update:model-value="updateImportClass($event === '__no_class__' ? '' : String($event ?? ''))">
          <ImportClassTrigger id="directory-import-class" class="directory-import__class-trigger" aria-labelledby="directory-import-class-label">
            <ImportClassValue placeholder="不关联班级" />
            <ChevronDown :size="16" aria-hidden="true" />
          </ImportClassTrigger>
          <ImportClassPortal>
            <ImportClassContent class="directory-import__class-content" position="popper" :side-offset="6" align="start">
              <ImportClassViewport class="directory-import__class-viewport">
                <ImportClassItem value="__no_class__" class="directory-import__class-item">
                  <ImportClassItemText>不关联班级</ImportClassItemText>
                  <ImportClassItemIndicator class="directory-import__class-indicator"><Check :size="15" aria-hidden="true" /></ImportClassItemIndicator>
                </ImportClassItem>
                <ImportClassItem v-for="item in sortedClasses" :key="item.class_ref" :value="item.class_ref" class="directory-import__class-item">
                  <ImportClassItemText>{{ className(item) }}</ImportClassItemText>
                  <ImportClassItemIndicator class="directory-import__class-indicator"><Check :size="15" aria-hidden="true" /></ImportClassItemIndicator>
                </ImportClassItem>
              </ImportClassViewport>
            </ImportClassContent>
          </ImportClassPortal>
        </ImportClassRoot>
        <label class="directory-import__file" for="directory-import-file">
          <span class="directory-import__file-icon"><FileSpreadsheet :size="18" aria-hidden="true" /></span>
          <span><strong>{{ csvFileName || '选择导入文件' }}</strong><small>{{ csvRows.length ? `本地格式检查通过，共 ${csvRows.length} 行` : '支持 .csv、.xlsx、.xls；不需要密码列' }}</small></span>
          <span class="directory-import__file-action">浏览文件</span>
        </label>
        <input id="directory-import-file" class="sr-only" type="file" accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.xls,application/vnd.ms-excel" :disabled="directoryState !== 'ready' || Boolean(csvIdempotencyKey) || Boolean(pendingAction)" @change="acceptCsvFile">
        <p v-if="csvClientError" class="directory-import__error" role="alert">{{ csvClientError }}</p>
        <p v-if="csvPreviewError" class="directory-import__error" role="alert">{{ csvPreviewError }}</p>
        <div class="directory-import__footer directory-import__footer--stage-one"><div class="directory-import__footer-actions"><button v-if="csvFileName || csvClientError" type="button" class="directory-import__back" :disabled="Boolean(pendingAction) || Boolean(csvIdempotencyKey)" @click="clearCsvFile">清除文件</button><AppButton type="button" :disabled="!csvRows.length || directoryState !== 'ready' || Boolean(pendingAction) || directoryStale || !frontendApi.previewSchoolAccountImport" :loading="pendingAction === 'preview-import'" @click="previewImport">进行服务端预览</AppButton></div></div>
      </section>

      <section v-else-if="importStage === 2" class="directory-import__stage" aria-labelledby="directory-import-stage-two">
        <h3 id="directory-import-stage-two">服务端预览</h3>
        <p>{{ csvFileName }} · 服务端将校验 {{ csvPreview?.row_count ?? csvRows.length }} 行，不会在此步骤创建账号。</p>
        <div v-if="csvPreviewError" class="directory-import__preview-error" role="alert"><CircleAlert :size="16" aria-hidden="true" />{{ csvPreviewError }}</div>
        <div v-else-if="csvPreview" class="directory-import__preview-summary" :class="csvPreview.valid && !csvPreview.errors.length ? 'directory-import__preview-summary--valid' : 'directory-import__preview-summary--invalid'">
          <span class="directory-import__preview-mark"><Check v-if="csvPreview.valid && !csvPreview.errors.length" :size="17" aria-hidden="true" /><CircleAlert v-else :size="17" aria-hidden="true" /></span>
          <div><strong>{{ csvPreview.valid && !csvPreview.errors.length ? '服务端检查通过' : '需要修正文件内容' }}</strong><span>{{ csvPreview.row_count }} 行 · {{ csvPreview.errors.length }} 个问题</span></div>
        </div>
        <ul v-if="csvPreview?.errors.length" class="directory-import__errors">
          <li v-for="(item, index) in csvPreview.errors.slice(0, 8)" :key="`${item.row_no}-${item.code}-${index}`"><span>第 {{ item.row_no }} 行</span>{{ serverImportErrorText[item.code] ?? '服务端拒绝此行。' }}<code>{{ item.code }}</code></li>
          <li v-if="csvPreview.errors.length > 8" class="directory-import__errors-more">另有 {{ csvPreview.errors.length - 8 }} 个问题。</li>
        </ul>
        <div v-if="!csvPreview && !csvPreviewError" class="directory-import__preview-error" role="status">尚未收到服务端预览。</div>
        <div class="directory-import__footer"><button class="directory-import__back" type="button" :disabled="Boolean(csvIdempotencyKey)" @click="clearServerPreview()">返回选择文件</button><AppButton type="button" :disabled="!canAdvanceToConfirm || Boolean(pendingAction)" @click="importStage = 3">继续确认<ChevronRight :size="15" aria-hidden="true" /></AppButton></div>
      </section>

      <section v-else class="directory-import__stage" aria-labelledby="directory-import-stage-three">
        <h3 id="directory-import-stage-three">确认导入</h3>
        <template v-if="importedBatch && !csvRows.length">
          <div class="directory-import__complete"><span><Check :size="20" aria-hidden="true" /></span><strong>已创建 {{ importedBatch.created_count }} 个账号</strong><p>待激活账号可在人员目录中逐个打开并设置登录密码。</p></div>
          <div class="directory-import__footer"><button class="directory-import__back" type="button" @click="closeImportWizard(false)">返回目录</button><AppButton type="button" variant="secondary" @click="startNewImport">再导入一批</AppButton></div>
        </template>
        <template v-else>
          <div class="directory-import__confirm-card"><span><FileSpreadsheet :size="18" aria-hidden="true" /></span><div><strong>{{ csvFileName }}</strong><small>{{ csvPreview?.row_count }} 个账号 · {{ importClassRef ? (directory?.classes.find((item) => item.class_ref === importClassRef) ? className(directory.classes.find((item) => item.class_ref === importClassRef)!) : '目标班级') : '不关联班级' }}</small></div></div>
          <p class="directory-import__confirm-copy">确认后服务端将一次性创建这批账号。账号需要后续逐个激活，不会自动生成或分发密码。</p>
          <p v-if="csvPreviewError" class="directory-import__error" role="alert">{{ csvPreviewError }}</p>
          <div class="directory-import__footer"><button class="directory-import__back" type="button" :disabled="Boolean(pendingAction)" @click="importStage = 2">返回预览</button><AppButton type="button" :disabled="!canAdvanceToConfirm || Boolean(pendingAction) || directoryStale || !frontendApi.importSchoolAccounts" :loading="pendingAction === 'import-accounts'" @click="importAccounts">确认并导入</AppButton></div>
        </template>
      </section>
    </div>
  </AppDialog>

  <ActivationDialogRoot :open="activationDialogOpen" @update:open="closeActivation">
    <ActivationDialogPortal>
      <ActivationDialogOverlay class="directory-activation-dialog__overlay" />
      <ActivationDialogContent class="directory-activation-dialog__panel">
        <header class="directory-activation-dialog__header"><div><span class="directory-activation-dialog__icon"><ShieldCheck :size="18" aria-hidden="true" /></span><div><ActivationDialogTitle class="directory-activation-dialog__title">激活账号</ActivationDialogTitle><ActivationDialogDescription class="directory-activation-dialog__description">{{ activationAccount ? `${activationAccount.display_name || roleLabel(activationAccount.role)} · 账号 ${shortRef(activationAccount.user_id)}` : '为待激活账号设置登录密码。' }}</ActivationDialogDescription></div></div><ActivationDialogClose as-child><button type="button" class="directory-activation-dialog__close" aria-label="关闭激活窗口"><X :size="17" aria-hidden="true" /></button></ActivationDialogClose></header>
        <form class="directory-dialog-form" @submit.prevent="activateAccount">
          <label for="directory-new-password">新登录密码</label>
          <input id="directory-new-password" v-model="newPassword" type="password" autocomplete="new-password" minlength="12" maxlength="256" :disabled="activationPending" required>
          <p>至少 12 位，并包含小写字母、大写字母、数字、符号中的至少三类。</p>
          <p v-if="activationError" class="directory-import__error" role="alert">{{ activationError }}</p>
          <div class="directory-dialog-form__actions"><AppButton type="button" variant="secondary" :disabled="activationPending" @click="closeActivation(false)">取消</AppButton><AppButton type="submit" :disabled="!newPassword || directoryStale || !activationAccount || activationAccount.status !== 'PENDING_ACTIVATION'" :loading="activationPending">激活账号</AppButton></div>
        </form>
      </ActivationDialogContent>
    </ActivationDialogPortal>
  </ActivationDialogRoot>
</template>

<style scoped>
.directory-studio { --directory-ink: #203b4d; --directory-muted: #718996; --directory-line: #e2ebef; --directory-blue: #0d96b8; --directory-blue-dark: #087d9b; min-width: 0; padding-bottom: 12px; color: var(--directory-ink); }
.directory-studio__header { display: flex; align-items: center; justify-content: flex-end; gap: 24px; margin: 4px 0 10px; }
.directory-studio__header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 9px; }
.directory-studio__school-action { display: inline-flex; max-width: min(300px, 30vw); min-height: 38px; align-items: center; gap: 8px; padding: 0 11px; border: 1px solid transparent; border-radius: 9px; color: #617987; background: transparent; font: inherit; font-size: 13px; cursor: pointer; transition: border-color 140ms ease, color 140ms ease, background-color 140ms ease; }
.directory-studio__school-action span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.directory-studio__school-action > svg:last-child { color: #91a3ac; }
.directory-studio__school-action:hover:not(:disabled) { border-color: #dce8ec; color: #22758d; background: #fff; }
.directory-studio__school-action:disabled { opacity: .52; cursor: not-allowed; }
.directory-studio__header-actions :deep(.app-button--sm),.directory-studio__tools :deep(.app-button--sm) { font-size: 15px; }
.directory-studio__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 56px; padding: 8px 0 11px; border-bottom: 1px solid var(--directory-line); }
.directory-studio__view-switch { position: relative; display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-items: center; gap: 0; min-width: 224px; padding: 4px; border: 1px solid #e3ecef; border-radius: 11px; background: #f2f7f8; }
.directory-studio__view-thumb { position: absolute; inset: 4px auto 4px 4px; width: calc((100% - 8px) / 2); border: 1px solid #e8eff1; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgb(37 69 81 / 10%); transition: transform 230ms cubic-bezier(.22, 1, .36, 1); }
.directory-studio__view-switch--classes .directory-studio__view-thumb { transform: translateX(100%); }
.directory-studio__view-switch button { position: relative; z-index: 1; display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 7px; padding: 0 11px; border: 0; border-radius: 8px; color: #6b838e; background: transparent; font: inherit; font-size: 13px; font-weight: 620; cursor: pointer; transition: color 150ms ease; }
.directory-studio__view-switch button > span { display: inline-grid; min-width: 19px; height: 19px; place-items: center; padding: 0 4px; border-radius: 6px; color: #78909b; background: #e7eff1; font-size: 11px; font-variant-numeric: tabular-nums; }
.directory-studio__view-switch button[aria-selected='true'] { color: #167d98; }
.directory-studio__view-switch button[aria-selected='true'] > span { color: #167d98; background: #eaf6f8; }
.directory-studio__tools { display: flex; align-items: center; gap: 9px; }
.directory-studio__search { display: flex; width: min(330px, 32vw); min-width: 188px; height: 38px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #dfe8ec; border-radius: 9px; color: #80949e; background: #fff; transition: border-color 140ms ease, box-shadow 140ms ease; }
.directory-studio__search:focus-within { border-color: #81c6d5; box-shadow: 0 0 0 3px rgb(14 158 190 / 9%); }
.directory-studio__search input { width: 100%; min-width: 0; height: 34px; border: 0; outline: 0; color: var(--directory-ink); background: transparent; font: inherit; font-size: 13px; }
.directory-studio__search input::placeholder { color: #96a6ae; }
.directory-studio__search input::-webkit-search-cancel-button { cursor: pointer; }
.directory-studio__search:has(input:disabled) { opacity: .55; }
.directory-studio__search kbd { padding: 2px 4px; border: 1px solid #e3eaed; border-radius: 4px; color: #8497a0; background: #f7f9fa; font: inherit; font-size: 11px; }
.directory-studio__filter-row { display: flex; align-items: center; gap: 5px; min-height: 53px; }
.directory-studio__filter-row button { display: inline-flex; min-height: 32px; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid transparent; border-radius: 7px; color: #728894; background: transparent; font: inherit; font-size: 14px; cursor: pointer; transition: color 130ms ease, background-color 130ms ease; }
.directory-studio__filter-row button:hover { color: #227d95; background: #f1f8fa; }
.directory-studio__filter-row button[aria-pressed='true'] { border-color: #dcebee; color: #197b94; background: #edf7f9; font-weight: 690; }
.directory-studio__filter-row button span { color: #94a5ad; font-size: 13px; font-variant-numeric: tabular-nums; }
.directory-studio__filter-spacer { flex: 1; }
.directory-studio__record-count,.directory-studio__table-total { color: #84969f; font-size: 14px; font-variant-numeric: tabular-nums; }
.directory-studio__callout { display: flex; align-items: flex-start; gap: 9px; margin: 0 0 12px; padding: 11px 13px; border: 1px solid #d8ebe9; border-radius: 9px; color: #397b76; background: #f1f8f6; font-size: 11px; line-height: 1.55; }
.directory-studio__callout > svg { flex: 0 0 auto; margin-top: 1px; }
.directory-studio__callout--error { border-color: #f0dcd8; color: #9b4b3c; background: #fcf5f3; }
.directory-studio__callout--warning { border-color: #f0e4c8; color: #906b2e; background: #fbf7ec; }
.directory-studio__table-card { overflow: hidden; border: 1px solid #e0e9ed; border-radius: 12px; background: #fff; box-shadow: 0 6px 20px rgb(41 75 91 / 3%); }
.directory-studio__table-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 67px; padding: 12px 19px; border-bottom: 1px solid #edf1f3; }
.directory-studio__table-heading h2 { margin: 0; color: var(--directory-ink); font-size: 18px; font-weight: 710; }
.directory-studio__table-heading p { margin: 4px 0 0; color: #8a9ca5; font-size: 14px; }
.directory-studio__table-wrap { width: 100%; }
.directory-studio__table { width: 100%; border-collapse: collapse; table-layout: fixed; text-align: left; }
.directory-studio__table thead { background: #fbfcfc; }
.directory-studio__table th { height: 43px; padding: 0 17px; color: #8b9ca4; font-size: 13px; font-weight: 650; }
.directory-studio__table th:first-child { width: 48%; padding-left: 20px; }
.directory-studio__table th:nth-child(2) { width: 17%; }
.directory-studio__table th:nth-child(3) { width: 27%; }
.directory-studio__table th:last-child { width: 48px; }
.directory-studio__table td { height: 70px; padding: 8px 17px; border-top: 1px solid #eff3f4; vertical-align: middle; }
.directory-studio__table td:first-child { padding-left: 20px; }
.directory-studio__table tbody tr { transition: background-color 140ms ease; }
.directory-studio__table tbody tr:hover { background: #f8fbfc; }
.directory-studio__row--disabled { opacity: .58; }
.directory-studio__member-trigger { display: inline-flex; width: 100%; min-width: 0; align-items: center; gap: 11px; padding: 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.directory-studio__member-trigger:disabled { cursor: not-allowed; }
.directory-studio__avatar,.directory-drawer__avatar { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border: 1px solid #dcebf0; border-radius: 11px; color: #207d98; background: #eff8fa; font-size: 15px; font-weight: 720; }
.directory-studio__table .directory-studio__avatar { font-size: 17px; }
.directory-studio__avatar--teacher,.directory-drawer__avatar--teacher { border-color: #e4e3f4; color: #6d6ca6; background: #f2f1fb; }
.directory-studio__member-copy { display: grid; min-width: 0; gap: 3px; }
.directory-studio__member-copy strong { overflow: hidden; color: #294253; font-size: 15px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.directory-studio__member-copy small { overflow: hidden; color: #91a1a9; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.directory-studio__role { display: inline-flex; min-height: 25px; align-items: center; padding: 0 8px; border: 1px solid #d8ebef; border-radius: 6px; color: #397d90; background: #f0f8fa; font-size: 13px; font-weight: 650; white-space: nowrap; }
.directory-studio__role--teacher { border-color: #e5e4f3; color: #7774a8; background: #f6f5fb; }
.directory-studio__status-stack { display: flex; flex-wrap: wrap; align-items: center; gap: 5px 7px; }
.directory-studio__status { display: inline-flex; align-items: center; gap: 6px; color: #68816e; font-size: 13px; font-weight: 620; white-space: nowrap; }
.directory-studio__status i { width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; background: currentColor; }
.directory-studio__status--available { color: #397f6e; }
.directory-studio__status--paused,.directory-studio__status--disabled { color: #a2733f; }
.directory-studio__status--unknown { color: #8798a0; }
.directory-studio__provisioning { display: inline-flex; min-height: 22px; align-items: center; padding: 0 7px; border-radius: 5px; color: #977128; background: #fbf4e3; font-size: 12px; font-weight: 650; white-space: nowrap; }
.directory-studio__provisioning--available { color: #39806f; background: #edf7f3; }
.directory-studio__provisioning--unknown { color: #748891; background: #f1f4f5; }
.directory-studio__action-heading { text-align: center; }
.directory-studio__action-cell { text-align: center; }
.directory-studio__row-action { display: inline-grid; width: 29px; height: 29px; place-items: center; border: 1px solid transparent; border-radius: 8px; color: #9aabb2; background: transparent; cursor: pointer; transition: color 130ms ease, border-color 130ms ease, background-color 130ms ease; }
.directory-studio__row-action:hover:not(:disabled) { border-color: #dcebef; color: #1684a0; background: #f0f8fa; }
.directory-studio__row-action:disabled { cursor: not-allowed; }
.directory-studio__table-empty { display: grid; min-height: 220px; justify-items: center; align-content: center; gap: 8px; padding: 24px; color: #7e919a; text-align: center; }
.directory-studio__table-empty strong { color: #496271; font-size: 16px; }
.directory-studio__table-empty > span:last-of-type { font-size: 14px; }
.directory-studio__table-empty button { margin-top: 4px; border: 0; color: #1684a0; background: transparent; font: inherit; font-size: 14px; font-weight: 650; cursor: pointer; }
.directory-studio__empty-icon { display: grid; width: 42px; height: 42px; place-items: center; border: 1px solid #e0eaed; border-radius: 13px; color: #468da1; background: #f1f8fa; }
.directory-studio__classes { padding-top: 6px; }
.directory-studio__classes-heading { display: flex; align-items: center; justify-content: flex-end; gap: 14px; margin: 0 0 20px; }
.directory-studio__class-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 19px; padding: 5px 2px 10px; }
.directory-studio__class-grid :deep(.workspace-folder__layer),.directory-studio__class-grid :deep(.workspace-folder__cover) { transition: none; }
.directory-studio__empty { display: flex; min-height: 260px; flex-direction: column; align-items: center; justify-content: center; gap: 9px; padding: 28px; border: 1px dashed #dbe6ea; border-radius: 12px; background: #fff; text-align: center; }
.directory-studio__empty h2 { margin: 4px 0 0; color: #344f5f; font-size: 14px; }
.directory-studio__empty p { max-width: 390px; margin: 0 0 7px; color: #82949d; font-size: 11px; line-height: 1.6; }
.directory-studio__empty--error { min-height: 320px; border-style: solid; }
.directory-studio__loading { display: grid; min-height: 260px; align-content: center; justify-items: center; gap: 10px; }
.directory-studio__loading p { margin: 3px 0 0; color: #82949d; font-size: 11px; }
.directory-studio__loading-line { display: block; width: min(420px, 62%); height: 46px; border: 1px solid #e8eef0; border-radius: 9px; background: linear-gradient(90deg, #f2f6f7 0%, #fafcfc 45%, #f2f6f7 100%); background-size: 200% 100%; animation: directory-sheen 1.2s ease-in-out infinite; }
.directory-studio__loading-line--wide { width: min(680px, 82%); height: 60px; }
.directory-studio__pending-strip { margin-top: 18px; padding: 15px 18px 13px; border: 1px solid #e8e7dc; border-radius: 11px; background: #fcfbf7; }
.directory-studio__pending-strip > header,.directory-studio__pending-strip > header > div { display: flex; align-items: center; }
.directory-studio__pending-strip > header { justify-content: space-between; gap: 12px; }
.directory-studio__pending-strip > header > div { gap: 9px; }
.directory-studio__pending-icon { display: grid; width: 31px; height: 31px; place-items: center; border-radius: 9px; color: #98732c; background: #f8f0de; }
.directory-studio__pending-strip h2 { margin: 0; color: #4d554e; font-size: 11px; font-weight: 700; }
.directory-studio__pending-strip header p { margin: 3px 0 0; color: #92928a; font-size: 9px; }
.directory-studio__pending-strip > header > span { display: grid; min-width: 24px; height: 24px; place-items: center; padding: 0 6px; border-radius: 7px; color: #8f712e; background: #f7f0e1; font-size: 10px; font-weight: 700; }
.directory-studio__pending-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; }
.directory-studio__pending-list > button { display: inline-flex; min-width: 175px; align-items: center; gap: 8px; padding: 7px 9px; border: 1px solid #eee9dd; border-radius: 8px; color: #67756f; background: #fff; text-align: left; cursor: pointer; transition: background-color 130ms ease, border-color 130ms ease; }
.directory-studio__pending-list > button:hover:not(:disabled) { border-color: #e2d8bd; background: #fffdf8; }
.directory-studio__pending-list > button:disabled { opacity: .55; cursor: not-allowed; }
.directory-studio__pending-avatar { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border-radius: 8px; color: #907333; background: #f7f0e1; font-size: 10px; font-weight: 700; }
.directory-studio__pending-avatar--teacher { color: #726fa7; background: #f1f0f8; }
.directory-studio__pending-list > button > span:nth-child(2) { display: grid; min-width: 0; gap: 2px; }
.directory-studio__pending-list strong { overflow: hidden; color: #52625d; font-size: 10px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.directory-studio__pending-list small { color: #97978f; font-size: 8px; }
.directory-studio__pending-list > button > svg { flex: 0 0 auto; margin-left: auto; color: #a99e82; }
.directory-studio__pending-more { align-self: center; color: #8e8d83; font-size: 9px; }
.directory-studio__pending-refresh { margin: 9px 0 0; color: #927342; font-size: 9px; }
.directory-detail__overlay { position: fixed; inset: 0; z-index: 80; background: rgb(25 41 54 / 23%); backdrop-filter: blur(3px); }
.directory-detail__overlay--opening { animation: directory-detail-overlay-in 180ms ease both; }
.directory-detail__overlay--closing { animation: directory-detail-overlay-out 380ms ease both; }
.directory-detail__overlay--instant { animation: none; }
.directory-detail__paper { position: fixed; z-index: 92; display: flex; flex-direction: column; gap: 4px; padding: 5px 6px; border: 1px solid color-mix(in srgb, var(--paper-accent,#168fae) 24%, white); border-radius: 7px; opacity: .95; background: var(--paper-surface,#fff); box-shadow: 0 7px 16px rgb(37 69 85 / 14%); transform-origin: center; animation: directory-detail-paper-fly 460ms linear both; pointer-events: none; }
.directory-detail__paper--closing { animation-name: directory-detail-paper-return; animation-duration: 460ms; animation-delay: 330ms; animation-timing-function: linear; }
.directory-detail__paper-mark { width: 11px; height: 3px; flex: 0 0 3px; border-radius: 3px; background: var(--paper-accent,#168fae); }.directory-detail__paper-line { display: block; width: 100%; height: 2px; border-radius: 3px; background: color-mix(in srgb, var(--paper-accent,#168fae) 24%, white); }.directory-detail__paper-line--short { width: 68%; }
.directory-detail__panel { position: fixed; top: 50%; left: 50%; z-index: 90; display: flex; width: min(600px,calc(100vw - 36px)); max-height: min(82dvh,680px); flex-direction: column; overflow: hidden; border: 1px solid #dfe8eb; border-top: 2px solid var(--directory-detail-accent,#168fae); border-radius: 18px; color: var(--directory-ink); background: #fff; box-shadow: 0 25px 75px rgb(25 50 66 / 24%); outline: none; transform: translate(-50%,-50%); transform-origin: center; animation: directory-detail-open 500ms cubic-bezier(.4,0,.2,1) 280ms both; }
.directory-detail__panel--member { width: min(480px,calc(100vw - 36px)); }
.directory-detail__panel--class,.directory-detail__panel--class.directory-detail__panel--closing { width: min(600px,calc(100vw - 36px)); animation: none; }
.directory-detail__panel--member { animation: directory-member-card-in 180ms cubic-bezier(.2,.75,.2,1) both; }
.directory-detail__panel--closing { animation-direction: reverse; animation-duration: 330ms; animation-delay: 0ms; animation-timing-function: cubic-bezier(.4,0,.2,1); pointer-events: none; }
.directory-detail__panel--member.directory-detail__panel--closing { animation: directory-member-card-out 150ms ease-in both; }
.directory-drawer__header { display: flex; min-height: 78px; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 20px 13px; border-bottom: 1px solid #edf1f2; background: #fbfdfd; }
.directory-drawer__eyebrow { display: block; margin-bottom: 4px; color: #70909c; font-size: 11px; font-weight: 680; }
.directory-drawer__title { display: block; overflow: hidden; max-width: 340px; color: #254254; font-family: var(--font-display); font-size: 20px; font-weight: 730; text-overflow: ellipsis; white-space: nowrap; }
.directory-drawer__close,.directory-activation-dialog__close { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid #e1e9ec; border-radius: 9px; color: #738792; background: #fff; cursor: pointer; }
.directory-drawer__close:hover,.directory-activation-dialog__close:hover { border-color: #c7e0e7; color: #167e98; background: #f5fafb; }
.directory-drawer__body { display: grid; align-content: start; gap: 15px; overflow-y: auto; padding: 16px 20px 20px; overscroll-behavior: contain; }
.directory-drawer__identity { display: flex; align-items: center; gap: 11px; }
.directory-drawer__avatar { width: 40px; height: 40px; flex-basis: 40px; border-radius: 12px; font-size: 16px; }
.directory-drawer__identity > div { display: flex; flex-wrap: wrap; align-items: center; min-width: 0; }
.directory-drawer__identity strong { overflow: hidden; color: #2c485a; font-size: 16px; font-weight: 720; text-overflow: ellipsis; white-space: nowrap; }
.directory-drawer__facts { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 9px; margin: 0; padding: 13px; border: 1px solid #e7edef; border-radius: 10px; background: #fbfcfc; }
.directory-drawer__facts > div { display: grid; align-content: start; gap: 6px; min-width: 0; }
.directory-drawer__facts > div:first-child { grid-column: 1 / -1; padding-bottom: 10px; border-bottom: 1px solid #e9eff1; }
.directory-drawer__facts dt { color: #81949d; font-size: 11px; }
.directory-drawer__facts dd { overflow: hidden; margin: 0; color: #405a68; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.directory-drawer__section { display: grid; gap: 11px; padding: 13px; border: 1px solid #e6edef; border-radius: 10px; background: #fff; }
.directory-drawer__section > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.directory-drawer__section h3 { margin: 0; color: #355060; font-size: 13px; font-weight: 700; }
.directory-drawer__section header p { margin: 4px 0 0; color: #82959d; font-size: 11px; line-height: 1.5; }
.directory-drawer__text-action { display: inline-flex; min-height: 30px; align-items: center; gap: 5px; padding: 0 8px; border: 0; border-radius: 6px; color: #19809a; background: #eff8fa; font: inherit; font-size: 11px; font-weight: 650; cursor: pointer; }
.directory-drawer__text-action:disabled { opacity: .5; cursor: not-allowed; }
.directory-drawer__value { margin: 0; color: #405b69; font-size: 14px; }
.directory-drawer__edit-form { display: grid; gap: 7px; }
.directory-drawer__edit-form input,.directory-dialog-form input,.directory-dialog-form select { width: 100%; min-height: 40px; padding: 0 11px; border: 1px solid #d9e5e9; border-radius: 8px; outline: none; color: #2c4859; background: #fff; font: inherit; font-size: 14px; }
.directory-drawer__edit-form input:focus,.directory-dialog-form input:focus,.directory-dialog-form select:focus { border-color: #77c4d4; box-shadow: 0 0 0 3px rgb(11 150 184 / 9%); }
.directory-drawer__edit-form p,.directory-dialog-form > p { margin: 0; color: #81939b; font-size: 11px; line-height: 1.5; }
.directory-drawer__edit-form > div,.directory-dialog-form__actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.directory-drawer__activation-card { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 10px; padding: 13px; border: 1px solid #eee5ce; border-radius: 10px; background: #fcfaf4; }
.directory-drawer__activation-icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 9px; color: #9c792d; background: #f6f0df; }
.directory-drawer__activation-card strong { color: #62583e; font-size: 12px; }
.directory-drawer__activation-card p { margin: 4px 0 0; color: #887e62; font-size: 11px; line-height: 1.5; }
.directory-drawer__class-summary { display: grid; gap: 12px; }
.directory-drawer__class-ref { display: flex; align-items: center; gap: 7px; color: #6e8996; font-size: 12px; }
.directory-drawer__class-ref > svg { color: #1585a1; }
.directory-drawer__class-ref span { overflow: hidden; margin-left: auto; color: #718791; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.directory-drawer__class-metrics { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px; }
.directory-drawer__class-metrics > div { display: grid; gap: 6px; padding: 12px; border: 1px solid #e5edef; border-radius: 10px; background: #fbfcfc; }
.directory-drawer__class-metrics span { color: #718791; font-size: 11px; }
.directory-drawer__class-metrics strong { color: #2d5264; font-size: 22px; font-weight: 730; font-variant-numeric: tabular-nums; }
.directory-drawer__assignment { gap: 10px; }
.directory-drawer__candidate-state { padding: 10px 11px; border-radius: 8px; color: #728790; background: #f7f9fa; font-size: 12px; line-height: 1.55; }
.directory-drawer__candidate-state--error { color: #8c623d; background: #fbf6ee; }
.directory-drawer__candidate-state button { margin-left: 6px; border: 0; color: #18819a; background: transparent; font: inherit; font-weight: 700; cursor: pointer; }
.directory-drawer__assign-row { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 8px; }
.directory-drawer__message { margin: 11px 18px 0; padding: 9px 11px; border-radius: 8px; color: #876635; background: #faf5e8; font-size: 12px; line-height: 1.5; }
.directory-dialog-form { display: grid; gap: 9px; }
.directory-dialog-form label { color: #556f7c; font-size: 11px; font-weight: 650; }
.directory-dialog-form__actions { margin-top: 7px; }
.directory-import { display: grid; gap: 17px; }
.directory-import__steps { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 0; margin: 0; padding: 0; list-style: none; }
.directory-import__steps li { position: relative; display: grid; justify-items: center; gap: 7px; min-width: 0; color: #97a5ab; font-size: 12px; text-align: center; }
.directory-import__steps li:not(:last-child)::after { position: absolute; top: 12px; left: calc(50% + 15px); right: calc(-50% + 15px); height: 1px; background: #e8edef; content: ''; }
.directory-import__steps li > span { position: relative; z-index: 1; display: grid; width: 24px; height: 24px; place-items: center; border: 1px solid #dfe8eb; border-radius: 50%; color: #80939d; background: #fff; font-size: 11px; font-weight: 700; }
.directory-import__steps strong { max-width: 100%; overflow: hidden; font-size: 12px; font-weight: 600; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.directory-import__step--active { color: #167f9a !important; }
.directory-import__step--active > span,.directory-import__step--done > span { border-color: #1594b2 !important; color: #fff !important; background: #1594b2 !important; }
.directory-import__step--active strong { font-weight: 730; }
.directory-import__step--done { color: #558b7d !important; }
.directory-import__step--done:not(:last-child)::after { background: #b9dfd3; }
.directory-import__stage { display: grid; gap: 11px; }
.directory-import__stage h3 { margin: 0; color: #2f4b5b; font-size: 13px; font-weight: 700; }
.directory-import__stage > p { margin: 0; color: #7b909a; font-size: 10px; line-height: 1.6; }
.directory-import__field { display: flex; align-items: center; gap: 8px; margin-top: 3px; color: #586f7c; font-size: 10px; font-weight: 650; }
.directory-import__field span { color: #9aa8ae; font-size: 9px; font-weight: 500; }
.directory-import__class-trigger { display: flex; width: 100%; min-height: 42px; align-items: center; justify-content: space-between; gap: 10px; padding: 0 12px; border: 1px solid #dce7eb; border-radius: 9px; color: #415d6c; background: #fff; font: inherit; font-size: 12px; text-align: left; cursor: pointer; transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease; }
.directory-import__class-trigger:hover:not(:disabled) { border-color: #b5d9e1; background: #fbfefe; }
.directory-import__class-trigger:focus-visible,.directory-import__class-trigger[data-state='open'] { border-color: #77c4d4; outline: none; box-shadow: 0 0 0 3px rgb(11 150 184 / 9%); }
.directory-import__class-trigger:disabled { opacity: .55; cursor: not-allowed; }
.directory-import__class-trigger > svg { flex: 0 0 auto; color: #78909d; transition: transform 140ms ease; }
.directory-import__class-trigger[data-state='open'] > svg { transform: rotate(180deg); }
:global(.directory-import__class-content) { z-index: 120; width: var(--reka-select-trigger-width, 100%); min-width: min(var(--reka-select-trigger-width, 100%), calc(100vw - 32px)); max-width: calc(100vw - 32px); overflow: hidden; border: 1px solid #dce8ed; border-radius: 11px; background: #fff; box-shadow: 0 16px 38px rgb(34 67 83 / 15%); }
:global(body > [data-reka-popper-content-wrapper]:has(.directory-import__class-content)) { z-index: 130 !important; }
:global(.directory-import__class-viewport) { max-height: min(260px, calc(100vh - 180px)); overflow-y: auto; padding: 5px; overscroll-behavior: contain; }
:global(.directory-import__class-item) { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 11px; border-radius: 7px; color: #3d5868; outline: none; font-size: 12px; cursor: pointer; }
:global(.directory-import__class-item[data-highlighted]) { color: #155e74; background: #eef8fa; }
:global(.directory-import__class-item[data-disabled]) { opacity: .45; cursor: not-allowed; }
:global(.directory-import__class-indicator) { display: flex; color: #0788a9; }
.directory-import__file { display: flex; min-height: 63px; align-items: center; gap: 10px; padding: 10px 11px; border: 1px dashed #cbdfe5; border-radius: 10px; background: #f8fbfc; cursor: pointer; }
.directory-import__file:hover { border-color: #8dc9d7; background: #f4fafb; }
.directory-import__file-icon { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border-radius: 9px; color: #1585a0; background: #eaf6f8; }
.directory-import__file > span:nth-child(2) { display: grid; min-width: 0; gap: 4px; }
.directory-import__file strong { overflow: hidden; color: #496370; font-size: 10px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.directory-import__file small { color: #8a9ba3; font-size: 8px; line-height: 1.4; }
.directory-import__file-action { margin-left: auto; color: #16829b; font-size: 9px; font-weight: 700; white-space: nowrap; }
.directory-import__error { margin: 0; color: #a24839 !important; font-size: 10px !important; line-height: 1.55; }
.directory-import__footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 3px; padding-top: 12px; border-top: 1px solid #edf1f2; }
.directory-import__footer-actions { display: flex; align-items: center; gap: 8px; }
.directory-import__footer > :deep(.app-button) { min-height: 36px; font-size: 10px; }
.directory-import__footer-actions > :deep(.app-button) { min-height: 36px; font-size: 10px; }
.directory-import__footer--stage-one { justify-content: flex-end; }
.directory-import__back { min-height: 34px; padding: 0 5px; border: 0; color: #738992; background: transparent; font: inherit; font-size: 10px; cursor: pointer; }
.directory-import__back:hover:not(:disabled) { color: #16829b; }
.directory-import__back:disabled { opacity: .5; cursor: not-allowed; }
.directory-import__preview-error { display: flex; align-items: flex-start; gap: 8px; padding: 10px 11px; border-radius: 8px; color: #936b3b; background: #fbf6ea; font-size: 10px; line-height: 1.55; }
.directory-import__preview-error > svg { flex: 0 0 auto; margin-top: 1px; }
.directory-import__preview-summary { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid #e2e9e9; border-radius: 9px; color: #5b7778; background: #f6faf8; }
.directory-import__preview-summary--valid { border-color: #d4eae1; color: #367b69; background: #f0f8f4; }
.directory-import__preview-summary--invalid { border-color: #f0e4cb; color: #927139; background: #fcf8ef; }
.directory-import__preview-mark { display: grid; width: 31px; height: 31px; flex: 0 0 31px; place-items: center; border-radius: 8px; background: rgb(255 255 255 / 74%); }
.directory-import__preview-summary > div { display: grid; gap: 4px; }
.directory-import__preview-summary strong { color: inherit; font-size: 10px; }
.directory-import__preview-summary span:last-child { font-size: 9px; }
.directory-import__errors { display: grid; max-height: 180px; gap: 6px; overflow-y: auto; margin: 0; padding: 0 1px; list-style: none; }
.directory-import__errors li { display: grid; grid-template-columns: 72px minmax(0,1fr); gap: 4px 8px; padding: 8px 9px; border: 1px solid #f0e9dd; border-radius: 7px; color: #806d4e; background: #fffcf6; font-size: 9px; }
.directory-import__errors li > span { grid-row: span 2; color: #8e6d32; font-weight: 650; }
.directory-import__errors code { color: #a49376; font-size: 8px; }
.directory-import__errors .directory-import__errors-more { display: block; border: 0; color: #8b7d64; background: transparent; }
.directory-import__complete { display: grid; justify-items: center; gap: 8px; padding: 20px 14px; border: 1px solid #d9ebe2; border-radius: 11px; background: #f3f9f5; text-align: center; }
.directory-import__complete > span { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 50%; color: #37816d; background: #e2f2e9; }
.directory-import__complete strong { color: #3b7061; font-size: 13px; }
.directory-import__complete p { max-width: 290px; margin: 0; color: #7a9488; font-size: 10px; line-height: 1.55; }
.directory-import__confirm-card { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid #e4ecee; border-radius: 9px; background: #fafcfc; }
.directory-import__confirm-card > span { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border-radius: 9px; color: #14849f; background: #edf7f9; }
.directory-import__confirm-card > div { display: grid; min-width: 0; gap: 4px; }
.directory-import__confirm-card strong { overflow: hidden; color: #4a6471; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.directory-import__confirm-card small { color: #899ba3; font-size: 9px; }
.directory-import__confirm-copy { padding: 3px 1px; }
.directory-activation-dialog__overlay { position: fixed; inset: 0; z-index: 120; background: rgb(25 41 54 / 35%); backdrop-filter: blur(2px); }
.directory-activation-dialog__panel { position: fixed; top: 50%; left: 50%; z-index: 130; width: min(440px, calc(100vw - 30px)); max-height: calc(100dvh - 28px); overflow-y: auto; padding: 21px; border: 1px solid #dde8eb; border-radius: 15px; background: #fff; box-shadow: 0 24px 64px rgb(27 49 61 / 22%); outline: none; transform: translate(-50%,-50%); animation: directory-modal-in 160ms cubic-bezier(.2,.75,.2,1) both; }
.directory-activation-dialog__header,.directory-activation-dialog__header > div { display: flex; align-items: center; }
.directory-activation-dialog__header { justify-content: space-between; gap: 15px; margin-bottom: 18px; }
.directory-activation-dialog__header > div { gap: 10px; min-width: 0; }
.directory-activation-dialog__icon { display: grid; width: 37px; height: 37px; flex: 0 0 37px; place-items: center; border-radius: 11px; color: #8e722e; background: #f8f2e4; }
.directory-activation-dialog__title { display: block; color: #314d5d; font-family: var(--font-display); font-size: 15px; font-weight: 720; }
.directory-activation-dialog__description { display: block; overflow: hidden; max-width: 280px; margin-top: 4px; color: #81939c; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.directory-detail__panel:focus-visible,.directory-activation-dialog__panel:focus-visible { outline: none; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; clip-path: inset(50%); }
@keyframes directory-sheen { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
@keyframes directory-detail-overlay-in { from { opacity: 0; backdrop-filter: blur(0); } to { opacity: 1; backdrop-filter: blur(3px); } }
@keyframes directory-detail-overlay-out { from { opacity: 1; backdrop-filter: blur(3px); } to { opacity: 0; backdrop-filter: blur(0); } }
@keyframes directory-detail-open { from { opacity: 0; border-radius: 7px; transform: translate(-50%,-50%) scale(var(--detail-card-scale,.1)) rotate(24deg); } to { opacity: 1; border-radius: 18px; transform: translate(-50%,-50%) scale(1) rotate(0); } }
@keyframes directory-member-card-in { from { opacity: 0; transform: translate(-50%,-50%) scale(.96); } to { opacity: 1; transform: translate(-50%,-50%) scale(1); } }
@keyframes directory-member-card-out { from { opacity: 1; transform: translate(-50%,-50%) scale(1); } to { opacity: 0; transform: translate(-50%,-50%) scale(.98); } }
@keyframes directory-detail-paper-fly {
  0% { opacity: .95; clip-path: inset(0 0 var(--directory-paper-occlusion,0%) 0); transform: translate(0,0) scale(1) rotate(0); }
  16.666% { clip-path: inset(0); transform: translate(var(--directory-paper-p1-x),var(--directory-paper-p1-y)) scale(1.05) rotate(4deg); }
  33.333% { transform: translate(var(--directory-paper-p2-x),var(--directory-paper-p2-y)) scale(1.1) rotate(8deg); }
  50% { transform: translate(var(--directory-paper-p3-x),var(--directory-paper-p3-y)) scale(1.17) rotate(12deg); }
  66.666% { transform: translate(var(--directory-paper-p4-x),var(--directory-paper-p4-y)) scale(1.23) rotate(16deg); }
  83.333% { transform: translate(var(--directory-paper-p5-x),var(--directory-paper-p5-y)) scale(1.3) rotate(20deg); }
  100% { opacity: 0; transform: translate(var(--directory-paper-dx),var(--directory-paper-dy)) scale(1.35) rotate(24deg); }
}
@keyframes directory-detail-paper-return {
  0% { opacity: 0; clip-path: inset(0); transform: translate(var(--directory-paper-dx),var(--directory-paper-dy)) scale(1.35) rotate(24deg); }
  16.666% { opacity: .95; transform: translate(var(--directory-paper-p5-x),var(--directory-paper-p5-y)) scale(1.3) rotate(20deg); }
  33.333% { opacity: .95; transform: translate(var(--directory-paper-p4-x),var(--directory-paper-p4-y)) scale(1.23) rotate(16deg); }
  50% { opacity: .95; transform: translate(var(--directory-paper-p3-x),var(--directory-paper-p3-y)) scale(1.17) rotate(12deg); }
  66.666% { opacity: .95; transform: translate(var(--directory-paper-p2-x),var(--directory-paper-p2-y)) scale(1.1) rotate(8deg); }
  83.333% { opacity: .95; clip-path: inset(0); transform: translate(var(--directory-paper-p1-x),var(--directory-paper-p1-y)) scale(1.05) rotate(4deg); }
  91.666% { opacity: .6; clip-path: inset(0 0 var(--directory-paper-half-occlusion,0%) 0); }
  100% { opacity: 0; clip-path: inset(0 0 var(--directory-paper-occlusion,0%) 0); transform: translate(0,0) scale(1) rotate(0); }
}
@keyframes directory-modal-in { from { opacity: .75; transform: translate(-50%, calc(-50% + 5px)) scale(.99); } to { opacity: 1; transform: translate(-50%,-50%) scale(1); } }
.directory-view-enter-active,.directory-view-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.directory-view-enter-from { opacity: 0; transform: translateY(3px); }
.directory-view-leave-to { opacity: 0; transform: translateY(-2px); }

@media (max-width: 960px) {
  .directory-studio__class-grid { grid-template-columns: repeat(2,minmax(0,1fr)); gap: 17px; }
  .directory-studio__table th:first-child { width: 44%; }
  .directory-studio__table th:nth-child(2) { width: 17%; }
  .directory-studio__table th:nth-child(3) { width: 31%; }
}
@media (max-width: 720px) {
  .directory-studio__header { align-items: flex-start; margin-top: 0; }
  .directory-studio__header-actions { flex-wrap: wrap; }
  .directory-studio__school-action { max-width: 190px; }
  .directory-studio__toolbar { align-items: stretch; flex-direction: column; gap: 10px; padding-bottom: 12px; }
  .directory-studio__tools { justify-content: space-between; }
  .directory-studio__search { width: 100%; flex: 1; }
  .directory-studio__filter-row { overflow-x: auto; min-height: 48px; }
  .directory-studio__filter-row button { flex: 0 0 auto; }
  .directory-studio__filter-spacer,.directory-studio__record-count { display: none; }
  .directory-studio__table th:first-child { width: 48%; }
  .directory-studio__table th:nth-child(2) { width: 14%; }
  .directory-studio__table th:nth-child(3) { width: 32%; }
  .directory-studio__table th,.directory-studio__table td { padding-right: 8px; padding-left: 8px; }
  .directory-studio__table td:first-child,.directory-studio__table th:first-child { padding-left: 12px; }
  .directory-studio__avatar { width: 31px; height: 31px; flex-basis: 31px; border-radius: 9px; }
  .directory-studio__member-trigger { gap: 7px; }
.directory-studio__member-copy strong { font-size: 14px; }
.directory-studio__member-copy small { font-size: 12px; }
  .directory-studio__status-stack { align-items: flex-start; flex-direction: column; gap: 3px; }
  .directory-studio__pending-list > button { min-width: min(100%, 188px); flex: 1 1 188px; }
}
@media (max-width: 520px) {
  .directory-studio__header { flex-direction: column; gap: 14px; }
  .directory-studio__header-actions { width: 100%; justify-content: space-between; }
  .directory-studio__school-action { max-width: calc(100% - 125px); }
  .directory-studio__view-switch { width: 100%; }
  .directory-studio__view-switch button { flex: 1; justify-content: center; padding: 0 7px; }
  .directory-studio__class-grid { grid-template-columns: minmax(0,1fr); gap: 15px; }
  .directory-studio__table th:nth-child(2),.directory-studio__table td:nth-child(2) { display: none; }
  .directory-studio__table th:first-child { width: 55%; }
  .directory-studio__table th:nth-child(3) { width: calc(45% - 48px); }
  .directory-studio__table th:last-child { width: 48px; }
  .directory-studio__table td { height: 62px; }
  .directory-studio__provisioning { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
  .directory-drawer__header { min-height: 70px; padding: 14px 16px 12px; }
  .directory-drawer__body { gap: 13px; padding: 14px 16px 18px; }
  .directory-drawer__assign-row { grid-template-columns: minmax(0,1fr); }
  .directory-drawer__assign-row > :deep(.app-button) { justify-self: end; }
  .directory-drawer__activation-card { grid-template-columns: auto minmax(0,1fr); }
  .directory-drawer__activation-card > :deep(.app-button) { grid-column: 2; justify-self: start; }
  .directory-import__steps li { font-size: 11px; }
  .directory-import__steps li:not(:last-child)::after { left: calc(50% + 14px); right: calc(-50% + 14px); }
  .directory-import__steps strong { font-size: 11px; }
  .directory-import__footer { align-items: center; }
}
@media (prefers-reduced-motion: reduce) {
  .directory-studio *, .directory-studio *::before, .directory-studio *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
  .directory-detail__overlay,.directory-detail__paper,.directory-detail__panel,.directory-activation-dialog__panel { animation-duration: .01ms !important; animation-iteration-count: 1 !important; }
  .directory-view-enter-active,.directory-view-leave-active { transition: none; }
}
</style>
