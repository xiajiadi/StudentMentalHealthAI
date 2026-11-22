<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown } from '@lucide/vue'
import { CollapsibleContent, CollapsibleRoot, CollapsibleTrigger } from 'reka-ui'
import { useRoute } from 'vue-router'
import AppDialog from '@/components/app/AppDialog.vue'
import type { Role } from '@/types/contracts'
import { workspaceGuides, helpTopics, type HelpTopic } from './workspace-guides'

const props = defineProps<{ role: Role; topic: HelpTopic }>()
const emit = defineEmits<{ close: [] }>()
const route = useRoute()
const sections = computed(() => props.topic === 'manual' ? workspaceGuides[props.role].sections : helpTopics[props.topic].sections)
const title = computed(() => props.topic === 'manual' ? workspaceGuides[props.role].title : helpTopics[props.topic].title)
const description = computed(() => props.topic === 'manual' ? workspaceGuides[props.role].intro : helpTopics[props.topic].intro)
const currentSection = computed(() => props.topic === 'manual' ? sections.value.find((section) => section.path === route.path)?.title : undefined)
const openSections = ref<Record<string, boolean>>({})
const isOpen = (key: string) => openSections.value[key] ?? (key === currentSection.value || key === sections.value[0]?.title)
</script>

<template>
  <AppDialog :open="true" :title="title" :description="description" @update:open="emit('close')">
    <div class="workspace-guide">
      <CollapsibleRoot v-for="section in sections" :key="section.title" class="workspace-guide__section" :open="isOpen(section.title)" @update:open="openSections[section.title] = $event">
        <CollapsibleTrigger class="workspace-guide__trigger">
          {{ section.title }}
          <ChevronDown :size="16" aria-hidden="true" />
        </CollapsibleTrigger>
        <CollapsibleContent class="workspace-guide__body">
          <ol>
            <li v-for="step in section.steps" :key="step">{{ step }}</li>
          </ol>
          <RouterLink v-if="section.path && route.path !== section.path" :to="section.path" @click="emit('close')">打开页面</RouterLink>
        </CollapsibleContent>
      </CollapsibleRoot>
    </div>
  </AppDialog>
</template>

<style scoped>
.workspace-guide { display: grid; gap: 8px; }
.workspace-guide__section { border: 1px solid var(--color-border); border-radius: var(--radius-control); }
.workspace-guide__trigger { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 10px; padding: 11px 12px; border: 0; border-radius: var(--radius-control); color: var(--color-text-primary); background: transparent; text-align: start; font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
.workspace-guide__trigger:hover { color: var(--color-primary); }
.workspace-guide__trigger:focus-visible, .workspace-guide__section a:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.workspace-guide__trigger svg { flex: none; transition: transform 220ms ease; }
.workspace-guide__trigger[data-state='open'] svg { transform: rotate(180deg); }
.workspace-guide__body { overflow: hidden; }
.workspace-guide__body[data-state='open'] { animation: guide-expand 220ms ease both; }
.workspace-guide__body[data-state='closed'] { animation: guide-collapse 190ms ease both; }
@keyframes guide-expand { from { height: 0; opacity: .65; } to { height: var(--reka-collapsible-content-height); opacity: 1; } }
@keyframes guide-collapse { from { height: var(--reka-collapsible-content-height); opacity: 1; } to { height: 0; opacity: .65; } }
@media (prefers-reduced-motion: reduce) { .workspace-guide__trigger svg { transition: none; } .workspace-guide__body[data-state] { animation: none; } }
.workspace-guide__section ol { display: grid; gap: 6px; margin: 0; padding: 0 16px 12px 34px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.workspace-guide__section a { display: inline-block; margin: 0 12px 12px; color: var(--color-primary); font-size: 13px; }
</style>
