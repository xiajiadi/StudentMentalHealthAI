<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import type {
  SchoolAccountImportRow,
  SchoolAccountBatch,
  SchoolAccountPreview,
  SchoolDirectory,
} from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { parseSchoolAccountCsv, type SchoolAccountCsvErrorCode } from '@/utils/school-account-csv'

const directory = ref<SchoolDirectory | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const pending = ref('')
const errorMessage = ref('')
const notice = ref('')
const schoolName = ref('')
const classNames = ref<Record<string, string>>({})
const memberNames = ref<Record<string, string>>({})
const selectedClassRef = ref('')
const csvRows = ref<SchoolAccountImportRow[]>([])
const csvError = ref('')
const preview = ref<SchoolAccountPreview | null>(null)
const previewErrors = ref<Array<{ row_no: number; code: string }>>([])
const importKey = ref('')
const importedBatch = ref<SchoolAccountBatch | null>(null)
const activationUserId = ref('')
const newPassword = ref('')

const apiAvailable = computed(() => Boolean(
  frontendApi.getSchoolAdminDirectory
  && frontendApi.updateSchoolDisplayName
  && frontendApi.updateSchoolClassDisplayName
  && frontendApi.updateSchoolMemberDisplayName
  && frontendApi.previewSchoolAccountImport
  && frontendApi.importSchoolAccounts
  && frontendApi.getSchoolAccountBatch
  && frontendApi.activateSchoolAccount,
))

const pendingAccounts = computed(() => {
  const found = new Map<string, { user_id: string; display_name: string; role: 'student' | 'teacher' }>()
  for (const member of directory.value?.members ?? []) {
    if (member.provisioning_status === 'PENDING_ACTIVATION') {
      found.set(member.user_id, { user_id: member.user_id, display_name: member.display_name ?? '', role: member.role })
    }
  }
  for (const account of importedBatch.value?.accounts ?? []) {
    if (directory.value?.members.some((member) => member.user_id === account.user_id && member.provisioning_status !== 'PENDING_ACTIVATION')) continue
    found.set(account.user_id, { user_id: account.user_id, display_name: account.display_name, role: account.role })
  }
  return [...found.values()]
})

const csvErrorText: Record<SchoolAccountCsvErrorCode, string> = {
  CSV_TOO_LARGE: 'CSV 文件超过 500 KiB。',
  CSV_INVALID_UTF8: 'CSV 文件必须使用有效 UTF-8 编码。',
  CSV_MALFORMED: 'CSV 格式无效，请检查引号和换行。',
  CSV_INVALID_HEADER: 'CSV 列必须严格为 login_name、display_name、role。',
  CSV_TOO_MANY_ROWS: '一次最多导入 100 个账号。',
  CSV_INVALID_ROW: 'CSV 中存在列数不一致或空行。',
  LOGIN_NAME_INVALID: '登录名必须符合 SYNTHETIC_ 加字母、数字或下划线格式。',
  LOGIN_NAME_DUPLICATE: 'CSV 中存在重复登录名（不区分大小写）。',
  DISPLAY_NAME_INVALID: '显示名称不能为空、不能含换行，且不能超过 120 个字符。',
  ROLE_INVALID: '角色只能是 student 或 teacher。',
}

const clearImportState = () => {
  csvRows.value = []
  csvError.value = ''
  preview.value = null
  previewErrors.value = []
  importKey.value = ''
  importedBatch.value = null
  activationUserId.value = ''
  newPassword.value = ''
}

watch(selectedClassRef, () => {
  preview.value = null
  previewErrors.value = []
  importKey.value = ''
})

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  notice.value = ''
  if (!apiAvailable.value || !frontendApi.getSchoolAdminDirectory) {
    state.value = 'error'
    errorMessage.value = '当前运行环境未提供学校目录服务；此页面不会使用演示数据代替服务端结果。'
    return
  }
  try {
    const result = await frontendApi.getSchoolAdminDirectory()
    directory.value = result.data
    schoolName.value = result.data.school.display_name ?? ''
    classNames.value = Object.fromEntries(result.data.classes.map((item) => [item.class_ref, item.display_name ?? '']))
    memberNames.value = Object.fromEntries(result.data.members.map((item) => [item.user_id, item.display_name ?? '']))
    if (!result.data.classes.some((item) => item.class_ref === selectedClassRef.value)) {
      selectedClassRef.value = ''
    }
    state.value = 'ready'
  } catch {
    directory.value = null
    state.value = 'error'
    errorMessage.value = '暂时无法读取当前学校目录。'
  }
}

const saveName = async (kind: 'school' | 'class' | 'member', reference = '') => {
  if (pending.value) return
  const value = kind === 'school' ? schoolName.value : kind === 'class' ? classNames.value[reference] ?? '' : memberNames.value[reference] ?? ''
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > 120) {
    errorMessage.value = '名称必须为 1 至 120 个字符。'
    return
  }
  const operation = kind === 'school'
    ? frontendApi.updateSchoolDisplayName
    : kind === 'class'
      ? frontendApi.updateSchoolClassDisplayName
      : frontendApi.updateSchoolMemberDisplayName
  if (!operation) return
  pending.value = `name-${kind}-${reference}`
  errorMessage.value = ''
  notice.value = ''
  try {
    if (kind === 'school') await frontendApi.updateSchoolDisplayName!(trimmed)
    else if (kind === 'class') await frontendApi.updateSchoolClassDisplayName!(reference, trimmed)
    else await frontendApi.updateSchoolMemberDisplayName!(reference, trimmed)
    await load()
    notice.value = '名称已保存。'
  } catch {
    errorMessage.value = '名称暂时无法保存，请刷新后重试。'
  } finally {
    pending.value = ''
  }
}

const acceptCsvFile = async (event: unknown) => {
  clearImportState()
  csvError.value = ''
  const input = (event as { target?: { files?: ArrayLike<{ size: number; arrayBuffer: () => Promise<ArrayBuffer> }> | null; value?: string } }).target
  if (!input) return
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 500 * 1024) {
    csvError.value = csvErrorText.CSV_TOO_LARGE
    return
  }
  let parsed: ReturnType<typeof parseSchoolAccountCsv>
  try {
    parsed = parseSchoolAccountCsv(new Uint8Array(await file.arrayBuffer()))
  } catch {
    csvError.value = csvErrorText.CSV_INVALID_UTF8
    return
  }
  if (!parsed.ok) {
    csvError.value = csvErrorText[parsed.code]
    return
  }
  csvRows.value = parsed.rows
  notice.value = `CSV 格式有效，共 ${parsed.rows.length} 行；预览后才能导入。`
}

const previewImport = async () => {
  if (pending.value || !csvRows.value.length || !frontendApi.previewSchoolAccountImport) return
  pending.value = 'preview'
  errorMessage.value = ''
  notice.value = ''
  preview.value = null
  previewErrors.value = []
  importKey.value = ''
  try {
    const result = await frontendApi.previewSchoolAccountImport(selectedClassRef.value || null, csvRows.value)
    preview.value = result.data
    previewErrors.value = result.data.errors
    notice.value = result.data.valid ? `服务端验证通过，共 ${result.data.row_count} 行。` : '服务端验证未通过，请根据行号和错误代码修改 CSV。'
  } catch {
    errorMessage.value = '服务端预览失败，尚未导入任何账号。'
  } finally {
    pending.value = ''
  }
}

const importAccounts = async () => {
  if (pending.value || !preview.value?.valid || preview.value.errors.length || !csvRows.value.length || !frontendApi.importSchoolAccounts) return
  if (!importKey.value) {
    const randomId = globalThis.crypto?.randomUUID?.()
    if (!randomId) {
      errorMessage.value = '当前浏览器无法生成安全的导入请求编号，请更新浏览器后重试。'
      return
    }
    importKey.value = `school-account-import-${randomId}`
  }
  pending.value = 'import'
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await frontendApi.importSchoolAccounts(selectedClassRef.value || null, csvRows.value, importKey.value)
    importedBatch.value = result.data
    csvRows.value = []
    preview.value = null
    previewErrors.value = []
    importKey.value = ''
    await load()
    notice.value = `服务端已一次性创建 ${result.data.created_count} 个待激活账号。`
  } catch {
    errorMessage.value = '导入结果尚未确认。可重试以复用同一请求编号；服务端会按整批幂等处理。'
  } finally {
    pending.value = ''
  }
}

const chooseActivation = (userId: string) => {
  activationUserId.value = userId
  newPassword.value = ''
  errorMessage.value = ''
}

const activateAccount = async () => {
  const account = pendingAccounts.value.find((item) => item.user_id === activationUserId.value)
  if (pending.value || !account || !newPassword.value || !frontendApi.activateSchoolAccount) return
  const password = newPassword.value
  pending.value = `activate-${account.user_id}`
  errorMessage.value = ''
  notice.value = ''
  try {
    await frontendApi.activateSchoolAccount(account.user_id, password)
    newPassword.value = ''
    importedBatch.value = null
    activationUserId.value = ''
    await load()
    notice.value = `账号 ${account.display_name || account.user_id.slice(-6)} 已激活。`
  } catch {
    errorMessage.value = '账号激活未完成。请确认密码要求后重新输入，再提交一次。'
  } finally {
    newPassword.value = ''
    pending.value = ''
  }
}

const shortRef = (value: string) => value.slice(-6)
const roleLabel = (role: 'student' | 'teacher') => role === 'student' ? '学生' : '教师'
const provisioningLabel = (status: string | null) => status === 'PENDING_ACTIVATION' ? '待激活' : status === 'ACTIVE' ? '可用' : '状态待确认'

onMounted(() => { void load() })
onBeforeUnmount(() => {
  newPassword.value = ''
  clearImportState()
})
</script>

<template>
  <section class="school-directory" aria-labelledby="school-directory-title">
    <header class="school-directory__heading">
      <div><span class="school-directory__eyebrow">学校目录</span><h2 id="school-directory-title">学校、班级与账号</h2><p>此处仅管理当前学校的显示名称和合成账号。</p></div>
      <AppButton variant="secondary" size="sm" :disabled="state === 'loading' || Boolean(pending)" @click="load">刷新目录</AppButton>
    </header>
    <AppStatusCallout v-if="errorMessage" tone="critical" title="操作未完成" :body="errorMessage" role="alert" />
    <AppStatusCallout v-if="notice" tone="info" title="目录状态" :body="notice" role="status" />
    <AppCard v-if="state === 'loading'" class="directory-panel" aria-busy="true"><p>正在读取当前学校目录…</p></AppCard>
    <AppCard v-else-if="state === 'error'" class="directory-panel" role="status"><p>{{ errorMessage }}</p></AppCard>
    <div v-else-if="directory" class="school-directory__grid">
      <AppCard class="directory-panel">
        <div class="directory-panel__heading"><h3>学校名称</h3><span>{{ directory.school.school_ref }}</span></div>
        <div class="directory-name-row">
          <label for="school-display-name">显示名称</label>
          <input id="school-display-name" v-model="schoolName" maxlength="120" autocomplete="off">
          <AppButton variant="secondary" size="sm" :disabled="Boolean(pending)" :loading="pending === 'name-school-'" @click="saveName('school')">保存</AppButton>
        </div>
      </AppCard>

      <AppCard class="directory-panel">
        <div class="directory-panel__heading"><h3>班级名称</h3><span>{{ directory.classes.length }} 个班级</span></div>
        <div v-if="!directory.classes.length" class="directory-empty">当前学校没有班级。</div>
        <div v-for="item in directory.classes" :key="item.class_ref" class="directory-name-row">
          <label :for="`class-name-${item.class_ref}`">班级 {{ shortRef(item.class_ref) }}</label>
          <input :id="`class-name-${item.class_ref}`" v-model="classNames[item.class_ref]" maxlength="120" autocomplete="off">
          <AppButton variant="secondary" size="sm" :disabled="Boolean(pending)" :loading="pending === `name-class-${item.class_ref}`" @click="saveName('class', item.class_ref)">保存</AppButton>
        </div>
      </AppCard>

      <AppCard class="directory-panel directory-panel--wide">
        <div class="directory-panel__heading"><h3>同校账号名称</h3><span>{{ directory.members.length }} 个账号</span></div>
        <div v-if="!directory.members.length" class="directory-empty">当前学校没有账号。</div>
        <div v-for="member in directory.members" :key="member.user_id" class="directory-name-row">
          <label :for="`member-name-${member.user_id}`">{{ roleLabel(member.role) }} · {{ shortRef(member.user_id) }}</label>
          <input :id="`member-name-${member.user_id}`" v-model="memberNames[member.user_id]" maxlength="120" autocomplete="off">
          <AppButton variant="secondary" size="sm" :disabled="Boolean(pending)" :loading="pending === `name-member-${member.user_id}`" @click="saveName('member', member.user_id)">保存</AppButton>
        </div>
      </AppCard>

      <AppCard class="directory-panel directory-panel--wide">
        <div class="directory-panel__heading"><h3>批量创建合成账号</h3><span>CSV · 最多 100 行</span></div>
        <p class="directory-hint">文件列必须为 login_name、display_name、role。密码列会被拒绝；账号导入后需分别设置登录密码。</p>
        <label class="directory-field" for="school-account-class">可选班级</label>
        <select id="school-account-class" v-model="selectedClassRef" :disabled="Boolean(pending)">
          <option value="">不关联班级</option>
          <option v-for="item in directory.classes" :key="item.class_ref" :value="item.class_ref">{{ item.display_name?.trim() || `班级 ${shortRef(item.class_ref)}` }}</option>
        </select>
        <label class="directory-field" for="school-account-csv">CSV 文件（最大 500 KiB）</label>
        <input id="school-account-csv" type="file" accept=".csv,text/csv" :disabled="Boolean(pending)" @change="acceptCsvFile">
        <p v-if="csvError" class="directory-error" role="alert">{{ csvError }}</p>
        <p v-if="csvRows.length" class="directory-hint">已在本页内存中读取 {{ csvRows.length }} 行。预览不会创建账号或显示登录名。</p>
        <div v-if="csvRows.length" class="directory-actions">
          <AppButton variant="secondary" :disabled="Boolean(pending)" :loading="pending === 'preview'" @click="previewImport">服务端预览</AppButton>
          <AppButton :disabled="Boolean(pending) || !preview?.valid || previewErrors.length > 0" :loading="pending === 'import'" @click="importAccounts">整批导入</AppButton>
        </div>
        <div v-if="preview" class="directory-preview" role="status">
          <strong>{{ preview.valid && previewErrors.length === 0 ? `通过 ${preview.row_count} 行` : `检查 ${preview.row_count} 行，${previewErrors.length} 个问题` }}</strong>
          <ul v-if="previewErrors.length"><li v-for="item in previewErrors" :key="`${item.row_no}-${item.code}`">第 {{ item.row_no }} 行 · {{ item.code }}</li></ul>
        </div>
      </AppCard>

      <AppCard v-if="pendingAccounts.length" class="directory-panel directory-panel--wide">
        <div class="directory-panel__heading"><h3>待激活账号</h3><span>{{ pendingAccounts.length }} 个</span></div>
        <div v-for="account in pendingAccounts" :key="account.user_id" class="directory-account-row">
          <div><strong>{{ account.display_name || `账号 ${shortRef(account.user_id)}` }}</strong><span>{{ roleLabel(account.role) }} · {{ provisioningLabel('PENDING_ACTIVATION') }}</span></div>
          <AppButton variant="secondary" size="sm" :disabled="Boolean(pending)" @click="chooseActivation(account.user_id)">设置登录密码</AppButton>
        </div>
        <form v-if="activationUserId" class="directory-activation" @submit.prevent="activateAccount">
          <label for="school-account-new-password">新登录密码</label>
          <input id="school-account-new-password" v-model="newPassword" type="password" autocomplete="off" required>
          <p>密码只发送给服务端验证并设置，不会显示在账号列表中。</p>
          <AppButton type="submit" :disabled="Boolean(pending) || !newPassword" :loading="pending.startsWith('activate-')">激活账号</AppButton>
        </form>
      </AppCard>
    </div>
  </section>
</template>

<style scoped>
.school-directory { display: grid; gap: 13px; margin-bottom: 16px; }
.school-directory__heading,.directory-panel__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.school-directory__heading h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 19px; }
.school-directory__heading p,.directory-hint,.directory-activation p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.6; }
.school-directory__eyebrow { color: #54809c; font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.school-directory__grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 13px; }
.directory-panel { display: grid; align-content: start; gap: 12px; min-width: 0; padding: 17px; }
.directory-panel--wide { grid-column: 1 / -1; }
.directory-panel__heading h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.directory-panel__heading span { color: var(--color-text-muted); font-size: 10px; }
.directory-name-row { display: grid; grid-template-columns: minmax(110px,.5fr) minmax(0,1fr) auto; align-items: center; gap: 8px; }
.directory-name-row label,.directory-field,.directory-activation label { color: var(--color-text-secondary); font-size: 11px; font-weight: 650; }
.directory-name-row input,.directory-panel select,.directory-panel input[type="file"],.directory-activation input { width: 100%; min-width: 0; min-height: 38px; padding: 7px 9px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 12px; }
.directory-name-row input:focus-visible,.directory-panel select:focus-visible,.directory-panel input[type="file"]:focus-visible,.directory-activation input:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.directory-hint { margin-top: -5px; }
.directory-field { margin-bottom: -7px; }
.directory-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.directory-preview { padding: 10px 12px; border-radius: 8px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 11px; }
.directory-preview ul { display: grid; gap: 4px; margin: 8px 0 0; padding-left: 18px; }
.directory-error { margin: 0; color: #ac392d; font-size: 11px; }
.directory-empty { color: var(--color-text-muted); font-size: 11px; }
.directory-account-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; border-top: 1px solid var(--color-border); }
.directory-account-row > div { display: grid; gap: 3px; min-width: 0; }
.directory-account-row strong { color: var(--color-text-primary); font-size: 12px; }
.directory-account-row span { color: var(--color-text-muted); font-size: 10px; }
.directory-activation { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1.5fr) auto; align-items: center; gap: 9px; padding-top: 11px; border-top: 1px solid var(--color-border); }
.directory-activation p { grid-column: 1 / -1; }
@media(max-width:700px) { .school-directory__grid { grid-template-columns: 1fr; }.directory-panel--wide { grid-column: auto; }.directory-name-row { grid-template-columns: minmax(0,1fr) auto; }.directory-name-row label { grid-column: 1 / -1; }.directory-activation { grid-template-columns: 1fr; }.directory-activation p { grid-column: auto; } }
</style>
