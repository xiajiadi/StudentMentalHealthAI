<script setup lang="ts">
import { LockKeyhole } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import StudentPageHero from '@/components/student/StudentPageHero.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
</script>

<template>
  <main class="content-wrap teacher-detail">
    <WorkspaceBreadcrumb
      homeLabel="教师工作区"
      homeTo="/teacher/overview"
      :parent="{ label: '任务进度', to: '/teacher/students' }"
      current="个体记录不可见"
    />
    <StudentPageHero
      eyebrow="教师工作区 · 隐私范围"
      title="个体记录不可见"
      subtitle="教师角色只查看获授权任务的整体完成进度。"
      image="/assets/psynova/student-page-heroes/feedback-hero.webp"
    />
    <AppStatusCallout
      tone="info"
      title="保护学生个人信息"
      body="此页面不会读取或展示个人测评状态、题目与作答、心理测量结果、教育支持对话、报告或复核内容。"
    />
    <AppCard class="unavailable-card">
      <span class="unavailable-card__icon"><LockKeyhole :size="19" aria-hidden="true" /></span>
      <div>
        <h2>请返回班级任务进度</h2>
        <p>当前项目没有可供教师查看的任务级安全汇总接口。单个主体的历史记录不会作为替代信息显示。</p>
      </div>
    </AppCard>
  </main>
</template>

<style scoped>
.teacher-detail { display: grid; gap: 16px; animation: page-in 240ms ease both; }
.teacher-detail :deep(.student-page-hero) { margin-bottom: 0; }
.unavailable-card { display: flex; align-items: flex-start; gap: 14px; padding: 22px; }
.unavailable-card__icon { display: grid; flex: 0 0 38px; width: 38px; height: 38px; place-items: center; border-radius: 9px; color: var(--color-attention); background: var(--color-attention-wash); }
.unavailable-card h2 { margin: 1px 0 0; color: var(--color-text-primary); font-size: 14px; }
.unavailable-card p { max-width: 720px; margin: 7px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
@media(max-width:600px) { .unavailable-card { padding: 18px; } }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
</style>
