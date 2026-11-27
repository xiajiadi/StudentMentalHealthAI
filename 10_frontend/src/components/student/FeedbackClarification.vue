<script setup lang="ts">
/* global AbortController */
import { onBeforeUnmount, ref } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppTextarea from '@/components/app/AppTextarea.vue'
import { schoolSupport, supportError, supportRequestKey } from '@/services/school-support'
import { readWorkspaceFeedbackGuide, type FeedbackGuide } from '@/services/workspace-agent'

const props = defineProps<{ feedbackRef: string; revision: number; guideEnabled?: boolean }>()
const mode = ref<'guide' | 'clarify'>()
const question = ref('')
const busy = ref(false)
const submitted = ref(false)
const failure = ref('')
const guide = ref<FeedbackGuide>()
const searchedText = ref('')
let guideRequest: AbortController | undefined
let attempt: { question: string; key: string } | undefined

function open(next: 'guide' | 'clarify') {
  mode.value = next
  failure.value = ''
}

async function search() {
  const text = question.value.trim()
  if (text.length < 2 || text.length > 240 || busy.value) return
  const request = new AbortController()
  guideRequest = request
  busy.value = true
  failure.value = ''
  guide.value = undefined
  try {
    guide.value = await readWorkspaceFeedbackGuide(props.feedbackRef, props.revision, text, request.signal)
    searchedText.value = text
  } catch {
    if (!request.signal.aborted) failure.value = '校内导读暂时无法使用，可以请心理教师说明'
  } finally {
    busy.value = false
  }
}

async function sendQuestion() {
  const text = question.value.trim()
  if (!text || busy.value || submitted.value) return
  busy.value = true
  failure.value = ''
  try {
    if (!attempt || attempt.question !== text) attempt = { question: text, key: supportRequestKey() }
    await schoolSupport.askAboutFeedback(props.feedbackRef, props.revision, text, attempt.key)
    submitted.value = true
    question.value = ''
  } catch (cause) {
    failure.value = supportError(cause).replace(/。$/u, '')
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(() => guideRequest?.abort())
</script>

<template>
  <p v-if="submitted" role="status">已提交说明请求，可在学校支持中查看进度</p>
  <div v-else-if="!mode" class="feedback-clarification__actions">
    <AppButton v-if="guideEnabled" variant="secondary" @click="open('guide')">在这份反馈里查找</AppButton>
    <AppButton variant="secondary" @click="open('clarify')">请心理教师说明</AppButton>
  </div>
  <form v-else class="feedback-clarification" @submit.prevent="mode === 'guide' ? search() : sendQuestion()">
    <AppTextarea
      id="feedback-clarification-question"
      v-model="question"
      label="你想确认什么"
      :rows="3"
      :maxlength="mode === 'guide' ? 240 : 800"
      :readonly="busy"
      :hint="mode === 'guide' ? '学校服务会在当前反馈版本里找相关原句' : '学校心理教师会收到你填写的问题和这份反馈的编号'"
      placeholder="例如，反馈里的哪一项建议想请老师进一步说明"
    />
    <p v-if="failure" role="alert">{{ failure }}</p>
    <section v-if="mode === 'guide' && guide && searchedText === question.trim()" class="feedback-clarification__result" aria-live="polite">
      <template v-if="guide.status === 'matched'">
        <div v-for="item in guide.excerpts" :key="item.source + item.text">
          <strong>{{ item.source === 'next_steps' ? '老师建议原文' : '相关反馈原文' }}</strong>
          <blockquote>{{ item.text }}</blockquote>
        </div>
      </template>
      <p v-else-if="guide.status === 'unmatched'">这份反馈没有找到能直接对应你问题的原句</p>
      <p v-else>可以请学校心理教师继续协助你</p>
    </section>
    <div class="feedback-clarification__actions">
      <AppButton type="button" variant="quiet" :disabled="busy" @click="mode = undefined">返回</AppButton>
      <AppButton v-if="mode === 'guide'" type="submit" :loading="busy" :disabled="question.trim().length < 2 || question.trim().length > 240">查找相关原文</AppButton>
      <AppButton v-else type="submit" :loading="busy" :disabled="!question.trim()">提交说明请求</AppButton>
      <AppButton v-if="mode === 'guide'" variant="secondary" :disabled="busy" @click="open('clarify')">请心理教师说明</AppButton>
    </div>
  </form>
</template>

<style scoped>
.feedback-clarification { display: grid; gap: 8px; margin-block: 12px; }
.feedback-clarification__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.feedback-clarification__result { padding: 12px; border-radius: var(--radius-control); background: var(--color-surface-muted); }
.feedback-clarification__result blockquote { margin: 4px 0 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.feedback-clarification__result p { margin: 0; }
</style>
