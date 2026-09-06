<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight } from '@lucide/vue'
import { Eye } from '@lucide/vue'
import { EyeOff } from '@lucide/vue'
import { LockKeyhole } from '@lucide/vue'
import { ShieldCheck } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppInput from '@/components/app/AppInput.vue'
import AppLogo from '@/components/app/AppLogo.vue'
import { frontendApi, MockApiError } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'
import type { Role } from '@/types/contracts'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()

const account = ref('demo')
const password = ref('demo')
const role = ref<Role>('student')
const showPassword = ref(false)
const isLoading = ref(false)
const errorMessage = ref('')
const accountError = ref('')
const passwordError = ref('')

const roleOptions: Array<{ value: Role; label: string; hint: string }> = [
  { value: 'student', label: '学生', hint: '查看自己的支持参考' },
  { value: 'teacher', label: '教师', hint: '查看受控支持摘要' },
  { value: 'reviewer', label: '复核员', hint: '处理需要人工确认的流程' },
]

const selectedRoleHint = computed(() => roleOptions.find((item) => item.value === role.value)?.hint || '')

const validate = () => {
  accountError.value = account.value.trim() ? '' : '请输入演示账号。'
  passwordError.value = password.value ? '' : '请输入演示密码。'
  return !accountError.value && !passwordError.value
}

const submit = async () => {
  errorMessage.value = ''
  if (!validate()) return

  isLoading.value = true
  try {
    const response = await frontendApi.login({ account: account.value, password: password.value, role: role.value })
    session.signIn(response.data)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : null
    const fallback = role.value === 'student' ? '/student/home' : role.value === 'teacher' ? '/teacher/overview' : '/reviewer/queue'
    await router.push(redirect && redirect.startsWith('/') ? redirect : fallback)
  } catch (error) {
    errorMessage.value = error instanceof MockApiError ? error.message : '登录没有完成，请稍后重试。'
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro" aria-labelledby="login-title">
      <div class="login-intro__top">
        <AppLogo />
        <span class="login-intro__env">本地演示</span>
      </div>
      <div class="login-intro__copy">
        <span class="page-kicker">教育支持系统</span>
        <h1 id="login-title">一份支持，<br /><em>从看见开始。</em></h1>
        <p>心桥把测评、依据与人工确认放在同一条清晰的工作流里，帮助学生、教师和复核员在各自的范围内完成下一步。</p>
      </div>
      <div class="login-intro__footer">
        <span class="login-intro__rule" aria-hidden="true"></span>
        <span>测 · 译 · 用 · 验</span>
      </div>
    </section>

    <section class="login-panel" aria-label="登录表单">
      <div class="login-panel__head">
        <span class="login-panel__eyebrow">欢迎回来</span>
        <h2>进入你的工作区</h2>
        <p>当前使用合成账号，仅用于验证界面流程。</p>
      </div>

      <form class="login-form" novalidate @submit.prevent="submit">
        <AppInput
          id="account"
          v-model="account"
          label="演示账号"
          autocomplete="username"
          placeholder="请输入账号"
          :error="accountError"
        />

        <label class="password-field" for="password">
          <span class="password-field__label">演示密码</span>
          <span class="password-field__control">
            <LockKeyhole :size="16" aria-hidden="true" />
            <input
              id="password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              placeholder="请输入密码"
              :aria-invalid="Boolean(passwordError)"
              :aria-describedby="passwordError ? 'password-error' : 'password-hint'"
            />
            <button type="button" class="password-field__toggle" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
              <EyeOff v-if="showPassword" :size="17" aria-hidden="true" />
              <Eye v-else :size="17" aria-hidden="true" />
            </button>
          </span>
          <span v-if="passwordError" id="password-error" class="password-field__error" role="alert">{{ passwordError }}</span>
          <span v-else id="password-hint" class="password-field__hint">演示密码可填写 demo；填写 wrong 或 network 可查看失败状态。</span>
        </label>

        <fieldset class="role-picker">
          <legend>选择演示身份</legend>
          <div class="role-picker__options" role="radiogroup" aria-label="选择演示身份">
            <button
              v-for="option in roleOptions"
              :key="option.value"
              type="button"
              class="role-picker__option"
              :class="{ 'role-picker__option--active': role === option.value }"
              role="radio"
              :aria-checked="role === option.value"
              @click="role = option.value"
            >
              <span class="role-picker__radio" aria-hidden="true"></span>
              <span>{{ option.label }}</span>
            </button>
          </div>
          <span class="role-picker__hint">{{ selectedRoleHint }}</span>
        </fieldset>

        <p v-if="errorMessage" class="login-form__error" role="alert" aria-live="assertive">{{ errorMessage }}</p>

        <AppButton type="submit" size="lg" block :loading="isLoading">
          进入工作区
          <ArrowRight :size="17" aria-hidden="true" />
        </AppButton>
      </form>

      <div class="login-panel__boundary">
        <ShieldCheck :size="16" aria-hidden="true" />
        <p>本轮仅使用合成数据，不展示诊断、治疗或未经审核的个性化建议。</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(420px, 0.9fr); min-height: 100vh; background: var(--color-canvas); }
.login-intro { position: relative; display: flex; flex-direction: column; justify-content: space-between; min-height: 100vh; padding: 42px clamp(32px, 7vw, 104px); overflow: hidden; border-right: 1px solid var(--color-border); background: var(--color-surface-blue); }
.login-intro::before { position: absolute; top: 30%; right: -110px; width: 360px; height: 360px; border: 1px solid rgb(37 99 235 / 12%); border-radius: 50%; content: ""; }
.login-intro::after { position: absolute; top: 38%; right: -20px; width: 180px; height: 180px; border: 1px solid rgb(15 118 110 / 14%); border-radius: 50%; content: ""; }
.login-intro__top, .login-intro__copy, .login-intro__footer { position: relative; z-index: 1; }
.login-intro__top { display: flex; align-items: center; justify-content: space-between; }
.login-intro__env { padding: 6px 9px; border: 1px solid rgb(183 121 31 / 20%); border-radius: 5px; color: var(--color-attention); background: rgb(255 250 235 / 70%); font-size: 11px; font-weight: 800; }
.login-intro__copy { max-width: 510px; margin: auto 0; padding: 90px 0; }
.login-intro__copy h1 { margin: 19px 0 20px; color: var(--color-text-primary); font-family: var(--font-display); font-size: clamp(38px, 5vw, 66px); font-weight: 700; letter-spacing: -0.06em; line-height: 1.14; }
.login-intro__copy h1 em { color: var(--color-primary); font-style: normal; }
.login-intro__copy p { max-width: 440px; margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.9; }
.login-intro__footer { display: flex; align-items: center; gap: 12px; color: var(--color-text-muted); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.1em; }
.login-intro__rule { display: inline-block; width: 34px; height: 1px; background: var(--color-primary); }
.login-panel { display: flex; flex-direction: column; justify-content: center; width: min(100% - 96px, 440px); min-height: 100vh; margin: 0 auto; padding: 56px 0; }
.login-panel__head { margin-bottom: 32px; }
.login-panel__eyebrow { color: var(--color-primary); font-size: 12px; font-weight: 800; letter-spacing: 0.1em; }
.login-panel__head h2 { margin: 10px 0 8px; color: var(--color-text-primary); font-family: var(--font-display); font-size: 30px; letter-spacing: -0.04em; }
.login-panel__head p { margin: 0; color: var(--color-text-secondary); font-size: 13px; line-height: 1.65; }
.login-form { display: grid; gap: 20px; }
.password-field { display: grid; gap: 7px; }
.password-field__label { color: var(--color-text-primary); font-size: 13px; font-weight: 700; }
.password-field__control { display: flex; align-items: center; gap: 9px; min-height: 46px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); color: var(--color-text-muted); background: var(--color-surface); transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease; }
.password-field__control:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(147 197 253 / 32%); }
.password-field__control input { min-width: 0; flex: 1; height: 42px; border: 0; outline: 0; color: var(--color-text-primary); background: transparent; font-size: 14px; }
.password-field__control input::placeholder { color: var(--color-text-muted); }
.password-field__toggle { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 0; border-radius: 6px; color: var(--color-text-secondary); background: transparent; cursor: pointer; }
.password-field__toggle:hover { color: var(--color-primary); background: var(--color-info-wash); }
.password-field__hint, .password-field__error { font-size: 12px; line-height: 1.5; }
.password-field__hint { color: var(--color-text-muted); }
.password-field__error { color: var(--color-critical); }
.role-picker { min-width: 0; margin: 0; padding: 0; border: 0; }
.role-picker legend { margin-bottom: 9px; color: var(--color-text-primary); font-size: 13px; font-weight: 700; }
.role-picker__options { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.role-picker__option { display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 42px; border: 1px solid var(--color-border); border-radius: 7px; color: var(--color-text-secondary); background: var(--color-surface); cursor: pointer; font-size: 12px; font-weight: 700; transition: border-color var(--motion-fast) ease, color var(--motion-fast) ease, background-color var(--motion-fast) ease; }
.role-picker__option:hover { border-color: var(--color-primary); color: var(--color-primary); }
.role-picker__option--active { border-color: var(--color-primary); color: var(--color-primary); background: var(--color-info-wash); }
.role-picker__radio { width: 8px; height: 8px; border: 1px solid currentColor; border-radius: 50%; }
.role-picker__option--active .role-picker__radio { box-shadow: inset 0 0 0 2px var(--color-info-wash); background: currentColor; }
.role-picker__hint { display: block; margin-top: 8px; color: var(--color-text-muted); font-size: 12px; }
.login-form__error { margin: -5px 0 0; padding: 10px 12px; border: 1px solid rgb(180 35 24 / 20%); border-radius: 7px; color: var(--color-critical); background: var(--color-critical-wash); font-size: 13px; line-height: 1.55; }
.login-panel__boundary { display: flex; gap: 9px; margin-top: 28px; padding-top: 17px; border-top: 1px solid var(--color-border); color: var(--color-support); }
.login-panel__boundary p { margin: 0; color: var(--color-text-muted); font-size: 11px; line-height: 1.6; }

@media (max-width: 860px) {
  .login-page { grid-template-columns: 1fr; }
  .login-intro { min-height: auto; padding: 28px 24px 34px; border-right: 0; border-bottom: 1px solid var(--color-border); }
  .login-intro__copy { margin: 55px 0 30px; padding: 0; }
  .login-intro__copy h1 { font-size: clamp(36px, 10vw, 52px); }
  .login-intro__copy p { font-size: 13px; }
  .login-intro__footer { display: none; }
  .login-panel { width: min(100% - 48px, 440px); min-height: auto; padding: 44px 0 48px; }
}

@media (max-width: 480px) {
  .login-intro { padding: 22px 16px 28px; }
  .login-panel { width: min(100% - 32px, 440px); padding-top: 34px; }
  .role-picker__options { grid-template-columns: 1fr; }
  .role-picker__option { justify-content: flex-start; padding: 0 14px; }
}
</style>
