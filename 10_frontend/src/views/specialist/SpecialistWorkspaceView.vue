<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, BookOpenCheck, ClipboardCheck, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import SpecialistTaskReviews from '@/components/school/SpecialistTaskReviews.vue'
import SpecialistResearchFeedback from '@/components/school/SpecialistResearchFeedback.vue'
import SpecialistResearchProgrammeCandidates from '@/components/school/SpecialistResearchProgrammeCandidates.vue'
import SpecialistIndependentEducationReviews from '@/components/school/SpecialistIndependentEducationReviews.vue'
import SpecialistCatManagement from '@/components/school/SpecialistCatManagement.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'
import SchoolResearchSourceCatalog from '@/components/school/SchoolResearchSourceCatalog.vue'
import SchoolConversationSafetyReviews from '@/components/school/SchoolConversationSafetyReviews.vue'

const route = useRoute()
const section = computed(() => String(route.params.section ?? 'overview'))
const page = computed(() => ({
  overview: { eyebrow: '心理专业工作区', title: '专业支持与协作', intro: '查看专业资料边界与任务工作流入口。涉及个体判断的事项仍需由具备资质的人员依据已确认流程独立处理。' },
  resources: { eyebrow: '专业资料', title: '研究教育来源目录', intro: '查看当前固定来源包的公开文献信息、权利记录和工程审核边界。目录不构成心理、伦理或正式发布批准。' },
  tasks: { eyebrow: '工作事项', title: '任务专业复核', intro: '查看已指派任务中的完成记录。复核决定不会自动发布学生反馈，需在记录中单独起草和发布。' },
  cat: { eyebrow: 'CAT 工程管理', title: '测评方案与模拟', intro: '管理合成题库与方案，或运行工程模拟。结果尚待心理学验证。' },
}[section.value as 'overview' | 'resources' | 'tasks' | 'cat'] ?? { eyebrow: '心理专业工作区', title: '专业支持与协作', intro: '查看当前可用的资料与工作入口。' }))
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

    <AppStatusCallout
      tone="info"
      title="专业判断由人完成；当前仅为合成演示工作区"
      body="此页面不含真实学生资料。系统不会替代专业人员作判断，也不会把演示内容当作个案资料；心理学审核、内容权利确认和真实研究许可均为独立流程，界面状态不构成任何批准。"
    />

    <template v-if="section === 'overview'">
      <section class="specialist-grid" aria-label="专业工作区功能状态">
        <AppCard class="specialist-card">
          <span class="specialist-card__icon specialist-card__icon--teal"><BookOpenCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-card__state">只读来源目录</span>
          <h2>专业资料</h2><p>查看固定研究来源包的来源、权利记录和审核限制；不展示来源片段正文。</p>
          <RouterLink to="/specialist/resources">查看来源目录 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
        </AppCard>
        <AppCard class="specialist-card">
          <span class="specialist-card__icon"><ClipboardCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-card__state">任务范围</span>
          <h2>专业工作事项</h2><p>查看已指派任务的完成记录并记录工作流状态；此操作不会发布学生报告。</p>
          <RouterLink to="/specialist/tasks">进入任务工作区 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
        </AppCard>
      </section>
      <AppCard class="specialist-boundary">
        <span class="specialist-boundary__icon"><ShieldCheck :size="19" aria-hidden="true" /></span>
        <div><span class="specialist-kicker">角色边界</span><h2>专业协作与安全复核是不同权限</h2><p>全局安全复核队列仍由“安全复核员（REVIEWER）”角色负责。心理老师只会看到后端当前指派给自己的对话安全流程摘要；流程标记不构成诊断或专业结论。</p></div>
      </AppCard>
    </template>

    <template v-else-if="section === 'resources'">
      <SchoolResearchSourceCatalog />
    </template>

    <template v-else-if="section === 'tasks'">
      <div class="specialist-workflow-stack">
        <SchoolConversationSafetyReviews />
        <SpecialistTaskReviews />
        <SpecialistResearchFeedback />
        <SpecialistIndependentEducationReviews />
        <SpecialistResearchProgrammeCandidates />
      </div>
    </template>
    <template v-else-if="section === 'cat'">
      <div class="specialist-workflow-stack">
        <SpecialistCatManagement />
        <SchoolResearchManagement mode="specialist" />
      </div>
    </template>
  </main>
</template>

<style scoped>
.specialist-workspace { display: grid; gap: 18px; padding-top: 18px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.specialist-page-hero { margin-bottom: 0; }
.specialist-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.specialist-card { position: relative; min-height: 173px; padding: 20px; }
.specialist-card__icon { display: grid; width: 40px; height: 40px; place-items: center; border-radius: 12px; color: #117e9b; background: #e8f6f9; }
.specialist-card__icon--teal { color: #218a8a; background: #e8f6f4; }
.specialist-card__state { position: absolute; top: 20px; right: 18px; padding: 6px 9px; border-radius: 999px; color: #865b13; background: #fbf2de; font-size: 11px; font-weight: 700; }
.specialist-card h2,.specialist-status-card h2 { margin: 14px 0 6px; color: var(--color-text-primary); font-size: 15px; }
.specialist-card p,.specialist-status-card p { max-width: 590px; margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.specialist-card a { display: inline-flex; align-items: center; gap: 6px; margin-top: 15px; color: #117e9b; font-size: 12px; font-weight: 700; }
.specialist-card a:hover { text-decoration: underline; text-underline-offset: 3px; }
.specialist-boundary { display: flex; gap: 14px; padding: 20px; }
.specialist-boundary__icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border-radius: 12px; color: #117e9b; background: #e8f6f9; }
.specialist-boundary h2,.specialist-resource-note h2,.specialist-blocked h2 { margin: 6px 0; color: var(--color-text-primary); font-size: 15px; }
.specialist-boundary p,.specialist-resource-note p,.specialist-blocked p { max-width: 780px; margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.specialist-workflow-stack { display: grid; gap: 18px; min-width: 0; }
.specialist-status-card { display: flex; align-items: flex-start; gap: 14px; padding: 20px; }
.specialist-status-card .specialist-card__state { position: static; display: inline-block; }
.specialist-status-card h2 { margin-top: 8px; }
.specialist-resource-note { display: flex; align-items: center; justify-content: space-between; gap: 20px; min-height: 180px; margin-top: 14px; padding: 22px; overflow: hidden; border: 1px solid #dcebe5; border-radius: 15px; background: #f0f7f4; }
.specialist-resource-note > div { max-width: 620px; }
.specialist-resource-note img { width: min(28%, 155px); max-height: 145px; object-fit: contain; }
.specialist-blocked { display: flex; gap: 14px; margin-bottom: 14px; padding: 21px; }
.specialist-blocked__icon { display: grid; width: 42px; height: 42px; flex: 0 0 42px; place-items: center; border-radius: 12px; color: #9b6a1b; background: #fbf1dc; }
.specialist-blocked h2 { margin-top: 7px; }
.specialist-blocked__foot { display: block; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 11px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:720px) {
  .specialist-workspace { gap: 15px; padding-top: 14px; }
  .specialist-grid { grid-template-columns: 1fr; }
  .specialist-resource-note { min-height: 0; }
  .specialist-resource-note img { width: 92px; }
  .specialist-status-card,.specialist-blocked { padding: 16px; }
}
</style>
