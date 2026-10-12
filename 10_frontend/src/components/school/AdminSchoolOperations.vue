<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleHelp, RotateCcw, UsersRound } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import AdminProfessionalAssignments from '@/components/school/AdminProfessionalAssignments.vue'
import type { SchoolClass, SchoolMember, SchoolTask, SchoolTaskEnrollment } from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { schoolCatActivations, type CatActivationMetadata } from '@/services/school-cat-activations'

const props = withDefaults(defineProps<{ mode?: 'all' | 'members' }>(), { mode: 'all' })
type LoadState = 'loading' | 'ready' | 'error'

const state = ref<LoadState>('loading')
const classes = ref<SchoolClass[]>([])
const students = ref<SchoolMember[]>([])
const teachers = ref<SchoolMember[]>([])
const tasks = ref<SchoolTask[]>([])
const selectedClassRef = ref('')
const selectedStudent = ref('')
const selectedTeacher = ref('')
const opensAt = ref('')
const dueAt = ref('')
const taskBindingMode = ref<'FIXTURE' | 'SAVED_VERSION'>('FIXTURE')
const selectedActivationRef = ref('')
const eligibleActivations = ref<CatActivationMetadata[]>([])
const activationState = ref<LoadState>('ready')
const activationError = ref('')
const activationHasMore = ref(false)
const activationSkip = ref(0)
const enrollmentsByTask = ref<Record<string, SchoolTaskEnrollment[]>>({})
const enrollmentTask = ref('')
const pending = ref('')
const errorMessage = ref('')
const notice = ref('')
const taskState = ref<LoadState>('ready')
const taskError = ref('')
const taskRequestGeneration = ref(0)
const enrollmentLoadingTask = ref('')
let activationRequestGeneration = 0
let disposed = false

const activeClass = computed(() => classes.value.find((item) => item.class_ref === selectedClassRef.value) ?? null)
const methodsAvailable = computed(() => Boolean(
  frontendApi.listSchoolClasses && frontendApi.listSchoolMembers && frontendApi.createSchoolClass &&
  frontendApi.assignSchoolStudent && frontendApi.assignSchoolTeacher && frontendApi.listSchoolTasks &&
  frontendApi.publishSchoolTask && frontendApi.listSchoolTaskEnrollments && frontendApi.revokeSchoolTaskEnrollment,
))

const requestMessage = (error: unknown, fallback: string) => {
  const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
  if (/auth_session_expired|auth_session_revoked/.test(code)) return '登录状态已过期，请重新登录后再试。'
  if (code === 'forbidden' || code === '403') return '当前账号暂时没有此项操作权限。'
  if (code === 'resource_not_found' || code === 'not_found' || code === '404') return '所选内容已不可用，请刷新后重试。'
  if (code === 'workflow_conflict' || code === 'conflict' || code === '409') return '数据已发生变化，请刷新后重试。'
  return fallback
}

const shortRef = (value: string) => value.slice(-6)
const classLabel = (value: string) => `班级 ${shortRef(value)}`
const taskLabel = (value: string) => `任务 ${shortRef(value)}`
const statusLabel = (status: string) => ({
  ACTIVE: '可用', active: '可用',
  PUBLISHED: '已发布', published: '已发布',
  REVOKED: '已撤销', revoked: '已撤销',
  COMPLETED: '已完成', completed: '已完成',
}[status] ?? '状态待确认')
const formatDate = (value: string | null) => {
  if (!value) return '未设置截止时间'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间待确认' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const loadTasks = async () => {
  const generation = ++taskRequestGeneration.value
  if (!selectedClassRef.value || !frontendApi.listSchoolTasks) {
    tasks.value = []
    taskState.value = 'ready'
    taskError.value = ''
    return
  }
  taskState.value = 'loading'
  taskError.value = ''
  try {
    const result = await frontendApi.listSchoolTasks(selectedClassRef.value)
    if (generation !== taskRequestGeneration.value) return
    tasks.value = result.data
    taskState.value = 'ready'
  } catch (error) {
    if (generation !== taskRequestGeneration.value) return
    tasks.value = []
    taskState.value = 'error'
    taskError.value = requestMessage(error, '暂时无法读取这个班级的任务。')
  }
}

const loadEligibleActivations = async (reset = true) => {
  if (taskBindingMode.value !== 'SAVED_VERSION') return
  const generation = ++activationRequestGeneration
  const skip = reset ? 0 : activationSkip.value
  if (reset) {
    eligibleActivations.value = []
    activationSkip.value = 0
    activationHasMore.value = false
    selectedActivationRef.value = ''
  }
  activationState.value = 'loading'
  activationError.value = ''
  try {
    const page = await schoolCatActivations.list({ skip, limit: 30 })
    if (disposed || generation !== activationRequestGeneration || taskBindingMode.value !== 'SAVED_VERSION') return
    const items = reset ? [] : eligibleActivations.value
    const byRef = new Map(items.map((item) => [item.activation_ref, item]))
    for (const item of page.items) byRef.set(item.activation_ref, item)
    eligibleActivations.value = [...byRef.values()]
    activationSkip.value = skip + page.items.length
    activationHasMore.value = page.has_more
    if (!eligibleActivations.value.some((item) => item.activation_ref === selectedActivationRef.value)) {
      selectedActivationRef.value = ''
    }
    activationState.value = 'ready'
  } catch (cause) {
    if (disposed || generation !== activationRequestGeneration) return
    eligibleActivations.value = []
    selectedActivationRef.value = ''
    activationHasMore.value = false
    activationState.value = 'error'
    activationError.value = requestMessage(cause, '暂时无法读取可用于新任务的合成版本。任务不会按其他版本发布。')
  }
}

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  notice.value = ''
  if (!methodsAvailable.value) {
    state.value = 'error'
    errorMessage.value = '当前运行环境未提供学校组织服务。此页面不会用演示数据代替服务端结果。'
    return
  }
  try {
    const [classResult, studentResult, teacherResult] = await Promise.all([
      frontendApi.listSchoolClasses!(),
      frontendApi.listSchoolMembers!('student'),
      frontendApi.listSchoolMembers!('teacher'),
    ])
    classes.value = classResult.data
    students.value = studentResult.data
    teachers.value = teacherResult.data
    if (!classes.value.some((item) => item.class_ref === selectedClassRef.value)) {
      selectedClassRef.value = classes.value[0]?.class_ref ?? ''
    }
    state.value = 'ready'
    await loadTasks()
  } catch (error) {
    classes.value = []
    students.value = []
    teachers.value = []
    tasks.value = []
    state.value = 'error'
    errorMessage.value = requestMessage(error, '暂时无法读取学校组织信息。')
  }
}

const createClass = async () => {
  if (pending.value || !frontendApi.createSchoolClass) return
  const randomId = globalThis.crypto?.randomUUID?.()
  if (!randomId) {
    errorMessage.value = '当前浏览器无法创建安全的班级编号，请更新浏览器后重试。'
    return
  }
  const value = `CLASS_${randomId.replaceAll('-', '')}`
  pending.value = 'create-class'
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await frontendApi.createSchoolClass(value)
    selectedClassRef.value = result.data.class_ref
    const successMessage = `${classLabel(result.data.class_ref)}已创建。`
    await load()
    notice.value = successMessage
  } catch (error) {
    errorMessage.value = requestMessage(error, '暂时无法创建班级。')
  } finally { pending.value = '' }
}

const assignMember = async (role: 'student' | 'teacher') => {
  if (!selectedClassRef.value || pending.value) return
  const member = role === 'student' ? selectedStudent.value : selectedTeacher.value
  if (!member) {
    errorMessage.value = role === 'student' ? '请先选择一名学生。' : '请先选择一名教师。'
    return
  }
  const operation = role === 'student' ? frontendApi.assignSchoolStudent : frontendApi.assignSchoolTeacher
  if (!operation) return
  pending.value = `assign-${role}`
  errorMessage.value = ''
  notice.value = ''
  try {
    await operation.call(frontendApi, selectedClassRef.value, member)
    if (role === 'student') selectedStudent.value = ''
    else selectedTeacher.value = ''
    const successMessage = role === 'student' ? '学生已加入班级。' : '教师已分配到班级。'
    await load()
    notice.value = successMessage
  } catch (error) {
    errorMessage.value = requestMessage(error, role === 'student' ? '暂时无法分配学生。' : '暂时无法分配教师。')
  } finally { pending.value = '' }
}

const publishTask = async () => {
  if (!selectedClassRef.value || pending.value || !frontendApi.publishSchoolTask) return
  const activation = taskBindingMode.value === 'SAVED_VERSION'
    ? eligibleActivations.value.find((item) => item.activation_ref === selectedActivationRef.value && item.status === 'ACTIVE')
    : undefined
  if (taskBindingMode.value === 'SAVED_VERSION'
    && (activationState.value !== 'ready' || !activation)) {
    errorMessage.value = activationState.value === 'error'
      ? '可用版本列表尚未读取成功。请重新读取；任务不会按默认方案发布。'
      : '请选择服务端列出的可用合成版本。'
    return
  }
  if (!opensAt.value) {
    errorMessage.value = '请设置开放时间。'
    return
  }
  const opens = new Date(opensAt.value)
  const due = dueAt.value ? new Date(dueAt.value) : null
  if (Number.isNaN(opens.getTime()) || (due && (Number.isNaN(due.getTime()) || due < opens))) {
    errorMessage.value = '截止时间不能早于开放时间。'
    return
  }
  pending.value = 'publish-task'
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = activation
      ? await frontendApi.publishSchoolTask(
        selectedClassRef.value, opens.toISOString(), due?.toISOString() ?? null, activation.activation_ref,
      )
      : await frontendApi.publishSchoolTask(
        selectedClassRef.value, opens.toISOString(), due?.toISOString() ?? null,
      )
    opensAt.value = ''
    dueAt.value = ''
    const selectedPlan = result.data.plan_name && result.data.plan_version_number
      ? `；绑定 ${result.data.plan_name} v${result.data.plan_version_number}`
      : ''
    notice.value = `${taskLabel(result.data.task_ref)}已发布，并按发布时班级名册建立报名记录${selectedPlan}。`
    await loadTasks()
    await loadClassesOnly()
  } catch (error) {
    errorMessage.value = requestMessage(error, '任务暂时无法发布，没有显示为成功。')
  } finally { pending.value = '' }
}

const loadClassesOnly = async () => {
  if (!frontendApi.listSchoolClasses) return
  try { classes.value = (await frontendApi.listSchoolClasses()).data } catch { /* keep current verified list; action result remains visible */ }
}

const toggleEnrollments = async (taskRef: string) => {
  if (enrollmentTask.value === taskRef) {
    enrollmentTask.value = ''
    enrollmentLoadingTask.value = ''
    return
  }
  if (!frontendApi.listSchoolTaskEnrollments) return
  enrollmentTask.value = taskRef
  enrollmentLoadingTask.value = taskRef
  errorMessage.value = ''
  try {
    const result = await frontendApi.listSchoolTaskEnrollments(taskRef)
    enrollmentsByTask.value = { ...enrollmentsByTask.value, [taskRef]: result.data }
  } catch (error) {
    enrollmentTask.value = ''
    errorMessage.value = requestMessage(error, '暂时无法读取报名情况。')
  } finally {
    if (enrollmentLoadingTask.value === taskRef) enrollmentLoadingTask.value = ''
  }
}

const revokeEnrollment = async (taskRef: string, enrollmentRef: string) => {
  const key = `revoke-${enrollmentRef}`
  if (pending.value || !frontendApi.revokeSchoolTaskEnrollment) return
  pending.value = key
  errorMessage.value = ''
  notice.value = ''
  try {
    await frontendApi.revokeSchoolTaskEnrollment(taskRef, enrollmentRef)
    notice.value = '该报名已撤销，学生不能继续访问对应任务。'
    try {
      const updated = await frontendApi.listSchoolTaskEnrollments?.(taskRef)
      if (updated) enrollmentsByTask.value = { ...enrollmentsByTask.value, [taskRef]: updated.data }
    } catch {
      notice.value = '撤销已成功，但最新报名列表暂时无法刷新。'
    }
    await loadTasks()
    await loadClassesOnly()
  } catch (error) {
    errorMessage.value = requestMessage(error, '报名暂时无法撤销。')
  } finally { pending.value = '' }
}

watch(taskBindingMode, (mode) => {
  activationRequestGeneration += 1
  eligibleActivations.value = []
  selectedActivationRef.value = ''
  activationError.value = ''
  activationHasMore.value = false
  activationSkip.value = 0
  activationState.value = mode === 'SAVED_VERSION' ? 'loading' : 'ready'
  if (mode === 'SAVED_VERSION') void loadEligibleActivations(true)
})
watch(selectedClassRef, () => {
  enrollmentTask.value = ''
  void loadTasks()
  if (taskBindingMode.value === 'SAVED_VERSION') void loadEligibleActivations(true)
})
onMounted(() => { void load() })
onBeforeUnmount(() => { disposed = true; activationRequestGeneration += 1 })
</script>

<template>
  <section class="school-operations" aria-labelledby="school-operations-title">
    <header class="school-operations__heading">
      <div><span class="school-operations__eyebrow">学校组织</span><h2 id="school-operations-title">班级与任务</h2><p>组织调整只影响所选学校内的合成账号和任务。</p></div>
      <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="load"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton>
    </header>

    <AppStatusCallout v-if="errorMessage && state !== 'error'" tone="critical" title="操作未完成" :body="errorMessage" role="alert" />
    <AppStatusCallout v-if="notice" tone="info" title="已收到服务端确认" :body="notice" role="status" />

    <AppCard v-if="state === 'loading'" class="school-panel" aria-busy="true"><p>正在读取班级和同校人员…</p></AppCard>
    <AppCard v-else-if="state === 'error'" class="school-panel school-panel--empty" role="status"><CircleHelp :size="19" aria-hidden="true" /><p>{{ errorMessage }}</p></AppCard>
    <template v-else>
      <div class="school-grid">
        <AppCard class="school-panel">
          <div class="school-panel__heading"><UsersRound :size="18" aria-hidden="true" /><div><h3>班级</h3><p>创建班级并查看当前分配人数。</p></div></div>
          <p class="school-form__hint">创建后会显示班级短号，完整编号由系统管理。</p>
          <AppButton class="school-create-class" size="sm" :loading="pending === 'create-class'" @click="createClass">创建班级</AppButton>
          <label class="school-form__label" for="school-class-select">当前班级</label>
          <select id="school-class-select" v-model="selectedClassRef" :disabled="!classes.length || Boolean(pending)">
            <option value="" disabled>请选择班级</option>
            <option v-for="item in classes" :key="item.class_ref" :value="item.class_ref">{{ item.display_name?.trim() || classLabel(item.class_ref) }} · 学生 {{ item.active_student_count }} · 教师 {{ item.active_teacher_count }}</option>
          </select>
          <p v-if="!classes.length" class="school-empty">当前没有可用班级。创建班级后，可分配同校人员并发布任务。</p>
        </AppCard>

        <AppCard class="school-panel">
          <div class="school-panel__heading"><UsersRound :size="18" aria-hidden="true" /><div><h3>人员分配</h3><p>选择服务端返回的同校在用账号，不输入学校或角色范围。</p></div></div>
          <div class="school-form">
            <label for="school-student-select">学生</label>
            <div class="school-form__row"><select id="school-student-select" v-model="selectedStudent" :disabled="!activeClass || Boolean(pending)"><option value="">选择学生</option><option v-for="member in students" :key="member.user_id" :value="member.user_id">{{ member.display_name?.trim() || `学生账号 ${shortRef(member.user_id)}` }}</option></select><AppButton variant="secondary" size="sm" :disabled="!activeClass || !selectedStudent" :loading="pending === 'assign-student'" @click="assignMember('student')">分配</AppButton></div>
            <p v-if="!students.length" class="school-form__hint">没有可分配的同校学生账号。</p>
            <label for="school-teacher-select">教师</label>
            <div class="school-form__row"><select id="school-teacher-select" v-model="selectedTeacher" :disabled="!activeClass || Boolean(pending)"><option value="">选择教师</option><option v-for="member in teachers" :key="member.user_id" :value="member.user_id">{{ member.display_name?.trim() || `教师账号 ${shortRef(member.user_id)}` }}</option></select><AppButton variant="secondary" size="sm" :disabled="!activeClass || !selectedTeacher" :loading="pending === 'assign-teacher'" @click="assignMember('teacher')">分配</AppButton></div>
            <p v-if="!teachers.length" class="school-form__hint">没有可分配的同校教师账号。</p>
          </div>
        </AppCard>
      </div>

      <AppCard v-if="props.mode === 'all'" class="school-panel school-panel--tasks">
        <div class="school-panel__heading"><div><h3>测评任务</h3><p>发布时会按当时的班级名册建立报名记录。</p></div></div>
        <form class="school-form school-form--dates" @submit.prevent="publishTask">
          <label for="school-task-opens">开放时间</label><input id="school-task-opens" v-model="opensAt" type="datetime-local" :disabled="!activeClass || Boolean(pending)" required>
          <label for="school-task-due">截止时间（可选）</label><input id="school-task-due" v-model="dueAt" type="datetime-local" :disabled="!activeClass || Boolean(pending)">
          <fieldset class="school-task-mode" :disabled="Boolean(pending)">
            <legend>任务题目来源</legend>
            <label><input id="school-task-mode-fixture" v-model="taskBindingMode" type="radio" value="FIXTURE">固定工程模板</label>
            <label><input id="school-task-mode-saved" v-model="taskBindingMode" type="radio" value="SAVED_VERSION">已启用的合成版本</label>
          </fieldset>
          <div v-if="taskBindingMode === 'SAVED_VERSION'" class="school-task-activation">
            <p class="school-form__hint">只列出当前学校可用于新任务的版本。此选择不会向管理员显示题目正文或配置参数。</p>
            <div v-if="activationState === 'loading'" class="school-empty" role="status" aria-busy="true">正在读取可用版本…</div>
            <div v-else-if="activationState === 'error'" class="school-empty school-empty--error" role="alert">{{ activationError }}<AppButton variant="secondary" size="sm" type="button" @click="loadEligibleActivations(true)">重新读取</AppButton></div>
            <template v-else>
              <label for="school-task-activation">已启用版本</label>
              <select id="school-task-activation" v-model="selectedActivationRef" :disabled="!activeClass || Boolean(pending) || activationState !== 'ready' || !eligibleActivations.length">
                <option value="">请选择版本</option>
                <option v-for="activation in eligibleActivations" :key="activation.activation_ref" :value="activation.activation_ref">{{ activation.plan_name }} v{{ activation.plan_version_number }} · {{ activation.bank_name }} v{{ activation.bank_version_number }}</option>
              </select>
              <p v-if="activationState === 'ready' && !eligibleActivations.length" class="school-form__hint">当前没有可用于新任务的启用版本。</p>
              <AppButton v-if="activationHasMore" variant="secondary" size="sm" type="button" :disabled="activationState === 'loading'" @click="loadEligibleActivations(false)">读取更多版本</AppButton>
            </template>
          </div>
          <AppButton type="submit" :disabled="!activeClass || (taskBindingMode === 'SAVED_VERSION' && (activationState !== 'ready' || !selectedActivationRef))" :loading="pending === 'publish-task'">发布任务</AppButton>
        </form>
        <div v-if="taskState === 'loading'" class="school-empty" aria-busy="true">正在读取当前班级任务…</div>
        <div v-else-if="taskState === 'error'" class="school-empty school-empty--error" role="alert">{{ taskError }}<AppButton variant="secondary" size="sm" @click="loadTasks">重新读取</AppButton></div>
        <div v-else-if="tasks.length" class="school-task-list">
          <article v-for="task in tasks" :key="task.task_ref" class="school-task">
            <div><strong>{{ taskLabel(task.task_ref) }}</strong><span class="school-task__status">{{ statusLabel(task.status) }}</span><p>{{ formatDate(task.opens_at) }} 至 {{ formatDate(task.due_at) }}</p><small>报名 {{ task.published_enrollment_count }} · 有效 {{ task.active_enrollment_count }} · 已撤销 {{ task.revoked_enrollment_count }}</small></div>
            <AppButton variant="secondary" size="sm" @click="toggleEnrollments(task.task_ref)">{{ enrollmentTask === task.task_ref ? '收起报名' : '管理报名' }}</AppButton>
            <div v-if="enrollmentTask === task.task_ref" class="school-task__enrollments">
              <div v-if="enrollmentLoadingTask === task.task_ref" class="school-form__hint" aria-busy="true">正在读取报名情况…</div>
              <div v-else-if="!enrollmentsByTask[task.task_ref]?.length" class="school-form__hint">当前没有可管理的报名记录。</div>
              <template v-else><div v-for="enrollment in enrollmentsByTask[task.task_ref]" :key="enrollment.enrollment_ref" class="school-task__enrollment"><span>报名 {{ shortRef(enrollment.enrollment_ref) }} · {{ statusLabel(enrollment.status) }}</span><AppButton v-if="!['revoked','REVOKED'].includes(enrollment.status)" variant="quiet" size="sm" :disabled="Boolean(pending)" :loading="pending === `revoke-${enrollment.enrollment_ref}`" @click="revokeEnrollment(task.task_ref, enrollment.enrollment_ref)">撤销</AppButton></div></template>
            </div>
          </article>
        </div>
        <div v-else class="school-empty">{{ activeClass ? '这个班级目前没有已发布任务。' : '先创建或选择一个班级。' }}</div>
        <AdminProfessionalAssignments v-if="taskState === 'ready'" :tasks="tasks" />
      </AppCard>
    </template>
  </section>
</template>

<style scoped>
.school-operations { display: grid; gap: 14px; margin-top: 16px; }
.school-operations__heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.school-operations__heading h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 19px; }
.school-operations__heading p,.school-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.school-operations__eyebrow { color: #54809c; font-size: 10px; font-weight: 800; letter-spacing: .08em; }
.school-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 13px; }
.school-panel { display: grid; align-content: start; gap: 14px; min-width: 0; padding: 18px; }
.school-panel__heading { display: flex; align-items: flex-start; gap: 10px; color: #388576; }
.school-panel__heading h3 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 15px; }
.school-panel__heading > div { min-width: 0; }
.school-form { display: grid; gap: 8px; }
.school-form label,.school-form__label { color: var(--color-text-secondary); font-size: 12px; font-weight: 650; }
.school-form input,.school-form select,.school-panel > select { width: 100%; min-width: 0; min-height: 40px; padding: 8px 10px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 13px; }
.school-form input:focus-visible,.school-form select:focus-visible,.school-panel > select:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.school-create-class { justify-self: start; }
.school-form__row { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px; }
.school-form--dates { grid-template-columns: repeat(2,minmax(0,1fr)); align-items: end; padding: 14px; border-radius: 10px; background: #f8fafb; }
.school-form--dates label { align-self: end; }
.school-form--dates button { grid-column: 1 / -1; justify-self: start; }
.school-task-mode,.school-task-activation { display: grid; grid-column: 1 / -1; gap: 8px; min-width: 0; margin: 0; padding: 10px; border: 1px solid var(--color-border); border-radius: 9px; background: #fff; }
.school-task-mode legend { padding: 0 4px; color: var(--color-text-secondary); font-size: 12px; font-weight: 650; }
.school-task-mode label { display: flex; align-items: center; gap: 7px; color: var(--color-text-secondary); font-size: 12px; }
.school-task-mode input { width: auto; min-height: 0; margin: 0; accent-color: #388576; }
.school-task-activation { background: #fcfdfc; }
.school-task-activation > label { margin-top: 2px; }
.school-form__hint { margin: 0; color: var(--color-text-muted); font-size: 11px; }
.school-empty { display: flex; align-items: center; gap: 8px; min-height: 50px; padding: 11px; border-radius: 9px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 12px; line-height: 1.55; }
.school-empty--error { color: #8f651d; background: #fcf7eb; }
.school-task-list { display: grid; gap: 9px; }
.school-task { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: start; gap: 10px; padding: 13px; border: 1px solid #eceef1; border-radius: 10px; }
.school-task strong { color: var(--color-text-primary); font-size: 13px; }
.school-task__status { display: inline-block; margin-left: 8px; padding: 3px 7px; border-radius: 999px; color: #287765; background: #e8f4ef; font-size: 10px; }
.school-task p { margin: 6px 0 3px; color: var(--color-text-secondary); font-size: 11px; }
.school-task small { color: var(--color-text-muted); font-size: 10px; }
.school-task__enrollments { display: grid; grid-column: 1 / -1; gap: 5px; padding-top: 8px; border-top: 1px solid var(--color-border); }
.school-task__enrollment { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--color-text-secondary); font-size: 11px; }
@media(max-width:760px) { .school-grid { grid-template-columns: 1fr; }.school-form--dates { grid-template-columns: 1fr; }.school-form--dates button { grid-column: auto; }.school-task { grid-template-columns: 1fr; }.school-task > button { justify-self: start; } }
</style>
