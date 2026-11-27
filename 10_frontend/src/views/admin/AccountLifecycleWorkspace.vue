<script setup lang="ts">
import { readSchoolRosterRecords, rosterTemplateMarker, STAFF_ROSTER_COLUMNS, STAFF_ROSTER_MARKER } from '@/services/school-roster-file'
import { ROSTER_WORKBOOK_BYTES, SCHOOL_ROSTER_ROWS } from '@/services/workspace-table'
import AppDialog from '@/components/app/AppDialog.vue'
import AppSelect from '@/components/app/AppSelect.vue'
import AppSelectOption from '@/components/app/AppSelectOption.vue'
/* global AbortController, KeyboardEvent, HTMLButtonElement, URL, Blob, File, TextEncoder, btoa */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'
import type {
  LifecycleAccountSummary, LifecycleCredential, LifecycleRecoveryTicket, LifecycleRosterPreview,
  LifecycleRosterRow, LifecycleStaffInvitation, LifecycleStaffRosterRow, SchoolDirectory,
} from '@/api/client'

type Section = 'overview' | 'roster' | 'staff' | 'recovery' | 'credentials' | 'status' | 'directory'
const props = defineProps<{ embeddedSection?: 'roster' | 'staff'; initialRosterFile?: File }>()
const section = ref<Section>(props.embeddedSection ?? 'overview')
const session = useSessionStore()
const route = useRoute()
watch(
  [() => route.query.directoryView, () => route.query.directoryAction],
  ([view, action], previous) => {
    if (props.embeddedSection) return
    const directoryActions = ['create-class', 'manage-class-people', 'issue-credentials', 'activate-account', 'import-accounts']
    if ((view === 'classes' && previous?.[0] !== view) || directoryActions.some((item) => item === action)) section.value = 'directory'
  },
  { immediate: true },
)
const allSections: Array<{ id: Section; label: string }> = [
  { id: 'overview', label: '概览' }, { id: 'roster', label: '学生名单' }, { id: 'staff', label: '教职工名单' },
  { id: 'credentials', label: '初始账号' }, { id: 'status', label: '账号状态' },
  { id: 'recovery', label: '安全恢复' }, { id: 'directory', label: '学校目录' },
]
const sections = props.embeddedSection
  ? allSections.filter((item) => item.id === props.embeddedSection || item.id === 'credentials')
  : allSections
const activeTabIndex = computed(() => sections.findIndex((item) => item.id === section.value))
const tabIndicatorStyle = computed(() => ({
  '--tab-index': activeTabIndex.value,
  '--tab-column': activeTabIndex.value % 3,
  '--tab-row': Math.floor(activeTabIndex.value / 3),
}))
const handleTabKeydown = (event: KeyboardEvent, index: number) => {
  const next = event.key === 'ArrowRight' ? (index + 1) % sections.length
    : event.key === 'ArrowLeft' ? (index + sections.length - 1) % sections.length
      : event.key === 'Home' ? 0 : event.key === 'End' ? sections.length - 1 : -1
  if (next < 0) return
  event.preventDefault()
  section.value = sections[next]!.id
  const tabs = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  tabs?.[next]?.focus()
}
const openCredentials = () => { section.value = 'credentials'; clearFeedback() }
const summary = ref<LifecycleAccountSummary | null>(null)
const directory = ref<SchoolDirectory | null>(null)
let directoryLoadedAt = 0
let directoryRequest: Promise<SchoolDirectory> | null = null
const loadDirectory = async (allowRecent = false) => {
  if (directoryRequest) return directoryRequest
  if (allowRecent && directory.value && Date.now() - directoryLoadedAt < 10_000) return directory.value
  if (!frontendApi.getSchoolAdminDirectory) throw new Error('学校目录服务不可用')
  directoryRequest = frontendApi.getSchoolAdminDirectory()
    .then(({ data }) => {
      directory.value = data
      directoryLoadedAt = Date.now()
      return data
    })
    .finally(() => { directoryRequest = null })
  return directoryRequest
}
const recoveryTickets = ref<LifecycleRecoveryTicket[]>([])
const staffInvitations = ref<LifecycleStaffInvitation[]>([])
const staffInvitationSearch = ref('')
const appliedInvitationSearch = ref('')
const staffInvitationPage = ref(1)
const staffInvitationPageSize = 30
const hasMoreStaffInvitations = ref(false)
const staffInvitationsLoading = ref(false)
let staffInvitationRequest = 0
const staffNameTarget = ref<LifecycleStaffInvitation | null>(null)
const staffNameDraft = ref('')
const staffNameError = ref('')
const busy = ref(false)
defineExpose({ openCredentials, busy })
const loadingAccounts = ref(false)
const error = ref('')
const notice = ref('')
const rows = ref<LifecycleRosterRow[]>([])
const preview = ref<LifecycleRosterPreview | null>(null)
const rosterRun = ref('')
const rosterImportKey = ref('')
const rosterProcessed = ref(0)
const rosterCreated = ref(0)
const rosterBatchSize = 200
const rosterPreviewConcurrency = 3
const pendingCredentialUserIds = ref<string[]>([])
const rosterCredentialDetails = ref<Record<string, { studentNumber: string; className: string }>>({})
const staffRows = ref<LifecycleStaffRosterRow[]>([])
const confirmStaffImport = ref(false)
const staffClassIssues = computed(() => {
  if (props.embeddedSection !== 'staff' || !directory.value) return []
  const available = new Set(directory.value.classes.filter((item) => item.status === 'ACTIVE').map((item) => item.class_ref))
  return staffRows.value.filter((row) => row.class_refs.some((ref) => !available.has(ref)))
})
const credentialRows = ref<LifecycleCredential[]>([])
const credentialPurpose = ref<'initial' | 'recovery'>('initial')
const credentialExportScope = ref('')
const credentialExportName = ref('')
const credentialExportOptions = computed(() => [
  { value: '', label: '本次全部账号' },
  ...[...new Set(credentialRows.value.flatMap((row) => row.class_ref.split('、')).filter(Boolean))]
    .map((value) => ({ value, label: value })),
])
const credentialsToExport = computed(() => credentialExportScope.value
  ? credentialRows.value.filter((row) => row.class_ref.split('、').includes(credentialExportScope.value))
  : credentialRows.value)
const matchingIssuedCredentials = computed(() => {
  const query = credentialExportName.value.trim().toLocaleLowerCase()
  return credentialsToExport.value.filter((row) =>
    !query || [row.display_name, row.login_name].some((value) => value?.toLocaleLowerCase().includes(query)))
})
watch(credentialExportOptions, (options) => {
  if (!options.some((option) => option.value === credentialExportScope.value)) credentialExportScope.value = ''
})
const passphrase = ref('')
const credentialSearch = ref('')
const credentialClassFilter = ref('')
const credentialRoleFilter = ref<'all' | 'student' | 'teacher'>('all')
const credentialPage = ref(1)
const invitation = ref({ employee_ref: '', display_name: '', role: 'teacher' as 'teacher' | 'psychological_specialist', work_contact: '', class_refs: [] as string[] })
const invitationVerified = ref(false)
const staffRecoveryTarget = ref<LifecycleStaffInvitation | null>(null)
const staffRecoveryReasonCode = ref('CREDENTIAL_LOST')
const staffRecoveryMethod = ref<'IN_PERSON' | 'VERIFIED_WORK_CONTACT'>('IN_PERSON')
const staffRecoveryVerified = ref(false)
const credentialUsers = ref<string[]>([])
const accountSelection = ref('')
const accountReason = ref('')
const recoveryReason = ref('')
const reauthPassword = ref('')
const recoveryReasons = ref<Record<string, string>>({})
const schoolRef = computed(() => directory.value?.school.school_ref ?? '')
const isSyntheticDemo = computed(() => directory.value?.school.data_origin === 'SYNTHETIC')
const usesDemoAdminSession = computed(() => /^PUBLICDEMO_[a-f0-9]{64}$/.test(session.user?.activeContext?.schoolRef ?? ''))
const credentialCandidates = computed(() => {
  const query = credentialSearch.value.trim().toLocaleLowerCase()
  return (directory.value?.members ?? []).filter((member) => {
    if (member.role !== 'student' && member.role !== 'teacher') return false
    if (credentialRoleFilter.value !== 'all' && member.role !== credentialRoleFilter.value) return false
    if (member.account_status === 'DISABLED' || member.account_status === 'LOCKED') return false
    if (member.provisioning_status !== 'PENDING_ACTIVATION' && member.provisioning_status !== 'ACTIVE') return false
    if (credentialClassFilter.value === '__unassigned__' && (member.class_refs?.length ?? 0) > 0) return false
    if (credentialClassFilter.value && credentialClassFilter.value !== '__unassigned__'
      && !member.class_refs?.includes(credentialClassFilter.value)) return false
    return !query || `${member.display_name ?? ''} ${member.user_id}`.toLocaleLowerCase().includes(query)
  })
})
const credentialPageSize = 25
const credentialPageCount = computed(() => Math.max(1, Math.ceil(credentialCandidates.value.length / credentialPageSize)))
const credentialPageRows = computed(() => credentialCandidates.value.slice(
  (credentialPage.value - 1) * credentialPageSize,
  credentialPage.value * credentialPageSize,
))
const selectedCredentialCount = computed(() => credentialUsers.value.length)
const statusSelection = ref('')
const statusSearch = ref('')
const statusPage = ref(1)
const statusPageSize = 25
const statusCandidates = computed(() => {
  const query = statusSearch.value.trim().toLocaleLowerCase()
  return (directory.value?.members ?? []).filter((member) =>
    !query || `${member.display_name ?? ''} ${member.user_id}`.toLocaleLowerCase().includes(query),
  )
})
const statusPageCount = computed(() => Math.max(1, Math.ceil(statusCandidates.value.length / statusPageSize)))
const statusPageRows = computed(() => statusCandidates.value.slice(
  (statusPage.value - 1) * statusPageSize,
  statusPage.value * statusPageSize,
))
const statusReason = ref('')
watch([credentialSearch, credentialClassFilter, credentialRoleFilter], () => { credentialPage.value = 1 })
watch(credentialCandidates, () => {
  if (credentialPage.value > credentialPageCount.value) credentialPage.value = credentialPageCount.value
})
watch(statusSearch, () => { statusPage.value = 1 })
watch(statusCandidates, () => {
  if (statusPage.value > statusPageCount.value) statusPage.value = statusPageCount.value
})
const apiReady = computed(() => Boolean(frontendApi.getLifecycleAccountSummary && frontendApi.getSchoolAdminDirectory))
const rosterIssueLabels: Record<string, string> = {
  DUPLICATE_ROW_NUMBER: '导入记录编号重复',
  INVALID_STUDENT_NUMBER: '学号格式无效',
  DUPLICATE_STUDENT_NUMBER: '文件中学号重复',
  STUDENT_NUMBER_UNAVAILABLE: '学号已被使用',
  BLANK_DISPLAY_NAME: '姓名不能为空',
  FORMULA_LIKE_VALUE: '姓名含电子表格公式内容',
  CLASS_UNAVAILABLE: '班级已停用或编号无效',
  CLASS_NAME_INVALID: '班级名称无效（最多120字符）',
  CLASS_NAME_AMBIGUOUS: '班级名称重复，请填写年级或准确的班级编号',
  GRADE_LEVEL_INVALID: '年级格式无效，请填写数字、年级代码或常用中文年级',
  GRADE_LEVEL_MISMATCH: '年级与班级不一致',
}
const rosterIssueLabel = (code: string) => rosterIssueLabels[code] ?? '记录无法导入'

const clearFeedback = () => { error.value = ''; notice.value = '' }
const classLabel = (classRef: string) => directory.value?.classes.find((item) => item.class_ref === classRef)?.display_name || classRef
const roleLabel = (role: string) => ({
  admin: '学校管理员', administrator: '学校管理员', student: '学生', teacher: '普通教师',
  psychological_specialist: '心理教师',
}[role] ?? role)
const memberStatusLabel = (member: SchoolDirectory['members'][number]) => {
  if (member.account_status === 'LOCKED') return '已锁定'
  if (member.account_status === 'DISABLED' || member.account_status === 'SUSPENDED') return '已停用'
  if (member.provisioning_status === 'PENDING_ACTIVATION') return '待首次登录'
  if (member.account_status === 'ACTIVE') return '已激活'
  return member.account_status
}
const toggleCredentialUser = (userId: string, checked: boolean) => {
  const selected = new Set(credentialUsers.value)
  if (checked) selected.add(userId)
  else selected.delete(userId)
  credentialUsers.value = [...selected]
}
const selectCurrentCredentialPage = () => {
  credentialUsers.value = [...new Set([...credentialUsers.value, ...credentialPageRows.value.map((item) => item.user_id)])]
}
const selectCredentialCandidates = () => {
  if (credentialCandidates.value.length > 200) {
    error.value = '每批最多签发 200 个账号，请按角色分批操作'
    return
  }
  credentialUsers.value = credentialCandidates.value.map((item) => item.user_id)
}
const updateInvitationRole = () => {
  if (invitation.value.role === 'psychological_specialist') invitation.value.class_refs = []
}
const invitationStatusLabel = (status: LifecycleStaffInvitation['status']) => ({
  ISSUED: '待接受', ACCEPTED: '已接受', EXPIRED: '已过期', REVOKED: '已撤销',
})[status]
const refreshStaffInvitations = async () => {
  if (!frontendApi.listStaffInvitations) return
  const request = ++staffInvitationRequest
  staffInvitationsLoading.value = true
  try {
    const result = await frontendApi.listStaffInvitations({
      limit: staffInvitationPageSize + 1,
      offset: (staffInvitationPage.value - 1) * staffInvitationPageSize,
      search: appliedInvitationSearch.value,
    })
    if (request !== staffInvitationRequest) return
    staffInvitations.value = result.data.slice(0, staffInvitationPageSize)
    hasMoreStaffInvitations.value = result.data.length > staffInvitationPageSize
  } finally {
    if (request === staffInvitationRequest) staffInvitationsLoading.value = false
  }
}
const changeInvitationPage = async (page: number, search = appliedInvitationSearch.value) => {
  const oldPage = staffInvitationPage.value
  const oldSearch = appliedInvitationSearch.value
  staffInvitationPage.value = page
  appliedInvitationSearch.value = search
  error.value = ''
  try { await refreshStaffInvitations() }
  catch (cause) {
    staffInvitationPage.value = oldPage
    appliedInvitationSearch.value = oldSearch
    error.value = cause instanceof Error ? cause.message : '无法读取邀请记录'
  }
}
const beginStaffNameEdit = (item: LifecycleStaffInvitation) => {
  staffNameTarget.value = item
  staffNameDraft.value = item.display_name ?? ''
  staffNameError.value = ''
}
const saveStaffName = async () => {
  const target = staffNameTarget.value
  const name = staffNameDraft.value.trim()
  if (busy.value || !target || !name || name === target.display_name || !frontendApi.updateStaffInvitationName) return
  busy.value = true
  staffNameError.value = ''
  try {
    const result = await frontendApi.updateStaffInvitationName(target.invitation_ref, name)
    staffInvitations.value = staffInvitations.value.map((item) => item.invitation_ref === target.invitation_ref
      ? { ...item, display_name: result.data.display_name }
      : item)
    if (directory.value) {
      directory.value = {
        ...directory.value,
        members: directory.value.members.map((member) => member.user_id === target.user_id
          ? { ...member, display_name: result.data.display_name }
          : member),
      }
    }
    staffNameTarget.value = null
    notice.value = '姓名已保存'
    if (appliedInvitationSearch.value) await loadSectionDetails('staff')
  } catch (cause) {
    staffNameError.value = cause instanceof Error ? cause.message : '无法保存姓名'
  } finally { busy.value = false }
}
const requireRecentReauthentication = async () => {
  if (usesDemoAdminSession.value) return
  if (!frontendApi.reauthenticate || !reauthPassword.value) throw new Error('请输入管理员当前密码')
  const currentPassword = reauthPassword.value
  try { await frontendApi.reauthenticate(currentPassword) }
  finally { reauthPassword.value = '' }
}
const loadData = async () => {
  if (loadingAccounts.value) return
  loadingAccounts.value = true
  try {
    if (!frontendApi.getLifecycleAccountSummary || !frontendApi.getSchoolAdminDirectory) throw new Error('账号生命周期服务不可用')
    const [summaryResponse] = await Promise.all([
      frontendApi.getLifecycleAccountSummary(), loadDirectory(),
    ])
    summary.value = summaryResponse.data
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '读取账号信息失败' }
  finally { loadingAccounts.value = false }
}

async function loadSectionDetails(current: Section) {
  try {
    if (current === 'staff' && !props.embeddedSection) await refreshStaffInvitations()
    if (current === 'recovery' && frontendApi.listRecoveryRequests) {
      recoveryTickets.value = (await frontendApi.listRecoveryRequests()).data
    }
  } catch (cause) {
    if (section.value === current) error.value = cause instanceof Error ? cause.message : '无法读取账号记录'
  }
}

watch(section, (current) => { void loadSectionDetails(current) })

const downloadRosterTemplate = () => {
  const csv = '\uFEFF# psynova_student_roster_template_v1\r\nstudent_number,display_name,class_ref,grade_level\r\n'
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'psynova-roster-template-v1.csv'; link.click(); URL.revokeObjectURL(url)
}

const downloadStaffRosterTemplate = () => {
  const csv = `\uFEFF${STAFF_ROSTER_MARKER}\r\n${STAFF_ROSTER_COLUMNS.join(',')}\r\n`
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'psynova-staff-roster-template-v1.csv'; link.click(); URL.revokeObjectURL(url)
}

let rosterRead: AbortController | undefined
let staffRead: AbortController | undefined
const parseRosterFile = async (file?: File) => {
  rosterRead?.abort()
  const request = new AbortController()
  rosterRead = request
  clearFeedback(); preview.value = null; rosterRun.value = ''; rosterImportKey.value = ''; rows.value = []
  rosterProcessed.value = 0
  rosterCreated.value = 0
  pendingCredentialUserIds.value = []
  rosterCredentialDetails.value = {}
  if (!file) return
  if (file.size > ROSTER_WORKBOOK_BYTES) { error.value = '文件不能超过 1 MiB'; return }
  try {
    const expected = ['student_number', 'display_name', 'class_ref', 'grade_level']
    const records = await readSchoolRosterRecords(file, request.signal)
    if (request.signal.aborted) return
    const marker = rosterTemplateMarker(records[0], '# psynova_student_roster_template_')
    if (marker) {
      if (marker !== '# psynova_student_roster_template_v1') throw new Error('花名册模板版本不受支持')
      records.shift()
    }
    if (JSON.stringify(records.shift()) !== JSON.stringify(expected)) throw new Error('模板列不匹配')
    if (records.length < 1 || records.length > SCHOOL_ROSTER_ROWS) throw new Error('导入须包含 1 到 3000 行学生记录')
    rows.value = records.map((record, index) => {
      if ((record.length !== 3 && record.length !== 4) || record.slice(0, 3).some((cell) => !cell)) throw new Error(`第 ${index + 2} 行信息不完整`)
      return { row_no: index + 1, student_number: record[0]!, display_name: record[1]!, class_ref: record[2]!, ...(record[3] ? { grade_level: record[3] } : {}) }
    })
    notice.value = `已读取 ${rows.value.length} 行，按班级分组预览`
    void previewRoster()
  } catch (cause) {
    if (request.signal.aborted) return
    rows.value = []; error.value = cause instanceof Error ? cause.message : '无法读取文件'
  }
}

const parseStaffFile = async (file?: File) => {
  staffRead?.abort()
  const request = new AbortController()
  staffRead = request
  confirmStaffImport.value = false
  clearFeedback(); staffRows.value = []
  if (!file) return
  if (file.size > ROSTER_WORKBOOK_BYTES) { error.value = '文件不能超过 1 MiB'; return }
  try {
    const records = await readSchoolRosterRecords(file, request.signal)
    if (request.signal.aborted) return
    const marker = rosterTemplateMarker(records[0], '# psynova_staff_roster_template_')
    if (marker) {
      if (marker !== STAFF_ROSTER_MARKER) throw new Error('教职工模板版本不受支持')
      records.shift()
    }
    if (JSON.stringify(records.shift()) !== JSON.stringify(STAFF_ROSTER_COLUMNS)) {
      throw new Error('教职工模板列不匹配')
    }
    if (records.length < 1 || records.length > SCHOOL_ROSTER_ROWS) throw new Error('名单须包含 1 到 3000 行教职工记录')
    const employeeRows = new Map<string, number>()
    staffRows.value = records.map((record, index) => {
      if (record.length !== 4 || record.slice(0, 3).some((cell) => !cell)) throw new Error(`第 ${index + 2} 行信息不完整`)
      const employeeRef = record[0]!
      if (!/^[ -~]{1,128}$/.test(employeeRef)) throw new Error(`第 ${index + 2} 行教职工编号须为 1 到 128 个可打印英文字母、数字或符号`)
      const employeeKey = employeeRef.toLowerCase()
      const priorRow = employeeRows.get(employeeKey)
      if (priorRow !== undefined) throw new Error(`第 ${index + 2} 行与第 ${priorRow} 行的教职工编号重复`)
      employeeRows.set(employeeKey, index + 2)
      if (record[1]!.length > 120) throw new Error(`第 ${index + 2} 行姓名不能超过 120 个字符`)
      const role = record[2]
      if (role !== 'teacher' && role !== 'psychological_specialist') throw new Error(`第 ${index + 2} 行角色必须是 teacher 或 psychological_specialist`)
      const classRefs = record[3] ? record[3].split('|').map((value) => value.trim()).filter(Boolean) : []
      if (classRefs.length > 50 || new Set(classRefs).size !== classRefs.length || classRefs.some((ref) => ref.length > 128)) {
        throw new Error(`第 ${index + 2} 行班级编号存在重复、过长或超出 50 个`)
      }
      if (role === 'teacher' && classRefs.length === 0) throw new Error(`第 ${index + 2} 行普通教师必须填写任教班级`)
      if (role === 'psychological_specialist' && classRefs.length > 0) throw new Error(`第 ${index + 2} 行心理老师不能分配普通教师班级范围`)
      return { row_no: index + 1, employee_ref: employeeRef, display_name: record[1]!, role, class_refs: classRefs }
    })
    notice.value = `已读取 ${staffRows.value.length} 行教职工名单`
  } catch (cause) {
    if (request.signal.aborted) return
    staffRows.value = []; error.value = cause instanceof Error ? cause.message : '无法读取文件'
  }
}

function readAttachedRoster(file?: File) {
  if (busy.value || rosterImportKey.value) return
  if (props.embeddedSection === 'staff') void parseStaffFile(file)
  if (props.embeddedSection === 'roster' && file) void parseRosterFile(file)
}

watch(() => props.initialRosterFile, readAttachedRoster)

function rosterBatch(offset: number) {
  // Propagate a supplied grade to blank entries in the same named class,
  // including when they fall into different request batches.
  const suppliedGrades = new Map<string, string>()
  for (const row of rows.value) {
    if (row.grade_level && !suppliedGrades.has(row.class_ref)) {
      suppliedGrades.set(row.class_ref, row.grade_level)
    }
  }
  return rows.value.slice(offset, offset + rosterBatchSize).map((row, index) => ({
    ...row,
    ...(row.grade_level || suppliedGrades.has(row.class_ref)
      ? { grade_level: row.grade_level || suppliedGrades.get(row.class_ref) } : {}),
    row_no: index + 1,
  }))
}

const previewRoster = async () => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.previewLifecycleRoster) throw new Error('花名册预览服务不可用')
    const errors: LifecycleRosterPreview['errors'] = []
    const seen = new Set<string>()
    const groups = new Map<string, number>()
    const plans = new Map<string, NonNullable<LifecycleRosterPreview['class_plan']>[number]>()
    const grades = new Map<string, Set<string>>()
    const planByInput = new Map<string, string>()
    for (const row of rows.value) {
      const number = row.student_number.normalize('NFKC').trim().toUpperCase()
      if (seen.has(number)) errors.push({ row_no: row.row_no, code: 'DUPLICATE_STUDENT_NUMBER' })
      seen.add(number)
      groups.set(row.class_ref, (groups.get(row.class_ref) ?? 0) + 1)
    }
    let valid = errors.length === 0
    if (valid) {
      const submitPreview = frontendApi.previewLifecycleRoster.bind(frontendApi)
      const offsets = Array.from({ length: Math.ceil(rows.value.length / rosterBatchSize) }, (_, index) => index * rosterBatchSize)
      for (let index = 0; index < offsets.length; index += rosterPreviewConcurrency) {
        const window = offsets.slice(index, index + rosterPreviewConcurrency)
        const results = await Promise.all(window.map(async (offset) => ({
          offset, receipt: (await submitPreview(rosterBatch(offset))).data,
        })))
        for (const { offset, receipt } of results) {
          valid = valid && receipt.valid
          errors.push(...receipt.errors.map((item) => ({ ...item, row_no: item.row_no + offset })))
          for (const plan of receipt.class_plan ?? []) {
            planByInput.set(plan.input_ref, plan.class_ref)
            const existing = plans.get(plan.class_ref)
            plans.set(plan.class_ref, existing
              ? { ...existing, row_count: existing.row_count + plan.row_count }
              : { ...plan })
            const known = grades.get(plan.class_ref) ?? new Set<string>()
            if (plan.grade_level) known.add(plan.grade_level)
            grades.set(plan.class_ref, known)
          }
        }
      }
    }
    const conflicting = new Set([...grades].filter(([, values]) => values.size > 1).map(([id]) => id))
    if (conflicting.size) {
      valid = false
      for (const row of rows.value) {
        const canonicalRef = planByInput.get(row.class_ref)
        if (canonicalRef && conflicting.has(canonicalRef)) errors.push({ row_no: row.row_no, code: 'GRADE_LEVEL_MISMATCH' })
      }
    }
    preview.value = {
      valid,
      row_count: rows.value.length,
      errors,
      class_groups: Array.from(groups, ([class_ref, row_count]) => ({ class_ref, row_count })),
      class_plan: [...plans.values()],
    }
    if (preview.value.valid && !preview.value.errors.length) notice.value = '预览通过，可确认导入'
    else notice.value = '存在错误或冲突，处理后重新预览'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '花名册预览失败' }
  finally { busy.value = false }
}

async function issuePendingRosterCredentials() {
  if (!pendingCredentialUserIds.value.length) return
  if (!frontendApi.issueLifecycleCredentials) throw new Error('初始密码生成服务不可用')
  const issued = (await frontendApi.issueLifecycleCredentials(pendingCredentialUserIds.value)).data
  credentialRows.value.push(...issued.credentials.map((row) => ({
    ...row, class_ref: rosterCredentialDetails.value[row.user_id]?.className || row.class_ref || '', role: 'student' as const,
  })))
  pendingCredentialUserIds.value = []
}

const importRoster = async () => {
  if (!preview.value?.valid || preview.value.errors.length || busy.value) return
  if (!rosterImportKey.value) {
    rosterImportKey.value = 'roster-' + crypto.randomUUID()
    credentialRows.value = []
    passphrase.value = ''
    credentialPurpose.value = 'initial'
    credentialExportScope.value = ''
    credentialExportName.value = ''
  }
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.importLifecycleRoster) throw new Error('花名册导入服务不可用')
    await issuePendingRosterCredentials()
    while (rosterProcessed.value < rows.value.length) {
      const offset = rosterProcessed.value
      const batch = rosterBatch(offset)
      const result = (await frontendApi.importLifecycleRoster(batch, rosterImportKey.value + '-' + offset)).data
      if (result.status !== 'COMPLETED' || result.row_count !== batch.length
        || result.created_count + result.skipped_count !== batch.length
        || result.accounts.length !== result.created_count) {
        throw new Error('未能确认当前批次的导入结果')
      }
      rosterRun.value = result.run_ref
      directoryLoadedAt = 0
      rosterCreated.value += result.created_count
      rosterProcessed.value += batch.length
      for (const account of result.accounts) {
        const original = batch[account.row_no - 1]
        if (original) {
          const plan = preview.value?.class_plan?.find((item) => item.class_ref === account.class_ref)
          rosterCredentialDetails.value[account.user_id] = {
            studentNumber: original.student_number, className: plan?.display_name || original.class_ref,
          }
        }
      }
      pendingCredentialUserIds.value = [...new Set(result.accounts.map((account) => account.user_id))]
      await issuePendingRosterCredentials()
    }
    credentialUsers.value = []
    rosterImportKey.value = ''
    preview.value = null
    if (credentialRows.value.length) section.value = 'credentials'
    notice.value = '已导入 ' + rosterCreated.value + ' 名学生并生成初始账号（' + credentialRows.value.length + ' 份凭据）'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '花名册导入或初始密码生成失败'
    if (rosterProcessed.value > 0) error.value += '；点击「继续导入」可从当前批次恢复'
  } finally { busy.value = false }
}

const importStaffRoster = async () => {
  if (busy.value || staffClassIssues.value.length) return
  confirmStaffImport.value = false
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.importLifecycleStaff || staffRows.value.length === 0) throw new Error('请选择教职工名单')
    const result = (await frontendApi.importLifecycleStaff(staffRows.value)).data
    if (result.created_count !== staffRows.value.length) throw new Error('未能确认教职工导入结果')
    credentialRows.value = result.credentials.map((row) => ({
      user_id: row.user_id,
      login_name: row.login_name,
      display_name: row.display_name,
      class_ref: row.class_refs.join('、'),
      credential: row.credential,
      expires_at: row.expires_at,
      role: row.role,
      invitation_ref: row.invitation_ref,
    }))
    passphrase.value = ''
    credentialPurpose.value = 'initial'
    staffRows.value = []
    directoryLoadedAt = 0
    section.value = 'credentials'
    notice.value = `已导入 ${result.created_count} 名教职工并生成初始账号，下载后交给对应人员`
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '教职工导入失败' }
  finally { busy.value = false }
}

const refreshRosterRun = async () => {
  if (!rosterRun.value || !frontendApi.getLifecycleRosterImport) return
  clearFeedback(); busy.value = true
  try {
    const result = (await frontendApi.getLifecycleRosterImport(rosterRun.value)).data
    notice.value = `导入状态：${result.status}，新增 ${result.created_count} 个，跳过 ${result.skipped_count} 个`
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '读取导入结果失败' }
  finally { busy.value = false }
}

const inviteStaff = async () => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.inviteSchoolStaff) throw new Error('教职工邀请服务不可用')
    if (!invitationVerified.value) throw new Error('请先完成校内身份核验')
    await requireRecentReauthentication()
    const result = (await frontendApi.inviteSchoolStaff({ ...invitation.value, verified: invitationVerified.value, delivery_channel: 'MANUAL' })).data
    credentialRows.value = [{ user_id: result.user_id, login_name: result.login_name, display_name: invitation.value.display_name, class_ref: invitation.value.class_refs.join(', '), credential: result.credential, expires_at: result.expires_at, invitation_ref: result.invitation_ref, role: invitation.value.role }]
    credentialPurpose.value = 'initial'
    passphrase.value = ''
    section.value = 'credentials'
    await refreshStaffInvitations()
    notice.value = isSyntheticDemo.value ? '邀请已登记，可下载账号 CSV 并交付本人' : '邀请已登记，请加密下载凭据后人工交付'
    invitation.value = { employee_ref: '', display_name: '', role: 'teacher', work_contact: '', class_refs: [] }
    invitationVerified.value = false
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '邀请登记失败' }
  finally { busy.value = false }
}

const revokeStaffInvitation = async (item: LifecycleStaffInvitation) => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.revokeStaffInvitation) throw new Error('邀请撤销服务不可用')
    await requireRecentReauthentication()
    await frontendApi.revokeStaffInvitation(item.invitation_ref, 'ADMINISTRATIVE_REVOCATION')
    await refreshStaffInvitations()
    notice.value = '邀请已撤销'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '邀请撤销失败' }
  finally { busy.value = false }
}

const reissueStaffInvitation = async (item: LifecycleStaffInvitation) => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.reissueStaffInvitation) throw new Error('邀请重签服务不可用')
    await requireRecentReauthentication()
    const result = (await frontendApi.reissueStaffInvitation(item.invitation_ref, 'ADMINISTRATIVE_REISSUE')).data
    credentialRows.value = [{
      user_id: result.user_id, login_name: result.login_name,
      display_name: item.display_name ?? item.login_name,
      class_ref: item.class_refs.join(', '), credential: result.credential,
      expires_at: result.expires_at, invitation_ref: result.invitation_ref, role: item.role,
    }]
    credentialPurpose.value = 'initial'
    passphrase.value = ''
    section.value = 'credentials'
    await refreshStaffInvitations()
    notice.value = isSyntheticDemo.value ? '新凭据已暂存，可下载账号 CSV 并交付本人' : '新凭据已暂存，请加密下载并人工交付'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '邀请重签失败' }
  finally { busy.value = false }
}

const beginStaffRecovery = (item: LifecycleStaffInvitation) => {
  staffRecoveryTarget.value = item
  staffRecoveryReasonCode.value = 'CREDENTIAL_LOST'
  staffRecoveryMethod.value = 'IN_PERSON'
  staffRecoveryVerified.value = false
  clearFeedback()
}

const cancelStaffRecovery = () => {
  staffRecoveryTarget.value = null
  staffRecoveryVerified.value = false
}

const issueStaffRecoveryCredential = async () => {
  const target = staffRecoveryTarget.value
  clearFeedback(); busy.value = true
  try {
    if (!target || !frontendApi.issueStaffRecoveryCredential) throw new Error('教职工恢复服务不可用')
    if (!staffRecoveryVerified.value || !staffRecoveryReasonCode.value.trim()) throw new Error('请完成身份核验并选择原因')
    await requireRecentReauthentication()
    const result = (await frontendApi.issueStaffRecoveryCredential(target.user_id, {
      reason_code: staffRecoveryReasonCode.value.trim(),
      verification_method: staffRecoveryMethod.value,
      identity_verified: true,
    })).data
    credentialRows.value = [{
      user_id: result.user_id,
      login_name: result.login_name,
      display_name: target.display_name ?? target.login_name,
      class_ref: target.class_refs.join(', '),
      credential: result.credential,
      expires_at: result.expires_at,
    }]
    credentialPurpose.value = 'recovery'
    passphrase.value = ''
    staffRecoveryTarget.value = null
    staffRecoveryVerified.value = false
    section.value = 'credentials'
    notice.value = '重置凭据已暂存，请加密下载并人工交付'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '重置凭据签发失败' }
  finally { busy.value = false }
}

const issueCredentials = async () => {
  clearFeedback(); busy.value = true; credentialRows.value = []
  try {
    if (!frontendApi.issueLifecycleCredentials || credentialUsers.value.length === 0) throw new Error('请选择待签发账号')
    if (credentialUsers.value.length > 200) throw new Error('每批最多签发 200 个账号，请按角色分批操作')
    const result = await frontendApi.issueLifecycleCredentials(credentialUsers.value)
    credentialRows.value = result.data.credentials.map((row) => ({
      ...row,
      role: directory.value?.members.find((member) => member.user_id === row.user_id)?.role as 'student' | 'teacher' | undefined,
    }))
    credentialPurpose.value = 'initial'
    credentialUsers.value = []
    passphrase.value = ''
    notice.value = isSyntheticDemo.value
      ? `已生成 ${credentialRows.value.length} 个初始账号，请下载 CSV 并交付本人`
      : `已暂存 ${credentialRows.value.length} 份一次性凭据，离开页面后将清除，请立即加密下载`
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '凭据签发失败' }
  finally { busy.value = false }
}

const csvCell = (value: unknown) => {
  let text = value == null ? '' : String(value)
  if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

const downloadInitialCredentialsCsv = (userId?: string) => {
  const selected = userId
    ? credentialsToExport.value.filter((row) => row.user_id === userId)
    : credentialsToExport.value
  if (!selected.length || !isSyntheticDemo.value || busy.value || rosterImportKey.value) return
  const hasRosterNumbers = selected.some((item) => rosterCredentialDetails.value[item.user_id])
  const rows = [
    ['凭据用途', '角色', ...(hasRosterNumbers ? ['学号'] : []), '姓名', '班级', '学校编号', '登录地址', '账号', credentialPurpose.value === 'initial' ? '初始密码（首次登录凭据）' : '重置凭据', '邀请编号', '有效期至'],
    ...selected.map((item) => [
      credentialPurpose.value === 'initial' ? '首次登录' : '密码重置',
      roleLabel(item.role ?? 'student'), ...(hasRosterNumbers ? [rosterCredentialDetails.value[item.user_id]?.studentNumber || ''] : []), item.display_name, item.class_ref, schoolRef.value,
      `${window.location.origin}/login?setup=${credentialPurpose.value === 'recovery' ? 'reset' : item.invitation_ref ? 'invite' : 'first'}`,
      item.login_name, item.credential, item.invitation_ref, item.expires_at,
    ]),
  ]
  const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = credentialPurpose.value === 'initial' ? 'psynova-initial-accounts.csv' : 'psynova-password-reset-credentials.csv'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  const exported = new Set(selected.map((row) => row.user_id))
  credentialRows.value = credentialRows.value.filter((row) => !exported.has(row.user_id))
  for (const id of exported) delete rosterCredentialDetails.value[id]
  credentialExportScope.value = ''
  passphrase.value = ''
  notice.value = credentialPurpose.value === 'initial'
    ? '账号文件已下载；初始密码首次使用后失效'
    : '重置凭据文件已下载；凭据首次使用后失效'
}

const base64 = (bytes: Uint8Array) => {
  const chunkSize = 24 * 1024
  const chunks: string[] = []
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    chunks.push(btoa(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))))
  }
  return chunks.join('')
}
const downloadEncryptedCredentials = async () => {
  clearFeedback()
  if (!credentialRows.value.length || passphrase.value.length < 12) { error.value = '请设置至少 12 位加密口令'; return }
  try {
    if (!globalThis.crypto?.subtle) throw new Error('浏览器不支持安全加密导出')
    const salt = crypto.getRandomValues(new Uint8Array(16)); const iv = crypto.getRandomValues(new Uint8Array(12))
    const material = await crypto.subtle.importKey('raw', new TextEncoder().encode(passphrase.value), 'PBKDF2', false, ['deriveKey'])
    const key = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: 310000, hash: 'SHA-256' }, material, { name: 'AES-GCM', length: 256 }, false, ['encrypt'])
    const plain = new TextEncoder().encode(JSON.stringify({ created_at: new Date().toISOString(), credentials: credentialRows.value }))
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plain)
    const encrypted = { format: 'psynova-credentials-encrypted-v1', algorithm: 'AES-256-GCM', kdf: 'PBKDF2-SHA-256', iterations: 310000, salt: base64(salt), iv: base64(iv), ciphertext: base64(new Uint8Array(ciphertext)) }
    const url = URL.createObjectURL(new Blob([JSON.stringify(encrypted, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'psynova-credentials-encrypted-v1.json'; link.click(); URL.revokeObjectURL(url)
    passphrase.value = ''
    notice.value = '加密文件已下载，请安全保存加密口令'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '凭据加密失败' }
}

const changeAccountStatus = async (status: 'ACTIVE' | 'DISABLED') => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.updateSchoolAccountStatus) throw new Error('账号状态服务不可用')
    if (!statusSelection.value || !statusReason.value.trim()) throw new Error('请选择账号并填写原因代码')
    await requireRecentReauthentication()
    await frontendApi.updateSchoolAccountStatus(statusSelection.value, status, statusReason.value.trim())
    statusReason.value = ''; notice.value = status === 'DISABLED' ? '账号已停用' : '账号已恢复'; await loadData()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '账号状态更新失败' }
  finally { busy.value = false }
}

const createStudentRecoveryRequest = async () => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.createRecoveryRequest) throw new Error('学生恢复申请服务不可用')
    if (!accountSelection.value.trim() || !accountReason.value.trim() || !recoveryReason.value.trim()) throw new Error('请填写学生账号、班级编号和申请原因代码')
    await frontendApi.createRecoveryRequest({ school_ref: schoolRef.value, username: accountSelection.value.trim(), class_ref: accountReason.value.trim(), reason_code: recoveryReason.value.trim() })
    notice.value = '恢复申请已提交，请联系教师完成身份核验'
    accountSelection.value = ''; accountReason.value = ''; recoveryReason.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '恢复申请失败' }
  finally { busy.value = false }
}

const approveRecovery = async (ticket: LifecycleRecoveryTicket) => {
  clearFeedback(); busy.value = true
  try {
    const reason = recoveryReasons.value[ticket.ticket_ref]?.trim()
    if (!reason) throw new Error('请填写处理原因代码')
    if (!frontendApi.approveRecoveryRequest) throw new Error('管理员审批服务不可用')
    await requireRecentReauthentication()
    const result = (await frontendApi.approveRecoveryRequest(ticket.ticket_ref, reason)).data
    notice.value = `审批完成，一次性恢复凭据已暂存，有效期至 ${result.expires_at}`
    credentialRows.value = [{ user_id: ticket.user_id, login_name: ticket.username, display_name: ticket.display_name, class_ref: ticket.class_ref ?? '', credential: result.credential, expires_at: result.expires_at }]
    credentialPurpose.value = 'recovery'
    if (frontendApi.listRecoveryRequests) recoveryTickets.value = (await frontendApi.listRecoveryRequests()).data
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '恢复请求处理失败' }
  finally { busy.value = false }
}

onMounted(() => {
  void loadData()
  if (props.initialRosterFile) readAttachedRoster(props.initialRosterFile)
})
onUnmounted(() => {
  rosterRead?.abort()
  staffRead?.abort()
  credentialRows.value = []
  passphrase.value = ''
  rows.value = []
  staffRows.value = []
})
</script>

<template>
  <section class="lifecycle" aria-labelledby="lifecycle-title">
    <header class="lifecycle__head"><div><h1 id="lifecycle-title">学校账号管理</h1><p>导入名单、分发初始账号及管理后续状态。</p></div><button type="button" class="lifecycle__secondary" :disabled="busy || loadingAccounts" @click="clearFeedback(); loadData(); loadSectionDetails(section)">刷新账号数据</button></header>
    <nav class="lifecycle__tabs" :style="tabIndicatorStyle" aria-label="学校账号管理功能" role="tablist">
      <span class="lifecycle__tab-indicator" aria-hidden="true" />
      <button v-for="(item, index) in sections" :id="`school-account-tab-${item.id}`" :key="item.id" type="button" role="tab" :aria-selected="section === item.id" :aria-controls="section === item.id ? 'school-account-panel' : undefined" :tabindex="section === item.id ? 0 : -1" @keydown="handleTabKeydown($event, index)" @click="section = item.id">{{ item.label }}</button>
    </nav>
    <p v-if="error" class="lifecycle__message lifecycle__message--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="lifecycle__message" role="status" aria-live="polite">{{ notice }}</p>
    <p v-if="!apiReady" class="lifecycle__message lifecycle__message--error">账号生命周期服务未连接</p>

    <div id="school-account-panel" role="tabpanel" :aria-labelledby="`school-account-tab-${section}`" tabindex="0">
    <div v-if="section === 'overview'" class="lifecycle__body">
      <div v-if="summary" class="lifecycle__metrics" aria-label="账号汇总">
        <div><span>账号总数</span><strong>{{ summary.total_accounts }}</strong></div><div><span>正常账号</span><strong>{{ summary.active_accounts }}</strong></div><div><span>待首次登录</span><strong>{{ summary.pending_activation }}</strong></div><div><span>已停用</span><strong>{{ summary.suspended_accounts }}</strong></div><div><span>班级</span><strong>{{ summary.classes }}</strong></div>
      </div>
      <p v-else class="lifecycle__empty">{{ loadingAccounts ? '正在读取服务端汇总…' : '暂无账号汇总' }}</p>
      <div class="lifecycle__next">
        <button type="button" class="lifecycle__primary" @click="section = 'roster'">导入学生名单</button>
        <button type="button" class="lifecycle__secondary" @click="section = 'staff'">管理教职工</button>
      </div>
    </div>

    <div v-else-if="section === 'roster'" class="lifecycle__body">
      <h3>导入学生名单</h3>
      <p>下载模板，填写学号、姓名、班级名称（或已有编号）和年级。上传后核对预览，确认即可自动建班、归班并生成初始账号。</p>
      <button type="button" class="lifecycle__secondary" @click="downloadRosterTemplate">下载 CSV 模板</button>
      <label class="lifecycle__field">选择 CSV 或 XLSX 文件<input type="file" accept=".csv,.xlsx" :disabled="busy || Boolean(rosterImportKey)" @change="parseRosterFile(($event.target as HTMLInputElement).files?.[0])"></label>
      <p v-if="rows.length" class="lifecycle__boundary">{{ rows.length }} 条记录，预览前 {{ Math.min(rows.length, 30) }} 条</p>
      <div v-if="rows.length" class="lifecycle__table-wrap"><table><thead><tr><th>行号</th><th>学号</th><th>姓名</th><th>班级</th><th>年级</th></tr></thead><tbody><tr v-for="row in rows.slice(0, 30)" :key="row.row_no"><td>{{ row.row_no }}</td><td>{{ row.student_number }}</td><td>{{ row.display_name }}</td><td>{{ row.class_ref }}</td><td>{{ row.grade_level || '—' }}</td></tr></tbody></table></div>
      <div v-if="preview" class="lifecycle__preview-summary" role="status">
        <span>服务端预览：{{ preview.row_count }} 条</span><span>{{ preview.class_plan?.length || preview.class_groups?.length || 0 }} 个班级</span><span v-if="preview.class_plan?.length">新建 {{ preview.class_plan.filter((item) => item.action === 'CREATE').length }} 个</span><span>异常 {{ preview.errors.length }} 条</span>
      </div>
      <div v-if="preview?.class_plan?.length" class="lifecycle__table-wrap lifecycle__table-wrap--summary"><table><thead><tr><th>班级</th><th>年级</th><th>人数</th><th>处理方式</th></tr></thead><tbody><tr v-for="group in preview.class_plan" :key="group.class_ref"><td>{{ group.display_name }}</td><td>{{ group.grade_level || '—' }}</td><td>{{ group.row_count }}</td><td>{{ group.action === 'CREATE' ? '自动新建' : '复用已有班级' }}</td></tr></tbody></table></div>
      <div v-else-if="preview?.class_groups?.length" class="lifecycle__table-wrap lifecycle__table-wrap--summary"><table><thead><tr><th>班级</th><th>人数</th></tr></thead><tbody><tr v-for="group in preview.class_groups" :key="group.class_ref"><td>{{ group.class_ref }}</td><td>{{ group.row_count }}</td></tr></tbody></table></div>
      <ul v-if="preview?.errors.length" class="lifecycle__issues" aria-label="导入异常"><li v-for="(item, index) in preview.errors" :key="`${item.row_no}:${item.code}:${index}`">第 {{ item.row_no }} 条：{{ rosterIssueLabel(item.code) }}</li></ul>
      <p v-if="rosterImportKey" role="status">已处理 {{ rosterProcessed }} / {{ rows.length }} 条，已签发 {{ credentialRows.length }} 份初始凭据，请在处理完成后下载</p>
      <button class="lifecycle__primary" type="button" :disabled="busy || !preview?.valid || Boolean(preview.errors.length)" @click="importRoster">{{ rosterImportKey ? '继续导入' : '导入并生成初始账号' }}</button>
      <button v-if="rosterRun" class="lifecycle__secondary" type="button" :disabled="busy" @click="refreshRosterRun">查看最近一批</button>
    </div>

    <div v-else-if="section === 'staff'" class="lifecycle__body">
      <div v-if="isSyntheticDemo" class="lifecycle__staff-import">
        <h3>导入普通教师和心理教师名单</h3>
        <button type="button" class="lifecycle__secondary" @click="downloadStaffRosterTemplate">下载 CSV 模板</button>
        <label class="lifecycle__field">选择 CSV 或 XLSX 文件<input type="file" accept=".csv,.xlsx" :disabled="busy" @change="parseStaffFile(($event.target as HTMLInputElement).files?.[0])"></label>
        <p>每次最多 3,000 人。普通教师班级用竖线分隔，心理教师不填班级</p>
        <div v-if="staffRows.length" class="lifecycle__boundary">已读取 {{ staffRows.length }} 行，普通教师 {{ staffRows.filter(row => row.role === 'teacher').length }} 人，心理教师 {{ staffRows.filter(row => row.role === 'psychological_specialist').length }} 人</div>
        <template v-if="embeddedSection === 'staff' && staffRows.length">
          <p>核对前 {{ Math.min(staffRows.length, 30) }} 条记录</p>
          <div class="lifecycle__table-wrap">
            <table aria-label="教职工名单预览">
              <thead><tr><th>编号</th><th>姓名</th><th>角色</th><th>任教班级</th></tr></thead>
              <tbody>
                <tr v-for="row in staffRows.slice(0, 30)" :key="row.row_no">
                  <td>{{ row.employee_ref }}</td><td>{{ row.display_name }}</td><td>{{ roleLabel(row.role) }}</td>
                  <td>{{ row.class_refs.map(classLabel).join('、') || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <ul v-if="staffClassIssues.length" class="lifecycle__issues" aria-label="教职工名单异常">
            <li v-for="row in staffClassIssues.slice(0, 30)" :key="row.row_no">第 {{ row.row_no + 1 }} 行包含本校不可用的任教班级</li>
          </ul>
        </template>
        <button class="lifecycle__primary" type="button" :disabled="busy || !staffRows.length || Boolean(staffClassIssues.length)" @click="embeddedSection === 'staff' ? confirmStaffImport = true : importStaffRoster()">{{ busy ? '正在处理…' : embeddedSection === 'staff' ? '核对并导入' : '导入并生成初始账号' }}</button>
        <AppDialog :open="confirmStaffImport" title="确认导入教职工" :description="`为 ${staffRows.length} 名教职工建立校园账号并签发一次性凭据`" @update:open="value => { if (!value) confirmStaffImport = false }">
          <div class="lifecycle__actions">
            <button type="button" class="lifecycle__secondary" @click="confirmStaffImport = false">返回核对</button>
            <button type="button" class="lifecycle__primary" :disabled="busy || !staffRows.length || Boolean(staffClassIssues.length)" @click="importStaffRoster">确认导入</button>
          </div>
        </AppDialog>
      </div>
      <template v-if="!embeddedSection">
      <h3>单个教职工邀请</h3>
      <form class="lifecycle__form" @submit.prevent="inviteStaff">
        <label>教职工编号<input v-model.trim="invitation.employee_ref" required maxlength="128" pattern="[\x20-\x7E]+" placeholder="PSY-001" title="请使用英文编号"></label><label>姓名<input v-model.trim="invitation.display_name" required maxlength="120"></label>
        <label>角色<AppSelect v-model="invitation.role" @update:model-value="updateInvitationRole"><AppSelectOption value="teacher">普通教师</AppSelectOption><AppSelectOption value="psychological_specialist">心理老师</AppSelectOption></AppSelect></label><label>校内联系方式<input v-model.trim="invitation.work_contact" required maxlength="160"></label>
        <label v-if="invitation.role === 'teacher'" class="lifecycle__field">任教班级<AppSelect v-model="invitation.class_refs" multiple><AppSelectOption v-for="item in directory?.classes ?? []" :key="item.class_ref" :value="item.class_ref">{{ item.display_name || item.class_ref }}</AppSelectOption></AppSelect></label>
        <label class="lifecycle__check"><input v-model="invitationVerified" type="checkbox">已核验身份与工作联系方式</label>
        <button class="lifecycle__primary" type="submit" :disabled="busy || !invitationVerified">登记邀请</button>
      </form>
      <label v-if="!usesDemoAdminSession" class="lifecycle__field">管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password"></label>
      <h3>邀请记录</h3>
      <form v-if="frontendApi.listStaffInvitations" class="lifecycle__form" @submit.prevent="changeInvitationPage(1, staffInvitationSearch.trim())">
        <label class="lifecycle__field">搜索邀请<input v-model="staffInvitationSearch" maxlength="128" placeholder="姓名、教职工编号或账号"></label>
        <button class="lifecycle__secondary" type="submit" :disabled="staffInvitationsLoading || busy">搜索</button>
      </form>
      <p v-if="staffInvitationsLoading" role="status">正在读取邀请记录…</p>
      <div v-else-if="staffInvitations.length" class="lifecycle__invitation-list">
        <article v-for="item in staffInvitations" :key="item.invitation_ref" class="lifecycle__invitation">
          <div class="lifecycle__invitation-identity"><strong>{{ item.display_name || item.login_name }}</strong><span>编号 {{ item.employee_ref }}，账号 {{ item.login_name }}，邀请编号 {{ item.invitation_ref }}</span></div>
          <div><span>{{ roleLabel(item.role) }}</span><span>{{ item.class_refs.length ? item.class_refs.map(classLabel).join('、') : '未分配班级' }}</span></div>
          <div><strong>{{ invitationStatusLabel(item.status) }}</strong><span>有效期至 {{ item.expires_at }}</span></div>
          <div class="lifecycle__invitation-actions">
            <button v-if="item.status !== 'REVOKED' && frontendApi.updateStaffInvitationName" type="button" class="lifecycle__secondary" :disabled="busy" @click="beginStaffNameEdit(item)">修改姓名</button>
            <button v-if="item.status !== 'ACCEPTED'" type="button" class="lifecycle__secondary" :disabled="busy" @click="reissueStaffInvitation(item)">重签凭据</button>
            <button v-else type="button" class="lifecycle__secondary" :disabled="busy" @click="beginStaffRecovery(item)">重置凭据</button>
            <button v-if="item.status === 'ISSUED' || item.status === 'EXPIRED'" type="button" class="lifecycle__secondary" :disabled="busy" @click="revokeStaffInvitation(item)">撤销邀请</button>
          </div>
        </article>
      </div>
      <p v-else-if="frontendApi.listStaffInvitations" class="lifecycle__empty">{{ appliedInvitationSearch ? '没有符合条件的邀请' : '暂无邀请记录' }}</p>
      <p v-else class="lifecycle__empty">邀请记录服务暂不可用</p>
      <div v-if="staffInvitationPage > 1 || hasMoreStaffInvitations" class="lifecycle__actions">
        <span>第 {{ staffInvitationPage }} 页</span>
        <button class="lifecycle__secondary" type="button" :disabled="staffInvitationPage === 1 || staffInvitationsLoading || busy" @click="changeInvitationPage(staffInvitationPage - 1)">上一页</button>
        <button class="lifecycle__secondary" type="button" :disabled="!hasMoreStaffInvitations || staffInvitationsLoading || busy" @click="changeInvitationPage(staffInvitationPage + 1)">下一页</button>
      </div>
      <AppDialog :open="Boolean(staffNameTarget)" title="修改教职工姓名" :description="staffNameTarget?.employee_ref" @update:open="value => { if (!value && !busy) staffNameTarget = null }">
        <form class="lifecycle__form" @submit.prevent="saveStaffName">
          <label class="lifecycle__field">姓名<input v-model.trim="staffNameDraft" required maxlength="120" autocomplete="off" :disabled="busy"></label>
          <p v-if="staffNameError" class="lifecycle__error" role="alert">{{ staffNameError }}</p>
          <div class="lifecycle__actions">
            <button class="lifecycle__primary" type="submit" :disabled="busy || !staffNameDraft || staffNameDraft === staffNameTarget?.display_name">保存姓名</button>
            <button class="lifecycle__secondary" type="button" :disabled="busy" @click="staffNameTarget = null">取消</button>
          </div>
        </form>
      </AppDialog>
      <DialogRoot :open="Boolean(staffRecoveryTarget)" @update:open="value => { if (!value) cancelStaffRecovery() }">
        <DialogPortal>
          <DialogOverlay class="lifecycle__modal-backdrop" />
          <DialogContent class="lifecycle__modal">
            <div class="lifecycle__modal-heading"><DialogTitle>重置教职工凭据</DialogTitle><DialogDescription>{{ staffRecoveryTarget?.display_name || staffRecoveryTarget?.login_name }}</DialogDescription></div>
            <label>核验方式<AppSelect v-model="staffRecoveryMethod"><AppSelectOption value="IN_PERSON">当面核验</AppSelectOption><AppSelectOption v-if="staffRecoveryTarget?.role === 'teacher'" value="VERIFIED_WORK_CONTACT">已核验的校内联系方式</AppSelectOption></AppSelect></label>
            <label>原因代码<input v-model.trim="staffRecoveryReasonCode" required maxlength="80"></label>
            <label class="lifecycle__check"><input v-model="staffRecoveryVerified" type="checkbox">已完成身份核验</label>
            <div class="lifecycle__actions"><DialogClose as-child><button type="button" class="lifecycle__secondary" :disabled="busy">取消</button></DialogClose><button type="button" class="lifecycle__primary" :disabled="busy || !staffRecoveryVerified" @click="issueStaffRecoveryCredential">签发一次性凭据</button></div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
      </template>
    </div>

    <div v-else-if="section === 'recovery'" class="lifecycle__body">
      <h3>安全恢复请求</h3><p>教师核验后，由管理员审批</p>
      <div class="lifecycle__form lifecycle__form--inline"><label>学生账号<input v-model="accountSelection" autocomplete="off"></label><label>班级编号<input v-model="accountReason" autocomplete="off"></label><label>申请原因代码<input v-model="recoveryReason" autocomplete="off"></label><button type="button" class="lifecycle__primary" :disabled="busy" @click="createStudentRecoveryRequest">提交学生申请</button></div>
      <label v-if="!usesDemoAdminSession" class="lifecycle__field">管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password"></label>
      <div v-if="recoveryTickets.length" class="lifecycle__tickets"><article v-for="ticket in recoveryTickets" :key="ticket.ticket_ref"><div><strong>{{ ticket.display_name }}</strong><span>{{ ticket.username }}，{{ ticket.class_ref || '未关联班级' }}</span><small>状态：{{ ticket.status }}，提交 {{ ticket.created_at }}</small></div><label>处理原因代码<input v-model.trim="recoveryReasons[ticket.ticket_ref]" required></label><div class="lifecycle__actions"><button type="button" class="lifecycle__primary" :disabled="busy" @click="approveRecovery(ticket)">管理员审批</button></div></article></div>
      <p v-else-if="frontendApi.listRecoveryRequests" class="lifecycle__empty">暂无待处理请求</p>
      <p v-else class="lifecycle__empty">恢复请求服务不可用</p>
    </div>

    <div v-else-if="section === 'credentials'" class="lifecycle__body">
      <h3>初始账号</h3><p v-if="isSyntheticDemo">初始密码仅能使用一次；首次登录时设置个人密码</p><p v-else>初始账号仅暂存在本页，请加密下载</p>
      <div class="lifecycle__credential-tools">
        <label>账号角色<AppSelect v-model="credentialRoleFilter"><AppSelectOption value="all">全部</AppSelectOption><AppSelectOption value="student">学生</AppSelectOption><AppSelectOption value="teacher">普通教师</AppSelectOption></AppSelect></label>
        <label>班级筛选<AppSelect v-model="credentialClassFilter"><AppSelectOption value="">全部班级</AppSelectOption><AppSelectOption value="__unassigned__">未分配班级</AppSelectOption><AppSelectOption v-for="item in directory?.classes ?? []" :key="item.class_ref" :value="item.class_ref">{{ item.display_name || item.class_ref }}</AppSelectOption></AppSelect></label>
        <label>搜索账号<input v-model.trim="credentialSearch" type="search" autocomplete="off" placeholder="姓名或账号编号"></label>
      </div>
      <div class="lifecycle__selection-tools"><span>符合筛选 {{ credentialCandidates.length }} 人，已选择 {{ selectedCredentialCount }} 人</span><button type="button" class="lifecycle__secondary" :disabled="!credentialPageRows.length" @click="selectCurrentCredentialPage">选择当前页</button><button type="button" class="lifecycle__secondary" :disabled="!credentialCandidates.length || credentialCandidates.length > 200" @click="selectCredentialCandidates">选择筛选结果</button><button type="button" class="lifecycle__secondary" :disabled="!credentialUsers.length" @click="credentialUsers = []">清空选择</button></div>
      <p v-if="credentialCandidates.length > 200" class="lifecycle__empty">每批最多签发 200 个账号，请按角色分批操作</p>
      <div v-if="credentialPageRows.length" class="lifecycle__table-wrap"><table><thead><tr><th scope="col">选择</th><th scope="col">姓名</th><th scope="col">角色</th><th scope="col">班级</th><th scope="col">账号编号</th></tr></thead><tbody><tr v-for="item in credentialPageRows" :key="item.user_id"><td><input type="checkbox" :checked="credentialUsers.includes(item.user_id)" :aria-label="`选择${item.display_name || item.user_id}`" @change="toggleCredentialUser(item.user_id, ($event.target as HTMLInputElement).checked)"></td><td>{{ item.display_name || '未填写姓名' }}</td><td>{{ roleLabel(item.role) }}</td><td>{{ item.class_refs?.map(classLabel).join('、') || '未分配' }}</td><td>{{ item.user_id }}</td></tr></tbody></table></div>
      <p v-else class="lifecycle__empty">没有符合条件的账号</p>
      <div class="lifecycle__selection-tools" aria-label="凭据名单分页"><span>第 {{ credentialPage }} / {{ credentialPageCount }} 页</span><button type="button" class="lifecycle__secondary" :disabled="credentialPage <= 1" @click="credentialPage -= 1">上一页</button><button type="button" class="lifecycle__secondary" :disabled="credentialPage >= credentialPageCount" @click="credentialPage += 1">下一页</button></div>
      <button v-if="rosterImportKey" type="button" class="lifecycle__primary" :disabled="busy" @click="section = 'roster'">返回学生名单继续导入</button>
      <button v-else-if="!credentialRows.length" type="button" class="lifecycle__primary" :disabled="busy || !credentialUsers.length" @click="issueCredentials">生成初始密码</button>
      <div v-if="credentialRows.length && isSyntheticDemo" class="lifecycle__credential-tools">
        <label for="credential-export-scope">下载范围<AppSelect id="credential-export-scope" v-model="credentialExportScope" :options="credentialExportOptions" /></label>
        <button type="button" class="lifecycle__primary" :disabled="busy || Boolean(rosterImportKey) || !credentialsToExport.length" @click="downloadInitialCredentialsCsv()">下载账号 CSV（{{ credentialsToExport.length }} 份）</button>
      </div>
      <label v-if="credentialRows.length && !isSyntheticDemo" class="lifecycle__field">加密口令（至少 12 位）<input v-model="passphrase" type="password" autocomplete="new-password" minlength="12"></label>
      <button v-if="credentialRows.length && !isSyntheticDemo" type="button" class="lifecycle__primary" :disabled="passphrase.length < 12" @click="downloadEncryptedCredentials">加密下载</button>
      <label v-if="credentialRows.length && isSyntheticDemo" class="lifecycle__field">查找已签发账号<input v-model="credentialExportName" type="search" placeholder="姓名或登录账号"></label>
      <p v-if="matchingIssuedCredentials.length > 30">已匹配 {{ matchingIssuedCredentials.length }} 份，显示前 30 份</p>
      <ul v-if="matchingIssuedCredentials.length" class="lifecycle__credential-records">
        <li v-for="row in matchingIssuedCredentials.slice(0, 30)" :key="row.user_id">
          {{ row.display_name }}（{{ roleLabel(row.role ?? 'student') }}，{{ row.login_name }}）
          <template v-if="row.invitation_ref">，邀请编号 {{ row.invitation_ref }}</template>
          <time :datetime="row.expires_at">，有效期至 {{ row.expires_at }}</time>
          <button v-if="isSyntheticDemo" type="button" class="lifecycle__secondary" :disabled="busy || Boolean(rosterImportKey)" :aria-label="`下载 ${row.display_name || row.login_name} 的账号`" @click="downloadInitialCredentialsCsv(row.user_id)">下载</button>
        </li>
      </ul>
    </div>

    <div v-else-if="section === 'directory'" class="lifecycle__body lifecycle__directory">
      <slot name="directory" :load-directory="loadDirectory" />
    </div>

    <div v-else class="lifecycle__body">
      <h3>账号状态</h3><p>{{ usesDemoAdminSession ? '恢复账号后仍按原有权限访问。' : '操作前需重新认证。恢复账号后仍按原有权限访问。' }}</p>
      <label class="lifecycle__field">搜索账号<input v-model.trim="statusSearch" type="search" autocomplete="off" placeholder="姓名或账号编号"></label>
      <div v-if="statusPageRows.length" class="lifecycle__table-wrap"><table><thead><tr><th scope="col">选择</th><th scope="col">成员</th><th scope="col">账号</th><th scope="col">角色</th><th scope="col">状态</th></tr></thead><tbody><tr v-for="item in statusPageRows" :key="item.user_id"><td><input type="radio" name="account-status-selection" :checked="statusSelection === item.user_id" :aria-label="`选择账号 ${item.display_name || item.user_id} ${item.user_id}`" @change="statusSelection = item.user_id"></td><td>{{ item.display_name || '未填写姓名' }}</td><td>{{ item.user_id }}</td><td>{{ roleLabel(item.role) }}</td><td>{{ memberStatusLabel(item) }}</td></tr></tbody></table></div>
      <p v-else class="lifecycle__empty">没有匹配账号</p>
      <div class="lifecycle__selection-tools" aria-label="账号列表分页"><span>{{ statusCandidates.length }} 个账号，第 {{ statusPage }} / {{ statusPageCount }} 页</span><button type="button" class="lifecycle__secondary" :disabled="statusPage <= 1" @click="statusPage -= 1">上一页</button><button type="button" class="lifecycle__secondary" :disabled="statusPage >= statusPageCount" @click="statusPage += 1">下一页</button></div>
      <label class="lifecycle__field">原因代码<input v-model.trim="statusReason" required maxlength="80" autocomplete="off"></label>
      <label v-if="!usesDemoAdminSession" class="lifecycle__field">管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password" required></label>
      <button type="button" class="lifecycle__primary" :disabled="busy || !statusSelection" @click="changeAccountStatus('DISABLED')">停用账号</button><button type="button" class="lifecycle__secondary" :disabled="busy || !statusSelection" @click="changeAccountStatus('ACTIVE')">恢复账号</button>
    </div>
    </div>
  </section>
</template>

<style scoped>
.lifecycle { display: grid; gap: 16px; margin-bottom: 24px; padding: 16px; border: .5px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); color: var(--color-text-primary); font-size: 12px; }
.lifecycle__head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.lifecycle__head h1 { margin: 0; font-family: var(--font-display); font-size: 24px; line-height: 1.35; font-weight: 650; }
.lifecycle__head p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 14px; }
.lifecycle__tabs { position: relative; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; padding: 4px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface-muted); }
.lifecycle__tabs button { position: relative; min-height: 38px; padding: 0 8px; border: 1px solid transparent; border-radius: var(--radius-control); color: var(--color-text-secondary); background: transparent; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; transition: color var(--motion-fast); }
.lifecycle__tabs button:hover { color: var(--color-primary); }
.lifecycle__tabs button[aria-selected="true"] { color: var(--color-primary); }
.lifecycle__tab-indicator { position: absolute; inset: 4px auto auto 4px; width: calc((100% - 32px) / 7); height: 38px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); box-shadow: var(--shadow-rest); transform: translateX(calc(var(--tab-index) * (100% + 4px))); transition: transform 220ms ease; pointer-events: none; }
.lifecycle__body.lifecycle__directory { width: 100%; min-width: 0; justify-items: stretch; }
.lifecycle__next { display: flex; flex-wrap: wrap; gap: 10px; }
.lifecycle input:not([type="checkbox"], [type="radio"]):focus, .lifecycle select:focus {
  border-color: var(--color-primary);
  outline: 2px solid color-mix(in srgb, var(--color-primary) 26%, transparent);
  outline-offset: 1px;
}
.lifecycle input[type="checkbox"], .lifecycle input[type="radio"] { min-height: auto; accent-color: var(--color-primary); }
.lifecycle__body { display: grid; align-content: start; justify-items: start; gap: 12px; min-width: 0; }.lifecycle__body h3 { margin: 0; font-size: 16px; }.lifecycle__body > p { margin: 0; color: var(--color-text-secondary); font-size: 12px; }.lifecycle__metrics { display: grid; width: 100%; grid-template-columns: repeat(auto-fit,minmax(130px,1fr)); border: .5px solid var(--color-border); }.lifecycle__metrics div { display: grid; gap: 8px; padding: 12px; border-right: .5px solid var(--color-border); border-bottom: .5px solid var(--color-border); }.lifecycle__metrics span { color: var(--color-text-muted); font-size: 12px; }.lifecycle__metrics strong { font-size: 24px; font-weight: 600; }.lifecycle__boundary { padding: 10px 12px; background: var(--color-info-wash); }
.lifecycle__staff-import { display: grid; width: 100%; gap: 10px; padding: 12px; border: .5px solid var(--color-border); background: var(--color-surface-muted); }
.lifecycle__message { margin: 0; padding: 9px 11px; border: .5px solid var(--color-border); color: var(--color-text-secondary); font-size: 12px; }.lifecycle__message--error { border-color: var(--color-critical); color: var(--color-critical); background: var(--color-critical-wash); }.lifecycle__empty { color: var(--color-text-muted); font-size: 12px; }.lifecycle__primary,.lifecycle__secondary { min-height: 36px; padding: 0 12px; border: .5px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-primary); background: var(--color-surface); font: inherit; font-size: 12px; cursor: pointer; }.lifecycle__primary { border-color: var(--color-primary); color: var(--color-text-inverse); background: var(--color-primary); }.lifecycle button:disabled { cursor: not-allowed; opacity: .55; }.lifecycle button:focus-visible,.lifecycle input:focus-visible,.lifecycle select:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.lifecycle__preview-summary { display: flex; flex-wrap: wrap; gap: 16px; color: var(--color-text-secondary); }
.lifecycle__credential-tools,.lifecycle__selection-tools { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; width: 100%; }
.lifecycle__credential-tools label { display: grid; gap: 7px; flex: 0 1 220px; min-width: min(160px, 100%); color: var(--color-text-secondary); font-size: 13px; }
.lifecycle__credential-tools input { min-height: 46px; width: 100%; }
.lifecycle__selection-tools { align-items: center; }
.lifecycle__field,.lifecycle__form label,.lifecycle__tickets label { display: grid; gap: 5px; min-width: min(100%,240px); color: var(--color-text-secondary); font-size: 12px; }.lifecycle input,.lifecycle select { min-height: 36px; padding: 6px 9px; border: .5px solid var(--color-border-strong); border-radius: var(--radius-control); color: var(--color-text-primary); background: var(--color-surface); font: inherit; font-size: 12px; }.lifecycle input[type="file"] { min-height: 40px; }.lifecycle select[multiple] { min-width: min(100%,420px); height: auto; }.lifecycle__form { display: grid; width: 100%; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 12px; }.lifecycle__check { display: flex !important; grid-column: 1/-1; align-items: center; }.lifecycle__check input { min-height: auto; }.lifecycle__form--inline { grid-template-columns: repeat(auto-fit,minmax(190px,1fr)); align-items: end; }
.lifecycle__table-wrap { width: 100%; max-height: 340px; overflow: auto; border: .5px solid var(--color-border); }.lifecycle table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }.lifecycle th,.lifecycle td { padding: 8px; border-bottom: .5px solid var(--color-border); }.lifecycle th { position: sticky; top: 0; background: var(--color-surface-muted); }.lifecycle__issues { display: grid; gap: 5px; margin: 0; padding-left: 20px; color: var(--color-critical); font-size: 12px; }.lifecycle__tickets { display: grid; width: 100%; gap: 9px; }.lifecycle__tickets article { display: grid; grid-template-columns: minmax(160px,1fr) minmax(160px,1fr) auto; align-items: end; gap: 12px; padding: 12px 0; border-bottom: .5px solid var(--color-border); }.lifecycle__tickets article > div:first-child { display: grid; gap: 4px; font-size: 12px; }.lifecycle__tickets span,.lifecycle__tickets small { color: var(--color-text-muted); font-size: 12px; }.lifecycle__actions { display: flex; gap: 6px; }
.lifecycle__credential-records { display: grid; min-width: 0; max-width: 100%; gap: 5px; margin: 0; padding-left: 20px; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }.lifecycle__credential-records li { min-width: 0; overflow-wrap: anywhere; }
.lifecycle__invitation-list { display: grid; width: 100%; }.lifecycle__invitation { display: grid; grid-template-columns: minmax(180px,1.2fr) minmax(150px,1fr) minmax(170px,1fr) auto; align-items: center; gap: 12px; padding: 12px 0; border-bottom: .5px solid var(--color-border); }.lifecycle__invitation > div:not(.lifecycle__invitation-actions),.lifecycle__invitation-identity { display: grid; gap: 4px; min-width: 0; overflow-wrap: anywhere; }.lifecycle__invitation span { color: var(--color-text-secondary); font-size: 12px; }.lifecycle__invitation-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.lifecycle__modal-backdrop { position: fixed; z-index: 90; inset: 0; background: color-mix(in srgb,var(--color-text-primary) 18%,transparent); }
.lifecycle__modal { position: fixed; top: 50%; left: 50%; z-index: 91; display: grid; width: min(420px,calc(100vw - 32px)); max-height: calc(100dvh - 32px); gap: 12px; overflow: auto; padding: 20px; border: .5px solid var(--color-border-strong); border-radius: var(--radius-dialog); color: var(--color-text-primary); background: var(--color-surface); box-shadow: var(--shadow-raised); transform: translate(-50%,-50%); }
.lifecycle__modal-heading { display: grid; gap: 4px; }.lifecycle__modal-heading h2 { margin: 0; font-size: 16px; }.lifecycle__modal-heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.lifecycle__modal label:not(.lifecycle__check) { display: grid; gap: 5px; color: var(--color-text-secondary); font-size: 12px; }
.lifecycle__modal input:not([type="checkbox"]),.lifecycle__modal select { min-height: 36px; padding: 0 9px; border: .5px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-text-primary); background: var(--color-surface); font: inherit; }
.lifecycle__modal :focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
@media(max-width:700px) { .lifecycle { padding: 12px; }.lifecycle__tabs { grid-template-columns: repeat(3,minmax(0,1fr)); grid-auto-rows: 38px; }.lifecycle__tab-indicator { width: calc((100% - 16px) / 3); transform: translate(calc(var(--tab-column) * (100% + 4px)), calc(var(--tab-row) * 42px)); }.lifecycle__tabs button { min-width: 0; padding: 0 4px; }.lifecycle__tickets article,.lifecycle__invitation { grid-template-columns: 1fr; }.lifecycle__head { align-items: flex-start; flex-wrap: wrap; }.lifecycle__head h1 { font-size: 20px; } }
@media (prefers-reduced-motion: reduce) { .lifecycle__tab-indicator, .lifecycle__tabs button { transition: none; } }
</style>
