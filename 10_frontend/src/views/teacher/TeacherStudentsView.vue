<script setup lang="ts">
import { LockKeyhole } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
</script>

<template>
  <main class="content-wrap teacher-students">
    <WorkspaceBreadcrumb homeLabel="教师工作区" homeTo="/teacher/overview" current="任务进度" />
    <StudentPageHero
      eyebrow="教师工作区 · Scope A"
      title="任务进度"
      subtitle="仅查看获授权任务的整体完成情况。"
      image="/assets/psynova/student-page-heroes/assessment-hero.webp"
    />
    <AppStatusCallout
      tone="info"
      title="不开放个人测评历史"
      body="学生测评详情和逐人历史属于个人信息，不在教师 Scope A 的展示范围内。"
    />
    <AppCard class="unavailable-card">
      <span class="unavailable-card__icon"><LockKeyhole :size="19" aria-hidden="true" /></span>
      <div>
        <h2>任务级汇总接口暂不可用</h2>
        <p>当前 API 只提供按匿名主体分组的记录。待后端提供带授权校验和隐私保护的任务汇总后，此处才会显示完成进度。</p>
      </div>
    </AppCard>
  </main>
</template>

<style scoped>
.teacher-students { display: grid; gap: 16px; animation: page-in 240ms ease both; }
.teacher-students :deep(.student-page-hero) { margin-bottom: 0; }
.unavailable-card { display: flex; align-items: flex-start; gap: 14px; padding: 22px; }
.unavailable-card__icon { display: grid; flex: 0 0 38px; width: 38px; height: 38px; place-items: center; border-radius: 9px; color: var(--color-attention); background: var(--color-attention-wash); }
.unavailable-card h2 { margin: 1px 0 0; color: var(--color-text-primary); font-size: 14px; }
.unavailable-card p { max-width: 720px; margin: 7px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
@media(max-width:600px) { .unavailable-card { padding: 18px; } }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
</style>
