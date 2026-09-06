<script setup lang="ts">
withDefaults(defineProps<{
  modelValue: string
  id: string
  label: string
  type?: string
  placeholder?: string
  autocomplete?: string
  error?: string
  hint?: string
}>(), {
  type: 'text',
  placeholder: '',
  autocomplete: 'off',
  error: '',
  hint: '',
})

defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <label class="app-field" :for="id">
    <span class="app-field__label">{{ label }}</span>
    <input
      :id="id"
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :autocomplete="autocomplete"
      :aria-invalid="Boolean(error)"
      :aria-describedby="error ? `${id}-error` : hint ? `${id}-hint` : undefined"
      class="app-input"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <span v-if="error" :id="`${id}-error`" class="app-field__error" role="alert">{{ error }}</span>
    <span v-else-if="hint" :id="`${id}-hint`" class="app-field__hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.app-field {
  display: grid;
  gap: 7px;
}

.app-field__label {
  color: var(--color-text-primary);
  font-size: 13px;
  font-weight: 700;
}

.app-input {
  width: 100%;
  min-height: 46px;
  padding: 0 13px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  background: var(--color-surface);
  font-size: 14px;
  transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
}

.app-input::placeholder { color: var(--color-text-muted); }
.app-input:hover { border-color: var(--color-border-hover); }
.app-input:focus { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(147 197 253 / 32%); outline: none; }

.app-field__hint,
.app-field__error {
  font-size: 12px;
  line-height: 1.5;
}

.app-field__hint { color: var(--color-text-muted); }
.app-field__error { color: var(--color-critical); }
</style>
