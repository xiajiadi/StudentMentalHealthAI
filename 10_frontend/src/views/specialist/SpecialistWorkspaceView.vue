<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, BookOpenCheck, ClipboardCheck, LockKeyhole, Scale, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import SpecialistTaskReviews from '@/components/school/SpecialistTaskReviews.vue'
import SpecialistResearchFeedback from '@/components/school/SpecialistResearchFeedback.vue'
import SpecialistResearchProgrammeCandidates from '@/components/school/SpecialistResearchProgrammeCandidates.vue'
import SpecialistCatManagement from '@/components/school/SpecialistCatManagement.vue'
import SchoolResearchManagement from '@/components/school/SchoolResearchManagement.vue'

const route = useRoute()
const section = computed(() => String(route.params.section ?? 'overview'))
const page = computed(() => ({
  overview: { eyebrow: '心理专业工作区', title: '专业支持与协作', intro: '查看专业资料边界与任务工作流入口。涉及个体判断的事项仍需由具备资质的人员依据已确认流程独立处理。' },
  resources: { eyebrow: '专业资料', title: '资料使用边界', intro: '资料审核与使用权限尚未在此工作区接通；当前页面不提供个体化建议或资料发布操作。' },
  tasks: { eyebrow: '工作事项', title: '任务专业复核', intro: '查看已指派任务中的完成记录。复核决定不会自动发布学生反馈，需在记录中单独起草和发布。' },
  cat: { eyebrow: 'CAT 工程管理', title: '测评方案与模拟', intro: '管理合成题库与方案，或运行工程模拟。结果尚待心理学验证。' },
}[section.value as 'overview' | 'resources' | 'tasks' | 'cat'] ?? { eyebrow: '心理专业工作区', title: '专业支持与协作', intro: '查看当前可用的资料与工作入口。' }))
</script>

<template>
  <main class="content-wrap specialist-workspace">
    <section class="specialist-hero" aria-labelledby="specialist-title">
      <img class="specialist-hero__flow" :src="'/assets/heartbridge/hero-flow-original.png'" alt="" aria-hidden="true">
      <div class="specialist-hero__copy">
        <span class="specialist-kicker">HEARTBRIDGE · 专业协作</span>
        <h1 id="specialist-title">让专业判断<br>始终留在人手中。</h1>
        <p>这里用于查看专业协作功能的接入状态。系统不会替代专业人员作判断，也不会把演示内容当作个案资料。</p>
        <div class="specialist-hero__tags"><span><Scale :size="15" aria-hidden="true" />人工判断优先</span><span><LockKeyhole :size="15" aria-hidden="true" />当前仅限演示</span></div>
      </div>
      <figure class="specialist-hero__art"><img :src="'/assets/heartbridge/card-specialist-original.png'" alt="" aria-hidden="true"><figcaption>专业支持协作空间</figcaption></figure>
    </section>

    <AppPageHeader class="specialist-heading" :eyebrow="page.eyebrow" :title="page.title" :intro="page.intro" />

    <template v-if="section === 'overview'">
      <AppStatusCallout tone="info" title="当前为合成演示工作区" body="此页面不含真实学生资料。心理学审核、内容权利确认和真实研究许可均为独立流程，界面状态不构成任何批准。" />
      <section class="specialist-grid" aria-label="专业工作区功能状态">
        <AppCard class="specialist-card">
          <span class="specialist-card__icon specialist-card__icon--teal"><BookOpenCheck :size="19" aria-hidden="true" /></span>
          <span class="specialist-card__state">待审核与接入</span>
          <h2>专业资料</h2><p>资料目录、来源权限与审核状态尚未连入此页面。</p>
          <RouterLink to="/specialist/resources">查看资料边界 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
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
        <div><span class="specialist-kicker">角色边界</span><h2>专业协作与安全复核是不同权限</h2><p>安全复核由单独的“安全复核员（REVIEWER）”角色及其后端权限负责。本角色没有安全队列或审核结论权限；也不会据此显示任何个案。</p></div>
      </AppCard>
    </template>

    <template v-else-if="section === 'resources'">
      <SchoolResearchManagement mode="specialist" />
    </template>

    <template v-else-if="section === 'tasks'">
      <SpecialistTaskReviews />
      <SpecialistResearchFeedback />
      <SpecialistResearchProgrammeCandidates />
    </template>
    <SpecialistCatManagement v-else-if="section === 'cat'" />
  </main>
</template>

<style scoped>
.specialist-workspace { padding-top: 26px; padding-bottom: 56px; animation: page-in 220ms ease both; }
.specialist-hero { position: relative; display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(230px, .8fr); align-items: center; min-height: 300px; overflow: hidden; padding: clamp(23px, 4vw, 42px); border: 1px solid #d7e8e2; border-radius: 20px; background: linear-gradient(112deg, #eef7f4 0%, #f8faf8 57%, #e9f3ef 100%); }
.specialist-hero__flow { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .13; pointer-events: none; }
.specialist-hero__copy { position: relative; z-index: 1; max-width: 570px; }.specialist-kicker { color: #438174; font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.specialist-hero h1 { margin: 14px 0 12px; color: #263e39; font-family: var(--font-display); font-size: clamp(30px, 4vw, 43px); font-weight: 650; letter-spacing: -.04em; line-height: 1.2; }
.specialist-hero__copy > p { max-width: 450px; margin: 0; color: #556b64; font-size: 13px; line-height: 1.8; }.specialist-hero__tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 19px; }.specialist-hero__tags span { display: inline-flex; align-items: center; gap: 6px; padding: 7px 10px; border: 1px solid rgb(79 131 115 / 16%); border-radius: 999px; color: #42665c; background: rgb(255 255 255 / 65%); font-size: 10px; font-weight: 700; }
.specialist-hero__art { position: relative; justify-self: end; width: min(100%, 240px); margin: 0; text-align: center; }.specialist-hero__art img { display: block; width: 100%; max-height: 195px; object-fit: contain; }.specialist-hero__art figcaption { margin-top: 5px; color: #648077; font-size: 10px; }
.specialist-heading { margin-top: 30px; }.specialist-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; margin-top: 15px; }.specialist-card { position: relative; min-height: 173px; padding: 18px; }.specialist-card__icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 11px; color: #167e9b; background: #e8f6f9; }.specialist-card__icon--teal { color: #388576; background: #e8f4ef; }.specialist-card__state { position: absolute; top: 19px; right: 16px; padding: 5px 8px; border-radius: 999px; color: #996517; background: #fbf2de; font-size: 10px; font-weight: 750; }.specialist-card h2,.specialist-status-card h2 { margin: 13px 0 5px; color: var(--color-text-primary); font-size: 14px; }.specialist-card p,.specialist-status-card p { max-width: 590px; margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.65; }.specialist-card a { display: inline-flex; align-items: center; gap: 5px; margin-top: 14px; color: #167e9b; font-size: 11px; font-weight: 750; }.specialist-card a:hover { text-decoration: underline; text-underline-offset: 3px; }
.specialist-boundary { display: flex; gap: 13px; margin-top: 14px; padding: 19px; }.specialist-boundary__icon { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border-radius: 10px; color: #167e9b; background: #e8f6f9; }.specialist-boundary h2,.specialist-resource-note h2,.specialist-blocked h2 { margin: 6px 0; color: var(--color-text-primary); font-size: 15px; }.specialist-boundary p,.specialist-resource-note p,.specialist-blocked p { max-width: 780px; margin: 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
.specialist-status-card { display: flex; align-items: flex-start; gap: 14px; padding: 20px; }.specialist-status-card .specialist-card__state { position: static; display: inline-block; }.specialist-status-card h2 { margin-top: 8px; }.specialist-resource-note { display: flex; align-items: center; justify-content: space-between; gap: 20px; min-height: 180px; margin-top: 14px; padding: 22px; overflow: hidden; border: 1px solid #dcebe5; border-radius: 15px; background: #f0f7f4; }.specialist-resource-note > div { max-width: 620px; }.specialist-resource-note img { width: min(28%, 155px); max-height: 145px; object-fit: contain; }.specialist-blocked { display: flex; gap: 14px; margin-bottom: 14px; padding: 21px; }.specialist-blocked__icon { display: grid; width: 42px; height: 42px; flex: 0 0 42px; place-items: center; border-radius: 12px; color: #9b6a1b; background: #fbf1dc; }.specialist-blocked h2 { margin-top: 7px; }.specialist-blocked__foot { display: block; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 10px; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:720px) { .specialist-workspace { padding-top: 18px; }.specialist-hero { grid-template-columns: 1fr; min-height: 0; }.specialist-hero__art { display: none; }.specialist-grid { grid-template-columns: 1fr; }.specialist-heading { margin-top: 24px; }.specialist-resource-note { min-height: 0; }.specialist-resource-note img { width: 92px; }.specialist-status-card,.specialist-blocked { padding: 16px; } }
</style>
