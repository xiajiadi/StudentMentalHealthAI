<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, BookOpenCheck, ClipboardCheck, FlaskConical, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import WorkspaceTabs from '@/components/workspace/WorkspaceTabs.vue'
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
const session = useSessionStore()
const section = computed(() => String(route.params.section ?? 'overview'))
const specialistScopeKey = computed(() => [
  session.user?.userId ?? '',
  session.role ?? '',
  session.user?.activeContext?.schoolRef ?? '',
  session.user?.activeContext?.role ?? '',
].join('|'))

const page = computed(() => ({
  overview: { eyebrow: '心理专业工作区', title: '专业工作台', intro: '从已授权的专业复核、资料目录和 CAT 工程入口继续工作。' },
  resources: { eyebrow: '专业资料', title: '研究教育来源目录', intro: '查看固定来源包的公开元数据、权利记录和工程审核范围。' },
  tasks: { eyebrow: '专业工作事项', title: '复核与协作', intro: '按工作类型查看服务端允许访问的记录，并在对应流程中完成处理。' },
  cat: { eyebrow: 'CAT 工程管理', title: '测评方案与模拟', intro: '管理服务端配置的合成题库、方案和工程模拟。' },
}[section.value as 'overview' | 'resources' | 'tasks' | 'cat'] ?? { eyebrow: '心理专业工作区', title: '专业工作台', intro: '查看当前可用的专业工作入口。' }))

const taskGroup = ref<TaskGroup>('professional')
const taskWorkflow = ref<TaskWorkflow>('task-review')
const catPanel = ref<'laboratory' | 'research'>('laboratory')
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

watch(taskGroup, (group) => {
  taskWorkflow.value = workflowsByGroup[group][0].value
}, { flush: 'sync' })

watch([section, () => route.hash], ([currentSection, hash]) => {
  if (currentSection === 'tasks') {
    if (hash === '#education') {
      taskGroup.value = 'education'
      taskWorkflow.value = 'independent-education'
    } else if (hash === '#safety') {
      taskGroup.value = 'safety'
      taskWorkflow.value = 'safety-review'
    } else {
      taskGroup.value = 'professional'
      taskWorkflow.value = 'task-review'
    }
  }
  if (currentSection === 'cat') catPanel.value = hash === '#research' ? 'research' : 'laboratory'
}, { immediate: true })

watch(specialistScopeKey, () => {
  taskGroup.value = 'professional'
  taskWorkflow.value = 'task-review'
  catPanel.value = 'laboratory'
}, { flush: 'sync' })
</script>

<template>
  <main class="content-wrap specialist-workspace">
    <WorkspaceBreadcrumb :current="page.title" home-label="心理工作区" home-to="/specialist/overview" />
    <StudentPageHero
      class="specialist-page-hero"
      :eyebrow="page.eyebrow"
      :title="page.title"
      :subtitle="page.intro"
      image="/assets/heartbridge/hero-flow-original.png"
      image-position="right center"
    />

    <template v-if="section === 'overview'">
      <section class="specialist-overview" aria-label="心理专业工作入口">
        <RouterLink class="specialist-entry specialist-entry--teal" to="/specialist/tasks#professional">
          <span class="specialist-entry__icon"><ClipboardCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-entry__state">按指派范围</span>
          <h2>专业复核与反馈</h2>
          <p>查看已指派的任务复核和研究反馈工作流。</p>
          <span class="specialist-entry__link">打开复核工作区 <ArrowRight :size="15" aria-hidden="true" /></span>
        </RouterLink>
        <RouterLink class="specialist-entry specialist-entry--blue" to="/specialist/tasks#education">
          <span class="specialist-entry__icon"><BookOpenCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-entry__state">教育内容</span>
          <h2>内容与研究候选</h2>
          <p>分别处理独立教育内容审核和研究项目候选。</p>
          <span class="specialist-entry__link">查看教育工作 <ArrowRight :size="15" aria-hidden="true" /></span>
        </RouterLink>
        <RouterLink class="specialist-entry specialist-entry--amber" to="/specialist/tasks#safety">
          <span class="specialist-entry__icon"><ShieldCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-entry__state">明确指派</span>
          <h2>安全工作流</h2>
          <p>只处理服务端指派给当前心理老师的安全记录。</p>
          <span class="specialist-entry__link">打开安全记录 <ArrowRight :size="15" aria-hidden="true" /></span>
        </RouterLink>
        <RouterLink class="specialist-entry specialist-entry--green" to="/specialist/resources">
          <span class="specialist-entry__icon"><BookOpenCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-entry__state">只读目录</span>
          <h2>专业资料</h2>
          <p>查阅来源元数据、权利记录和当前来源包范围。</p>
          <span class="specialist-entry__link">打开资料目录 <ArrowRight :size="15" aria-hidden="true" /></span>
        </RouterLink>
        <RouterLink class="specialist-entry specialist-entry--violet" to="/specialist/cat">
          <span class="specialist-entry__icon"><FlaskConical :size="19" aria-hidden="true" /></span>
          <span class="specialist-entry__state">工程配置</span>
          <h2>CAT 实验室</h2>
          <p>查看当前题库配置、运行工程模拟或进入研究管理。</p>
          <span class="specialist-entry__link">打开 CAT 工作区 <ArrowRight :size="15" aria-hidden="true" /></span>
        </RouterLink>
      </section>
      <AppCard class="specialist-boundary">
        <span class="specialist-boundary__icon"><ShieldCheck :size="19" aria-hidden="true" /></span>
        <div><span class="specialist-kicker">专业职责</span><h2>专业判断由人完成</h2><p>任务复核、研究反馈、教育内容审核和安全流程分别遵循各自的服务端状态。安全复核员的全局权限不会自动授予心理老师；教育反馈也不会因完成复核而自动发布。</p></div>
      </AppCard>
    </template>

    <template v-else-if="section === 'resources'">
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
        <WorkspaceTabs v-model="taskGroup" id="specialist-task-groups" label="专业工作类型" :tabs="taskGroups">
          <template #panel>
            <section class="specialist-task-workspace__group">
              <WorkspaceTabs v-model="taskWorkflow" id="specialist-task-workflows" label="当前工作类型" :tabs="taskWorkflows">
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
        <WorkspaceTabs v-model="catPanel" id="specialist-cat-tabs" label="CAT 管理功能" :tabs="catTabs">
          <template #panel="{ tab }">
            <div class="specialist-cat-workspace__panel">
              <SpecialistCatManagement v-if="tab.value === 'laboratory'" :key="specialistScopeKey" />
              <SchoolResearchManagement v-else :key="specialistScopeKey" mode="specialist" />
            </div>
          </template>
        </WorkspaceTabs>
      </section>
    </template>
  </main>
</template>

<style scoped>
.specialist-workspace { display: grid; gap: 18px; padding-top: 18px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.specialist-page-hero { margin-bottom: 0; }
.specialist-page-hero :deep(.student-page-hero__image) { opacity: .28; filter: saturate(.42); }
.specialist-page-hero :deep(.student-page-hero__shade) { background: rgb(244 249 246 / 82%); }
.specialist-overview { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 14px; }
.specialist-entry { position: relative; display: flex; min-width: 0; min-height: 202px; flex-direction: column; align-items: flex-start; padding: 19px; border: 1px solid #e1ebe6; border-radius: 15px; background: #fff; box-shadow: 0 5px 18px rgb(29 49 43 / 3%); color: inherit; text-decoration: none; transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease; }
.specialist-entry:hover { border-color: #c6ddd3; box-shadow: 0 10px 24px rgb(29 49 43 / 7%); transform: translateY(-2px); }
.specialist-entry:focus-visible { outline: 3px solid var(--color-focus-ring, #38a4bf); outline-offset: 3px; }
.specialist-entry__icon { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 12px; color: #247869; background: #eaf5f1; }
.specialist-entry--blue .specialist-entry__icon { color: #317c9a; background: #edf6f8; }
.specialist-entry--amber .specialist-entry__icon { color: #9a712d; background: #fbf5e8; }
.specialist-entry--green .specialist-entry__icon { color: #397c68; background: #edf6f0; }
.specialist-entry--violet .specialist-entry__icon { color: #6f6f9f; background: #f1f0fa; }
.specialist-entry__state { position: absolute; top: 20px; right: 18px; max-width: calc(100% - 85px); padding: 5px 8px; border-radius: 999px; color: #58736a; background: #f2f7f4; font-size: 11px; font-weight: 700; text-align: center; }
.specialist-entry h2 { margin: 15px 0 6px; color: var(--color-text-primary); font-size: 16px; line-height: 1.35; }
.specialist-entry p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.specialist-entry__link { display: inline-flex; align-items: center; gap: 6px; margin-top: auto; padding-top: 14px; color: #247869; font-size: 12px; font-weight: 720; }
.specialist-entry:hover .specialist-entry__link { text-decoration: underline; text-underline-offset: 3px; }
.specialist-boundary { display: flex; gap: 14px; padding: 19px 20px; }
.specialist-boundary__icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 12px; color: #317b94; background: #edf6f8; }
.specialist-kicker { color: #548275; font-size: 10px; font-weight: 760; }
.specialist-boundary h2 { margin: 4px 0; color: var(--color-text-primary); font-size: 15px; }
.specialist-boundary p { max-width: 900px; margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.specialist-task-workspace,.specialist-cat-workspace { display: grid; gap: 14px; min-width: 0; }
.specialist-task-workspace__group { display: grid; gap: 14px; min-width: 0; }
.specialist-task-workspace__content,.specialist-cat-workspace__panel,.specialist-resources { min-width: 0; }
.specialist-task-workspace__content:focus-visible,.specialist-task-workspace__group:focus-visible,.specialist-cat-workspace__panel:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 3px; border-radius: 10px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 1024px) { .specialist-overview { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 640px) { .specialist-workspace { gap: 15px; padding-top: 14px; }.specialist-overview { grid-template-columns: 1fr; gap: 11px; }.specialist-entry { min-height: 178px; padding: 16px; }.specialist-boundary { padding: 16px; } }
@media (prefers-reduced-motion: reduce) { .specialist-entry { transition-duration: .01ms; } }
</style>
