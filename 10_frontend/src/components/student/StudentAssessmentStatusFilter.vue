<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { studentAssessmentStatusFilters, type StudentAssessmentStatusFilterValue } from './assessment-status-filter'

const props = withDefaults(defineProps<{
  modelValue: StudentAssessmentStatusFilterValue
  ariaLabel?: string
}>(), {
  ariaLabel: '按状态筛选',
})

const emit = defineEmits<{
  'update:modelValue': [value: StudentAssessmentStatusFilterValue]
}>()

const filterContainer = ref<HTMLElement | null>(null)
const filterButtonElements = new Map<StudentAssessmentStatusFilterValue, HTMLButtonElement>()
const filterIndicator = ref({ x: 0, y: 0, width: 0, height: 0, visible: false })
const filterIndicatorStyle = computed(() => ({
  width: `${filterIndicator.value.width}px`,
  height: `${filterIndicator.value.height}px`,
  transform: `translate(${filterIndicator.value.x}px, ${filterIndicator.value.y}px)`,
  opacity: filterIndicator.value.visible ? '1' : '0',
}))

const setFilterButton = (id: StudentAssessmentStatusFilterValue, element: unknown) => {
  if (element instanceof HTMLButtonElement) filterButtonElements.set(id, element)
  else filterButtonElements.delete(id)
}

const updateFilterIndicator = async () => {
  await nextTick()
  const container = filterContainer.value
  const button = filterButtonElements.get(props.modelValue)
  if (!container || !button) {
    filterIndicator.value = { ...filterIndicator.value, visible: false }
    return
  }

  const containerRect = container.getBoundingClientRect()
  const buttonRect = button.getBoundingClientRect()
  filterIndicator.value = {
    x: buttonRect.left - containerRect.left,
    y: buttonRect.top - containerRect.top,
    width: buttonRect.width,
    height: buttonRect.height,
    visible: true,
  }
}

watch(() => props.modelValue, () => void updateFilterIndicator(), { flush: 'post' })

onMounted(() => {
  void updateFilterIndicator()
  window.addEventListener('resize', updateFilterIndicator)
})

onBeforeUnmount(() => window.removeEventListener('resize', updateFilterIndicator))
</script>

<template>
  <div ref="filterContainer" class="assessment-filters" role="group" :aria-label="ariaLabel">
    <span class="assessment-filters__indicator" :style="filterIndicatorStyle" aria-hidden="true"></span>
    <button
      v-for="filter in studentAssessmentStatusFilters"
      :key="filter.id"
      :ref="(element) => setFilterButton(filter.id, element)"
      type="button"
      :class="{ 'assessment-filter--active': modelValue === filter.id }"
      :aria-pressed="modelValue === filter.id"
      @click="emit('update:modelValue', filter.id)"
    >{{ filter.label }}</button>
  </div>
</template>

<style scoped>
.assessment-filters { position: relative; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); width: min(288px, 100%); min-width: 0; flex: 0 1 288px; box-sizing: border-box; padding: 4px; border-radius: 9px; background: #fafbfd; box-shadow: inset 0 0 0 1px #eceef1; }
.assessment-filters__indicator { position: absolute; z-index: 0; top: 0; left: 0; border-radius: 7px; background: #00addf; box-shadow: 0 2px 6px rgb(0 136 178 / 20%); pointer-events: none; transition: transform 360ms cubic-bezier(.2,.8,.2,1), width 360ms cubic-bezier(.2,.8,.2,1), height 220ms ease, opacity var(--motion-fast); }
.assessment-filters button { position: relative; z-index: 1; min-width: 0; min-height: 36px; padding: 0 8px; border: 0; border-radius: 7px; color: #596574; background: transparent; cursor: pointer; font: inherit; font-size: 13px; font-weight: 600; white-space: nowrap; transition: color var(--motion-fast); }
.assessment-filters button:hover:not(.assessment-filter--active) { color: #263b4c; }
.assessment-filters button.assessment-filter--active { color: #fff; background: transparent; }
.assessment-filters button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }

@media (max-width: 680px) {
  .assessment-filters { flex-basis: 288px; }
  .assessment-filters button { min-height: 36px; padding: 0 6px; font-size: 13px; }
}

@media (max-width: 520px) {
  .assessment-filters button { padding: 0 4px; font-size: 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .assessment-filters__indicator { transition: none; }
}
</style>
