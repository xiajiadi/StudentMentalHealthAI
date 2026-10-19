<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Activity, ArrowRight, Building2, CircleHelp, RefreshCw } from '@lucide/vue'
import type { DependencyStatusDto } from '@/api/generated/types.gen'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import WorkspaceTabs from '@/components/workspace/WorkspaceTabs.vue'
import AdminSchoolOperations from '@/components/school/AdminSchoolOperations.vue'
import AdminOperationsAudit from '@/components/school/AdminOperationsAudit.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'
import SafetyAssignments from '@/components/school/SafetyAssignments.vue'
import AdminOperationsDesk from '@/components/admin/AdminOperationsDesk.vue'
import AdminDirectoryStudio from '@/components/school/AdminDirectoryStudio.vue'
import { readDependencyHealth } from '@/views/admin/health'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const session = useSessionStore()
const schoolScopeKey = computed(() => [
  session.user?.userId ?? '', session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '', session.user?.activeContext?.role ?? '',
].join('|'))
const section = computed(() => String(route.params.section ?? 'overview'))
const auditTab = ref<'assignments' | 'records'>('assignments')
const auditTabs = [
  { value: 'assignments', label: '待处理事项' },
  { value: 'records', label: '操作记录' },
] as const
const healthState = ref<'loading' | 'ready' | 'error'>('loading')
const dependencies = ref<Record<string, DependencyStatusDto>>({})
const page = computed(() => ({
  overview: { eyebrow: '学校管理空间', title: '管理概览', intro: '学校事务，从这里开始。' },
  users: { eyebrow: '学校组织与人员目录', title: '班级与账号', intro: '有序管理学校组织与人员，减少重复操作。' },
  tasks: { eyebrow: '学校任务管理', title: '测评任务', intro: '在同一工作区设置班级、配置和时间，并查看服务端返回的任务记录。' },
  audit: { eyebrow: '学校运营事务', title: '运营事务', intro: '处理待分配事项，或查看能够验证本校归属的操作记录。' },
  settings: { eyebrow: '系统状态', title: '服务健康目录', intro: '查看健康端点当前返回的依赖状态和集成说明。' },
}[section.value as 'overview' | 'users' | 'tasks' | 'audit' | 'settings'] ?? { eyebrow: '学校管理空间', title: '管理概览', intro: '查看本地服务公开的依赖能力状态。' }))
const healthRows = computed(() => Object.entries(dependencies.value ?? {}).map(([name, value]) => ({ name, status: value.status, integration: value.integration })))
const healthSummary = computed(() => ({
  total: healthRows.value.length,
  available: healthRows.value.filter((item) => item.status === 'READY' || item.status === 'AVAILABLE').length,
  unavailable: healthRows.value.filter((item) => item.status === 'UNAVAILABLE').length,
  other: healthRows.value.filter((item) => !['READY', 'AVAILABLE', 'UNAVAILABLE'].includes(item.status)).length,
}))
const healthLabel = (status: string) => status === 'READY' || status === 'AVAILABLE' ? '可用' : status === 'UNAVAILABLE' ? '不可用' : status === 'DEFERRED' ? '未配置' : status === 'DISABLED' ? '已关闭' : status || '未知'
const healthTone = (status: string) => status === 'READY' || status === 'AVAILABLE' ? 'health-row__status--ready' : status === 'UNAVAILABLE' ? 'health-row__status--down' : 'health-row__status--unknown'

const loadHealth = async () => {
  healthState.value = 'loading'
  try {
    const result = await readDependencyHealth()
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('依赖状态响应格式无法识别。')
    dependencies.value = result
    healthState.value = 'ready'
  } catch {
    dependencies.value = {}
    healthState.value = 'error'
  }
}

watch([section, () => route.hash], ([value, hash]) => {
  if (value === 'settings') void loadHealth()
  if (value === 'audit') auditTab.value = hash === '#operations-audit' ? 'records' : 'assignments'
}, { immediate: true })
</script>

<template>
  <main class="content-wrap admin-workspace" :class="{ 'admin-workspace--overview': section === 'overview' }">
    <WorkspaceBreadcrumb :current="page.title" home-label="学校管理员" home-to="/admin/overview" />
    <template v-if="section === 'overview'">
      <section class="admin-overview" aria-label="管理概览">
        <AdminOperationsDesk :key="schoolScopeKey" />

        <section v-if="route.hash === '#admin-school-operations'" id="admin-school-operations" class="admin-overview__workflow" aria-labelledby="admin-overview-tasks-title">
          <div class="admin-overview__workflow-heading"><span>本校工作流程</span><h2 id="admin-overview-tasks-title">测评任务与人员分配</h2></div>
          <AdminSchoolOperations :key="schoolScopeKey" />
        </section>

        <section v-if="route.hash === '#admin-research-management'" id="admin-research-management" class="admin-overview__workflow" aria-labelledby="admin-overview-research-title">
          <div class="admin-overview__workflow-heading"><span>现有研究管理流程</span><h2 id="admin-overview-research-title">研究班级任务管理</h2></div>
          <SchoolResearchManagement :key="schoolScopeKey" mode="admin" />
        </section>
      </section>
    </template>

    <template v-else-if="section === 'users'">
      <AdminDirectoryStudio :key="schoolScopeKey" />
    </template>

    <template v-else>
      <StudentPageHero
        :eyebrow="page.eyebrow"
        :title="page.title"
        :subtitle="page.intro"
        image="/assets/heartbridge/card-admin-original.png"
        image-position="center 48%"
      />

      <template v-if="section === 'tasks'">
        <section class="admin-task-dispatch" aria-label="测评任务调度">
          <AppStatusCallout tone="info" title="任务发布" body="班级、可用配置和任务状态来自服务端。发布后以服务端确认及任务列表为准。" />
          <AdminSchoolOperations :key="schoolScopeKey" mode="tasks" />
        </section>
      </template>

      <template v-else-if="section === 'audit'">
        <section class="admin-audit" aria-label="学校运营事务">
          <AppStatusCallout tone="info" title="按事务类型查看" body="待处理安全事项和学校运营记录仍由各自的服务端工作流管理。" />
          <WorkspaceTabs v-model="auditTab" id="admin-audit-tabs" label="运营事务类型" :tabs="auditTabs">
            <template #panel="{ tab }">
              <section class="admin-audit__panel">
                <SafetyAssignments v-if="tab.value === 'assignments'" :key="schoolScopeKey" />
                <AdminOperationsAudit v-else :key="schoolScopeKey" :scope-key="schoolScopeKey" />
              </section>
            </template>
          </WorkspaceTabs>
        </section>
      </template>

      <template v-else>
        <section class="admin-settings" aria-label="服务健康目录">
          <AppCard class="health-panel">
            <div class="health-panel__heading">
              <span class="health-panel__icon"><Activity :size="19" aria-hidden="true" /></span>
              <div><span class="health-panel__eyebrow">服务端只读状态</span><h2>依赖能力</h2><p>由 GET /health/dependencies 返回；此页不计算运行时长或总体健康百分比。</p></div>
              <button class="health-refresh" type="button" :disabled="healthState === 'loading'" @click="loadHealth"><RefreshCw :size="15" aria-hidden="true" />刷新状态</button>
            </div>
            <div v-if="healthState === 'loading'" class="health-message" role="status" aria-live="polite" aria-busy="true">正在读取服务端状态…</div>
            <div v-else-if="healthState === 'error'" class="health-message health-message--error" role="status"><CircleHelp :size="17" aria-hidden="true" /><span>健康端点暂不可用；当前各项状态均未知。刷新成功后再显示最新状态。</span></div>
            <template v-else-if="healthRows.length">
              <dl class="health-summary" aria-label="依赖状态汇总">
                <div><dt>依赖条目</dt><dd>{{ healthSummary.total }}</dd></div>
                <div><dt>可用</dt><dd>{{ healthSummary.available }}</dd></div>
                <div><dt>不可用</dt><dd>{{ healthSummary.unavailable }}</dd></div>
                <div><dt>其他状态</dt><dd>{{ healthSummary.other }}</dd></div>
              </dl>
              <div class="health-list" aria-label="服务端返回的依赖列表">
                <details v-for="item in healthRows" :key="item.name" class="health-row">
                  <summary>
                    <span class="health-row__name">{{ item.name.replaceAll('_', ' ') }}</span>
                    <span class="health-row__integration">{{ item.integration || '集成说明暂缺' }}</span>
                    <span class="health-row__status" :class="healthTone(item.status)"><i aria-hidden="true"></i>{{ healthLabel(item.status) }}</span>
                  </summary>
                  <div class="health-row__detail"><span>集成说明</span><p>{{ item.integration || '服务端未提供集成说明。' }}</p></div>
                </details>
              </div>
            </template>
            <div v-else class="health-message" role="status">健康端点未返回依赖条目，当前没有可展示的服务状态。</div>
          </AppCard>

          <AppCard class="health-disclosure">
            <div><span class="health-disclosure__eyebrow">运营工作流</span><h2>待分配安全事项</h2><p>从运营事务页进入待处理事项。当前页面不提供服务启停、重启或数据库维护操作。</p></div>
            <RouterLink to="/admin/audit#safety-assignments">打开待处理事项 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
          </AppCard>
          <AppCard class="health-scope"><Building2 :size="18" aria-hidden="true" /><p>服务状态仅描述健康端点当前返回的依赖信息；它不代表心理学审核、测量学验证或生产就绪。</p></AppCard>
        </section>
      </template>
    </template>
  </main>
</template>

<style scoped>
.admin-workspace { padding-top: 30px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.admin-workspace--overview { padding-bottom: 28px; }
.admin-overview { min-width: 0; }
.admin-overview__workflow { margin-top: 36px; scroll-margin-top: calc(var(--layout-topbar) + 20px); }.admin-overview__workflow-heading { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }.admin-overview__workflow-heading > span { color: #6f95a5; font-size: 10px; font-weight: 680; }.admin-overview__workflow-heading h2 { margin: 0; color: var(--color-text-primary); font-size: 19px; font-weight: 720; }
.admin-task-dispatch,.admin-audit,.admin-settings { display: grid; gap: 16px; min-width: 0; }
.admin-audit__panel { min-width: 0; }
.health-panel { padding: 21px; }
.health-panel__heading { display: flex; align-items: center; gap: 13px; }
.health-panel__icon { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 12px; color: #287d70; background: #eaf5f1; }
.health-panel__heading > div { min-width: 0; }
.health-panel__heading h2 { margin: 3px 0 4px; color: var(--color-text-primary); font-size: 17px; }
.health-panel__heading p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.health-panel__eyebrow,.health-disclosure__eyebrow { color: #548275; font-size: 10px; font-weight: 760; letter-spacing: .04em; }
.health-refresh { display: inline-flex; align-items: center; gap: 6px; min-height: 37px; margin-left: auto; padding: 0 12px; border: 1px solid var(--color-border); border-radius: 9px; color: var(--color-text-secondary); background: white; cursor: pointer; font: inherit; font-size: 12px; font-weight: 650; white-space: nowrap; }
.health-refresh:hover:not(:disabled) { border-color: #b8d6cd; color: #286c5d; background: #f8fbf9; }
.health-refresh:disabled { opacity: .6; cursor: wait; }
.health-summary { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 9px; margin: 19px 0 0; }
.health-summary > div { min-width: 0; padding: 13px 14px; border: 1px solid #e7eee9; border-radius: 11px; background: #fafcfb; }
.health-summary dt { color: var(--color-text-muted); font-size: 11px; }
.health-summary dd { margin: 7px 0 0; color: #315e51; font-size: 22px; font-variant-numeric: tabular-nums; font-weight: 720; }
.health-list { margin-top: 17px; border-top: 1px solid var(--color-border); }
.health-row { border-bottom: 1px solid var(--color-border); }
.health-row summary { display: grid; grid-template-columns: minmax(120px,.68fr) minmax(0,1.35fr) 100px 24px; align-items: center; gap: 12px; min-height: 56px; list-style: none; cursor: pointer; }
.health-row summary::-webkit-details-marker { display: none; }
.health-row summary::after { grid-column: 4; content: '＋'; color: #789088; font-size: 16px; }
.health-row[open] summary::after { content: '−'; }
.health-row__name { color: var(--color-text-primary); font-size: 13px; font-weight: 690; text-transform: capitalize; overflow-wrap: anywhere; }
.health-row__integration { overflow: hidden; color: var(--color-text-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.health-row__status { display: inline-flex; align-items: center; justify-self: end; gap: 6px; font-size: 11px; font-weight: 750; white-space: nowrap; }
.health-row__status i { width: 7px; height: 7px; border-radius: 50%; background: currentcolor; }
.health-row__status--ready { color: #287765; }.health-row__status--down { color: #ac392d; }.health-row__status--unknown { color: #9b6a1b; }
.health-row__detail { display: grid; grid-template-columns: 100px minmax(0,1fr); gap: 12px; padding: 0 16px 16px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.health-row__detail span { color: var(--color-text-muted); font-weight: 650; }.health-row__detail p { margin: 0; }
.health-message { display: flex; align-items: center; gap: 9px; min-height: 64px; margin-top: 16px; padding: 15px; border-radius: 10px; color: var(--color-text-secondary); background: #f7f8f9; font-size: 13px; line-height: 1.55; }
.health-message--error { color: #8f651d; background: #fcf7eb; }
.health-disclosure { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 0; padding: 19px 21px; }
.health-disclosure h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 15px; }.health-disclosure p { margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.health-disclosure a { display: inline-flex; align-items: center; gap: 6px; flex: 0 0 auto; padding: 9px 12px; border: 1px solid #d5e6df; border-radius: 9px; color: #286c5d; background: #f7fbf8; font-size: 12px; font-weight: 700; text-decoration: none; }
.health-disclosure a:focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 2px; }
.health-scope { display: flex; align-items: flex-start; gap: 10px; padding: 14px 17px; color: #6d7c88; }.health-scope p { margin: 0; font-size: 12px; line-height: 1.65; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:720px) { .admin-workspace { padding-top: 18px; }.admin-overview__workflow { margin-top: 28px; }.health-panel { padding: 16px; }.health-panel__heading { align-items: flex-start; flex-wrap: wrap; }.health-refresh { margin-left: 52px; }.health-summary { grid-template-columns: repeat(2,minmax(0,1fr)); }.health-row summary { grid-template-columns: minmax(0,1fr) auto; gap: 5px 10px; padding: 9px 0; }.health-row__integration { grid-column: 1; }.health-row__status { grid-column: 2; grid-row: 1 / span 2; }.health-row summary::after { grid-column: 2; grid-row: 3; justify-self: end; }.health-row__detail { grid-template-columns: 1fr; gap: 4px; padding: 0 4px 14px; }.health-disclosure { align-items: flex-start; flex-direction: column; padding: 16px; } }
</style>
