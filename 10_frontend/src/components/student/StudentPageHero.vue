<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow: string
  title: string
  subtitle: string
  image: string
  imagePosition?: string
  lightText?: boolean
}>(), {
  imagePosition: 'center',
  lightText: false,
})
</script>

<template>
  <section class="student-page-hero" :class="{ 'student-page-hero--light-text': lightText }" aria-labelledby="student-page-hero-title">
    <img class="student-page-hero__image" :src="image" :style="{ objectPosition: imagePosition }" alt="" aria-hidden="true" />
    <div class="student-page-hero__shade" aria-hidden="true"></div>
    <div class="student-page-hero__content">
      <div class="student-page-hero__copy">
        <span class="student-page-hero__eyebrow">{{ eyebrow }}</span>
        <h1 id="student-page-hero-title">{{ title }}</h1>
        <p>{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="student-page-hero__actions">
        <slot name="actions" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.student-page-hero { position: relative; isolation: isolate; display: flex; min-height: 188px; align-items: center; overflow: hidden; margin: 0 0 27px; border: 1px solid rgb(226 232 240 / 72%); border-radius: 12px; color: #1d1d1f; background: #e9f5f7; box-shadow: 0 8px 22px rgb(20 55 66 / 8%); }
.student-page-hero__image, .student-page-hero__shade { position: absolute; z-index: -1; inset: 0; width: 100%; height: 100%; }
.student-page-hero__image { object-fit: cover; }
.student-page-hero__shade { background: linear-gradient(90deg, rgb(255 255 255 / 38%) 0%, rgb(255 255 255 / 22%) 58%, rgb(255 255 255 / 9%) 100%); }
.student-page-hero__content { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 24px; padding: 30px clamp(24px, 4vw, 42px); }
.student-page-hero__copy { max-width: 620px; }
.student-page-hero__eyebrow { display: inline-block; margin-bottom: 10px; padding: 4px 10px; border: 1px solid rgb(255 255 255 / 82%); border-radius: 999px; color: #475569; background: rgb(255 255 255 / 66%); backdrop-filter: blur(8px); font-size: 11px; font-weight: 600; letter-spacing: .08em; line-height: 1.3; }
.student-page-hero h1 { margin: 0; color: #1d1d1f; font-family: var(--font-sans); font-size: 28px; font-weight: 600; letter-spacing: -.02em; line-height: 1.2; }
.student-page-hero p { max-width: 58ch; margin: 6px 0 0; color: #6b7280; font-family: var(--font-sans); font-size: 14px; font-weight: 400; line-height: 1.5; }
.student-page-hero--light-text h1, .student-page-hero--light-text p { color: #fff; text-shadow: 0 1px 3px rgb(15 58 92 / 26%); }
.student-page-hero__actions { display: flex; flex: 0 0 auto; align-items: center; justify-content: flex-end; gap: 12px; }

@media (max-width: 700px) {
  .student-page-hero { min-height: 176px; margin-bottom: 22px; }
  .student-page-hero__content { align-items: flex-start; flex-direction: column; gap: 16px; padding: 24px; }
  .student-page-hero__copy { max-width: 100%; }
  .student-page-hero__eyebrow { margin-bottom: 8px; }
  .student-page-hero h1 { font-size: clamp(24px, 7vw, 28px); }
  .student-page-hero p { margin-top: 6px; font-size: 14px; }
  .student-page-hero__actions { justify-content: flex-start; }
}
</style>
