<script setup lang="ts">
/* global KeyboardEvent, HTMLButtonElement, URL, Blob, File, TextDecoder, TextEncoder, btoa */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
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
import type {
  LifecycleAccountSummary, LifecycleCredential, LifecycleRecoveryTicket, LifecycleRosterPreview,
  LifecycleRosterRow, LifecycleStaffInvitation, SchoolDirectory,
} from '@/api/client'

type Section = 'overview' | 'roster' | 'staff' | 'recovery' | 'credentials' | 'status'
const section = ref<Section>('overview')
const sections: Array<{ id: Section; label: string }> = [
  { id: 'overview', label: '概览' }, { id: 'roster', label: '学生花名册' }, { id: 'staff', label: '教职工邀请' },
  { id: 'recovery', label: '安全恢复' }, { id: 'credentials', label: '一次性凭据' }, { id: 'status', label: '账号状态' },
]
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
defineExpose({ openCredentials })
const summary = ref<LifecycleAccountSummary | null>(null)
const directory = ref<SchoolDirectory | null>(null)
const recoveryTickets = ref<LifecycleRecoveryTicket[]>([])
const staffInvitations = ref<LifecycleStaffInvitation[]>([])
const busy = ref(false)
const error = ref('')
const notice = ref('')
const rows = ref<LifecycleRosterRow[]>([])
const preview = ref<LifecycleRosterPreview | null>(null)
const rosterRun = ref('')
const rosterImportKey = ref('')
const credentialRows = ref<LifecycleCredential[]>([])
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
  CLASS_UNAVAILABLE: '班级不存在或已停用',
  GRADE_LEVEL_MISMATCH: '年级与班级不一致',
}
const rosterIssueLabel = (code: string) => rosterIssueLabels[code] ?? '记录无法导入'

const clearFeedback = () => { error.value = ''; notice.value = '' }
const classLabel = (classRef: string) => directory.value?.classes.find((item) => item.class_ref === classRef)?.display_name || classRef
const roleLabel = (role: string) => ({
  admin: '学校管理员', administrator: '学校管理员', student: '学生', teacher: '普通教师',
  psychological_specialist: '心理老师',
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
  staffInvitations.value = (await frontendApi.listStaffInvitations()).data
}
const requireRecentReauthentication = async () => {
  if (!frontendApi.reauthenticate || !reauthPassword.value) throw new Error('请输入管理员当前密码')
  const currentPassword = reauthPassword.value
  try { await frontendApi.reauthenticate(currentPassword) }
  finally { reauthPassword.value = '' }
}
const loadData = async () => {
  clearFeedback()
  busy.value = true
  try {
    if (!frontendApi.getLifecycleAccountSummary || !frontendApi.getSchoolAdminDirectory) throw new Error('账号生命周期服务不可用')
    const [summaryResponse, directoryResponse] = await Promise.all([
      frontendApi.getLifecycleAccountSummary(), frontendApi.getSchoolAdminDirectory(),
    ])
    summary.value = summaryResponse.data
    directory.value = directoryResponse.data
    if (frontendApi.listRecoveryRequests) recoveryTickets.value = (await frontendApi.listRecoveryRequests()).data
    await refreshStaffInvitations()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '读取账号信息失败' }
  finally { busy.value = false }
}

const downloadRosterTemplate = () => {
  const csv = '\uFEFF# psynova_student_roster_template_v1\r\nstudent_number,display_name,class_ref,grade_level\r\n'
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'psynova-roster-template-v1.csv'; link.click(); URL.revokeObjectURL(url)
}

const parseCsvRecords = (text: string): string[][] => {
  const result: string[][] = []
  let record: string[] = []; let field = ''; let quoted = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]!
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1 }
      else if (char === '"') quoted = false
      else field += char
    } else if (char === '"') {
      if (field) throw new Error('CSV 引号格式错误')
      quoted = true
    } else if (char === ',') { record.push(field.trim()); field = '' }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[index + 1] === '\n') index += 1
      record.push(field.trim()); field = ''
      if (record.some((value) => value)) result.push(record)
      record = []
    } else field += char
  }
  if (quoted) throw new Error('CSV 存在未闭合的引号')
  record.push(field.trim())
  if (record.some((value) => value)) result.push(record)
  return result
}

const parseRosterFile = async (file?: File) => {
  clearFeedback(); preview.value = null; rosterRun.value = ''; rosterImportKey.value = ''; rows.value = []
  if (!file) return
  if (file.size > 1024 * 1024) { error.value = '文件不能超过 1 MiB'; return }
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()).replace(/^\uFEFF/, '')
    const records = parseCsvRecords(text)
    const versionMarker = '# psynova_student_roster_template_v1'
    if (records[0]?.length === 1 && records[0][0]?.startsWith('# psynova_student_roster_template_')) {
      if (records.shift()?.[0] !== versionMarker) throw new Error('花名册模板版本不受支持')
    }
    const expected = ['student_number', 'display_name', 'class_ref', 'grade_level']
    if (JSON.stringify(records.shift()) !== JSON.stringify(expected)) throw new Error('模板列不匹配')
    if (records.length < 1 || records.length > 200) throw new Error('导入须包含 1 到 200 行学生记录')
    rows.value = records.map((record, index) => {
      if ((record.length !== 3 && record.length !== 4) || record.slice(0, 3).some((cell) => !cell)) throw new Error(`第 ${index + 2} 行信息不完整`)
      return { row_no: index + 1, student_number: record[0]!, display_name: record[1]!, class_ref: record[2]!, ...(record[3] ? { grade_level: record[3] } : {}) }
    })
    notice.value = `已读取 ${rows.value.length} 行，按班级分组预览`
  } catch (cause) { rows.value = []; error.value = cause instanceof Error ? cause.message : '无法读取文件' }
}

const previewRoster = async () => {
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.previewLifecycleRoster) throw new Error('花名册预览服务不可用')
    preview.value = (await frontendApi.previewLifecycleRoster(rows.value)).data
    if (preview.value.valid && !preview.value.errors.length) notice.value = '预览通过，可确认导入'
    else notice.value = '存在错误或冲突，处理后重新预览'
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '花名册预览失败' }
  finally { busy.value = false }
}

const importRoster = async () => {
  if (!preview.value?.valid || preview.value.errors.length) return
  clearFeedback(); busy.value = true
  try {
    if (!frontendApi.importLifecycleRoster) throw new Error('花名册导入服务不可用')
    if (!rosterImportKey.value) rosterImportKey.value = `roster-${crypto.randomUUID()}`
    const result = (await frontendApi.importLifecycleRoster(rows.value, rosterImportKey.value)).data
    rosterRun.value = result.run_ref
    await loadData()
    notice.value = `导入任务 ${result.run_ref} 已受理，新增 ${result.created_count} 个账号`
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '花名册导入失败' }
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
    credentialRows.value = [{ user_id: result.user_id, login_name: result.login_name, display_name: invitation.value.display_name, class_ref: invitation.value.class_refs.join(', '), credential: result.credential, expires_at: result.expires_at, invitation_ref: result.invitation_ref }]
    passphrase.value = ''
    section.value = 'credentials'
    await refreshStaffInvitations()
    notice.value = '邀请已登记，请加密下载凭据后人工交付'
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
      expires_at: result.expires_at, invitation_ref: result.invitation_ref,
    }]
    passphrase.value = ''
    section.value = 'credentials'
    await refreshStaffInvitations()
    notice.value = '新凭据已暂存，请加密下载并人工交付'
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
    await requireRecentReauthentication()
    const result = await frontendApi.issueLifecycleCredentials(credentialUsers.value)
    credentialRows.value = result.data.credentials.map((row) => ({
      ...row,
      role: directory.value?.members.find((member) => member.user_id === row.user_id)?.role as 'student' | 'teacher' | undefined,
    }))
    credentialUsers.value = []
    passphrase.value = ''
    notice.value = `已暂存 ${credentialRows.value.length} 份一次性凭据，离开页面后将清除，请立即加密下载`
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '凭据签发失败' }
  finally { busy.value = false }
}

const base64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes))
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
    if (frontendApi.listRecoveryRequests) recoveryTickets.value = (await frontendApi.listRecoveryRequests()).data
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '恢复请求处理失败' }
  finally { busy.value = false }
}

onMounted(loadData)
onUnmounted(() => { credentialRows.value = []; passphrase.value = ''; rows.value = [] })
</script>

<template>
  <section class="lifecycle" aria-labelledby="lifecycle-title">
    <header class="lifecycle__head"><h2 id="lifecycle-title">学校账号生命周期</h2><button type="button" class="lifecycle__secondary" :disabled="busy" @click="loadData">刷新</button></header>
    <nav class="lifecycle__tabs" aria-label="账号生命周期功能" role="tablist">
      <button v-for="(item, index) in sections" :key="item.id" type="button" role="tab" :aria-selected="section === item.id" :tabindex="section === item.id ? 0 : -1" @keydown="handleTabKeydown($event, index)" @click="section = item.id">{{ item.label }}</button>
    </nav>
    <p v-if="error" class="lifecycle__message lifecycle__message--error" role="alert">{{ error }}</p>
    <p v-if="notice" class="lifecycle__message" role="status" aria-live="polite">{{ notice }}</p>
    <p v-if="!apiReady" class="lifecycle__message lifecycle__message--error">账号生命周期服务未连接</p>

    <div v-if="section === 'overview'" class="lifecycle__body">
      <div v-if="summary" class="lifecycle__metrics" aria-label="账号汇总">
        <div><span>账号总数</span><strong>{{ summary.total_accounts }}</strong></div><div><span>正常账号</span><strong>{{ summary.active_accounts }}</strong></div><div><span>待首次登录</span><strong>{{ summary.pending_activation }}</strong></div><div><span>已停用</span><strong>{{ summary.suspended_accounts }}</strong></div><div><span>班级</span><strong>{{ summary.classes }}</strong></div>
      </div>
      <p v-else class="lifecycle__empty">{{ busy ? '正在读取服务端汇总…' : '暂无账号汇总' }}</p>
    </div>

    <div v-else-if="section === 'roster'" class="lifecycle__body">
      <h3>导入学生花名册</h3>
      <button type="button" class="lifecycle__secondary" @click="downloadRosterTemplate">下载模板 v1</button>
      <label class="lifecycle__field">选择 CSV 文件<input type="file" accept=".csv,text/csv" :disabled="busy" @change="parseRosterFile(($event.target as HTMLInputElement).files?.[0])"></label>
      <p v-if="rows.length" class="lifecycle__boundary">{{ rows.length }} 条记录，{{ new Set(rows.map((row) => row.class_ref)).size }} 个班级</p>
      <div v-if="rows.length" class="lifecycle__table-wrap"><table><thead><tr><th>行号</th><th>学号</th><th>姓名</th><th>班级</th><th>年级</th></tr></thead><tbody><tr v-for="row in rows.slice(0, 200)" :key="row.row_no"><td>{{ row.row_no }}</td><td>{{ row.student_number }}</td><td>{{ row.display_name }}</td><td>{{ row.class_ref }}</td><td>{{ row.grade_level || '—' }}</td></tr></tbody></table></div>
      <div v-if="preview" class="lifecycle__preview-summary" role="status">
        <span>服务端预览：{{ preview.row_count }} 条</span><span>{{ preview.class_groups?.length ?? 0 }} 个班级</span><span>异常 {{ preview.errors.length }} 条</span>
      </div>
      <div v-if="preview?.class_groups?.length" class="lifecycle__table-wrap lifecycle__table-wrap--summary"><table><thead><tr><th>班级</th><th>人数</th></tr></thead><tbody><tr v-for="group in preview.class_groups" :key="group.class_ref"><td>{{ group.class_ref }}</td><td>{{ group.row_count }}</td></tr></tbody></table></div>
      <ul v-if="preview?.errors.length" class="lifecycle__issues" aria-label="导入异常"><li v-for="(item, index) in preview.errors" :key="`${item.row_no}:${item.code}:${index}`">第 {{ item.row_no }} 条：{{ rosterIssueLabel(item.code) }}</li></ul>
      <button class="lifecycle__primary" type="button" :disabled="busy || rows.length === 0" @click="previewRoster">服务端预览</button>
      <button class="lifecycle__primary" type="button" :disabled="busy || !preview?.valid || Boolean(preview.errors.length)" @click="importRoster">确认导入</button>
      <button v-if="rosterRun" class="lifecycle__secondary" type="button" :disabled="busy" @click="refreshRosterRun">查看导入结果</button>
    </div>

    <div v-else-if="section === 'staff'" class="lifecycle__body">
      <h3>教职工邀请</h3><p>交付方式：校内人工交付，不发送短信或邮件</p>
      <form class="lifecycle__form" @submit.prevent="inviteStaff">
        <label>教职工编号<input v-model.trim="invitation.employee_ref" required maxlength="128" pattern="[\x20-\x7E]+" placeholder="PSY-001" title="请使用英文编号"></label><label>姓名<input v-model.trim="invitation.display_name" required maxlength="120"></label>
        <label>角色<select v-model="invitation.role" @change="updateInvitationRole"><option value="teacher">普通教师</option><option value="psychological_specialist">心理老师</option></select></label><label>校内联系方式<input v-model.trim="invitation.work_contact" required maxlength="160"></label>
        <label v-if="invitation.role === 'teacher'" class="lifecycle__field">任教班级<select v-model="invitation.class_refs" multiple size="4"><option v-for="item in directory?.classes ?? []" :key="item.class_ref" :value="item.class_ref">{{ item.display_name || item.class_ref }}</option></select></label>
        <label class="lifecycle__check"><input v-model="invitationVerified" type="checkbox">已核验身份与工作联系方式</label>
        <button class="lifecycle__primary" type="submit" :disabled="busy || !invitationVerified">登记邀请</button>
      </form>
      <label class="lifecycle__field">管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password"></label>
      <h3>邀请记录</h3>
      <div v-if="staffInvitations.length" class="lifecycle__invitation-list">
        <article v-for="item in staffInvitations" :key="item.invitation_ref" class="lifecycle__invitation">
          <div class="lifecycle__invitation-identity"><strong>{{ item.display_name || item.login_name }}</strong><span>编号 {{ item.employee_ref }}，账号 {{ item.login_name }}，邀请编号 {{ item.invitation_ref }}</span></div>
          <div><span>{{ roleLabel(item.role) }}</span><span>{{ item.class_refs.length ? item.class_refs.map(classLabel).join('、') : '未分配班级' }}</span></div>
          <div><strong>{{ invitationStatusLabel(item.status) }}</strong><span>有效期至 {{ item.expires_at }}</span></div>
          <div class="lifecycle__invitation-actions">
            <button v-if="item.status !== 'ACCEPTED'" type="button" class="lifecycle__secondary" :disabled="busy" @click="reissueStaffInvitation(item)">重签凭据</button>
            <button v-else type="button" class="lifecycle__secondary" :disabled="busy" @click="beginStaffRecovery(item)">重置凭据</button>
            <button v-if="item.status === 'ISSUED' || item.status === 'EXPIRED'" type="button" class="lifecycle__secondary" :disabled="busy" @click="revokeStaffInvitation(item)">撤销邀请</button>
          </div>
        </article>
      </div>
      <p v-else-if="frontendApi.listStaffInvitations" class="lifecycle__empty">暂无邀请记录</p>
      <p v-else class="lifecycle__empty">邀请记录服务暂不可用</p>
      <DialogRoot :open="Boolean(staffRecoveryTarget)" @update:open="value => { if (!value) cancelStaffRecovery() }">
        <DialogPortal>
          <DialogOverlay class="lifecycle__modal-backdrop" />
          <DialogContent class="lifecycle__modal">
            <div class="lifecycle__modal-heading"><DialogTitle>重置教职工凭据</DialogTitle><DialogDescription>{{ staffRecoveryTarget?.display_name || staffRecoveryTarget?.login_name }}</DialogDescription></div>
            <label>核验方式<select v-model="staffRecoveryMethod"><option value="IN_PERSON">当面核验</option><option v-if="staffRecoveryTarget?.role === 'teacher'" value="VERIFIED_WORK_CONTACT">已核验的校内联系方式</option></select></label>
            <label>原因代码<input v-model.trim="staffRecoveryReasonCode" required maxlength="80"></label>
            <label class="lifecycle__check"><input v-model="staffRecoveryVerified" type="checkbox">已完成身份核验</label>
            <div class="lifecycle__actions"><DialogClose as-child><button type="button" class="lifecycle__secondary" :disabled="busy">取消</button></DialogClose><button type="button" class="lifecycle__primary" :disabled="busy || !staffRecoveryVerified" @click="issueStaffRecoveryCredential">签发一次性凭据</button></div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </div>

    <div v-else-if="section === 'recovery'" class="lifecycle__body">
      <h3>安全恢复请求</h3><p>教师核验后，由管理员审批</p>
      <div class="lifecycle__form lifecycle__form--inline"><label>学生账号<input v-model="accountSelection" autocomplete="off"></label><label>班级编号<input v-model="accountReason" autocomplete="off"></label><label>申请原因代码<input v-model="recoveryReason" autocomplete="off"></label><button type="button" class="lifecycle__primary" :disabled="busy" @click="createStudentRecoveryRequest">提交学生申请</button></div>
      <label>管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password"></label>
      <div v-if="recoveryTickets.length" class="lifecycle__tickets"><article v-for="ticket in recoveryTickets" :key="ticket.ticket_ref"><div><strong>{{ ticket.display_name }}</strong><span>{{ ticket.username }}，{{ ticket.class_ref || '未关联班级' }}</span><small>状态：{{ ticket.status }}，提交 {{ ticket.created_at }}</small></div><label>处理原因代码<input v-model.trim="recoveryReasons[ticket.ticket_ref]" required></label><div class="lifecycle__actions"><button type="button" class="lifecycle__primary" :disabled="busy" @click="approveRecovery(ticket)">管理员审批</button></div></article></div>
      <p v-else-if="frontendApi.listRecoveryRequests" class="lifecycle__empty">暂无待处理请求</p>
      <p v-else class="lifecycle__empty">恢复请求服务不可用</p>
    </div>

    <div v-else-if="section === 'credentials'" class="lifecycle__body">
      <h3>一次性凭据</h3><p>凭据仅暂存在本页，下载文件经过加密</p>
      <div class="lifecycle__credential-tools">
        <label>账号角色<select v-model="credentialRoleFilter"><option value="all">全部</option><option value="student">学生</option><option value="teacher">普通教师</option></select></label>
        <label>班级筛选<select v-model="credentialClassFilter"><option value="">全部班级</option><option value="__unassigned__">未分配班级</option><option v-for="item in directory?.classes ?? []" :key="item.class_ref" :value="item.class_ref">{{ item.display_name || item.class_ref }}</option></select></label>
        <label>搜索账号<input v-model.trim="credentialSearch" type="search" autocomplete="off" placeholder="姓名或账号编号"></label>
      </div>
      <div class="lifecycle__selection-tools"><span>符合筛选 {{ credentialCandidates.length }} 人，已选择 {{ selectedCredentialCount }} 人</span><button type="button" class="lifecycle__secondary" :disabled="!credentialPageRows.length" @click="selectCurrentCredentialPage">选择当前页</button><button type="button" class="lifecycle__secondary" :disabled="!credentialCandidates.length || credentialCandidates.length > 200" @click="selectCredentialCandidates">选择筛选结果</button><button type="button" class="lifecycle__secondary" :disabled="!credentialUsers.length" @click="credentialUsers = []">清空选择</button></div>
      <p v-if="credentialCandidates.length > 200" class="lifecycle__empty">每批最多签发 200 个账号，请按角色分批操作</p>
      <div v-if="credentialPageRows.length" class="lifecycle__table-wrap"><table><thead><tr><th scope="col">选择</th><th scope="col">姓名</th><th scope="col">角色</th><th scope="col">班级</th><th scope="col">账号编号</th></tr></thead><tbody><tr v-for="item in credentialPageRows" :key="item.user_id"><td><input type="checkbox" :checked="credentialUsers.includes(item.user_id)" :aria-label="`选择${item.display_name || item.user_id}`" @change="toggleCredentialUser(item.user_id, ($event.target as HTMLInputElement).checked)"></td><td>{{ item.display_name || '未填写姓名' }}</td><td>{{ roleLabel(item.role) }}</td><td>{{ item.class_refs?.map(classLabel).join('、') || '未分配' }}</td><td>{{ item.user_id }}</td></tr></tbody></table></div>
      <p v-else class="lifecycle__empty">没有符合条件的账号</p>
      <div class="lifecycle__selection-tools" aria-label="凭据名单分页"><span>第 {{ credentialPage }} / {{ credentialPageCount }} 页</span><button type="button" class="lifecycle__secondary" :disabled="credentialPage <= 1" @click="credentialPage -= 1">上一页</button><button type="button" class="lifecycle__secondary" :disabled="credentialPage >= credentialPageCount" @click="credentialPage += 1">下一页</button></div>
      <label>管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password" required></label>
      <button type="button" class="lifecycle__primary" :disabled="busy || !credentialUsers.length" @click="issueCredentials">发行凭据</button>
      <label v-if="credentialRows.length" class="lifecycle__field">加密口令（至少 12 位）<input v-model="passphrase" type="password" autocomplete="new-password" minlength="12"></label>
      <button v-if="credentialRows.length" type="button" class="lifecycle__primary" :disabled="passphrase.length < 12" @click="downloadEncryptedCredentials">加密下载</button>
      <ul v-if="credentialRows.length" class="lifecycle__credential-records"><li v-for="row in credentialRows" :key="row.user_id">{{ row.display_name }}（{{ roleLabel(row.role ?? 'student') }}，{{ row.login_name }}）<template v-if="row.invitation_ref">，邀请编号 {{ row.invitation_ref }}</template>，凭据已暂存，有效期至 {{ row.expires_at }}</li></ul>
    </div>

    <div v-else class="lifecycle__body">
      <h3>账号状态</h3><p>操作前需重新认证，恢复不会扩大原有权限</p>
      <label class="lifecycle__field">搜索账号<input v-model.trim="statusSearch" type="search" autocomplete="off" placeholder="姓名或账号编号"></label>
      <div v-if="statusPageRows.length" class="lifecycle__table-wrap"><table><thead><tr><th scope="col">选择</th><th scope="col">成员</th><th scope="col">账号</th><th scope="col">角色</th><th scope="col">状态</th></tr></thead><tbody><tr v-for="item in statusPageRows" :key="item.user_id"><td><input type="radio" name="account-status-selection" :checked="statusSelection === item.user_id" :aria-label="`选择账号 ${item.display_name || item.user_id} ${item.user_id}`" @change="statusSelection = item.user_id"></td><td>{{ item.display_name || '未填写姓名' }}</td><td>{{ item.user_id }}</td><td>{{ roleLabel(item.role) }}</td><td>{{ memberStatusLabel(item) }}</td></tr></tbody></table></div>
      <p v-else class="lifecycle__empty">没有匹配账号</p>
      <div class="lifecycle__selection-tools" aria-label="账号列表分页"><span>{{ statusCandidates.length }} 个账号，第 {{ statusPage }} / {{ statusPageCount }} 页</span><button type="button" class="lifecycle__secondary" :disabled="statusPage <= 1" @click="statusPage -= 1">上一页</button><button type="button" class="lifecycle__secondary" :disabled="statusPage >= statusPageCount" @click="statusPage += 1">下一页</button></div>
      <label class="lifecycle__field">原因代码<input v-model.trim="statusReason" required maxlength="80" autocomplete="off"></label><label class="lifecycle__field">管理员当前密码<input v-model="reauthPassword" type="password" autocomplete="current-password" required></label>
      <button type="button" class="lifecycle__primary" :disabled="busy || !statusSelection" @click="changeAccountStatus('DISABLED')">停用账号</button><button type="button" class="lifecycle__secondary" :disabled="busy || !statusSelection" @click="changeAccountStatus('ACTIVE')">恢复账号</button>
    </div>
  </section>
</template>

<style scoped>
.lifecycle { display: grid; gap: 16px; margin-bottom: 24px; padding: 16px; border: .5px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); color: var(--color-text-primary); font-size: 12px; }
.lifecycle__head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }.lifecycle__head h2 { margin: 0; font-size: 24px; line-height: 1.35; font-weight: 600; }
.lifecycle__tabs { display: flex; gap: 5px; overflow-x: auto; border-bottom: .5px solid var(--color-border); }.lifecycle__tabs button { min-height: 38px; padding: 0 12px; border: 0; border-bottom: .5px solid transparent; color: var(--color-text-secondary); background: transparent; font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; }.lifecycle__tabs button[aria-selected="true"] { border-bottom-color: var(--color-primary); color: var(--color-primary); }
.lifecycle__body { display: grid; align-content: start; justify-items: start; gap: 12px; min-width: 0; }.lifecycle__body h3 { margin: 0; font-size: 16px; }.lifecycle__body > p { margin: 0; color: var(--color-text-secondary); font-size: 12px; }.lifecycle__metrics { display: grid; width: 100%; grid-template-columns: repeat(auto-fit,minmax(130px,1fr)); border: .5px solid var(--color-border); }.lifecycle__metrics div { display: grid; gap: 8px; padding: 12px; border-right: .5px solid var(--color-border); border-bottom: .5px solid var(--color-border); }.lifecycle__metrics span { color: var(--color-text-muted); font-size: 12px; }.lifecycle__metrics strong { font-size: 24px; font-weight: 600; }.lifecycle__boundary { padding: 10px 12px; background: var(--color-info-wash); }
.lifecycle__message { margin: 0; padding: 9px 11px; border: .5px solid var(--color-border); color: var(--color-text-secondary); font-size: 12px; }.lifecycle__message--error { border-color: var(--color-critical); color: var(--color-critical); background: var(--color-critical-wash); }.lifecycle__empty { color: var(--color-text-muted); font-size: 12px; }.lifecycle__primary,.lifecycle__secondary { min-height: 36px; padding: 0 12px; border: .5px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-primary); background: var(--color-surface); font: inherit; font-size: 12px; cursor: pointer; }.lifecycle__primary { border-color: var(--color-primary); color: var(--color-text-inverse); background: var(--color-primary); }.lifecycle button:disabled { cursor: not-allowed; opacity: .55; }.lifecycle button:focus-visible,.lifecycle input:focus-visible,.lifecycle select:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.lifecycle__preview-summary { display: flex; flex-wrap: wrap; gap: 16px; color: var(--color-text-secondary); }
.lifecycle__credential-tools,.lifecycle__selection-tools { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; width: 100%; }
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
@media(max-width:700px) { .lifecycle { padding: 12px; }.lifecycle__tabs { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); overflow: visible; }.lifecycle__tabs button { min-width: 0; padding: 0 4px; white-space: normal; }.lifecycle__tickets article,.lifecycle__invitation { grid-template-columns: 1fr; }.lifecycle__head h2 { font-size: 16px; } }
</style>
