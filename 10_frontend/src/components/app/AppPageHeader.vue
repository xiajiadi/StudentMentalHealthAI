<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow?: string
  title: string
  intro?: string
  fixtureLabel?: string
}>(), {
  eyebrow: '工作台',
  intro: '',
  fixtureLabel: '',
})
</script>

<template>
  <header class="page-header">
    <div>
      <span class="page-kicker">{{ eyebrow }}</span>
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="intro" class="page-intro">{{ intro }}</p>
    </div>
    <div class="page-header__side">
      <span v-if="fixtureLabel" class="fixture-label">{{ fixtureLabel }}</span>
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 28px;
}

.page-header__side {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 3px;
}

.fixture-label {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid rgb(183 121 31 / 18%);
  border-radius: 6px;
  color: var(--color-attention);
  background: var(--color-attention-wash);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

@media (max-width: 680px) {
  .page-header {
    display: block;
    margin-bottom: 22px;
  }

  .page-header__side {
    justify-content: flex-start;
    padding-top: 15px;
  }
}
</style>
