<script setup lang="ts">
import { ref } from 'vue'
import AppCard from '@/components/app/AppCard.vue'
import AdminOperationsAudit from '@/components/school/AdminOperationsAudit.vue'
import SafetyAssignments from '@/components/school/SafetyAssignments.vue'

type LoadState = 'loading' | 'ready' | 'error'

const props = defineProps<{ scopeKey: string }>()
const auditState = ref<LoadState>('loading')
const auditPageCount = ref<number | null>(null)
const assignmentsState = ref<LoadState>('loading')
const unassignedTotal = ref<number | null>(null)

function updateAuditSummary(summary: { state: LoadState; count: number | null }) {
  auditState.value = summary.state
  auditPageCount.value = summary.count
}
function updateAssignmentSummary(summary: { state: LoadState; total: number | null }) {
  assignmentsState.value = summary.state
  unassignedTotal.value = summary.total
}
</script>

<template>
  <section class="admin-operations-workspace" aria-label="学校运营事务工作区">
    <AppCard class="admin-operations-workspace__summary" aria-label="运营事务概况">
      <div class="admin-operations-workspace__summary-label"><strong>工作概况</strong><span>按当前页面权限返回</span></div>
      <dl>
        <div><dt>本页操作记录</dt><dd>{{ auditState === 'ready' ? auditPageCount : '—' }}</dd></div>
        <div><dt>本校待分配事项</dt><dd>{{ assignmentsState === 'ready' ? unassignedTotal : '—' }}</dd></div>
      </dl>
    </AppCard>

    <section class="admin-operations-workspace__panel" aria-label="操作记录工作区">
      <AdminOperationsAudit :key="props.scopeKey" :scope-key="props.scopeKey" @summary-change="updateAuditSummary" />
    </section>
    <section class="admin-operations-workspace__panel" aria-label="事项分配工作区">
      <SafetyAssignments :key="props.scopeKey" @summary-change="updateAssignmentSummary" />
    </section>
  </section>
</template>

<style scoped>
.admin-operations-workspace { display: grid; gap: 18px; min-width: 0; }
.admin-operations-workspace__summary { display: grid; grid-template-columns: minmax(150px,.55fr) minmax(0,1.45fr); align-items: center; gap: 16px; padding: 13px 17px; }
.admin-operations-workspace__summary-label { display: grid; gap: 4px; }
.admin-operations-workspace__summary-label strong { color: #365361; font-size: 15px; }
.admin-operations-workspace__summary-label span { color: #82939a; font-size: 12px; }
.admin-operations-workspace__summary dl { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); margin: 0; }
.admin-operations-workspace__summary dl > div { display: grid; gap: 4px; min-width: 0; padding: 2px 17px; border-left: 1px solid #edf0f2; }
.admin-operations-workspace__summary dt { color: #82929a; font-size: 13px; }
.admin-operations-workspace__summary dd { margin: 0; color: #2b4553; font-size: 23px; font-weight: 720; font-variant-numeric: tabular-nums; }
.admin-operations-workspace__summary dl > div:nth-child(2) dd { color: #9a7026; }
.admin-operations-workspace__panel { min-width: 0; padding-top: 2px; }
@media (max-width: 660px) {
  .admin-operations-workspace { gap: 12px; }
  .admin-operations-workspace__summary { grid-template-columns: minmax(0,1fr); gap: 11px; padding: 12px; }
  .admin-operations-workspace__summary dl > div { padding-inline: 10px; }
  .admin-operations-workspace__summary dl > div:first-child { padding-left: 0; border-left: 0; }
}
</style>
