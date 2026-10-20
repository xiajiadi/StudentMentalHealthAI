<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import SpecialistWorkspaceAtlas from './SpecialistWorkspaceAtlas.vue'
import SpecialistTaskReviews from '@/components/school/SpecialistTaskReviews.vue'
import SpecialistResearchFeedback from '@/components/school/SpecialistResearchFeedback.vue'
import SpecialistResearchProgrammeCandidates from '@/components/school/SpecialistResearchProgrammeCandidates.vue'
import SpecialistIndependentEducationReviews from '@/components/school/SpecialistIndependentEducationReviews.vue'
import SpecialistCatWorkspace from '@/components/school/SpecialistCatWorkspace.vue'
import SpecialistFlowstage from '@/components/school/SpecialistFlowstage.vue'
import SchoolResearchSourceCatalog from '@/components/school/SchoolResearchSourceCatalog.vue'
import SchoolConversationSafetyReviews from '@/components/school/SchoolConversationSafetyReviews.vue'
import { useSessionStore } from '@/stores/session'
import {
  isSpecialistWorkflowKey,
  type SpecialistWorkflowKey,
} from './specialist-workflow-flowstage'

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
  resources: { eyebrow: '专业资料', title: '专业资料', intro: '研究来源、权利信息与专业引用目录' },
  tasks: { eyebrow: '专业工作事项', title: '专业工作事项', intro: '让复杂的专业工作，回到清晰的下一步。' },
  cat: { eyebrow: '心理工作区', title: 'CAT 实验室', intro: '题库管理、自适应测验工程模拟与研究配置' },
}[section.value as 'overview' | 'resources' | 'tasks' | 'cat'] ?? { eyebrow: '心理专业工作区', title: '专业工作台', intro: '查看当前可用的专业工作入口。' }))

const taskWorkflow = ref<SpecialistWorkflowKey>('task-reviews')
const workflowComponents: Record<SpecialistWorkflowKey, Component> = {
  'task-reviews': SpecialistTaskReviews,
  'research-feedback': SpecialistResearchFeedback,
  'education-review': SpecialistIndependentEducationReviews,
  'research-candidates': SpecialistResearchProgrammeCandidates,
  'assigned-safety': SchoolConversationSafetyReviews,
}
const workflowComponent = computed(() => workflowComponents[taskWorkflow.value])

function applyRouteSelection() {
  const currentSection = section.value
  const rawFocus = route.query.focus
  const focus = typeof rawFocus === 'string' ? rawFocus : undefined
  const hasFocusParameter = rawFocus !== undefined

  if (currentSection === 'tasks') {
    if (hasFocusParameter) {
      taskWorkflow.value = isSpecialistWorkflowKey(focus) ? focus : 'task-reviews'
      return
    }
    if (route.hash === '#education') {
      taskWorkflow.value = 'education-review'
    } else if (route.hash === '#safety') {
      taskWorkflow.value = 'assigned-safety'
    } else {
      taskWorkflow.value = 'task-reviews'
    }
  }
}

watch([section, () => route.query.focus, () => route.hash], applyRouteSelection, { immediate: true })

async function syncFocus(focus: SpecialistWorkflowKey) {
  const currentFocus = Array.isArray(route.query.focus) ? route.query.focus[0] : route.query.focus
  if (currentFocus === focus && !route.hash) return
  await router.push({
    path: route.path,
    query: { ...route.query, focus },
    hash: '',
  })
}

function updateTaskWorkflow(value: string) {
  if (!isSpecialistWorkflowKey(value)) return
  taskWorkflow.value = value
  void syncFocus(value)
}

watch(specialistScopeKey, () => {
  taskWorkflow.value = 'task-reviews'
  applyRouteSelection()
}, { flush: 'sync' })
</script>

<template>
  <main class="content-wrap specialist-workspace" :class="{ 'specialist-workspace--tasks': section === 'tasks' }">
    <WorkspaceBreadcrumb :current="page.title" home-label="心理工作区" home-to="/specialist/overview" />
    <template v-if="section === 'overview'">
      <SpecialistWorkspaceAtlas />
    </template>

    <template v-else>
      <StudentPageHero
        v-if="section !== 'resources' && section !== 'cat' && section !== 'tasks'"
        class="specialist-page-hero"
        :eyebrow="page.eyebrow"
        :title="page.title"
        :subtitle="page.intro"
        image="/assets/heartbridge/hero-flow-original.png"
        image-position="right center"
      />

      <template v-if="section === 'resources'">
        <section class="specialist-resources" aria-label="专业资料">
          <SchoolResearchSourceCatalog />
        </section>
      </template>

      <template v-else-if="section === 'tasks'">
        <SpecialistFlowstage
          :workflow="taskWorkflow"
          :workflow-component="workflowComponent"
          :scope-key="specialistScopeKey"
          @update:workflow="updateTaskWorkflow"
        />
      </template>

      <template v-else-if="section === 'cat'">
        <SpecialistCatWorkspace />
      </template>
    </template>
  </main>
</template>

<style scoped>
.specialist-workspace { display: grid; gap: 18px; padding-top: 18px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.specialist-workspace--tasks { gap: 8px; }
.specialist-workspace--tasks :deep(.workspace-breadcrumb) { margin-bottom: 0; }
.specialist-page-hero { margin-bottom: 0; }
.specialist-resources { min-width: 0; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 640px) { .specialist-workspace { gap: 15px; padding-top: 14px; }.specialist-workspace--tasks { gap: 8px; } }
@media (prefers-reduced-motion: reduce) { .specialist-workspace { animation: none; } }
</style>
