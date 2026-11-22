<script setup lang="ts" generic="T extends string | number | (string | number)[] | null">
import { computed, ref, useSlots, type VNode } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxPortal,
  ComboboxRoot,
  ComboboxTrigger,
  ComboboxViewport,
  SelectContent,
  SelectGroup,
  SelectLabel,
  SelectPortal,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from 'reka-ui'
import AppSelectOption from './AppSelectOption.vue'
import { emptySelectOption } from './select-value'
import { matchesOption } from './option-search'

defineOptions({ inheritAttrs: false })
const model = defineModel<T>()

const props = defineProps<{
  id?: string
  options?: ReadonlyArray<{ value: string | number; label: string }>
  placeholder?: string
  disabled?: boolean
  multiple?: boolean
  required?: boolean
  singleLine?: boolean
  variant?: 'login'
}>()
const slots = useSlots()
const searchTerm = ref('')
const open = ref(false)
type Choice = { value: string | number | null; label: string; group?: string; disabled?: boolean }

function childrenOf(node: VNode): VNode[] {
  if (Array.isArray(node.children)) return node.children as VNode[]
  if (node.children && typeof node.children === 'object' && 'default' in node.children) {
    return (node.children.default as () => VNode[])()
  }
  return []
}

function textOf(node: VNode): string {
  return typeof node.children === 'string' ? node.children : childrenOf(node).map(textOf).join('')
}

function choicesIn(nodes: VNode[], group?: string): Choice[] {
  return nodes.flatMap((node) => {
    if (node.type === AppSelectOption) {
      const { value, disabled } = node.props ?? {}
      return [{ value, label: textOf(node).trim(), disabled: disabled === '' || Boolean(disabled), group }]
    }
    const children = childrenOf(node)
    const groupLabel = node.type === SelectGroup ? children.find((item) => item.type === SelectLabel) : undefined
    return choicesIn(children, groupLabel ? textOf(groupLabel).trim() : group)
  })
}

const choices = computed<Choice[]>(() => [...(props.options ?? []), ...choicesIn(slots.default?.() ?? [])])
const searchable = computed(() => choices.value.filter((choice) => !choice.disabled).length > 10)
const selectedLabel = (value: unknown) => choices.value.find((choice) => choice.value === value)?.label ?? ''
const displayValue = (value: unknown) => Array.isArray(value) ? value.map(selectedLabel).filter(Boolean).join('、') : selectedLabel(value)
const visibleChoices = computed(() => {
  const query = searchTerm.value.trim()
  if (!query || query === displayValue(model.value)) return choices.value
  return choices.value.filter((choice) => matchesOption(`${choice.group ?? ''} ${choice.label}`, query, String(choice.value ?? '')))
})

function updateOpen(value: boolean) {
  open.value = value
  if (!value) searchTerm.value = displayValue(model.value)
}

function updateValue(value: unknown) {
  // Values are supplied by the option components in this select.
  model.value = (value === emptySelectOption ? '' : value) as T | undefined
}
</script>

<template>
  <ComboboxRoot
    v-if="searchable" :model-value="model === '' ? emptySelectOption : model" :open="open"
    :disabled="disabled" :multiple="multiple" :required="required" ignore-filter open-on-focus open-on-click
    @update:model-value="updateValue" @update:open="updateOpen"
  >
    <ComboboxAnchor as-child>
      <div class="app-select app-select--search" :class="{ 'app-select--login': variant === 'login' }" :data-state="open ? 'open' : 'closed'" :data-disabled="disabled || undefined">
        <ComboboxInput v-bind="$attrs" :id="id" v-model="searchTerm" class="app-select__input" :display-value="value => displayValue(value === emptySelectOption ? '' : value)"
          :placeholder="placeholder || '输入关键词搜索或选择'" autocomplete="off" @focus="($event.target as HTMLInputElement).select()" />
        <ComboboxTrigger class="app-select__search-trigger" type="button" aria-label="展开选项">
          <ChevronDown class="app-select__arrow" :size="18" aria-hidden="true" />
        </ComboboxTrigger>
      </div>
    </ComboboxAnchor>
    <ComboboxPortal>
      <ComboboxContent class="app-select__panel app-select__panel--search" :class="{ 'app-select__panel--single-line': singleLine }" position="popper" :side-offset="6" :collision-padding="12">
        <ComboboxViewport class="app-select__viewport">
          <ComboboxEmpty class="app-select__empty">没有匹配选项</ComboboxEmpty>
          <ComboboxItem v-for="choice in visibleChoices" :key="String(choice.value)" :value="choice.value === '' ? emptySelectOption : choice.value"
            :disabled="choice.disabled" class="app-select__item">
            <span>{{ choice.group ? `${choice.group} · ` : '' }}{{ choice.label }}</span>
            <ComboboxItemIndicator class="app-select__indicator"><Check :size="16" aria-hidden="true" /></ComboboxItemIndicator>
          </ComboboxItem>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
  <SelectRoot v-else :model-value="model === '' ? emptySelectOption : model" :disabled="disabled" :multiple="multiple" :required="required" @update:model-value="updateValue">
    <SelectTrigger v-bind="$attrs" :id="id" type="button" class="app-select" :class="{ 'app-select--login': variant === 'login' }">
      <SelectValue class="app-select__value" :placeholder="placeholder" />
      <ChevronDown class="app-select__arrow" :size="18" aria-hidden="true" />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent class="app-select__panel" :class="{ 'app-select__panel--single-line': singleLine }" position="popper" :side-offset="6" :collision-padding="12">
        <SelectViewport class="app-select__viewport">
          <AppSelectOption v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</AppSelectOption>
          <slot />
        </SelectViewport>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>

<style scoped>
.app-select {
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-sizing: border-box;
  gap: 12px;
  width: 100%;
  min-width: 0;
  min-height: 46px;
  padding: 8px 13px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  background: var(--color-surface);
  font: inherit;
  font-size: 14px;
  text-align: start;
  cursor: pointer;
}
.app-select--login {
  min-height: 0;
  padding: clamp(13px, 0.7vw, 14px) 20px;
  border-color: transparent;
  border-radius: 6px;
  color: #1e1d29;
  background: rgb(24 26 31 / 7%);
  font-size: clamp(16px, 0.9vw, 17px);
  font-weight: 500;
  line-height: 1.3;
}
.app-select:focus-visible, .app-select[data-state='open'], .app-select--search:focus-within {
  border-color: var(--color-primary);
  outline: 2px solid color-mix(in srgb, var(--color-primary) 26%, transparent);
  outline-offset: 1px;
}
.app-select__value[data-placeholder] { color: var(--color-text-muted); }
.app-select:disabled, .app-select[data-disabled] { cursor: not-allowed; opacity: .65; }
.app-select--search { padding-block: 0; padding-inline-end: 7px; cursor: text; }
.app-select__input { flex: 1; width: 100%; min-width: 0; min-height: 44px; padding: 0; border: 0; outline: none; color: inherit; background: transparent; font: inherit; text-overflow: ellipsis; }
.app-select__input::placeholder { color: var(--color-text-muted); }
.app-select__search-trigger { display: grid; flex: 0 0 32px; height: 32px; place-items: center; padding: 0; border: 0; border-radius: var(--radius-control); background: transparent; cursor: pointer; }
.app-select__search-trigger:hover { background: var(--color-info-wash); }
.app-select__value { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-select__arrow { flex: 0 0 auto; color: var(--color-text-secondary); }
.app-select[data-state='open'] .app-select__arrow { transform: rotate(180deg); }
:global(.app-select__panel) {
  z-index: 130;
  box-sizing: border-box;
  width: var(--reka-select-trigger-width);
  max-width: var(--reka-select-content-available-width);
  max-height: min(20rem, var(--reka-select-content-available-height));
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  color: var(--color-text-primary);
  background: var(--color-surface);
  box-shadow: var(--shadow-raised);
}
:global(.app-select__viewport) { padding: 4px; }
:global(body > [data-reka-popper-content-wrapper]:has(.app-select__panel)) { z-index: 130 !important; }
:global(.app-select__panel--search) {
  width: var(--reka-combobox-trigger-width);
  max-width: var(--reka-combobox-content-available-width);
  max-height: min(20rem, var(--reka-combobox-content-available-height));
}
:global(.app-select__empty) { padding: 12px; color: var(--color-text-muted); font-size: 14px; }
:global(.app-select__group-label) { padding: 8px 12px 3px; color: var(--color-text-muted); font-size: 12px; }
:global(.app-select__item) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 16px;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-control);
  outline: none;
  overflow-wrap: anywhere;
  font-size: 14px;
  cursor: pointer;
}
:global(.app-select__item[data-highlighted]), :global(.app-select__item[data-state='checked']) {
  color: var(--color-primary);
  background: var(--color-info-wash);
}
:global(.app-select__item[data-disabled]) { color: var(--color-text-muted); cursor: default; }
:global(.app-select__panel--single-line .app-select__item) {
  grid-template-columns: minmax(0, 1fr) 16px;
  white-space: nowrap;
}
:global(.app-select__indicator) { display: flex; }
</style>
