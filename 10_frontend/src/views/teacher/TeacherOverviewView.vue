<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ListChecks, LockKeyhole, RotateCcw } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import type { TeacherTaskProgress } from '@/api/client'
import { frontendApi } from '@/services/mock-api'

const state = ref<'loading' | 'ready' | 'error'>('loading')
const rows = ref<TeacherTaskProgress[]>([])
const errorMessage = ref('')
const requestGeneration = ref(0)

const shortRef = (value: string) => value.slice(-6)
const statusLabel = (value: string) => ({ PUBLISHED: '已发布', published: '已发布', CANCELLED: '已取消', cancelled: '已取消' }[value] ?? '状态待确认')
const formatDate = (value: string | null) => {
  if (!value) return '未设置截止时间'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '时间待确认' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

const load = async () => {
  const generation = ++requestGeneration.value
  state.value = 'loading'
  errorMessage.value = ''
  rows.value = []
  if (!frontendApi.listTeacherSchoolTaskProgress) {
    state.value = 'error'
    errorMessage.value = '当前运行环境未提供教师任务汇总服务。'
    return
  }
  try {
    const result = await frontendApi.listTeacherSchoolTaskProgress()
    if (generation !== requestGeneration.value) return
    rows.value = result.data
    state.value = 'ready'
  } catch (error) {
    if (generation !== requestGeneration.value) return
    const code = typeof error === 'object' && error !== null && 'code' in error ? String(error.code).toLowerCase() : ''
    if (/auth_session_expired|auth_session_revoked/.test(code)) errorMessage.value = '登录状态已过期，请重新登录后再试。'
    else if (code === 'forbidden' || code === '403') errorMessage.value = '当前账号暂时无法查看这些任务。'
    else if (code === 'resource_not_found' || code === 'not_found' || code === '404') errorMessage.value = '任务信息已变化，请刷新列表。'
    else errorMessage.value = '暂时无法读取任务进度，请稍后重试。'
    state.value = 'error'
  }
}

onMounted(() => { void load() })
</script>

<template>
  <main class="content-wrap teacher-overview">
    <WorkspaceBreadcrumb homeLabel="教师工作区" homeTo="/teacher/overview" current="班级任务进度" />
    <StudentPageHero
      eyebrow="教师工作区 · Scope A"
      title="班级任务进度"
      subtitle="查看已分配班级的任务整体完成情况。"
      image="/assets/psynova/student-page-heroes/history-hero.webp"
    />
    <AppStatusCallout tone="info" title="仅显示任务汇总" body="此页不会显示学生名单、个人测评记录、作答、报告或支持对话。" />

    <AppCard class="task-progress-panel">
      <div class="task-progress-panel__heading"><div><ListChecks :size="19" aria-hidden="true" /><div><h2>已分配任务</h2><p>汇总人数包含仍有效的报名；已撤销报名单独列示。</p></div></div><AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="load"><RotateCcw :size="15" aria-hidden="true" />刷新</AppButton></div>
      <div v-if="state === 'loading'" class="task-progress-state" aria-busy="true">正在读取任务汇总…</div>
      <div v-else-if="state === 'error'" class="task-progress-state task-progress-state--error" role="alert"><span><LockKeyhole :size="17" aria-hidden="true" />{{ errorMessage }}</span><AppButton variant="secondary" size="sm" @click="load">重新读取</AppButton></div>
      <div v-else-if="!rows.length" class="task-progress-state" role="status">当前没有分配给你的班级任务。</div>
      <div v-else class="task-progress-list">
        <article v-for="row in rows" :key="`${row.class_ref}:${row.task_ref}`" class="task-progress-row">
          <header><div><span class="task-progress-row__class">班级 {{ shortRef(row.class_ref) }}</span><h3>任务 {{ shortRef(row.task_ref) }}</h3></div><span class="task-progress-row__status">{{ statusLabel(row.task_status) }}</span></header>
          <p class="task-progress-row__dates">{{ formatDate(row.opens_at) }} 至 {{ formatDate(row.due_at) }}</p>
          <dl><div><dt>报名总数</dt><dd>{{ row.published_enrollment_count }}</dd></div><div><dt>当前有效</dt><dd>{{ row.active_enrollment_count }}</dd></div><div><dt>未开始</dt><dd>{{ row.not_started_count }}</dd></div><div><dt>准备中</dt><dd>{{ row.created_count }}</dd></div><div><dt>进行中</dt><dd>{{ row.in_progress_count }}</dd></div><div><dt>已完成</dt><dd>{{ row.completed_count }}</dd></div><div><dt>已结束</dt><dd>{{ row.abandoned_count }}</dd></div><div><dt>不可继续</dt><dd>{{ row.invalid_count }}</dd></div><div><dt>已撤销</dt><dd>{{ row.revoked_enrollment_count }}</dd></div></dl>
        </article>
      </div>
    </AppCard>
    <p class="task-progress-footnote">进度仅用于安排班级任务，不包含个人测评信息或心理判断。</p>
  </main>
</template>

<style scoped>
.teacher-overview { display: grid; gap: 16px; animation: page-in 220ms ease both; }
.teacher-overview :deep(.student-page-hero) { margin-bottom: 0; }
.task-progress-panel { padding: 22px; }
.task-progress-panel__heading,.task-progress-panel__heading > div { display: flex; align-items: center; justify-content: space-between; gap: 11px; }
.task-progress-panel__heading > div { justify-content: flex-start; color: var(--color-support); }
.task-progress-panel__heading h2 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 15px; }
.task-progress-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.task-progress-state { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 112px; margin-top: 16px; padding: 18px; border-radius: 12px; color: var(--color-text-secondary); background: #f8fafb; font-size: 12px; }
.task-progress-state--error { justify-content: space-between; color: #8f651d; background: #fcf7eb; }
.task-progress-state--error > span { display: flex; align-items: center; gap: 8px; }
.task-progress-list { display: grid; gap: 12px; margin-top: 17px; }
.task-progress-row { padding: 17px; border: 1px solid #e8edf0; border-radius: 14px; }
.task-progress-row header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.task-progress-row__class { color: #54809c; font-size: 10px; font-weight: 750; }
.task-progress-row h3 { margin: 4px 0 0; color: var(--color-text-primary); font-size: 14px; }
.task-progress-row__status { padding: 4px 8px; border-radius: 999px; color: #287765; background: #e8f4ef; font-size: 10px; }
.task-progress-row__dates { margin: 8px 0 12px; color: var(--color-text-secondary); font-size: 11px; }
.task-progress-row dl { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 7px; margin: 0; }
.task-progress-row dl > div { display: grid; gap: 4px; min-width: 0; padding: 10px; border-radius: 10px; background: #f7f8f9; }
.task-progress-row dt { color: var(--color-text-muted); font-size: 10px; }
.task-progress-row dd { margin: 0; color: var(--color-text-primary); font-size: 17px; font-weight: 700; }
.task-progress-footnote { margin: 0 2px; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:760px) { .task-progress-row dl { grid-template-columns: repeat(3,minmax(0,1fr)); }.task-progress-panel { padding: 17px; } }
</style>
