<script setup lang="ts">
import { ArrowUpRight, BookOpen, CloudSun, HeartHandshake, MoonStar, Smile } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'
import { studentEducationArticles } from '@/services/student-education'

const icons = { emotions: Smile, stress: CloudSun, sleep: MoonStar, support: HeartHandshake }
const articles = studentEducationArticles.map((article) => ({
  ...article,
  icon: icons[article.id as keyof typeof icons] ?? BookOpen,
}))
</script>

<template>
  <div class="content-wrap content-wrap--student knowledge">
    <WorkspaceBreadcrumb current="心理知识" />
    <header class="knowledge__heading">
      <BookOpen :size="25" aria-hidden="true" />
      <h1>心理知识</h1>
    </header>
    <div class="knowledge__articles">
      <AppCard v-for="article in articles" :key="article.id" class="knowledge__card">
        <article :aria-labelledby="article.id">
          <span class="knowledge__topic"><component :is="article.icon" :size="18" aria-hidden="true" />{{ article.topic }}</span>
          <h2 :id="article.id">{{ article.title }}</h2>
          <p v-for="paragraph in article.paragraphs" :key="paragraph">{{ paragraph }}</p>
          <a :href="article.url" target="_blank" rel="noopener noreferrer">
            {{ article.source }} <ArrowUpRight :size="14" aria-hidden="true" />
          </a>
        </article>
      </AppCard>
    </div>
    <nav aria-label="下一步" class="knowledge__links">
      <RouterLink to="/student/workspace?chat=1">回智能体聊聊</RouterLink>
      <RouterLink to="/student/school-support">联系心理教师</RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.knowledge { padding-bottom: 28px; }
.knowledge__heading { display: flex; align-items: center; gap: 12px; margin: 12px 0 20px; }
.knowledge__heading svg, .knowledge__topic, .knowledge a { color: var(--color-primary-active); }
.knowledge__heading h1 { margin: 0; font: 700 clamp(24px, 4vw, 34px)/1.25 var(--font-display); }
.knowledge__articles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.knowledge__card { padding: clamp(16px, 2.4vw, 28px); border: 1px solid var(--color-border); }
.knowledge__card article { display: grid; align-content: start; height: 100%; gap: 10px; }
.knowledge__topic, .knowledge__card a, .knowledge__links { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.knowledge__topic { font-size: 13px; font-weight: 600; }
.knowledge__card h2 { margin: 0; color: var(--color-text-primary); font-size: 19px; }
.knowledge__card p { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.7; }
.knowledge__card a { width: fit-content; font-size: 12px; }
.knowledge__links { margin-top: 20px; gap: 16px; font-size: 14px; }
.knowledge a:hover { text-decoration: underline; }
@media (max-width: 680px) { .knowledge__articles { grid-template-columns: minmax(0, 1fr); } }
</style>
