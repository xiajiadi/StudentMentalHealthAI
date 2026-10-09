<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { AppWindow } from '@lucide/vue'
import AppPageHeader from '@/components/app/AppPageHeader.vue'

const route = useRoute()
const sectionLabels: Record<string, string> = {
  overview: '工作概览', resources: '专业资料', tasks: '事项处理', users: '账号管理', settings: '系统设置',
}
const title = computed(() => sectionLabels[String(route.params.section)] || '工作区')
</script>

<template>
  <div class="content-wrap workspace-placeholder">
    <AppPageHeader eyebrow="HEARTBRIDGE WORKSPACE" :title="title" intro="此账号已由服务端识别。当前原型还没有为这个入口接入具体页面。" />
    <section class="workspace-placeholder__card surface" aria-live="polite">
      <span class="workspace-placeholder__icon"><AppWindow :size="22" aria-hidden="true" /></span>
      <div><h2>页面尚未接入</h2><p>已保留此角色的工作区导航；页面数据和操作会在对应模块完成后显示。</p></div>
    </section>
  </div>
</template>

<style scoped>
.workspace-placeholder__card { display: flex; align-items: flex-start; gap: 16px; max-width: 740px; margin-top: 28px; padding: 24px; border-radius: 14px; }
.workspace-placeholder__icon { display: inline-grid; place-items: center; width: 42px; height: 42px; flex: 0 0 42px; border-radius: 12px; color: var(--color-primary); background: #e8f9fe; }
.workspace-placeholder__card h2 { margin: 1px 0 7px; font-size: 15px; }
.workspace-placeholder__card p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
</style>
