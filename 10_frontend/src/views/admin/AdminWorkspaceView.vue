<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRoute } from 'vue-router'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import AdminSchoolOperations from '@/components/school/AdminSchoolOperations.vue'
import AdminTaskDispatch from '@/components/school/AdminTaskDispatch.vue'
import AdminOperationsWorkspace from '@/components/school/AdminOperationsWorkspace.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'
import AdminOperationsDesk from '@/components/admin/AdminOperationsDesk.vue'
import AdminDirectoryStudio from '@/components/school/AdminDirectoryStudio.vue'
import AdminSystemHealth from '@/components/admin/AdminSystemHealth.vue'
import AccountLifecycleWorkspace from '@/views/admin/AccountLifecycleWorkspace.vue'
import { useSessionStore } from '@/stores/session'

const route = useRoute()
const session = useSessionStore()
const lifecycleWorkspace = ref<InstanceType<typeof AccountLifecycleWorkspace> | null>(null)
const schoolScopeKey = computed(() => [
  session.user?.userId ?? '', session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '', session.user?.activeContext?.role ?? '',
].join('|'))
const section = computed(() => String(route.params.section ?? 'overview'))
const pageTitle = computed(() => ({
  overview: '管理概览',
  users: '账号管理',
  tasks: '测评任务',
  audit: '运营事务',
  settings: '系统状态',
}[section.value as 'overview' | 'users' | 'tasks' | 'audit' | 'settings'] ?? '管理概览'))
const openCredentials = async () => {
  await nextTick()
  lifecycleWorkspace.value?.openCredentials()
}
</script>

<template>
  <main class="content-wrap admin-workspace" :class="{ 'admin-workspace--overview': section === 'overview', 'admin-workspace--tasks': section === 'tasks' }">
    <WorkspaceBreadcrumb :current="pageTitle" home-label="管理员工作区" home-to="/admin/overview" />
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
      <AccountLifecycleWorkspace ref="lifecycleWorkspace" :key="`${schoolScopeKey}-lifecycle`" />
      <details class="admin-directory-details">
        <summary>学校目录维护</summary>
        <AdminDirectoryStudio :key="schoolScopeKey" @open-credentials="openCredentials" />
      </details>
    </template>

    <template v-else>
      <template v-if="section === 'tasks'">
        <section class="admin-task-dispatch" aria-label="测评任务调度">
          <AdminTaskDispatch :key="schoolScopeKey" />
        </section>
      </template>

      <template v-else-if="section === 'audit'">
        <section class="admin-audit" aria-label="学校运营事务">
          <AdminOperationsWorkspace :key="schoolScopeKey" :scope-key="schoolScopeKey" />
        </section>
      </template>

      <template v-else>
        <section class="admin-settings" aria-label="系统状态">
          <AdminSystemHealth :key="schoolScopeKey" />
        </section>
      </template>
    </template>
  </main>
</template>

<style scoped>
.admin-workspace { padding-top: 30px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.admin-workspace--overview { padding-bottom: 28px; }
.admin-workspace--tasks { padding-bottom: 0; }
.admin-overview { min-width: 0; }
.admin-overview__workflow { margin-top: 36px; scroll-margin-top: calc(var(--layout-topbar) + 20px); }.admin-overview__workflow-heading { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; }.admin-overview__workflow-heading > span { color: #6f95a5; font-size: 10px; font-weight: 680; }.admin-overview__workflow-heading h2 { margin: 0; color: var(--color-text-primary); font-size: 19px; font-weight: 720; }
.admin-task-dispatch,.admin-audit,.admin-settings { display: grid; gap: 16px; min-width: 0; }
.admin-directory-details { margin: 20px 0; border-top: 1px solid var(--color-border); }.admin-directory-details > summary { padding: 14px 0; color: var(--color-text-secondary); cursor: pointer; font-size: 14px; }.admin-directory-details > summary:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:720px) { .admin-workspace { padding-top: 18px; }.admin-overview__workflow { margin-top: 28px; } }
</style>
