<script setup lang="ts">
import { LockKeyhole } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
</script>

<template>
  <main class="content-wrap teacher-students">
    <AppPageHeader eyebrow="教师工作区" title="任务进度" intro="教师视图仅提供获授权的任务级整体进度。" />
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
.teacher-students { animation: page-in 240ms ease both; }
.unavailable-card { display: flex; align-items: flex-start; gap: 13px; margin-top: 17px; padding: 20px; }
.unavailable-card__icon { display: grid; flex: 0 0 38px; width: 38px; height: 38px; place-items: center; border-radius: 9px; color: var(--color-attention); background: var(--color-attention-wash); }
.unavailable-card h2 { margin: 1px 0 0; color: var(--color-text-primary); font-size: 14px; }
.unavailable-card p { max-width: 720px; margin: 7px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.7; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
</style>
