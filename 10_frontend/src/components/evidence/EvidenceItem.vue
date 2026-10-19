<script setup lang="ts">
import { ExternalLink } from '@lucide/vue'
import { FileText } from '@lucide/vue'
import type { Citation } from '@/types/contracts'

defineProps<{
  citation: Citation
}>()
</script>

<template>
  <article class="evidence-item">
    <div class="evidence-item__marker" aria-hidden="true"><FileText :size="16" /></div>
    <div class="evidence-item__body">
      <div class="evidence-item__heading">
        <span class="evidence-item__id">{{ citation.citation_id }}</span>
        <h3>{{ citation.title || '来源标题不可用' }}</h3>
      </div>
      <p v-if="citation.excerpt" class="evidence-item__excerpt">“{{ citation.excerpt }}”</p>
      <dl class="evidence-item__meta">
        <div v-if="citation.organization"><dt>来源组织</dt><dd>{{ citation.organization }}</dd></div>
        <div v-if="citation.locator"><dt>定位</dt><dd>{{ citation.locator }}</dd></div>
        <div><dt>片段</dt><dd class="evidence-item__mono">{{ citation.chunk_id }}</dd></div>
      </dl>
      <span class="evidence-item__trace"><ExternalLink :size="13" aria-hidden="true" /> 已审核引用，合成资料</span>
    </div>
  </article>
</template>

<style scoped>
.evidence-item { display: flex; gap: 13px; padding: 16px 0; border-bottom: 1px solid var(--color-border); }
.evidence-item:last-child { border-bottom: 0; }
.evidence-item__marker { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; flex: 0 0 30px; border: 1px solid rgb(37 99 235 / 16%); border-radius: 7px; color: var(--color-primary); background: var(--color-info-wash); }
.evidence-item__heading { display: flex; align-items: baseline; gap: 9px; flex-wrap: wrap; }
.evidence-item__id { color: var(--color-primary); font-family: var(--font-mono); font-size: 11px; font-weight: 700; }
.evidence-item h3 { margin: 0; color: var(--color-text-primary); font-size: 14px; font-weight: 700; line-height: 1.5; }
.evidence-item__excerpt { margin: 7px 0 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.7; }
.evidence-item__meta { display: grid; gap: 4px; margin: 9px 0 0; }
.evidence-item__meta div { display: flex; gap: 8px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; }
.evidence-item__meta dt { flex: 0 0 auto; color: var(--color-text-muted); }
.evidence-item__meta dd { margin: 0; overflow-wrap: anywhere; }
.evidence-item__mono { font-family: var(--font-mono); font-size: 10px; }
.evidence-item__trace { display: inline-flex; align-items: center; gap: 5px; margin-top: 9px; color: var(--color-support); font-size: 11px; font-weight: 700; }
</style>
