<script setup lang="ts">
import { computed } from 'vue'
import { Check, ChevronsUpDown } from '@lucide/vue'
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
} from 'reka-ui'
import type { SchoolMember } from '@/api/client'

const props = withDefaults(defineProps<{
  modelValue: string
  members: SchoolMember[]
  role: 'student' | 'teacher'
  disabled?: boolean
}>(), { disabled: false })

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const roleName = computed(() => props.role === 'student' ? '学生' : '教师')
const nameFor = (member: SchoolMember) => member.display_name?.trim() || `${roleName.value}账号`
const shortRef = (value: string) => value.slice(-6)
const displayValue = (value: unknown) => {
  if (typeof value !== 'string') return ''
  const member = props.members.find((candidate) => candidate.user_id === value)
  return member ? `${nameFor(member)} · ${shortRef(member.user_id)}` : ''
}
const searchableText = (member: SchoolMember) => `${nameFor(member)} ${member.user_id}`
const updateValue = (value: unknown) => emit('update:modelValue', typeof value === 'string' ? value : '')
</script>

<template>
  <ComboboxRoot
    :model-value="modelValue || undefined"
    :disabled="disabled"
    :open-on-focus="true"
    :reset-search-term-on-select="true"
    @update:model-value="updateValue"
  >
    <ComboboxAnchor as-child>
      <div class="admin-member-combobox__control">
        <ComboboxInput
          class="admin-member-combobox__input"
          :display-value="displayValue"
          :aria-label="`搜索并选择${roleName}`"
          :placeholder="`搜索${roleName}姓名或账号编号`"
          autocomplete="off"
        />
        <ComboboxTrigger class="admin-member-combobox__trigger" :aria-label="`显示${roleName}列表`">
          <ChevronsUpDown :size="15" aria-hidden="true" />
        </ComboboxTrigger>
      </div>
    </ComboboxAnchor>
    <ComboboxPortal>
      <ComboboxContent class="admin-member-combobox__content" position="popper" :side-offset="6" :avoid-collisions="true">
        <ComboboxViewport class="admin-member-combobox__viewport">
          <ComboboxEmpty class="admin-member-combobox__empty">没有匹配的{{ roleName }}账号</ComboboxEmpty>
          <ComboboxItem
            v-for="member in members"
            :key="member.user_id"
            :value="member.user_id"
            :text-value="searchableText(member)"
            class="admin-member-combobox__item"
          >
            <span class="admin-member-combobox__item-copy">
              <strong>{{ nameFor(member) }}</strong>
              <small>账号 · {{ shortRef(member.user_id) }}</small>
            </span>
            <ComboboxItemIndicator class="admin-member-combobox__indicator">
              <Check :size="15" aria-hidden="true" />
            </ComboboxItemIndicator>
          </ComboboxItem>
        </ComboboxViewport>
      </ComboboxContent>
    </ComboboxPortal>
  </ComboboxRoot>
</template>

<style scoped>
.admin-member-combobox__control { display: flex; min-width: 0; min-height: 42px; align-items: center; gap: 4px; padding: 0 7px 0 12px; border: 1px solid #dbe6eb; border-radius: 10px; background: #fff; transition: border-color 140ms ease, box-shadow 140ms ease; }
.admin-member-combobox__control:focus-within { border-color: #73bfd0; box-shadow: 0 0 0 3px rgb(0 157 191 / 10%); }
.admin-member-combobox__input { width: 100%; min-width: 0; height: 38px; border: 0; outline: 0; color: #263f50; background: transparent; font: inherit; font-size: 12px; }
.admin-member-combobox__input::placeholder { color: #91a2ac; }
.admin-member-combobox__trigger { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; border: 0; border-radius: 7px; color: #78909d; background: transparent; cursor: pointer; }
.admin-member-combobox__trigger:hover { color: #117f9d; background: #eff8fa; }
.admin-member-combobox__trigger:focus-visible { outline: 2px solid #279de0; outline-offset: 1px; }
:global(.admin-member-combobox__content) { z-index: 120; width: var(--reka-combobox-trigger-width); min-width: 240px; max-width: min(420px, calc(100vw - 32px)); overflow: hidden; border: 1px solid #dce8ed; border-radius: 12px; background: #fff; box-shadow: 0 16px 38px rgb(34 67 83 / 15%); }
:global(body > [data-reka-popper-content-wrapper]:has(.admin-member-combobox__content)) { z-index: 130 !important; }
:global(.admin-member-combobox__viewport) { max-height: min(280px, calc(100vh - 180px)); overflow-y: auto; padding: 5px; overscroll-behavior: contain; }
:global(.admin-member-combobox__empty) { padding: 13px 10px; color: #7c909b; font-size: 12px; text-align: center; }
:global(.admin-member-combobox__item) { display: flex; min-height: 46px; align-items: center; justify-content: space-between; gap: 12px; padding: 7px 10px; border-radius: 8px; color: #3d5868; outline: none; cursor: pointer; }
:global(.admin-member-combobox__item[data-highlighted]) { color: #155e74; background: #eef8fa; }
:global(.admin-member-combobox__item[data-disabled]) { opacity: .45; cursor: not-allowed; }
:global(.admin-member-combobox__item-copy) { display: grid; gap: 3px; min-width: 0; }
:global(.admin-member-combobox__item-copy strong) { overflow: hidden; color: #283f50; font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
:global(.admin-member-combobox__item-copy small) { color: #8b9ea7; font-size: 10px; }
:global(.admin-member-combobox__indicator) { display: flex; color: #0788a9; }

@media (prefers-reduced-motion: reduce) { .admin-member-combobox__control { transition: none; } }
</style>
