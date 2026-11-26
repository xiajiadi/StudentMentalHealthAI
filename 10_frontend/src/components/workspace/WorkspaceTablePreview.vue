<script setup lang="ts">
import { computed, ref } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppDialog from '@/components/app/AppDialog.vue'
import type { LocalWorkspaceSheet, WorkspaceTableSummary } from '@/services/workspace-table'

const props = defineProps<{ name: string; sheets: LocalWorkspaceSheet[] }>()
const emit = defineEmits<{ close: []; confirm: [summary: WorkspaceTableSummary] }>()
const selected = ref<number[]>([])
const sheetIndex = ref(0)
const sheet = computed(() => props.sheets[sheetIndex.value])
const table = computed(() => sheet.value.table)
const format = new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 8 })

function confirm() {
  if (!selected.value.length || selected.value.length > 12) return
  const columns = table.value.columns
    .filter(({ column }) => selected.value.includes(column))
    .map(({ column, count, min, max, mean, sum }) => ({ column, count, min, max, mean, sum }))
  emit('confirm', { rows: table.value.rows, columns })
}
</script>

<template>
  <AppDialog :open="true" title="选择表格统计" description="在本机计算。最多选择 12 个合成数据列，提交时只使用统计值和列号" @update:open="(open) => { if (!open) emit('close') }">
    <p class="table-filename">{{ name }} · {{ table.rows }} 行数据</p>
    <label v-if="sheets.length > 1" class="table-sheet">
      <span>选择工作表</span>
      <select v-model.number="sheetIndex" @change="selected = []">
        <option v-for="(option, index) in sheets" :key="index" :value="index">{{ option.name }}</option>
      </select>
    </label>
    <p v-else-if="sheet.name" class="table-filename">工作表 · {{ sheet.name }}</p>
    <ul class="table-choices" aria-label="可用数字列">
      <li v-for="column in table.columns" :key="column.column">
        <label>
          <input v-model="selected" type="checkbox" :value="column.column" :disabled="selected.length >= 12 && !selected.includes(column.column)" />
          <span>第 {{ column.column }} 列{{ column.label ? ` · ${column.label}` : '' }}</span>
          <small>{{ column.count }} 个数值 · 平均值 {{ format.format(column.mean) }} · 合计 {{ format.format(column.sum) }}</small>
        </label>
      </li>
    </ul>
    <small>空白、文字和超出 ±10 亿范围的单元格不会计入统计</small>
    <small v-if="sheet.name">第一行用作列名，公式只读取工作簿中已保存的数值</small>
    <div class="table-actions">
      <AppButton variant="quiet" @click="emit('close')">取消</AppButton>
      <AppButton :disabled="!selected.length" @click="confirm">使用所选统计</AppButton>
    </div>
  </AppDialog>
</template>

<style scoped>
.table-filename { overflow-wrap: anywhere; }
.table-sheet { display: grid; gap: 4px; }
.table-sheet select { width: 100%; min-height: 36px; padding: 5px 8px; color: var(--color-text-primary); background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-control); }
.table-choices { display: grid; gap: 8px; max-height: 38vh; overflow: auto; padding: 0; list-style: none; }
.table-choices label { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 4px 8px; cursor: pointer; overflow-wrap: anywhere; }
.table-choices label small { grid-column: 2; }
.table-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
</style>
