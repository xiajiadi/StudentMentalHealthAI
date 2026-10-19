<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'

export interface TeacherClassOption {
  value: string
  label: string
}

const props = withDefaults(defineProps<{
  modelValue: string
  options: TeacherClassOption[]
  ariaLabel?: string
  disabled?: boolean
}>(), {
  ariaLabel: '按班级筛选',
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const root = ref<HTMLElement | null>(null)
const listbox = ref<HTMLElement | null>(null)
const isOpen = ref(false)
const isKeyboardMode = ref(false)
const activeIndex = ref(0)
const listboxId = `teacher-class-select-listbox-${useId()}`

const selectedIndex = computed(() => props.options.findIndex((option) => option.value === props.modelValue))
const selectedLabel = computed(() => props.options[selectedIndex.value]?.label ?? '')
const activeDescendantId = computed(() => isOpen.value && props.options[activeIndex.value]
  ? `${listboxId}-option-${activeIndex.value}`
  : undefined)

const setActiveIndex = (index: number) => {
  if (!props.options.length) {
    activeIndex.value = 0
    return
  }

  activeIndex.value = Math.max(0, Math.min(index, props.options.length - 1))
  void nextTick(() => {
    listbox.value?.querySelector<HTMLElement>(`[data-option-index="${activeIndex.value}"]`)?.scrollIntoView({ block: 'nearest' })
  })
}

const openMenu = (index = selectedIndex.value) => {
  if (props.disabled || !props.options.length) return
  isOpen.value = true
  setActiveIndex(index < 0 ? 0 : index)
}

const closeMenu = () => {
  isOpen.value = false
}

const commitOption = (index: number) => {
  const option = props.options[index]
  if (!option) return
  emit('update:modelValue', option.value)
  closeMenu()
  isKeyboardMode.value = false
}

const toggleMenu = () => {
  isKeyboardMode.value = false
  if (isOpen.value) closeMenu()
  else openMenu()
}

const onTriggerKeydown = (event: KeyboardEvent) => {
  if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) isKeyboardMode.value = true
  if (event.key === 'Tab') {
    closeMenu()
    return
  }

  if (event.key === 'Escape' && isOpen.value) {
    event.preventDefault()
    closeMenu()
    return
  }

  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!isOpen.value) openMenu()
    else setActiveIndex(activeIndex.value + (event.key === 'ArrowDown' ? 1 : -1))
    return
  }

  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    if (!isOpen.value) isOpen.value = true
    setActiveIndex(event.key === 'Home' ? 0 : props.options.length - 1)
    return
  }

  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (isOpen.value) commitOption(activeIndex.value)
    else openMenu()
  }
}

const onOutsidePointerDown = (event: PointerEvent) => {
  if (event.target instanceof Node && !root.value?.contains(event.target)) closeMenu()
}

const onListPointerMove = () => {
  if (!isKeyboardMode.value) return
  isKeyboardMode.value = false
  if (selectedIndex.value >= 0) activeIndex.value = selectedIndex.value
}

watch(() => props.modelValue, () => {
  if (selectedIndex.value >= 0) activeIndex.value = selectedIndex.value
})

watch(() => props.options, (options) => {
  if (!options.length || props.disabled) closeMenu()
  if (activeIndex.value >= options.length) activeIndex.value = Math.max(0, options.length - 1)
}, { deep: true })

watch(() => props.disabled, (disabled) => {
  if (disabled) closeMenu()
})

onMounted(() => document.addEventListener('pointerdown', onOutsidePointerDown))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutsidePointerDown))
</script>

<template>
  <div ref="root" class="teacher-class-select">
    <button
      type="button"
      class="teacher-class-select__trigger"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="ariaLabel"
      :aria-valuetext="selectedLabel"
      :aria-expanded="isOpen"
      :aria-controls="listboxId"
      :aria-activedescendant="activeDescendantId"
      :disabled="disabled"
      @click="toggleMenu"
      @keydown="onTriggerKeydown"
    >
      <span class="teacher-class-select__value">{{ selectedLabel }}</span>
      <ChevronDown :size="15" aria-hidden="true" :class="{ 'teacher-class-select__chevron--open': isOpen }" />
    </button>

    <Transition name="teacher-class-select-menu">
      <div v-show="isOpen" class="teacher-class-select__menu">
        <ul
          :id="listboxId"
          ref="listbox"
          class="teacher-class-select__options"
          :class="{ 'teacher-class-select__options--keyboard': isKeyboardMode }"
          role="listbox"
          :aria-label="ariaLabel"
          :aria-hidden="!isOpen"
          @pointermove="onListPointerMove"
          @pointerdown="isKeyboardMode = false"
        >
          <li
            v-for="(option, index) in options"
            :id="`${listboxId}-option-${index}`"
            :key="option.value"
            class="teacher-class-select__option"
            :class="{
              'teacher-class-select__option--selected': option.value === modelValue,
              'teacher-class-select__option--active': isKeyboardMode && index === activeIndex,
            }"
            role="option"
            :aria-selected="option.value === modelValue"
            :data-option-index="index"
            @click="commitOption(index)"
          >
            <span>{{ option.label }}</span>
            <Check v-if="option.value === modelValue" :size="14" aria-hidden="true" />
          </li>
        </ul>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.teacher-class-select { position: relative; width: 100%; min-width: 0; }
.teacher-class-select__trigger { display: flex; width: 100%; min-width: 154px; height: 36px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 11px 0 12px; border: 1px solid #dfe6eb; border-radius: 9px; color: #344657; background: #fff; font: inherit; font-size: 11px; text-align: left; cursor: pointer; transition: border-color 140ms ease, background-color 140ms ease; }
.teacher-class-select__trigger:hover:not(:disabled) { border-color: #a5d2de; background: #fbfeff; }
.teacher-class-select__trigger:focus-visible { border-color: #279de0; outline: 2px solid #279de0; outline-offset: 2px; }
.teacher-class-select__trigger[aria-expanded='true'] { border-color: #79c9db; outline: 2px solid #279de0; outline-offset: 2px; }
.teacher-class-select__trigger:disabled { color: #98a6b2; background: #f7f9fa; cursor: not-allowed; }
.teacher-class-select__value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.teacher-class-select__trigger > svg { flex: 0 0 auto; color: #758897; transition: transform 140ms ease; }
.teacher-class-select__trigger > svg.teacher-class-select__chevron--open { transform: rotate(180deg); }
.teacher-class-select__menu { position: absolute; z-index: 30; top: calc(100% + 6px); left: 0; min-width: max(100%, 176px); padding: 5px; border: 1px solid #e2ebef; border-radius: 12px; background: #fff; box-shadow: 0 12px 28px rgb(35 68 84 / 13%); transform-origin: top center; }
.teacher-class-select__options { max-height: min(288px, calc(100vh - 140px)); overflow-y: auto; margin: 0; padding: 0; list-style: none; overscroll-behavior: contain; scrollbar-width: none; }
.teacher-class-select__options::-webkit-scrollbar { display: none; width: 0; height: 0; }
.teacher-class-select__option { display: flex; min-height: 36px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 10px; border-radius: 8px; color: #536979; font-size: 12px; cursor: pointer; transition: color 120ms ease, background-color 120ms ease; }
.teacher-class-select__option:hover,.teacher-class-select__option--active { color: #365c6d; background: #f1f9fb; }
.teacher-class-select__options--keyboard .teacher-class-select__option:hover:not(.teacher-class-select__option--active) { color: #536979; background: transparent; }
.teacher-class-select__option--selected { color: #008eb5; background: #eaf7fa; font-weight: 650; }
.teacher-class-select__option--selected.teacher-class-select__option--active { background: #e2f4f8; }
.teacher-class-select__option > svg { flex: 0 0 auto; color: #008eb5; }
.teacher-class-select-menu-enter-active,.teacher-class-select-menu-leave-active { transition: opacity 120ms ease, transform 120ms ease; }
.teacher-class-select-menu-enter-from,.teacher-class-select-menu-leave-to { opacity: 0; transform: translateY(-3px); }

@media (prefers-reduced-motion: reduce) {
  .teacher-class-select__trigger,.teacher-class-select__trigger > svg,.teacher-class-select__option,.teacher-class-select-menu-enter-active,.teacher-class-select-menu-leave-active { transition: none; }
}
</style>
