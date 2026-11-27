<script setup lang="ts">
import { ref } from 'vue'
import AppButton from '@/components/app/AppButton.vue'
import AppTextarea from '@/components/app/AppTextarea.vue'
import { schoolSupport, supportError, supportRequestKey } from '@/services/school-support'

const props = defineProps<{ feedbackRef: string; revision: number }>()
const open = ref(false)
const question = ref('')
const busy = ref(false)
const submitted = ref(false)
const failure = ref('')
let attempt: { question: string; key: string } | undefined

async function submit() {
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
</script>

<template>
  <p v-if="submitted" role="status">已提交说明请求，可在学校支持中查看进度</p>
  <AppButton v-else-if="!open" variant="secondary" @click="open = true">请心理教师说明</AppButton>
  <form v-else class="feedback-clarification" @submit.prevent="submit">
    <AppTextarea
      id="feedback-clarification-question"
      v-model="question"
      label="你想确认什么"
      :rows="3"
      :maxlength="800"
      :readonly="busy"
      hint="学校心理教师会收到你填写的问题和这份反馈的编号"
      placeholder="例如，反馈里的哪一项建议想请老师进一步说明"
    />
    <p v-if="failure" role="alert">{{ failure }}</p>
    <div class="feedback-clarification__actions">
      <AppButton type="button" variant="quiet" :disabled="busy" @click="open = false">返回</AppButton>
      <AppButton type="submit" :loading="busy" :disabled="!question.trim()">提交说明请求</AppButton>
    </div>
  </form>
</template>

<style scoped>
.feedback-clarification { display: grid; gap: 8px; margin-block: 12px; }
.feedback-clarification__actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
