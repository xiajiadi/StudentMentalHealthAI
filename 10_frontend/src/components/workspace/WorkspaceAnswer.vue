<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ text: string }>()
const segments = computed(() => props.text.split(/(```[^\n]*\n[\s\S]*?```)/g)
  .filter((segment) => segment.trim())
  .map((segment) => segment.startsWith('```')
    ? { code: segment.slice(segment.indexOf('\n') + 1, -3).trimEnd(), lines: [] }
    : { code: undefined, lines: segment.trim().split('\n') }))
</script>

<template>
  <div class="answer">
    <template v-for="(segment, index) in segments" :key="index">
      <pre v-if="segment.code !== undefined"><code>{{ segment.code }}</code></pre>
      <template v-else>
        <template v-for="(line, lineIndex) in segment.lines" :key="lineIndex">
          <component :is="line.startsWith('### ') ? 'h4' : 'h3'" v-if="/^#{1,3}\s/.test(line)">{{ line.replace(/^#{1,3}\s+/, '') }}</component>
          <p v-else-if="line.trim()" :class="{ 'answer__bullet': /^\s*[-*]\s/.test(line) }">
            <template v-for="(part, partIndex) in line.replace(/^\s*[-*]\s+/, '• ').split(/(\*\*[^*]+\*\*|`[^`]+`)/g)" :key="partIndex">
              <strong v-if="part.startsWith('**') && part.endsWith('**') && part.length > 4">{{ part.slice(2, -2) }}</strong>
              <code v-else-if="part.startsWith('`') && part.endsWith('`') && part.length > 2">{{ part.slice(1, -1) }}</code>
              <template v-else>{{ part }}</template>
            </template>
          </p>
        </template>
      </template>
    </template>
  </div>
</template>

<style scoped>
.answer { display: grid; gap: 7px; overflow-wrap: anywhere; min-width: 0; }
.answer h3, .answer h4 { margin: 6px 0 0; }
.answer p { margin: 0; }
.answer__bullet { padding-inline-start: 12px; }
.answer pre { overflow: auto; background: var(--color-info-wash); padding: 12px; border-radius: var(--radius-control); }
</style>
