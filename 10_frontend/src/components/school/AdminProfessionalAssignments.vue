<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RotateCcw, UserRoundCog } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import type { SchoolTask } from '@/api/client'
import {
  newProfessionalAssignmentIdempotencyKey,
  professionalAssignments,
  type ProfessionalReviewAssignment,
  type ProfessionalReviewSpecialist,
} from '@/services/professional-assignments'

const props = defineProps<{ tasks: SchoolTask[] }>()
type LoadState = 'loading' | 'ready' | 'error'
type AssignmentOperation =
  | { kind: 'assign'; taskRef: string; specialistUserId: string; key: string }
  | { kind: 'revoke'; taskRef: string; assignmentRef: string; key: string }

const specialists = ref<ProfessionalReviewSpecialist[]>([])
const assignments = ref<ProfessionalReviewAssignment[]>([])
const specialistsState = ref<LoadState>('loading')
const assignmentsState = ref<LoadState>('loading')
const specialistsError = ref('')
const assignmentsError = ref('')
const selectedTaskRef = ref(props.tasks[0]?.task_ref ?? '')
const selectedSpecialistId = ref('')
const pending = ref(false)
const failedOperation = ref<AssignmentOperation | null>(null)
const operationError = ref('')
const notice = ref('')
const loadGeneration = ref(0)
const scopeGeneration = ref(0)

const selectedTask = computed(() => props.tasks.find((task) => task.task_ref === selectedTaskRef.value) ?? null)
const taskAssignments = computed(() => assignments.value.filter((item) => item.task_ref === selectedTaskRef.value))
const activeSpecialistIds = computed(() => new Set(taskAssignments.value.filter((item) => item.status === 'ACTIVE').map((item) => item.specialist_user_id)))
const availableSpecialists = computed(() => specialists.value.filter((person) => !activeSpecialistIds.value.has(person.user_id)))

const taskOptionLabel = (task: SchoolTask) => {
  const index = props.tasks.findIndex((item) => item.task_ref === task.task_ref)
  return `第 ${index + 1} 项，${formatDate(task.opens_at)} 至 ${formatDate(task.due_at)}`
}

const formatDate = (value: string | null) => {
  if (!value) return '未设截止时间'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '时间待确认'
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const specialistLabel = (userId: string) => {
  const index = specialists.value.findIndex((item) => item.user_id === userId)
  if (index < 0) return '未列入当前可选名单的专员'
  const name = specialists.value[index]?.display_name?.trim()
  return name || `专员 ${index + 1}`
}

const statusLabel = (status: ProfessionalReviewAssignment['status']) => status === 'ACTIVE' ? '当前有效' : '已撤销'

const loadSpecialists = async (generation: number) => {
  specialistsState.value = 'loading'
  specialistsError.value = ''
  try {
    const result = await professionalAssignments.listSpecialists()
    if (generation !== loadGeneration.value) return
    specialists.value = result
    specialistsState.value = 'ready'
  } catch {
    if (generation !== loadGeneration.value) return
    specialists.value = []
    specialistsState.value = 'error'
    specialistsError.value = '暂时无法读取可分配的同校专员。'
  }
}

const loadAssignments = async (generation: number) => {
  assignmentsState.value = 'loading'
  assignmentsError.value = ''
  try {
    const result = await professionalAssignments.listAssignments()
    if (generation !== loadGeneration.value) return
    assignments.value = result
    assignmentsState.value = 'ready'
  } catch {
    if (generation !== loadGeneration.value) return
    assignments.value = []
    assignmentsState.value = 'error'
    assignmentsError.value = '暂时无法读取任务分配记录。'
  }
}

const refresh = async () => {
  const generation = ++loadGeneration.value
  notice.value = ''
  await Promise.all([loadSpecialists(generation), loadAssignments(generation)])
}

const runOperation = async (operation: AssignmentOperation) => {
  if (pending.value) return
  const operationScope = scopeGeneration.value
  pending.value = true
  failedOperation.value = null
  operationError.value = ''
  notice.value = ''
  try {
    if (operation.kind === 'assign') {
      await professionalAssignments.assign(operation.taskRef, operation.specialistUserId, operation.key)
      notice.value = '专员已分配到任务。'
    } else {
      await professionalAssignments.revoke(operation.taskRef, operation.assignmentRef, operation.key)
      notice.value = '该任务分配已撤销。'
    }
    if (operationScope !== scopeGeneration.value) return
    selectedSpecialistId.value = ''
    const generation = ++loadGeneration.value
    await loadAssignments(generation)
  } catch (error) {
    if (operationScope !== scopeGeneration.value) return
    const code = error && typeof error === 'object' && 'code' in error ? String(error.code).toUpperCase() : ''
    const retryable = Boolean(error && typeof error === 'object' && 'retryable' in error && error.retryable)
    if (retryable) {
      failedOperation.value = operation
      operationError.value = '服务端未确认操作结果。可使用相同请求重试，避免重复创建分配。'
    } else {
      failedOperation.value = null
      if (code === 'FORBIDDEN' || code === '403' || code === 'AUTH_SESSION_EXPIRED' || code === 'AUTH_SESSION_REVOKED') {
        operationError.value = '账号权限或登录状态可能已变化。请刷新页面；如仍无法操作，请重新登录。'
      } else if (code === 'RESOURCE_NOT_FOUND' || code === 'NOT_FOUND' || code === '404') {
        operationError.value = '任务或分配记录已不存在，请刷新分配记录后再操作。'
      } else if (code === 'WORKFLOW_CONFLICT' || code === 'IDEMPOTENCY_CONFLICT' || code === 'CONFLICT' || code === '409') {
        operationError.value = '任务分配状态已发生变化，请刷新分配记录后再操作。'
      } else {
        operationError.value = '操作未完成，请刷新分配记录后确认当前状态。'
      }
    }
  } finally {
    if (operationScope === scopeGeneration.value) pending.value = false
  }
}

const assign = async () => {
  if (!selectedTask.value || !selectedSpecialistId.value || pending.value || specialistsState.value !== 'ready') return
  try {
    await runOperation({
      kind: 'assign', taskRef: selectedTask.value.task_ref,
      specialistUserId: selectedSpecialistId.value, key: newProfessionalAssignmentIdempotencyKey(),
    })
  } catch {
    operationError.value = '当前浏览器无法安全建立请求标识，请更新浏览器后重试。'
  }
}

const revoke = async (assignment: ProfessionalReviewAssignment) => {
  if (assignment.status !== 'ACTIVE' || pending.value) return
  try {
    await runOperation({
      kind: 'revoke', taskRef: assignment.task_ref,
      assignmentRef: assignment.assignment_ref, key: newProfessionalAssignmentIdempotencyKey(),
    })
  } catch {
    operationError.value = '当前浏览器无法安全建立请求标识，请更新浏览器后重试。'
  }
}

const retry = async () => {
  if (failedOperation.value && !pending.value) await runOperation(failedOperation.value)
}

watch(() => props.tasks, (tasks) => {
  scopeGeneration.value += 1
  const generation = ++loadGeneration.value
  specialists.value = []
  assignments.value = []
  specialistsError.value = ''
  assignmentsError.value = ''
  failedOperation.value = null
  operationError.value = ''
  notice.value = ''
  selectedSpecialistId.value = ''
  pending.value = false
  if (!tasks.some((task) => task.task_ref === selectedTaskRef.value)) {
    selectedTaskRef.value = tasks[0]?.task_ref ?? ''
  }
  if (!tasks.length) {
    specialistsState.value = 'ready'
    assignmentsState.value = 'ready'
    return
  }
  void Promise.all([loadSpecialists(generation), loadAssignments(generation)])
})
watch(selectedTaskRef, () => { selectedSpecialistId.value = '' })
onMounted(() => { void refresh() })
onBeforeUnmount(() => {
  scopeGeneration.value += 1
  loadGeneration.value += 1
})
</script>

<template>
  <AppCard class="professional-assignments" aria-labelledby="professional-assignments-title">
    <header class="professional-assignments__heading">
      <div class="professional-assignments__title">
        <UserRoundCog :size="18" aria-hidden="true" />
        <div>
          <h3 id="professional-assignments-title">专业人员分配</h3>
          <p>按任务分配同校专员。此处仅管理分配状态，不显示个案内容。</p>
        </div>
      </div>
      <AppButton variant="secondary" size="sm" :disabled="pending" @click="refresh">
        <RotateCcw :size="15" aria-hidden="true" />刷新
      </AppButton>
    </header>

    <AppStatusCallout v-if="operationError" tone="critical" title="操作未确认" :body="operationError" role="alert" />
    <AppButton v-if="failedOperation" variant="secondary" size="sm" :disabled="pending" :loading="pending" @click="retry">使用相同请求重试</AppButton>
    <AppStatusCallout v-if="notice" tone="info" title="服务端已确认" :body="notice" role="status" />

    <div class="professional-assignments__form">
      <template v-if="props.tasks.length > 1">
        <label for="professional-assignment-task">任务</label>
        <select id="professional-assignment-task" v-model="selectedTaskRef" :disabled="!props.tasks.length || pending">
          <option value="" disabled>请选择任务</option>
          <option v-for="task in props.tasks" :key="task.task_ref" :value="task.task_ref">{{ taskOptionLabel(task) }}</option>
        </select>
      </template>
      <label for="professional-assignment-specialist">同校专员</label>
      <div class="professional-assignments__action">
        <select id="professional-assignment-specialist" v-model="selectedSpecialistId" :disabled="!selectedTask || specialistsState !== 'ready' || !availableSpecialists.length || pending">
          <option value="">选择专员</option>
          <option v-for="(specialist, index) in specialists" :key="specialist.user_id" :value="specialist.user_id" :disabled="activeSpecialistIds.has(specialist.user_id)">
            {{ specialist.display_name?.trim() || `专员 ${index + 1}` }}{{ activeSpecialistIds.has(specialist.user_id) ? '，已分配' : '' }}
          </option>
        </select>
        <AppButton size="sm" :disabled="!selectedTask || !selectedSpecialistId || pending || specialistsState !== 'ready' || assignmentsState !== 'ready'" :loading="pending && failedOperation?.kind === 'assign'" @click="assign">分配</AppButton>
      </div>
      <p v-if="specialistsState === 'loading'" class="professional-assignments__hint" aria-busy="true">正在读取同校专员…</p>
      <div v-else-if="specialistsState === 'error'" class="professional-assignments__hint professional-assignments__hint--error" role="alert">{{ specialistsError }}<AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton></div>
      <p v-else-if="!specialists.length" class="professional-assignments__hint">当前没有可分配的同校专员。</p>
      <p v-else-if="selectedTask && !availableSpecialists.length" class="professional-assignments__hint">当前任务的专员均已分配。</p>
    </div>

    <div v-if="assignmentsState === 'loading'" class="professional-assignments__hint" aria-busy="true">正在读取分配记录…</div>
    <div v-else-if="assignmentsState === 'error'" class="professional-assignments__hint professional-assignments__hint--error" role="alert">{{ assignmentsError }}<AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton></div>
    <div v-else-if="!props.tasks.length" class="professional-assignments__empty">当前班级还没有已发布任务。</div>
    <div v-else-if="!taskAssignments.length" class="professional-assignments__empty">这个任务还没有专员分配记录。</div>
    <ul v-else class="professional-assignments__list" aria-label="当前任务的专员分配">
      <li v-for="assignment in taskAssignments" :key="assignment.assignment_ref" class="professional-assignments__row">
        <div>
          <strong>{{ specialistLabel(assignment.specialist_user_id) }}</strong>
          <span :class="['professional-assignments__status', { 'professional-assignments__status--revoked': assignment.status === 'REVOKED' }]">{{ statusLabel(assignment.status) }}</span>
          <p>分配于 {{ formatDate(assignment.assigned_at) }}<template v-if="assignment.revoked_at">，撤销于 {{ formatDate(assignment.revoked_at) }}</template></p>
        </div>
        <AppButton v-if="assignment.status === 'ACTIVE'" variant="quiet" size="sm" :disabled="pending" :loading="pending && failedOperation?.kind === 'revoke' && failedOperation.assignmentRef === assignment.assignment_ref" @click="revoke(assignment)">撤销分配</AppButton>
      </li>
    </ul>
  </AppCard>
</template>

<style scoped>
.professional-assignments { display: grid; gap: 13px; min-width: 0; padding: 17px; }
.professional-assignments__heading,.professional-assignments__title,.professional-assignments__action,.professional-assignments__row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.professional-assignments__title { justify-content: flex-start; align-items: flex-start; color: #388576; }
.professional-assignments__title h3 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 15px; }
.professional-assignments__title p,.professional-assignments__row p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.professional-assignments__form { display: grid; grid-template-columns: 140px minmax(0,1fr); align-items: center; gap: 8px 12px; max-width: 720px; }
.professional-assignments__form label { color: var(--color-text-secondary); font-size: 12px; font-weight: 650; }
.professional-assignments__form select { width: 100%; min-width: 0; min-height: 40px; padding: 8px 10px; border: 1px solid var(--color-border); border-radius: 8px; color: var(--color-text-primary); background: #fff; font: inherit; font-size: 13px; }
.professional-assignments__form select:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }
.professional-assignments__action { justify-content: flex-start; }
.professional-assignments__action select { flex: 1; }
.professional-assignments__hint,.professional-assignments__empty { grid-column: 1 / -1; display: flex; align-items: center; gap: 9px; margin: 0; padding: 10px; border-radius: 8px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 12px; line-height: 1.5; }
.professional-assignments__hint--error { color: #8f651d; background: #fcf7eb; }
.professional-assignments__list { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.professional-assignments__row { min-width: 0; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: 9px; }
.professional-assignments__row > div { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 9px; min-width: 0; }
.professional-assignments__row p { flex-basis: 100%; }
.professional-assignments__status { color: #247761; font-size: 11px; font-weight: 700; }
.professional-assignments__status--revoked { color: var(--color-text-muted); }
@media (max-width: 620px) {
  .professional-assignments__heading,.professional-assignments__row { align-items: flex-start; }
  .professional-assignments__form { grid-template-columns: 1fr; gap: 6px; }
  .professional-assignments__form label:not(:first-child) { margin-top: 5px; }
  .professional-assignments__action { align-items: stretch; }
}
</style>
