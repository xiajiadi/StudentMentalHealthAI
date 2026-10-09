<script setup lang="ts">
import { ref } from 'vue'
import { Eye, EyeOff, LockKeyhole, ShieldCheck } from '@lucide/vue'
import AppButton from '@/components/app/AppButton.vue'
import AppInput from '@/components/app/AppInput.vue'
import AppLogo from '@/components/app/AppLogo.vue'
import { useSessionStore } from '@/stores/session'
import { frontendApi } from '@/services/mock-api'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const account = ref('')
const password = ref('')
const showPassword = ref(false)
const isLoading = ref(false)
const errorMessage = ref('')
const accountError = ref('')
const passwordError = ref('')

const roleHome: Record<string, string> = {
  student: '/student/home', teacher: '/teacher/overview',
  psychological_specialist: '/specialist/overview', school_admin: '/admin/overview', reviewer: '/reviewer/queue',
}

const submit = async () => {
  errorMessage.value = ''
  accountError.value = account.value.trim() ? '' : '请输入账号。'
  passwordError.value = password.value ? '' : '请输入密码。'
  if (accountError.value || passwordError.value) return

  isLoading.value = true
  try {
    const response = await frontendApi.login({ account: account.value.trim(), password: password.value })
    session.signIn(response.data)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : null
    await router.push(redirect || roleHome[response.data.role] || '/login')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录没有完成，请稍后重试。'
  } finally { isLoading.value = false }
}
</script>

<template>
  <main class="login-page">
    <section class="login-visual" aria-label="心桥教育支持">
      <div class="login-visual__brand"><AppLogo /></div>
      <div class="login-visual__tile" aria-hidden="true">
        <div class="login-visual__orb login-visual__orb--one"></div><div class="login-visual__orb login-visual__orb--two"></div>
        <div class="login-visual__bridge"><span></span><span></span><span></span><span></span></div>
        <div class="login-visual__tile-copy"><small>HEARTBRIDGE</small><strong>让支持<br />清晰可达</strong><span>测评 · 依据 · 支持</span></div>
        <div class="login-visual__spark login-visual__spark--one"></div><div class="login-visual__spark login-visual__spark--two"></div>
      </div>
      <p class="login-visual__caption">在清晰的边界里，让每一步支持都有依据。</p>
    </section>

    <section class="login-side" aria-labelledby="login-title">
      <div class="login-card">
        <div class="login-card__brand"><AppLogo /></div>
        <div class="login-card__head">
          <span class="login-card__eyebrow">欢迎使用心桥</span>
          <h1 id="login-title">登录你的账号</h1>
          <p>请输入组织提供的账号和密码。</p>
        </div>
        <form class="login-form" novalidate @submit.prevent="submit">
          <AppInput id="account" v-model="account" label="账号" autocomplete="username" placeholder="请输入账号" :error="accountError" />
          <label class="password-field" for="password">
            <span class="password-field__label">密码</span>
            <span class="password-field__control"><LockKeyhole :size="16" aria-hidden="true" /><input id="password" v-model="password" :type="showPassword ? 'text' : 'password'" autocomplete="current-password" placeholder="请输入密码" :aria-invalid="Boolean(passwordError)" :aria-describedby="passwordError ? 'password-error' : undefined" /><button type="button" class="password-field__toggle" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" :size="17" /><Eye v-else :size="17" /></button></span>
            <span v-if="passwordError" id="password-error" class="password-field__error" role="alert">{{ passwordError }}</span>
          </label>
          <p v-if="errorMessage" class="login-form__error" role="alert" aria-live="assertive">{{ errorMessage }}</p>
          <AppButton type="submit" size="lg" block :loading="isLoading">登录</AppButton>
        </form>
        <div class="login-card__boundary"><ShieldCheck :size="17" aria-hidden="true" /><p>工作区和可访问内容由服务端账号权限决定。</p></div>
        <p class="login-card__help">登录遇到问题？请联系学校信息管理员。</p>
      </div>
      <footer class="login-side__footer">心桥 · 心理健康教育支持</footer>
    </section>
  </main>
</template>

<style scoped>
.login-page { display: grid; grid-template-columns: minmax(420px, .92fr) minmax(500px, 1.08fr); min-height: 100vh; background: #f4f5f6; }
.login-visual { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; padding: 34px; overflow: hidden; background: #f1f3f3; }
.login-visual__brand { position: absolute; top: 35px; left: 44px; }
.login-visual__tile { position: relative; display: flex; align-items: center; justify-content: center; width: min(100%, 440px); aspect-ratio: 1; overflow: hidden; border-radius: 26px; color: #fff; background: linear-gradient(145deg, rgb(0 167 207 / 30%), rgb(32 191 209 / 24%)), url('/assets/heartbridge/hero-flow-original.png') center / cover; box-shadow: 0 30px 70px rgb(21 108 117 / 17%); }
.login-visual__tile::before, .login-visual__tile::after { position: absolute; border: 1px solid rgb(255 255 255 / 22%); border-radius: 50%; content: ""; }
.login-visual__tile::before { width: 88%; aspect-ratio: 1; }
.login-visual__tile::after { width: 68%; aspect-ratio: 1; }
.login-visual__orb { position: absolute; border-radius: 50%; background: rgb(255 255 255 / 12%); filter: blur(1px); }
.login-visual__orb--one { top: -12%; right: -9%; width: 48%; aspect-ratio: 1; }
.login-visual__orb--two { bottom: -20%; left: -12%; width: 55%; aspect-ratio: 1; background: rgb(255 255 255 / 9%); }
.login-visual__bridge { position: absolute; top: 20%; left: 19%; display: flex; align-items: center; gap: 9px; width: 62%; transform: rotate(-22deg); }
.login-visual__bridge span { display: block; width: 25%; height: 1px; background: rgb(255 255 255 / 58%); }
.login-visual__bridge span:nth-child(2), .login-visual__bridge span:nth-child(4) { transform: translateY(-7px); }
.login-visual__tile-copy { position: relative; z-index: 1; display: grid; justify-items: center; gap: 15px; text-align: center; text-shadow: 0 2px 12px rgb(8 92 102 / 12%); }
.login-visual__tile-copy small { font-size: 10px; font-weight: 700; letter-spacing: .25em; opacity: .8; }
.login-visual__tile-copy strong { font-size: clamp(30px, 3.1vw, 46px); font-weight: 600; letter-spacing: .08em; line-height: 1.35; }
.login-visual__tile-copy span { font-size: 12px; letter-spacing: .12em; opacity: .85; }
.login-visual__spark { position: absolute; width: 7px; height: 7px; border: 1px solid rgb(255 255 255 / 78%); border-radius: 50%; }
.login-visual__spark--one { top: 23%; right: 21%; }.login-visual__spark--two { bottom: 24%; left: 22%; width: 5px; height: 5px; }
.login-visual__caption { margin: 24px 0 0; color: #747e84; font-size: 12px; letter-spacing: .04em; }
.login-side { position: relative; display: grid; place-items: center; min-height: 100vh; padding: 42px 36px 66px; background: #f8f9fa; }
.login-card { width: min(100%, 438px); padding: 43px 42px 35px; border: 1px solid #edf0f2; border-radius: 16px; background: white; box-shadow: 0 20px 55px rgb(24 39 49 / 7%); }
.login-card__brand { display: none; }
.login-card__head { margin: 0 0 29px; }
.login-card__eyebrow { color: #00a8d0; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.login-card__head h1 { margin: 10px 0 9px; color: #242d32; font-size: 26px; font-weight: 700; letter-spacing: -.035em; }
.login-card__head p { margin: 0; color: #828c92; font-size: 13px; line-height: 1.6; }
.login-form { display: grid; gap: 21px; }
.password-field { display: grid; gap: 7px; }
.password-field__label { color: #384349; font-size: 12px; font-weight: 700; }
.password-field__control { display: flex; align-items: center; gap: 9px; min-height: 47px; padding: 0 12px; border: 1px solid #dfe4e7; border-radius: 8px; color: #98a1a6; background: white; transition: border-color var(--motion-fast), box-shadow var(--motion-fast); }
.password-field__control:focus-within { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgb(0 177 226 / 12%); }
.password-field__control input { min-width: 0; flex: 1; height: 43px; border: 0; outline: 0; color: #303b41; background: transparent; font-size: 13px; }
.password-field__control input::placeholder { color: #abb3b7; }
.password-field__toggle { display: inline-grid; place-items: center; width: 32px; height: 32px; border: 0; border-radius: 6px; color: #7f898f; background: transparent; cursor: pointer; }
.password-field__error { color: #b42318; font-size: 11px; }
.login-form__error { margin: -7px 0 0; padding: 10px 12px; border: 1px solid rgb(180 35 24 / 18%); border-radius: 7px; color: #8f1d14; background: #fff3f1; font-size: 12px; line-height: 1.55; }
.login-card__boundary { display: flex; align-items: flex-start; gap: 9px; margin-top: 24px; padding-top: 18px; border-top: 1px solid #edf0f2; color: #00a8d0; }
.login-card__boundary p { margin: 0; color: #828c92; font-size: 11px; line-height: 1.6; }
.login-card__help { margin: 18px 0 0; color: #91999e; font-size: 11px; text-align: center; }
.login-side__footer { position: absolute; right: 30px; bottom: 21px; left: 30px; color: #a3aaae; font-size: 10px; text-align: center; }
@media (max-width: 960px) { .login-page { grid-template-columns: minmax(320px, .85fr) minmax(420px, 1.15fr); }.login-visual__brand { top: 25px; left: 26px; }.login-card { padding: 36px 30px 30px; } }
@media (max-width: 760px) { .login-page { display: flex; flex-direction: column; }.login-visual { min-height: auto; padding: 86px 22px 24px; }.login-visual__brand { top: 20px; left: 20px; }.login-visual__tile { width: min(67vw, 270px); border-radius: 18px; }.login-visual__tile-copy { gap: 8px; }.login-visual__tile-copy strong { font-size: 27px; }.login-visual__tile-copy small { font-size: 8px; }.login-visual__tile-copy span { font-size: 9px; }.login-visual__caption { margin-top: 15px; font-size: 10px; }.login-side { min-height: 0; flex: 1; padding: 10px 18px 60px; }.login-card { width: min(100%, 440px); padding: 31px 27px 27px; }.login-side__footer { bottom: 19px; } }
@media (max-width: 400px) { .login-visual { padding-top: 75px; }.login-visual__tile { width: 62vw; }.login-side { padding-right: 12px; padding-left: 12px; }.login-card { padding-right: 20px; padding-left: 20px; } }
</style>
