<script setup lang="ts">
import AppButton from '@/components/app/AppButton.vue'
import type { CatDraft } from '@/services/workspace-agent'

defineProps<{ draft: CatDraft; administrator: boolean; busy: boolean }>()
const emit = defineEmits<{ action: [draft: CatDraft, action: 'save' | 'approve' | 'publish'] }>()
const date = (value: string) => new Date(value).toLocaleString('zh-CN')
const states = {
  PREVIEW: '待保存', SAVED: '待批准合成施测', APPROVED: '已交接管理员', PUBLISHED: '已发布',
}
</script>

<template>
  <article class="cat-draft">
    <strong>{{ draft.plan_name }} · {{ states[draft.state] }}</strong>
    <span>拟安排班级 {{ draft.class_designation }}</span>
    <span>开放 {{ date(draft.opens_at) }} · 截止 {{ date(draft.due_at) }}</span>
    <small>{{ draft.item_count }} 道题 · 施测 {{ draft.min_items }}–{{ draft.max_items }} 题 · {{ draft.configuration === 'attachment' ? '附件配置' : '学校合成工程模板' }}</small>
    <AppButton v-if="administrator && draft.state === 'APPROVED'" variant="secondary" :loading="busy" @click="emit('action', draft, 'publish')">核对 CAT 发布</AppButton>
    <AppButton v-else-if="!administrator && draft.state === 'PREVIEW'" variant="secondary" :loading="busy" @click="emit('action', draft, 'save')">保存题库和方案</AppButton>
    <AppButton v-else-if="!administrator && draft.state === 'SAVED'" variant="secondary" :loading="busy" @click="emit('action', draft, 'approve')">审阅合成施测资格</AppButton>
  </article>
</template>

<style scoped>
.cat-draft { display: grid; justify-items: start; gap: 5px; padding-block: 8px; }
</style>
