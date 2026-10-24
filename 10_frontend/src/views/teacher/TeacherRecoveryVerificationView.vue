<script setup lang="ts">
import { ref } from 'vue'
import { frontendApi } from '@/services/mock-api'

const ticketRef = ref('')
const reasonCode = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')

const verify = async () => {
  error.value = ''; notice.value = ''
  if (!ticketRef.value.trim() || !reasonCode.value.trim()) {
    error.value = '请填写恢复请求编号和核验原因代码'
    return
  }
  if (!frontendApi.verifyRecoveryRequest) {
    error.value = '教师核验服务暂不可用'
    return
  }
  busy.value = true
  try {
    await frontendApi.verifyRecoveryRequest(ticketRef.value.trim(), reasonCode.value.trim())
    notice.value = '已提交，请提醒学生等待管理员审批'
    ticketRef.value = ''; reasonCode.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '核验未完成'
  } finally { busy.value = false }
}
</script>

<template>
  <main class="recovery-verify content-wrap" aria-labelledby="recovery-verify-title">
    <header><p>账号安全</p><h1 id="recovery-verify-title">教师身份核验</h1><span>核对学生身份后提交核验结果</span></header>
    <form @submit.prevent="verify">
      <label for="recovery-ticket">恢复请求编号</label><input id="recovery-ticket" v-model.trim="ticketRef" autocomplete="off" required>
      <p class="recovery-verify__hint">管理员审批后发放恢复凭据</p>
      <label for="recovery-reason">核验原因代码</label><input id="recovery-reason" v-model.trim="reasonCode" autocomplete="off" required>
      <p v-if="error" class="recovery-verify__error" role="alert">{{ error }}</p>
      <p v-if="notice" class="recovery-verify__notice" role="status" aria-live="polite">{{ notice }}</p>
      <button type="submit" :disabled="busy">{{ busy ? '正在提交…' : '提交核验' }}</button>
    </form>
  </main>
</template>

<style scoped>
.recovery-verify { display: grid; align-content: start; gap: 22px; padding-top: 28px; padding-bottom: 48px; color: var(--color-text-primary); }
.recovery-verify header { display: grid; gap: 6px; }.recovery-verify header p { margin: 0; color: var(--color-primary); font-size: 12px; }.recovery-verify h1 { margin: 0; font-size: 20px; }.recovery-verify header span,.recovery-verify__hint { color: var(--color-text-muted); font-size: 12px; }
.recovery-verify form { display: grid; justify-self: start; gap: 9px; width: min(100%,560px); padding: 18px; border: .5px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }.recovery-verify label { margin-top: 5px; color: var(--color-text-secondary); font-size: 12px; }.recovery-verify input { min-height: 38px; padding: 7px 10px; border: .5px solid var(--color-border-strong); border-radius: var(--radius-control); color: var(--color-text-primary); background: var(--color-surface); font: inherit; font-size: 12px; }.recovery-verify__hint { margin: 0; }.recovery-verify__error,.recovery-verify__notice { margin: 0; padding: 9px; border: .5px solid var(--color-border); font-size: 12px; }.recovery-verify__error { border-color: var(--color-critical); color: var(--color-critical); background: var(--color-critical-wash); }.recovery-verify__notice { border-color: var(--color-support); color: var(--color-support); background: var(--color-support-wash); }.recovery-verify button { min-height: 38px; border: .5px solid var(--color-primary); border-radius: var(--radius-button); color: var(--color-text-inverse); background: var(--color-primary); font: inherit; font-size: 12px; cursor: pointer; }.recovery-verify button:disabled { cursor: wait; opacity: .6; }.recovery-verify input:focus-visible,.recovery-verify button:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
</style>
