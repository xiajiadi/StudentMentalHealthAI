<script setup lang="ts">
import { LockKeyhole, ListChecks, UsersRound } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
</script>

<template>
  <main class="content-wrap teacher-overview">
    <AppPageHeader
      eyebrow="教师工作区"
      title="班级任务进度"
      intro="查看获授权任务的整体完成情况，帮助安排课堂跟进。"
    />

    <AppStatusCallout
      tone="info"
      title="教师 Scope A · 仅看整体进度"
      body="此工作区不展示学生分数、作答、测评详情、支持对话、个人报告或复核信息。"
    />

    <section class="overview-grid" aria-label="教师可用范围">
      <AppCard class="scope-card">
        <div class="scope-card__icon scope-card__icon--blue"><ListChecks :size="19" aria-hidden="true" /></div>
        <div>
          <h2>任务级完成汇总</h2>
          <p>后续可展示获授权任务的开始、完成和未完成进度。</p>
        </div>
        <span class="scope-card__state">接口待补齐</span>
      </AppCard>

      <AppCard class="scope-card">
        <div class="scope-card__icon scope-card__icon--teal"><UsersRound :size="19" aria-hidden="true" /></div>
        <div>
          <h2>群体范围</h2>
          <p>仅在服务端确认授权且汇总满足隐私保护要求后显示。</p>
        </div>
        <span class="scope-card__state">暂不可用</span>
      </AppCard>
    </section>

    <AppCard class="blocked-panel">
      <div class="blocked-panel__heading">
        <span class="blocked-panel__icon"><LockKeyhole :size="18" aria-hidden="true" /></span>
        <div>
          <span class="section-label">当前状态</span>
          <h2>安全的任务进度暂不可读取</h2>
        </div>
      </div>
      <p>
        当前教师概览接口返回按匿名主体拆分的测评记录，并包含报告与复核状态计数；它没有任务级进度，也没有小组汇总抑制规则。
        为避免显示个人记录或可识别的小组信息，此页面不会请求或呈现这些数据。
      </p>
      <div class="blocked-panel__footer">
        <span class="status-dot" aria-hidden="true"></span>
        <span>等待提供经过授权和隐私保护的任务汇总接口</span>
      </div>
    </AppCard>

    <p class="scope-footnote">页面不包含合成或真实学生明细。当前不可用状态不代表班级没有任务。</p>
  </main>
</template>

<style scoped>
.teacher-overview { animation: page-in 240ms ease both; }
.overview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.scope-card { display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; align-items: center; gap: 13px; min-height: 102px; padding: 17px; }
.scope-card__icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 9px; }
.scope-card__icon--blue { color: var(--color-primary); background: var(--color-info-wash); }
.scope-card__icon--teal { color: var(--color-support); background: var(--color-support-wash); }
.scope-card h2 { margin: 0; color: var(--color-text-primary); font-size: 14px; }
.scope-card p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.scope-card__state { align-self: start; padding: 5px 8px; border-radius: 999px; color: var(--color-attention); background: var(--color-attention-wash); font-size: 10px; font-weight: 700; white-space: nowrap; }
.blocked-panel { margin-top: 16px; padding: 22px; }
.blocked-panel__heading { display: flex; align-items: center; gap: 11px; }
.blocked-panel__icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 9px; color: var(--color-attention); background: var(--color-attention-wash); }
.blocked-panel h2 { margin: 4px 0 0; color: var(--color-text-primary); font-size: 16px; }
.blocked-panel > p { max-width: 760px; margin: 15px 0 0 47px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.75; }
.blocked-panel__footer { display: flex; align-items: center; gap: 8px; margin: 17px 0 0 47px; padding-top: 13px; border-top: 1px solid var(--color-border); color: var(--color-text-muted); font-size: 11px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-attention); }
.scope-footnote { margin: 13px 2px 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }
@keyframes page-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 700px) { .overview-grid { grid-template-columns: 1fr; }.scope-card { grid-template-columns: 38px minmax(0, 1fr); }.scope-card__state { grid-column: 2; justify-self: start; margin-top: -5px; }.blocked-panel { padding: 18px; }.blocked-panel > p, .blocked-panel__footer { margin-left: 0; } }
</style>
