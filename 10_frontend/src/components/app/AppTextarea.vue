<script setup lang="ts">
withDefaults(defineProps<{
  modelValue: string
  id: string
  label: string
  placeholder?: string
  hint?: string
  rows?: number
}>(), {
  placeholder: '',
  hint: '',
  rows: 4,
})

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <label class="app-field" :for="id">
    <span class="app-field__label">{{ label }}</span>
    <textarea
      :id="id"
      :rows="rows"
      :value="modelValue"
      :placeholder="placeholder"
      class="app-textarea"
      :aria-describedby="hint ? `${id}-hint` : undefined"
      @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    ></textarea>
    <span v-if="hint" :id="`${id}-hint`" class="app-field__hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.app-field { display: grid; gap: 7px; }
.app-field__label { color: var(--color-text-primary); font-size: 13px; font-weight: 700; }
.app-textarea {
  width: 100%;
  min-height: 100px;
  padding: 12px 13px;
  resize: vertical;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  background: var(--color-surface);
  font-size: 14px;
  line-height: 1.6;
  transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
}
.app-textarea::placeholder { color: var(--color-text-muted); }
.app-textarea:focus { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(147 197 253 / 32%); outline: none; }
.app-field__hint { color: var(--color-text-muted); font-size: 12px; line-height: 1.5; }
</style>
