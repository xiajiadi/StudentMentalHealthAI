<script setup lang="ts">
import { ArrowUpRight, BookOpen, CloudSun, HeartHandshake, MoonStar, Smile } from '@lucide/vue'
import AppCard from '@/components/app/AppCard.vue'
import WorkspaceBreadcrumb from '@/components/student/WorkspaceBreadcrumb.vue'

const articles = [
  {
    id: 'emotions', icon: Smile, topic: '认识情绪', title: '给今天的情绪起个名字',
    paragraphs: [
      '回想今天一个让你印象深刻的时刻。试着用一个具体的词描述感受，比如紧张、委屈、期待或失落。同一件事也可以带来几种感受',
      '如果一时找不到词，可以先看看身体的反应，再想想发生了什么。你可以只写给自己，也可以找一个信任的人说说',
    ],
    source: '联合国儿童基金会｜如何帮助青少年表达情绪（英文）',
    url: 'https://www.unicef.org/parenting/mental-health/3-ways-help-teens-express-emotions',
  },
  {
    id: 'stress', icon: CloudSun, topic: '学习压力', title: '忙不过来时，先找一个能做的小步骤',
    paragraphs: [
      '准备考试、赶作业或适应新环境时，感到压力很常见。你可以把眼下最挂心的事情写下来，再圈出今天能做的一步，比如先整理一道错题',
      '安排一点休息和活动时间。如果压力持续影响睡眠、学习或日常生活，可以请信任的成年人陪你一起想办法',
    ],
    source: '世界卫生组织｜压力',
    url: 'https://www.who.int/zh/news-room/questions-and-answers/item/stress',
  },
  {
    id: 'sleep', icon: MoonStar, topic: '睡眠习惯', title: '给忙碌的一天留一点收尾时间',
    paragraphs: [
      '试着在平时相近的时间起床和睡觉。睡前可以把明天要做的事记下来，给自己留一小段时间读书或听轻柔的音乐',
      '看看哪些睡前习惯让你更难休息，例如临睡前喝含咖啡因的饮料或一直刷手机。先挑一项试着改几天，观察对自己有没有帮助',
    ],
    source: '世界卫生组织｜压力与睡眠习惯',
    url: 'https://www.who.int/zh/news-room/questions-and-answers/item/stress',
  },
  {
    id: 'support', icon: HeartHandshake, topic: '了解自己与求助', title: '想找人聊聊，可以怎么开口？',
    paragraphs: [
      '心理健康也包括我们怎样应对压力、与人相处和参与日常生活。你可以留意自己最近的心情、作息和感兴趣的事有没有变化',
      '开口时可以从一句具体的话开始，比如「最近我常常睡不好，我想找个人聊聊」。你可以先联系信任的师长，也可以使用学校的心理支持渠道',
    ],
    source: '世界卫生组织｜青少年精神卫生',
    url: 'https://www.who.int/zh/news-room/fact-sheets/detail/adolescent-mental-health/',
  },
]
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
