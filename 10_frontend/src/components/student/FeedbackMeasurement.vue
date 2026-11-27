<script setup lang="ts">
/* global AbortController */
import { onBeforeUnmount, ref } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppCard from '@/components/app/AppCard.vue'
import AppStatusCallout from '@/components/app/AppStatusCallout.vue'
import { readWorkspaceFeedbackMeasurement, type FeedbackMeasurement } from '@/services/workspace-agent'

const props = defineProps<{ feedbackRef: string }>()
const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const measurement = ref<FeedbackMeasurement>()
const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
let controller: AbortController | undefined

async function open() {
  if (state.value === 'loading') return
  const request = new AbortController()
  controller = request
  state.value = 'loading'
  try {
    const result = await readWorkspaceFeedbackMeasurement(props.feedbackRef, request.signal)
    if (request.signal.aborted) return
    measurement.value = result
    state.value = 'ready'
  } catch {
    if (!request.signal.aborted) state.value = 'error'
  }
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="feedback-measurement">
    <AppButton v-if="state === 'idle' || state === 'loading'" variant="secondary" :disabled="state === 'loading'" @click="open">
      {{ state === 'loading' ? '正在读取测量记录' : '查看本次测量记录' }}
    </AppButton>
    <AppStatusCallout v-else-if="state === 'error'" tone="attention" title="本次测量记录暂时无法打开">
      <AppButton variant="secondary" size="sm" @click="open">重试</AppButton>
    </AppStatusCallout>
    <AppCard v-else-if="measurement" class="feedback-measurement__record">
      <h4>本次测量记录</h4>
      <dl>
        <div><dt>完成时间</dt><dd>{{ dateFormat.format(new Date(measurement.completed_at)) }}</dd></div>
        <div><dt>已答题数</dt><dd>{{ measurement.answered_count }}</dd></div>
        <div><dt>题库版本</dt><dd>{{ measurement.item_bank_version || '记录未提供' }}</dd></div>
      </dl>
      <template v-if="measurement.status === 'engineering' && measurement.dimensions.some((item) => item.estimate !== null)">
        <p>这些数值是合成题库的算法估计，只用于核对本次测量。标准误表示估计的不确定程度</p>
        <dl v-for="dimension in measurement.dimensions" :key="dimension.label" class="feedback-measurement__dimension">
          <div><dt>测量维度</dt><dd>{{ dimension.label }}</dd></div>
          <div><dt>估计值（θ）</dt><dd>{{ dimension.estimate ?? '数据不足' }}</dd></div>
          <div><dt>标准误（SE）</dt><dd>{{ dimension.standard_error ?? '记录未提供' }}</dd></div>
        </dl>
      </template>
      <p v-else>{{ measurement.status === 'unscored' ? '本次没有计算分数' : '本次记录暂无可展示的测量值' }}</p>
    </AppCard>
  </div>
</template>

<style scoped>
.feedback-measurement { margin-block: 12px; }
.feedback-measurement__record { display: grid; gap: 12px; padding: 16px; }
.feedback-measurement__record h4,
.feedback-measurement__record p,
.feedback-measurement__record dl,
.feedback-measurement__record dd { margin: 0; }
.feedback-measurement__record p,
.feedback-measurement__record dt { color: var(--color-text-secondary); font-size: 13px; }
.feedback-measurement__record dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 110px), 1fr)); gap: 8px; }
.feedback-measurement__record dd { overflow-wrap: anywhere; font-size: 14px; }
.feedback-measurement__dimension { padding-top: 10px; border-top: 1px solid var(--color-border); }
</style>
