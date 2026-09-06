<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { Search } from '@lucide/vue'
import { UserRound } from '@lucide/vue'
import { RotateCcw } from '@lucide/vue'
import AppBadge from '@/components/app/AppBadge.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppInput from '@/components/app/AppInput.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import type { TeacherOverviewViewModel } from '@/types/view-models'

interface StudentRecord {
  subjectId: string
  caseId: string
  state: string
  lastSeen: string
  tone: 'teal' | 'amber' | 'blue'
  note: string
}

const state = ref<'loading' | 'ready' | 'error'>('loading')
const data = ref<TeacherOverviewViewModel | null>(null)
const search = ref('')
const errorMessage = ref('')

const records = computed<StudentRecord[]>(() => {
  if (!data.value) return []
  return data.value.attentionCases.map((item) => ({
    subjectId: item.subjectId,
    caseId: item.caseId,
    state: item.state,
    lastSeen: item.updatedAt,
    tone: item.priority === 'high' ? 'amber' : item.state === '已安排回看' ? 'blue' : 'teal',
    note: item.priority === 'high' ? '安全流程已暂停' : '可安排支持性沟通',
  }))
})

const filteredRecords = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return records.value
  return records.value.filter((record) => `${record.subjectId} ${record.caseId} ${record.state}`.toLowerCase().includes(query))
})

const load = async () => {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const response = await frontendApi.getTeacherOverview()
    data.value = response.data
    state.value = 'ready'
  } catch (error) {
    state.value = 'error'
    errorMessage.value = error instanceof MockApiError ? error.message : '学生支持记录暂时无法加载。'
  }
}

onMounted(load)
</script>

<template>
  <div class="content-wrap teacher-students">
    <div v-if="state === 'loading'" class="students-loading" aria-busy="true" aria-label="正在加载学生支持记录"><div class="skeleton skeleton--small"></div><div class="skeleton skeleton--title"></div><div class="skeleton skeleton--table"></div></div>
    <AppStatusCallout v-else-if="state === 'error'" tone="critical" title="记录暂时无法加载" :body="errorMessage"><button class="inline-retry" type="button" @click="load"><RotateCcw :size="15" aria-hidden="true" />重新加载</button></AppStatusCallout>
    <template v-else-if="data">
      <AppPageHeader eyebrow="教师工作区" title="学生支持" intro="使用匿名案例标识查看受控摘要和支持流程状态。" :fixture-label="data.fixtureLabel">
        <template #actions><AppBadge tone="blue"><UserRound :size="14" aria-hidden="true" />{{ records.length }} 条合成记录</AppBadge></template>
      </AppPageHeader>

      <AppCard class="students-toolbar">
        <div class="students-toolbar__search"><Search :size="17" aria-hidden="true" /><AppInput id="student-search" v-model="search" label="" placeholder="搜索案例标识或流程状态" /></div>
        <span class="students-toolbar__scope">只搜索当前授权范围</span>
      </AppCard>

      <div v-if="filteredRecords.length" class="student-records" aria-label="学生支持记录列表">
        <AppCard v-for="record in filteredRecords" :key="record.caseId" class="student-record">
          <div class="student-record__id"><span class="student-record__mark" aria-hidden="true"><UserRound :size="17" /></span><span><strong>{{ record.subjectId }}</strong><small>{{ record.caseId }}</small></span></div>
          <div class="student-record__state"><span>当前状态</span><AppBadge :tone="record.tone" dot>{{ record.state }}</AppBadge></div>
          <div class="student-record__note"><span>备注</span><strong>{{ record.note }}</strong></div>
          <div class="student-record__time"><span>最近更新</span><strong>{{ record.lastSeen }}</strong></div>
          <RouterLink :to="`/teacher/students/${record.caseId}`" class="student-record__link">查看摘要 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
        </AppCard>
      </div>

      <AppCard v-else class="students-empty">
        <Search :size="21" aria-hidden="true" /><strong>没有匹配记录</strong><p>试试案例标识或“等待人工复核”等状态词。</p>
      </AppCard>

      <AppStatusCallout class="students-boundary" tone="info" title="教师端披露边界" body="这里不显示姓名、学号、原始回答、模型原文或内部测量参数。需要人工确认的流程不会在此继续生成。" />
    </template>
  </div>
</template>

<style scoped>
.teacher-students { animation: page-in 260ms ease both; }
.students-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 12px 15px; }
.students-toolbar__search { display: flex; align-items: center; gap: 9px; min-width: min(100%, 390px); color: var(--color-text-muted); }
.students-toolbar__search :deep(.app-field) { flex: 1; }
.students-toolbar__search :deep(.app-field__label) { display: none; }
.students-toolbar__search :deep(.app-input) { min-height: 40px; border-color: var(--color-border); background: var(--color-surface-muted); }
.students-toolbar__scope { color: var(--color-text-muted); font-size: 11px; }
.student-records { display: grid; gap: 9px; margin-top: 16px; }
.student-record { display: grid; grid-template-columns: minmax(200px, 1.25fr) minmax(150px, 0.9fr) minmax(150px, 0.9fr) minmax(130px, 0.75fr) auto; align-items: center; gap: 16px; padding: 15px 17px; }
.student-record__id { display: flex; align-items: center; gap: 10px; min-width: 0; }
.student-record__mark { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; flex: 0 0 34px; border-radius: 8px; color: var(--color-primary); background: var(--color-info-wash); }
.student-record__id > span:last-child, .student-record__state, .student-record__note, .student-record__time { display: grid; gap: 4px; min-width: 0; }
.student-record__id strong { overflow: hidden; font-family: var(--font-mono); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.student-record__id small { color: var(--color-text-muted); font-family: var(--font-mono); font-size: 9px; }
.student-record__state > span, .student-record__note > span, .student-record__time > span { color: var(--color-text-muted); font-size: 10px; }
.student-record__note strong, .student-record__time strong { overflow: hidden; color: var(--color-text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.student-record__time strong { color: var(--color-text-secondary); font-weight: 600; }
.student-record__link { display: inline-flex; align-items: center; gap: 5px; color: var(--color-primary); font-size: 12px; font-weight: 700; white-space: nowrap; }
.student-record__link:hover { text-decoration: underline; text-underline-offset: 3px; }
.students-boundary { margin-top: 24px; }
.students-empty { display: grid; justify-items: center; padding: 46px 20px; text-align: center; color: var(--color-text-muted); }
.students-empty strong { margin-top: 12px; color: var(--color-text-primary); font-size: 14px; }
.students-empty p { margin: 6px 0 0; font-size: 12px; }
.inline-retry { display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: 7px; color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; font-size: 12px; font-weight: 700; }
.inline-retry:hover { border-color: var(--color-primary); color: var(--color-primary); }
.students-loading { padding-top: 12px; }.skeleton { position: relative; overflow: hidden; border-radius: 7px; background: var(--color-surface-skeleton); }.skeleton::after { position: absolute; inset: 0; content: ""; background: linear-gradient(90deg, transparent, rgb(255 255 255 / 58%), transparent); animation: shimmer 1.4s infinite; transform: translateX(-100%); }.skeleton--small { width: 140px; height: 14px; }.skeleton--title { width: 280px; height: 34px; margin-top: 17px; }.skeleton--table { height: 180px; margin-top: 32px; }
@keyframes page-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } } @keyframes shimmer { to { transform: translateX(100%); } }
@media (max-width: 900px) { .student-record { grid-template-columns: minmax(220px, 1fr) minmax(150px, 0.7fr) minmax(150px, 0.7fr) auto; }.student-record__time { display: none; } }
@media (max-width: 680px) { .students-toolbar { align-items: flex-start; flex-direction: column; gap: 7px; }.students-toolbar__search { width: 100%; }.student-record { grid-template-columns: 1fr auto; gap: 14px; }.student-record__state { justify-items: end; }.student-record__note { grid-column: 1 / 2; }.student-record__link { grid-column: 2; grid-row: 2; }.students-toolbar__scope { padding-left: 26px; } }
</style>
