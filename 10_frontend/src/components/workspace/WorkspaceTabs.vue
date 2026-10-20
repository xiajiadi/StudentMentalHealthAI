<script setup lang="ts">
import { TabsContent, TabsIndicator, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'

export type WorkspaceTabOption = {
  value: string
  label: string
  disabled?: boolean
}

defineProps<{
  modelValue: string
  tabs: readonly WorkspaceTabOption[]
  label: string
  id?: string
  keepMounted?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <TabsRoot
    :id="id"
    :model-value="modelValue"
    activation-mode="automatic"
    class="workspace-tabs-root"
    @update:model-value="emit('update:modelValue', String($event))"
  >
    <TabsList
      class="workspace-tabs"
      :aria-label="label"
      :style="{ '--workspace-tabs-count': Math.max(tabs.length, 1) }"
    >
      <TabsIndicator class="workspace-tabs__indicator" aria-hidden="true" />
      <TabsTrigger
        v-for="tab in tabs"
        :key="tab.value"
        class="workspace-tabs__tab"
        :value="tab.value"
        :disabled="tab.disabled"
      >
        {{ tab.label }}
      </TabsTrigger>
    </TabsList>

    <TabsContent
      v-for="tab in tabs"
      :key="`${tab.value}-panel`"
      class="workspace-tabs__panel"
      :value="tab.value"
      :force-mount="keepMounted || undefined"
    >
      <slot name="panel" :tab="tab" />
    </TabsContent>
  </TabsRoot>
</template>

<style scoped>
.workspace-tabs-root { display: block; min-width: 0; }

:deep(.workspace-tabs) {
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--workspace-tabs-count), minmax(0, 1fr));
  min-width: 0;
  padding: 4px;
  border: 1px solid #e2eae6;
  border-radius: 12px;
  background: #f3f7f5;
  isolation: isolate;
}

:deep(.workspace-tabs__indicator) {
  position: absolute;
  z-index: 0;
  top: 0;
  left: 0;
  width: var(--reka-tabs-indicator-size, 0px);
  height: var(--reka-tabs-indicator-thickness, 0px);
  border: 1px solid #e4ebe7;
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 1px 3px rgb(32 60 48 / 7%);
  transform: translateX(var(--reka-tabs-indicator-position, 0px));
  transition: transform 220ms cubic-bezier(.2, .8, .2, 1);
  pointer-events: none;
}

:deep(.workspace-tabs__tab) {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  min-height: 40px;
  padding: 8px 11px;
  border: 0;
  border-radius: 9px;
  color: #60746b;
  background: transparent;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  line-height: 1.35;
  text-align: center;
  overflow-wrap: anywhere;
  cursor: pointer;
  transition: color 180ms ease;
}

:deep(.workspace-tabs__tab[data-state="active"]) { color: #246d60; }
:deep(.workspace-tabs__tab:disabled) { opacity: .5; cursor: not-allowed; }
:deep(.workspace-tabs__tab:focus-visible) { outline: 2px solid var(--color-focus-ring, #38a4bf); outline-offset: 1px; }
:deep(.workspace-tabs__panel) { min-width: 0; }
:deep(.workspace-tabs__panel:focus-visible) { outline: 2px solid var(--color-focus-ring, #38a4bf); outline-offset: 3px; border-radius: 10px; }

@media (max-width: 420px) {
  :deep(.workspace-tabs__tab) { min-height: 38px; padding-inline: 6px; font-size: 12px; }
}

@media (prefers-reduced-motion: reduce) {
  :deep(.workspace-tabs__indicator),:deep(.workspace-tabs__tab) { transition-duration: .01ms; }
}
</style>
