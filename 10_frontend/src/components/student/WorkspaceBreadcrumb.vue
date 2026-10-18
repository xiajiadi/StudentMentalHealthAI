<script setup lang="ts">
defineProps<{
  current: string
  parent?: { label: string; to: string }
  homeLabel?: string
  homeTo?: string
}>()
</script>

<template>
  <nav class="workspace-breadcrumb" aria-label="当前位置">
    <ol>
      <li><RouterLink :to="homeTo ?? '/student/home'">{{ homeLabel ?? '学生空间' }}</RouterLink></li>
      <template v-if="parent">
        <li class="workspace-breadcrumb__separator" aria-hidden="true">/</li>
        <li><RouterLink :to="parent.to">{{ parent.label }}</RouterLink></li>
      </template>
      <li class="workspace-breadcrumb__separator" aria-hidden="true">/</li>
      <li class="workspace-breadcrumb__current" aria-current="page">{{ current }}</li>
    </ol>
  </nav>
</template>

<style scoped>
.workspace-breadcrumb { margin: 0 0 14px; font-family: var(--font-sans); }
.workspace-breadcrumb ol { display: flex; align-items: center; gap: 14px; margin: 0; padding: 0; list-style: none; }
.workspace-breadcrumb a, .workspace-breadcrumb__current { font-size: 14px; font-weight: 600; line-height: 1.3; text-decoration: none; }
.workspace-breadcrumb a { color: #6a6e7b; }
.workspace-breadcrumb a:hover { color: var(--color-primary); }
.workspace-breadcrumb a:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 3px; border-radius: 2px; }
.workspace-breadcrumb__separator { color: #9ba0aa; font-size: 14px; font-weight: 500; line-height: 1; }
.workspace-breadcrumb__current { color: #1e1d29; }

@media (max-width: 600px) {
  .workspace-breadcrumb { margin-bottom: 11px; }
  .workspace-breadcrumb ol { gap: 10px; }
  .workspace-breadcrumb a, .workspace-breadcrumb__current { font-size: 12px; }
  .workspace-breadcrumb__separator { font-size: 12px; }
}
</style>
