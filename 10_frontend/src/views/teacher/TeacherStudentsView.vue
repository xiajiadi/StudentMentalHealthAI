<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, RotateCcw, Search, UsersRound } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppInput from '@/components/app/AppInput.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { isTeacherForbidden, teacherApi, type TeacherStudentSummary } from './teacher-api'

const state = ref<'loading' | 'ready' | 'error' | 'forbidden'>('loading')
const records = ref<TeacherStudentSummary[]>([])
const search = ref('')
const errorMessage = ref('')

const filteredRecords = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return records.value
  return records.value.filter((record) => record.subject_id.toLowerCase().includes(query))
})

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const overview = (await teacherApi.getTeacherOverview()).data
    records.value = overview.students
    state.value = 'ready'
  } catch (error) {
    state.value = isTeacherForbidden(error) ? 'forbidden' : 'error'
    errorMessage.value = state.value === 'forbidden' ? '当前账号没有查看此授权范围的权限。' : '学生测评历史暂时无法加载，请稍后重试。'
  }
}

const formatTime = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '暂无记录'

onMounted(load)
</script>

<template>
  <div class="content-wrap teacher-students">
    <div v-if="state === 'loading'" class="loading-state" aria-busy="true">正在读取授权范围内的测评记录…</div>
    <AppStatusCallout v-else-if="state === 'forbidden'" tone="critical" title="没有查看权限" :body="errorMessage" />
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="测评历史暂时无法加载" :body="errorMessage"><button class="inline-retry" type="button" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</button></AppStatusCallout>
    <template v-else>
      <AppPageHeader eyebrow="教师工作区" title="测评历史" intro="仅列出当前账号授权范围内，确有合成测评记录的匿名主体。" />
      <AppStatusCallout tone="info" title="展示内容" body="列表只包含匿名主体标识、测评数量、完成状态和最近记录时间；不会显示回答内容、支持对话或心理测量参数。" />
      <AppCard class="students-toolbar">
        <div class="students-toolbar__search"><Search :size="17" aria-hidden="true" /><AppInput id="subject-search" v-model="search" label="搜索匿名主体" placeholder="输入匿名主体 ID" /></div>
        <AppBadge tone="blue"><UsersRound :size="14" aria-hidden="true" />{{ records.length }} 个有记录的主体</AppBadge>
      </AppCard>

      <div v-if="filteredRecords.length" class="student-records" aria-label="匿名主体测评历史列表">
        <AppCard v-for="record in filteredRecords" :key="record.subject_id" class="student-record">
          <div class="student-record__id"><strong>{{ record.subject_id }}</strong><small>匿名主体</small></div>
          <div><span class="field-label">测评记录</span><strong>{{ record.assessment_count }}</strong></div>
          <div><span class="field-label">已完成</span><strong>{{ record.completed_count }}</strong></div>
          <div><span class="field-label">进行中</span><strong>{{ record.in_progress_count }}</strong></div>
          <div><span class="field-label">最近记录</span><time v-if="record.last_activity_at" :datetime="record.last_activity_at">{{ formatTime(record.last_activity_at) }}</time><strong v-else>暂无记录</strong></div>
          <RouterLink :to="`/teacher/students/${encodeURIComponent(record.subject_id)}`" class="student-record__link">查看历史 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
        </AppCard>
      </div>
      <AppCard v-else class="empty-state">
        <strong>{{ records.length ? '没有匹配的匿名主体' : '当前授权范围内没有合成测评记录' }}</strong>
        <p>{{ records.length ? '请检查匿名主体 ID。' : '有实际记录后，主体和测评历史会显示在这里。' }}</p>
      </AppCard>
    </template>
  </div>
</template>

<style scoped>
.teacher-students { animation: page-in 240ms ease both; }
.students-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 18px; padding: 12px 15px; }
.students-toolbar__search { display: flex; align-items: center; gap: 9px; min-width: min(100%, 410px); color: var(--color-text-muted); }
.students-toolbar__search :deep(.app-field) { flex: 1; }
.students-toolbar__search :deep(.app-field__label) { display: none; }
.students-toolbar__search :deep(.app-input) { min-height: 40px; border-color: var(--color-border); background: var(--color-surface-muted); }
.student-records { display: grid; gap: 9px; margin-top: 15px; }
.student-record { display: grid; grid-template-columns: minmax(150px, 1.2fr) repeat(3, minmax(72px, .55fr)) minmax(180px, 1.1fr) auto; align-items: center; gap: 15px; padding: 15px 17px; }
.student-record > div:not(:first-child) { display: grid; gap: 5px; color: var(--color-text-primary); font-size: 12px; }
.student-record__id { display: grid; gap: 4px; min-width: 0; }
.student-record__id strong { overflow: hidden; font-family: var(--font-mono); font-size: 11px; text-overflow: ellipsis; }
.student-record__id small, .field-label { color: var(--color-text-muted); font-size: 10px; }
.student-record time { color: var(--color-text-secondary); font-size: 11px; }
.student-record__link { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-size: 12px; font-weight: 700; white-space: nowrap; }
.student-record__link:hover { text-decoration: underline; text-underline-offset: 3px; }
.empty-state { display: grid; justify-items: center; margin-top: 15px; padding: 40px 20px; text-align: center; }
.empty-state strong { color: var(--color-text-primary); font-size: 14px; }
.empty-state p { margin: 7px 0 0; color: var(--color-text-muted); font-size: 12px; }
.loading-state { padding: 22px 0; color: var(--color-text-secondary); font-size: 13px; }
.inline-retry { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; font-size: 12px; font-weight: 700; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 860px) { .student-records { overflow-x: auto; }.student-record { min-width: 810px; } }
@media (max-width: 560px) { .students-toolbar { align-items: flex-start; flex-direction: column; }.students-toolbar__search { min-width: 100%; } }
</style>
