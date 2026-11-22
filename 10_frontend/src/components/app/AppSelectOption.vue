<script setup lang="ts">
import { Check } from '@lucide/vue'
import { SelectItem, SelectItemIndicator, SelectItemText } from 'reka-ui'
import { emptySelectOption } from './select-value'

defineProps<{ value: number | string | null; disabled?: boolean }>()
</script>

<template>
  <SelectItem :value="value === '' ? emptySelectOption : value" :disabled="disabled" class="app-select__item">
    <SelectItemText><slot /></SelectItemText>
    <SelectItemIndicator class="app-select__indicator"><Check :size="16" aria-hidden="true" /></SelectItemIndicator>
  </SelectItem>
</template>
