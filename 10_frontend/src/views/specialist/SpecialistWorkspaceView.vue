<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search } from '@lucide/vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import WorkspaceTabs from '@/components/workspace/WorkspaceTabs.vue'
import SpecialistWorkspaceAtlas from './SpecialistWorkspaceAtlas.vue'
import {
  type SpecialistAtlasFocus,
} from './specialist-workspace-atlas'
import SpecialistTaskReviews from '@/components/school/SpecialistTaskReviews.vue'
import SpecialistResearchFeedback from '@/components/school/SpecialistResearchFeedback.vue'
import SpecialistResearchProgrammeCandidates from '@/components/school/SpecialistResearchProgrammeCandidates.vue'
import SpecialistIndependentEducationReviews from '@/components/school/SpecialistIndependentEducationReviews.vue'
import SpecialistCatManagement from '@/components/school/SpecialistCatManagement.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'
import SchoolResearchSourceCatalog from '@/components/school/SchoolResearchSourceCatalog.vue'
import SchoolConversationSafetyReviews from '@/components/school/SchoolConversationSafetyReviews.vue'
import { useSessionStore } from '@/stores/session'

type TaskGroup = 'professional' | 'education' | 'safety'
type TaskWorkflow = 'task-review' | 'research-feedback' | 'independent-education' | 'research-candidates' | 'safety-review'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const section = computed(() => String(route.params.section ?? 'overview'))
const specialistScopeKey = computed(() => [
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
].join('|'))

const page = computed(() => ({
  overview: { eyebrow: '心理专业工作区', title: '工作概览', intro: '八个功能入口，一步直达。' },
  resources: { eyebrow: '专业资料', title: '研究教育来源目录', intro: '查看固定来源包的公开元数据、权利记录和工程审核范围。' },
  tasks: { eyebrow: '专业工作事项', title: '复核与协作', intro: '按工作类型查看服务端允许访问的记录，并在对应流程中完成处理。' },
  cat: { eyebrow: 'CAT 工程管理', title: '测评方案与模拟', intro: '管理服务端配置的合成题库、方案和工程模拟。' },
}[section.value as 'overview' | 'resources' | 'tasks' | 'cat'] ?? { eyebrow: '心理专业工作区', title: '专业工作台', intro: '查看当前可用的专业工作入口。' }))

const taskGroup = ref<TaskGroup>('professional')
const taskWorkflow = ref<TaskWorkflow>('task-review')
const catPanel = ref<'laboratory' | 'research'>('laboratory')
const atlasRef = ref<InstanceType<typeof SpecialistWorkspaceAtlas> | null>(null)
const taskGroups = [
  { value: 'professional', label: '专业复核与反馈' },
  { value: 'education', label: '教育内容与候选' },
  { value: 'safety', label: '安全工作流' },
] as const
const workflowsByGroup: Record<TaskGroup, Array<{ value: TaskWorkflow; label: string }>> = {
  professional: [
    { value: 'task-review', label: '指派任务复核' },
    { value: 'research-feedback', label: '研究反馈' },
  ],
  education: [
    { value: 'independent-education', label: '独立教育内容' },
    { value: 'research-candidates', label: '研究项目候选' },
  ],
  safety: [
    { value: 'safety-review', label: '指派安全记录' },
  ],
}
const taskWorkflows = computed(() => workflowsByGroup[taskGroup.value])
const workflowComponent = computed(() => ({
  'task-review': SpecialistTaskReviews,
  'research-feedback': SpecialistResearchFeedback,
  'independent-education': SpecialistIndependentEducationReviews,
  'research-candidates': SpecialistResearchProgrammeCandidates,
  'safety-review': SchoolConversationSafetyReviews,
})[taskWorkflow.value])
const catTabs = [
  { value: 'laboratory', label: 'CAT 实验室' },
  { value: 'research', label: '研究管理' },
] as const

const workflowByFocus: Partial<Record<SpecialistAtlasFocus, { group: TaskGroup; workflow: TaskWorkflow }>> = {
  'task-reviews': { group: 'professional', workflow: 'task-review' },
  'research-feedback': { group: 'professional', workflow: 'research-feedback' },
  'education-review': { group: 'education', workflow: 'independent-education' },
  'research-candidates': { group: 'education', workflow: 'research-candidates' },
  'assigned-safety': { group: 'safety', workflow: 'safety-review' },
}
const focusByWorkflow: Record<TaskWorkflow, SpecialistAtlasFocus> = {
  'task-review': 'task-reviews',
  'research-feedback': 'research-feedback',
  'independent-education': 'education-review',
  'research-candidates': 'research-candidates',
  'safety-review': 'assigned-safety',
}

function applyRouteSelection() {
  const currentSection = section.value
  const rawFocus = route.query.focus
  const focus = typeof rawFocus === 'string' ? rawFocus : undefined
  const hasFocusParameter = rawFocus !== undefined

  if (currentSection === 'tasks') {
    if (hasFocusParameter) {
      const selection = focus && Object.prototype.hasOwnProperty.call(workflowByFocus, focus)
        ? workflowByFocus[focus as SpecialistAtlasFocus]
        : undefined
      if (selection) {
        taskGroup.value = selection.group
        taskWorkflow.value = selection.workflow
      } else {
        taskGroup.value = 'professional'
        taskWorkflow.value = 'task-review'
      }
      return
    }
    if (route.hash === '#education') {
      taskGroup.value = 'education'
      taskWorkflow.value = 'independent-education'
    } else if (route.hash === '#safety') {
      taskGroup.value = 'safety'
      taskWorkflow.value = 'safety-review'
    } else {
      taskGroup.value = 'professional'
      taskWorkflow.value = 'task-review'
    }
  }
  if (currentSection === 'cat') {
    if (hasFocusParameter) {
      catPanel.value = focus === 'research-management' ? 'research' : 'laboratory'
      return
    }
    catPanel.value = route.hash === '#research' ? 'research' : 'laboratory'
  }
}

watch([section, () => route.query.focus, () => route.hash], applyRouteSelection, { immediate: true })

async function syncFocus(focus: SpecialistAtlasFocus) {
  const currentFocus = Array.isArray(route.query.focus) ? route.query.focus[0] : route.query.focus
  if (currentFocus === focus && !route.hash) return
  await router.replace({
    path: route.path,
    query: { ...route.query, focus },
    hash: '',
  })
}

function updateTaskGroup(value: string) {
  if (!taskGroups.some((group) => group.value === value)) return
  const group = value as TaskGroup
  taskGroup.value = group
  const workflow = workflowsByGroup[group][0].value
  taskWorkflow.value = workflow
  void syncFocus(focusByWorkflow[workflow])
}

function updateTaskWorkflow(value: string) {
  if (!workflowsByGroup[taskGroup.value].some((workflow) => workflow.value === value)) return
  taskWorkflow.value = value as TaskWorkflow
  void syncFocus(focusByWorkflow[taskWorkflow.value])
}

function updateCatPanel(value: string) {
  if (value !== 'laboratory' && value !== 'research') return
  catPanel.value = value
  void syncFocus(value === 'research' ? 'research-management' : 'simulation')
}

function openAtlasQuickSearch() {
  atlasRef.value?.openPalette()
}

watch(specialistScopeKey, () => {
  taskGroup.value = 'professional'
  taskWorkflow.value = 'task-review'
  catPanel.value = 'laboratory'
  applyRouteSelection()
}, { flush: 'sync' })
</script>

<template>
  <main class="content-wrap specialist-workspace">
    <WorkspaceBreadcrumb :current="page.title" home-label="心理工作区" home-to="/specialist/overview" />
    <template v-if="section === 'overview'">
      <header class="specialist-overview-heading">
        <div>
          <h1>{{ page.title }}</h1>
          <p>{{ page.intro }}</p>
        </div>
        <button class="specialist-quick-trigger" type="button" @click="openAtlasQuickSearch">
          <Search :size="16" aria-hidden="true" />
          <span>快速直达</span>
          <kbd>Ctrl K</kbd>
        </button>
      </header>
      <SpecialistWorkspaceAtlas ref="atlasRef" />
    </template>

    <template v-else>
      <StudentPageHero
        class="specialist-page-hero"
        :eyebrow="page.eyebrow"
        :title="page.title"
        :subtitle="page.intro"
        image="/assets/heartbridge/hero-flow-original.png"
        image-position="right center"
      />

      <template v-if="section === 'resources'">
        <section class="specialist-resources" aria-label="研究教育来源目录">
          <SchoolResearchSourceCatalog />
        </section>
      </template>

      <template v-else-if="section === 'tasks'">
        <section class="specialist-task-workspace" aria-label="专业工作事项">
          <AppStatusCallout
            tone="info"
            title="每类事项使用独立工作流"
            body="切换工作类型只更换列表与详情界面，不会改变记录状态或自动发布学生可见反馈。"
          />
          <WorkspaceTabs :model-value="taskGroup" id="specialist-task-groups" label="专业工作类型" :tabs="taskGroups" @update:model-value="updateTaskGroup">
            <template #panel>
              <section class="specialist-task-workspace__group">
                <WorkspaceTabs :model-value="taskWorkflow" id="specialist-task-workflows" label="当前工作类型" :tabs="taskWorkflows" @update:model-value="updateTaskWorkflow">
                  <template #panel>
                    <div class="specialist-task-workspace__content">
                      <component :is="workflowComponent" :key="specialistScopeKey" />
                    </div>
                  </template>
                </WorkspaceTabs>
              </section>
            </template>
          </WorkspaceTabs>
        </section>
      </template>

      <template v-else-if="section === 'cat'">
        <section class="specialist-cat-workspace" aria-label="CAT 实验与研究管理">
          <WorkspaceTabs :model-value="catPanel" id="specialist-cat-tabs" label="CAT 管理功能" :tabs="catTabs" @update:model-value="updateCatPanel">
            <template #panel="{ tab }">
              <div class="specialist-cat-workspace__panel">
                <SpecialistCatManagement v-if="tab.value === 'laboratory'" :key="specialistScopeKey" />
                <SchoolResearchManagement v-else :key="specialistScopeKey" mode="specialist" />
              </div>
            </template>
          </WorkspaceTabs>
        </section>
      </template>
    </template>
  </main>
</template>

<style scoped>
.specialist-workspace { display: grid; gap: 18px; padding-top: 18px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.specialist-page-hero { margin-bottom: 0; }
.specialist-overview-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.specialist-overview-heading h1 { margin: 0; color: var(--color-text-primary); font-size: 24px; font-weight: 730; line-height: 1.3; }
.specialist-overview-heading p { margin: 5px 0 0; color: var(--color-text-muted); font-size: 13px; line-height: 1.5; }
.specialist-quick-trigger { display: inline-flex; min-height: 38px; flex: 0 0 auto; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #dfe7ed; border-radius: 9px; color: #4d6371; background: #fff; cursor: pointer; font: inherit; font-size: 12px; font-weight: 640; box-shadow: 0 2px 8px rgb(30 60 75 / 3%); transition: border-color 180ms ease, color 180ms ease, background-color 180ms ease; }
.specialist-quick-trigger:hover { border-color: #a7dce8; color: var(--color-primary-active); background: #f7fcfd; }
.specialist-quick-trigger:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.specialist-quick-trigger svg { color: var(--color-primary-active); }
.specialist-quick-trigger kbd { padding: 2px 5px; border: 1px solid #e1e8ed; border-radius: 5px; color: #7e8e99; background: #f8fafb; font-family: inherit; font-size: 9px; font-weight: 600; }
.specialist-task-workspace,.specialist-cat-workspace { display: grid; gap: 14px; min-width: 0; }
.specialist-task-workspace__group { display: grid; gap: 14px; min-width: 0; }
.specialist-task-workspace__content,.specialist-cat-workspace__panel,.specialist-resources { min-width: 0; }
.specialist-task-workspace__content:focus-visible,.specialist-task-workspace__group:focus-visible,.specialist-cat-workspace__panel:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 3px; border-radius: 10px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 640px) { .specialist-workspace { gap: 15px; padding-top: 14px; }.specialist-overview-heading { align-items: flex-start; }.specialist-overview-heading h1 { font-size: 21px; }.specialist-overview-heading p { max-width: 210px; font-size: 12px; }.specialist-quick-trigger { min-height: 35px; gap: 6px; padding: 0 8px; font-size: 11px; }.specialist-quick-trigger kbd { display: none; } }
@media (prefers-reduced-motion: reduce) { .specialist-workspace { animation: none; } }
</style>
