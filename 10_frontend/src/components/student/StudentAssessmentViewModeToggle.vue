<script setup lang="ts">
type ViewMode = 'grid' | 'list'

const props = withDefaults(defineProps<{
  modelValue: ViewMode
  ariaLabel?: string
}>(), {
  ariaLabel: '显示方式',
})

const emit = defineEmits<{
  'update:modelValue': [value: ViewMode]
}>()
</script>

<template>
  <div class="assessment-view-toggle" role="group" :aria-label="ariaLabel">
    <button
      type="button"
      aria-label="列表显示"
      :aria-pressed="modelValue === 'list'"
      :class="{ 'assessment-view-toggle__button--active': modelValue === 'list' }"
      @click="emit('update:modelValue', 'list')"
    >
      <svg class="assessment-view-toggle__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M3.0997 2.76764H1.69974C1.23308 2.76764 0.999756 3.00097 0.999756 3.46762V4.86758C0.999756 5.33424 1.23308 5.56756 1.69974 5.56756H3.0997C3.56635 5.56756 3.79968 5.33424 3.79968 4.86758V3.46762C3.79968 3.00097 3.56635 2.76764 3.0997 2.76764Z" fill="currentColor" />
        <path d="M18.4986 2.76764H5.89896C5.4323 2.76764 5.19897 3.00097 5.19897 3.46762V4.86758C5.19897 5.33424 5.4323 5.56756 5.89896 5.56756H18.4986C18.9653 5.56756 19.1986 5.33424 19.1986 4.86758V3.46762C19.1986 3.00097 18.9653 2.76764 18.4986 2.76764Z" fill="currentColor" />
        <path d="M1.69974 8.36764H3.0997C3.56635 8.36764 3.79968 8.60097 3.79968 9.06762V10.4676C3.79968 10.9342 3.56635 11.1676 3.09974 11.1676H1.69974C1.23308 11.1676 0.999756 10.9342 0.999756 10.4676V9.06762C0.999756 8.60097 1.23308 8.36764 1.69974 8.36764Z" fill="currentColor" />
        <path d="M18.4986 8.36774H5.89896C5.4323 8.36774 5.19897 8.60106 5.19897 9.06772V10.4677C5.19897 10.9343 5.4323 11.1677 5.89896 11.1677H18.4986C18.9653 11.1677 19.1986 10.9343 19.1986 10.4677V9.06772C19.1986 8.60106 18.9653 8.36774 18.4986 8.36774Z" fill="currentColor" />
        <path d="M1.69974 13.9676H3.0997C3.56635 13.9676 3.79968 14.201 3.79968 14.6676V16.0676C3.79968 16.5342 3.56635 16.7676 3.09974 16.7676H1.69974C1.23308 16.7676 0.999756 16.5344 0.999756 16.0678V14.6678C0.999756 14.2012 1.23308 13.9678 1.69974 13.9678Z" fill="currentColor" />
        <path d="M18.4986 13.9678H5.89896C5.4323 13.9678 5.19897 14.2012 5.19897 14.6678V16.0678C5.19897 16.5344 5.4323 16.7678 5.89896 16.7678H18.4986C18.9653 16.7678 19.1986 16.5344 19.1986 16.0678V14.6678C19.1986 14.2012 18.9653 13.9678 18.4986 13.9678Z" fill="currentColor" />
      </svg>
    </button>
    <span class="assessment-view-toggle__divider" aria-hidden="true"></span>
    <button
      type="button"
      aria-label="三列网格显示"
      :aria-pressed="modelValue === 'grid'"
      :class="{ 'assessment-view-toggle__button--active': modelValue === 'grid' }"
      @click="emit('update:modelValue', 'grid')"
    >
      <svg class="assessment-view-toggle__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2.5" y="2.5" width="6.667" height="6.667" rx="0.833" /><rect x="10.833" y="2.5" width="6.667" height="6.667" rx="0.833" /><rect x="2.5" y="10.833" width="6.667" height="6.667" rx="0.833" /><rect x="10.833" y="10.833" width="6.667" height="6.667" rx="0.833" /></svg>
    </button>
  </div>
</template>

<style scoped>
.assessment-view-toggle { display: flex; width: 76px; height: 36px; flex: 0 0 auto; align-items: center; justify-content: center; padding: 3px 4px; border: 1px solid #dedfe3; border-radius: 9px; background: #fff; }
.assessment-view-toggle button { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; border: 0; border-radius: 4px; color: #69707b; background: transparent; cursor: pointer; transition: color var(--motion-fast), background-color var(--motion-fast); }
.assessment-view-toggle button:hover { color: #252832; background: #f2f3f4; }
.assessment-view-toggle button.assessment-view-toggle__button--active { color: #00a9dd; }
.assessment-view-toggle__icon { width: 18px; height: 18px; fill: currentColor; }
.assessment-view-toggle__divider { width: 1px; height: 21px; flex: 0 0 1px; margin: 0 3px; background: #d9dce1; }
.assessment-view-toggle button:focus-visible { outline: 2px solid #279de0; outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  .assessment-view-toggle button { transition: none; }
}
</style>
