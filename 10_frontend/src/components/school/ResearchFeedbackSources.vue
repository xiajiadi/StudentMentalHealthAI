<script setup lang="ts">
defineProps<{ sourceCards: Array<{
  chunk_id: string; record_id: string; source_id: string; title: string; organization: string; canonical_url: string;
  record_locator: string; source_population_scope: string; source_language: string;
  license: string; license_url: string; attribution: string; excerpt_text: string;
  consumer_age_min: number; consumer_age_max: number;
}> }>()

function sourceUrl(value: string): string | undefined {
  try {
    const url = new window.URL(value)
    return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password ? url.href : undefined
  } catch { return undefined }
}
</script>

<template>
  <section v-if="sourceCards.length" class="feedback-sources" aria-label="反馈参考来源">
    <h4>参考来源</h4>
    <details v-for="source in sourceCards" :key="source.chunk_id">
      <summary>{{ source.title }}</summary>
      <p>{{ source.organization }} · {{ source.record_locator }} · 记录 {{ source.record_id }} · 来源 {{ source.source_id }}</p>
      <p>研究涉及人群：{{ source.source_population_scope }}；本功能面向 {{ source.consumer_age_min }}–{{ source.consumer_age_max }} 岁；原文语言：{{ source.source_language }}</p>
      <blockquote>{{ source.excerpt_text }}</blockquote>
      <p>{{ source.attribution }}</p>
      <p><a v-if="sourceUrl(source.canonical_url)" :href="sourceUrl(source.canonical_url)" target="_blank" rel="noopener noreferrer">查看原始来源</a><span v-else>来源链接不可用</span> · <a v-if="sourceUrl(source.license_url)" :href="sourceUrl(source.license_url)" target="_blank" rel="noopener noreferrer">{{ source.license }}</a><span v-else>{{ source.license }}</span></p>
    </details>
  </section>
</template>

<style scoped>
.feedback-sources { display: grid; gap: 8px; min-width: 0; }
.feedback-sources h4 { margin: 0; font-size: 13px; }
.feedback-sources details { padding: 10px 12px; border: 1px solid var(--color-border, #dfe7e3); border-radius: 8px; }
.feedback-sources summary { cursor: pointer; font-size: 12px; font-weight: 650; overflow-wrap: anywhere; }
.feedback-sources p,.feedback-sources blockquote { margin: 9px 0 0; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.feedback-sources p { color: var(--color-text-secondary); }
.feedback-sources blockquote { padding-left: 12px; border-left: 2px solid #75a997; white-space: pre-wrap; }
.feedback-sources a { color: #216e64; text-decoration: underline; }
.feedback-sources :focus-visible { outline: 2px solid #438e7b; outline-offset: 3px; }
</style>
