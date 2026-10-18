<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, ArrowUpDown, ListChecks, RotateCcw, Search, UsersRound } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { useTeacherTaskProgress } from '@/composables/useTeacherTaskProgress'
import { summarizeTeacherClasses, teacherClassDisplayLabel } from '@/utils/teacher-task-progress'

type ClassSort = 'name' | 'completion' | 'tasks'

const { state, rows, errorMessage, refresh, isDemo } = useTeacherTaskProgress({ demoMode: true })
const query = ref('')
const sort = ref<ClassSort>('name')
const classes = computed(() => {
  const normalizedQuery = query.value.trim().toLocaleLowerCase()
  return summarizeTeacherClasses(rows.value)
    .filter((item) => !normalizedQuery || `${teacherClassDisplayLabel(item.classRef, rows.value)} ${item.classRef}`.toLocaleLowerCase().includes(normalizedQuery))
    .sort((a, b) => {
      if (sort.value === 'completion') return b.completionRate - a.completionRate || a.classRef.localeCompare(b.classRef, 'zh-CN')
      if (sort.value === 'tasks') return b.taskCount - a.taskCount || a.classRef.localeCompare(b.classRef, 'zh-CN')
      return teacherClassDisplayLabel(a.classRef, rows.value).localeCompare(teacherClassDisplayLabel(b.classRef, rows.value), 'zh-CN')
    })
})
const classTo = (classRef: string) => `/teacher/classes/${encodeURIComponent(classRef)}`
</script>

<template>
  <main class="content-wrap teacher-classes">
    <WorkspaceBreadcrumb home-label="教师工作区" home-to="/teacher/overview" current="班级进度" />
    <header class="teacher-page-heading">
      <span class="teacher-page-heading__icon"><UsersRound :size="21" aria-hidden="true" /></span>
      <div><h1>班级进度</h1><p>这是一个以班级为中心的页面，而不是学生心理档案。</p></div>
    </header>

    <AppCard class="class-library">
      <header class="class-library__toolbar">
        <div class="class-library__title"><span class="class-library__icon"><ListChecks :size="18" aria-hidden="true" /></span><div><h2>我的班级</h2><p>展示当前账号可查看且有任务汇总的班级</p></div></div>
        <div class="class-library__actions">
          <label class="class-library__search"><span class="sr-only">搜索班级</span><Search :size="15" aria-hidden="true" /><input v-model="query" type="search" placeholder="搜索班级" :disabled="state !== 'ready'" /></label>
          <label class="class-library__sort"><span class="sr-only">排序班级</span><ArrowUpDown :size="14" aria-hidden="true" /><select v-model="sort" :disabled="state !== 'ready' || !rows.length"><option value="name">按班级</option><option value="completion">按完成率</option><option value="tasks">按任务数</option></select></label>
          <AppButton variant="secondary" size="sm" :disabled="state === 'loading'" @click="refresh"><RotateCcw :size="14" aria-hidden="true" />刷新</AppButton>
        </div>
      </header>

      <div v-if="state === 'loading'" class="class-library__state" aria-busy="true" role="status">正在读取班级进度…</div>
      <AppStatusCallout v-else-if="state === 'error'" class="class-library__message" tone="critical" title="班级进度暂不可用" :body="errorMessage">
        <AppButton variant="secondary" size="sm" @click="refresh">重新读取</AppButton>
      </AppStatusCallout>
      <div v-else-if="classes.length === 0" class="class-library__state" role="status">{{ query ? '没有匹配的班级。' : '当前没有可查看的授权班级任务汇总。' }}</div>
      <div v-else class="class-library__table-wrap">
        <table class="class-library__table">
          <thead><tr><th scope="col">班级名称</th><th scope="col">测评任务数</th><th scope="col">完成率</th><th scope="col"><span class="sr-only">操作</span>查看进度</th></tr></thead>
          <tbody>
            <tr v-for="item in classes" :key="item.classRef">
              <th scope="row"><span class="class-library__name">{{ teacherClassDisplayLabel(item.classRef, rows) }}</span><small>授权汇总</small></th>
              <td><strong>{{ item.taskCount }}</strong><span class="class-library__unit">项</span></td>
              <td><div class="class-library__completion"><template v-if="item.activeEnrollmentCount > 0"><span class="class-library__track" role="progressbar" :aria-valuenow="item.completionRate" aria-valuemin="0" aria-valuemax="100" :aria-label="`班级 ${shortTeacherRef(item.classRef)} 汇总完成率`"><span :style="{ width: `${item.completionRate}%` }"></span></span><strong>{{ item.completionRate }}%</strong></template><strong v-else aria-label="无有效报名，完成率不可用">—</strong></div><small>{{ item.completedCount }} / {{ item.activeEnrollmentCount }} 有效报名人次</small></td>
              <td><RouterLink class="class-library__link" :to="classTo(item.classRef)">查看进度 <ArrowRight :size="15" aria-hidden="true" /></RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <footer v-if="state === 'ready' && classes.length" class="class-library__footer">
        {{ classes.length }} 个授权班级 · 点击班级可查看任务级进度、报名人次、截止时间与图表；不显示个人测评结果。<span v-if="isDemo">本地合成数据仅用于界面预览。</span>
      </footer>
    </AppCard>
  </main>
</template>

<style scoped>
.teacher-classes { display: grid; gap: 16px; padding-top: 0; padding-bottom: 56px; animation: page-in 220ms ease both; }
.teacher-page-heading { display: flex; align-items: center; gap: 13px; padding: 2px 0 4px; }
.teacher-page-heading__icon { display: grid; width: 42px; height: 42px; flex: 0 0 42px; place-items: center; border-radius: 13px; color: var(--color-primary-active); background: #e8f8fc; }
.teacher-page-heading h1 { margin: 0 0 4px; color: var(--color-text-primary); font-size: 22px; line-height: 1.2; }
.teacher-page-heading p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.5; }
.class-library { display: grid; gap: 14px; padding: 20px 22px 14px; }
.class-library__toolbar,.class-library__title,.class-library__actions { display: flex; align-items: center; gap: 12px; }
.class-library__toolbar { justify-content: space-between; }
.class-library__title { min-width: 0; }
.class-library__icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 12px; color: #117e9b; background: #e8f6f9; }
.class-library__title h2 { margin: 0 0 3px; color: var(--color-text-primary); font-size: 15px; }
.class-library__title p { margin: 0; color: var(--color-text-secondary); font-size: 11px; line-height: 1.5; }
.class-library__actions { flex: 0 0 auto; }
.class-library__search,.class-library__sort { display: flex; align-items: center; gap: 7px; min-height: 36px; padding: 0 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-button); color: var(--color-text-muted); background: var(--color-surface); }
.class-library__search input,.class-library__sort select { width: 112px; min-width: 0; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font: inherit; font-size: 11px; }
.class-library__search input::placeholder { color: var(--color-text-muted); }
.class-library__sort select { width: 84px; cursor: pointer; }
.class-library__search:focus-within,.class-library__sort:focus-within { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.class-library__state { display: grid; min-height: 130px; place-items: center; padding: 20px; border-radius: var(--radius-card); color: var(--color-text-secondary); background: var(--color-surface-soft); font-size: 12px; text-align: center; }
.class-library__message { margin: 0; }
.class-library__table-wrap { min-width: 0; overflow-x: auto; }
.class-library__table { width: 100%; border-collapse: collapse; text-align: left; }
.class-library__table th,.class-library__table td { padding: 14px 12px; border-top: 1px solid #edf0f2; vertical-align: middle; }
.class-library__table thead th { color: var(--color-text-muted); font-size: 10px; font-weight: 650; white-space: nowrap; }
.class-library__table tbody th { min-width: 150px; font-weight: 400; }
.class-library__name { display: block; color: var(--color-text-primary); font-size: 13px; font-weight: 650; }
.class-library__table small { display: block; margin-top: 4px; color: var(--color-text-muted); font-size: 10px; line-height: 1.5; }
.class-library__table td > strong { color: var(--color-text-primary); font-size: 14px; }
.class-library__unit { margin-left: 4px; color: var(--color-text-muted); font-size: 10px; }
.class-library__completion { display: flex; align-items: center; gap: 10px; min-width: 150px; }
.class-library__track { display: block; width: min(18vw, 150px); min-width: 80px; height: 6px; overflow: hidden; border-radius: 999px; background: #e2edef; }
.class-library__track > span { display: block; height: 100%; border-radius: inherit; background: #1e9caa; transition: width 180ms ease; }
.class-library__completion strong { color: #147f8e; font-size: 12px; font-variant-numeric: tabular-nums; }
.class-library__link { display: inline-flex; align-items: center; gap: 6px; color: var(--color-primary-active); font-size: 11px; font-weight: 650; text-decoration: none; white-space: nowrap; }
.class-library__link:hover { text-decoration: underline; text-underline-offset: 3px; }
.class-library__link:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 3px; border-radius: 3px; }
.class-library__footer { padding-top: 11px; border-top: 1px solid #edf0f2; color: var(--color-text-muted); font-size: 10px; text-align: right; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 560px) { .teacher-page-heading h1 { font-size: 20px; }.teacher-page-heading p { font-size: 12px; } }
@media (max-width: 850px) { .class-library__toolbar { align-items: flex-start; flex-direction: column; }.class-library__actions { width: 100%; }.class-library__search { flex: 1; }.class-library__search input { width: 100%; }.class-library__table td,.class-library__table th { padding-inline: 9px; } }
@media (max-width: 560px) { .class-library { padding: 16px 13px 12px; }.class-library__actions { flex-wrap: wrap; gap: 8px; }.class-library__table { min-width: 570px; }.class-library__table th,.class-library__table td { padding: 12px 9px; } }
</style>
