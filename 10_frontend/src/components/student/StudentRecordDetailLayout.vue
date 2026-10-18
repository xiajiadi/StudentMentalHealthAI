<script setup lang="ts">
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'

type DetailMetadata = { label: string; value: string }
type DetailAnchor = { id: string; label: string }

withDefaults(defineProps<{
  current: string
  parent: { label: string; to: string }
  eyebrow: string
  title: string
  summary: string
  image: string
  imagePosition?: string
  metadata?: DetailMetadata[]
  badges?: string[]
  tableOfContents?: DetailAnchor[]
}>(), {
  imagePosition: 'center',
  metadata: () => [],
  badges: () => [],
  tableOfContents: () => [],
})
</script>

<template>
  <div class="student-record-detail">
    <WorkspaceBreadcrumb :current="current" :parent="parent" />

    <header class="student-record-detail__hero">
      <div class="student-record-detail__copy">
        <span class="student-record-detail__eyebrow">{{ eyebrow }}</span>
        <div v-if="metadata.length" class="student-record-detail__metadata" aria-label="记录时间与信息">
          <span v-for="item in metadata" :key="item.label" class="student-record-detail__metadata-item">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </span>
        </div>
        <h1>{{ title }}</h1>
        <p>{{ summary }}</p>
        <ul v-if="badges.length" class="student-record-detail__badges" aria-label="记录标签">
          <li v-for="badge in badges" :key="badge">{{ badge }}</li>
        </ul>
      </div>
      <img class="student-record-detail__image" :src="image" :style="{ objectPosition: imagePosition }" alt="" aria-hidden="true" />
    </header>

    <div class="student-record-detail__body">
      <div class="student-record-detail__content"><slot /></div>
      <aside v-if="tableOfContents.length || $slots.aside" class="student-record-detail__aside">
        <div class="student-record-detail__aside-panel">
          <nav v-if="tableOfContents.length" aria-label="本页内容">
            <h2>本页内容</h2>
            <a v-for="item in tableOfContents" :key="item.id" :href="`#${item.id}`">{{ item.label }}</a>
          </nav>
          <slot name="aside" />
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.student-record-detail { display: grid; gap: 0; }
.student-record-detail__hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 38%); align-items: stretch; gap: clamp(20px, 3vw, 38px); min-height: 238px; margin-bottom: 22px; padding: 22px; border: 1px solid #e6ebf0; border-radius: 12px; background: #fff; box-shadow: 0 5px 18px rgb(20 36 50 / 7%); }
.student-record-detail__copy { display: flex; min-width: 0; flex-direction: column; align-items: flex-start; justify-content: center; padding: 4px 0 4px 8px; }
.student-record-detail__eyebrow { display: inline-flex; align-items: center; min-height: 24px; padding: 4px 10px; border: 1px solid #dce7ec; border-radius: 999px; color: #4e626d; background: #f4f8fa; font-size: 10px; font-weight: 700; letter-spacing: .08em; line-height: 1.3; }
.student-record-detail__metadata { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 12px 0 0; }
.student-record-detail__metadata-item { display: inline-flex; flex-wrap: wrap; align-items: baseline; gap: 5px; color: #68727f; font-size: 12px; line-height: 1.5; }
.student-record-detail__metadata-item strong { color: #46505d; font-weight: 600; }
.student-record-detail__copy h1 { margin: 10px 0 0; color: #1e1d29; font-family: var(--font-sans); font-size: clamp(23px, 2.5vw, 31px); font-weight: 650; letter-spacing: -.025em; line-height: 1.25; overflow-wrap: anywhere; }
.student-record-detail__copy > p { max-width: 62ch; margin: 8px 0 0; color: #5f6875; font-size: 14px; line-height: 1.7; }
.student-record-detail__badges { display: flex; flex-wrap: wrap; gap: 7px; margin: 13px 0 0; padding: 0; list-style: none; }
.student-record-detail__badges li { padding: 4px 9px; border: 1px solid #e1e7ec; border-radius: 6px; color: #52606d; background: #f6f8fa; font-size: 11px; font-weight: 600; line-height: 1.35; }
.student-record-detail__image { display: block; width: 100%; min-height: 190px; max-height: 264px; align-self: center; aspect-ratio: 16 / 9; border-radius: 9px; background: #edf3f6; object-fit: cover; }
.student-record-detail__body { display: grid; grid-template-columns: minmax(0, 1fr) minmax(200px, 250px); align-items: start; gap: 22px; }
.student-record-detail__content { display: grid; min-width: 0; gap: 24px; }
.student-record-detail__aside { min-width: 0; }
.student-record-detail__aside-panel { position: sticky; top: calc(var(--layout-topbar, 64px) + 18px); display: grid; gap: 18px; padding: 18px; border: 1px solid #e6ebf0; border-radius: 10px; background: #fff; box-shadow: 0 4px 14px rgb(20 36 50 / 5%); }
.student-record-detail__aside-panel nav { display: grid; gap: 11px; }
.student-record-detail__aside-panel h2 { margin: 0 0 1px; color: #596371; font-size: 13px; font-weight: 650; }
.student-record-detail__aside-panel a { display: block; padding-left: 11px; border-left: 2px solid #e2e8ed; color: #697481; font-size: 12px; line-height: 1.5; text-decoration: none; transition: color var(--motion-fast), border-color var(--motion-fast); }
.student-record-detail__aside-panel a:hover { border-left-color: var(--color-primary); color: var(--color-primary); }
.student-record-detail__aside-panel a:focus-visible { border-radius: 2px; outline: 2px solid var(--color-focus-ring); outline-offset: 3px; }

@media (max-width: 900px) {
  .student-record-detail__body { grid-template-columns: 1fr; }
  .student-record-detail__aside { order: -1; }
  .student-record-detail__aside-panel { position: static; }
  .student-record-detail__aside-panel nav { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); align-items: start; }
  .student-record-detail__aside-panel h2 { grid-column: 1 / -1; }
}

@media (max-width: 640px) {
  .student-record-detail__hero { grid-template-columns: 1fr; gap: 15px; min-height: 0; padding: 16px; }
  .student-record-detail__copy { padding: 2px 2px 0; }
  .student-record-detail__image { min-height: 0; max-height: none; }
  .student-record-detail__body { gap: 16px; }
  .student-record-detail__aside-panel { padding: 14px; }
}

@media (prefers-reduced-motion: reduce) {
  .student-record-detail__aside-panel a { transition: none; }
}
</style>
