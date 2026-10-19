<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { CircleHelp, X } from '@lucide/vue'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import AppButton from '@/components/app/AppButton.vue'
import { useSessionStore } from '@/stores/session'
import { useAssessmentStore } from '@/stores/assessment'
import type { LoginResult } from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const assessment = useAssessmentStore()
const pendingContext = ref<LoginResult | null>(null)
const selectedContext = ref('')
const account = ref('')
const password = ref('')
const isLoading = ref(false)
const helpOpen = ref(false)
const errorMessage = ref('')
const accountError = ref('')
const passwordError = ref('')

const roleHome: Record<string, string> = {
  student: '/student/home', teacher: '/teacher/overview',
  psychological_specialist: '/specialist/overview', school_admin: '/admin/overview', reviewer: '/reviewer/queue',
}

const roleLabels: Record<string, string> = {
  student: 'Student', teacher: 'Teacher', psychological_specialist: 'Psychological specialist', school_admin: 'School administrator',
}

onMounted(() => {
  if (session.user?.availableContexts?.length && !session.user.activeContext) pendingContext.value = session.user
})

const enterWorkspace = async (user: LoginResult) => {
  assessment.reset()
  session.signIn(user)
  const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') && !route.query.redirect.startsWith('//') ? route.query.redirect : null
  await router.push(redirect || roleHome[user.role] || '/login')
}

const chooseContext = async () => {
  const context = pendingContext.value?.availableContexts?.[Number(selectedContext.value)]
  if (!selectedContext.value || !context || !frontendApi.switchActiveContext) return
  isLoading.value = true
  errorMessage.value = ''
  try {
    const result = await frontendApi.switchActiveContext(context)
    if (result.data.userId !== pendingContext.value?.userId || result.data.activeContext?.role !== context.role || result.data.activeContext.schoolRef !== context.schoolRef) {
      throw new Error('Workspace selection has not been confirmed')
    }
    await enterWorkspace(result.data)
    pendingContext.value = null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Workspace selection could not be completed'
  } finally { isLoading.value = false }
}

const submit = async () => {
  errorMessage.value = ''
  accountError.value = account.value.trim() ? '' : 'Enter your username'
  passwordError.value = password.value ? '' : 'Enter your password'
  if (accountError.value || passwordError.value) return

  isLoading.value = true
  try {
    const response = await frontendApi.login({ account: account.value.trim(), password: password.value })
    password.value = ''
    if (response.data.availableContexts?.length && !response.data.activeContext) {
      pendingContext.value = response.data
      return
    }
    await enterWorkspace(response.data)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Sign in could not be completed. Try again later'
    errorMessage.value = message.replace(/[。.]$/, '')
  } finally { isLoading.value = false }
}
</script>

<template>
  <main class="login-page">
    <img class="login-page__brand" src="/assets/psynova/wordmark.png" alt="PsyNova">

    <div class="login-content">
      <section class="login-visual" aria-label="PsyNova Workspace">
        <div class="login-visual__tile" aria-hidden="true">
          <img class="login-visual__flow-track" src="/assets/psynova/gentle-rightward-flow.svg" alt="" aria-hidden="true">
          <span>PsyNova Workspace</span>
        </div>
      </section>

      <section class="login-side" aria-labelledby="login-title">
        <div class="login-card">
          <div class="login-card__brand">
            <img src="/assets/psynova/mark.png" alt="" aria-hidden="true">
          </div>
          <div class="login-card__head">
            <h1 id="login-title">Enter your workspace</h1>
          </div>
          <form v-if="!pendingContext" class="login-form" novalidate @submit.prevent="submit">
            <div class="login-field">
              <input
                id="account"
                v-model="account"
                class="login-input"
                type="text"
                autocomplete="username"
                placeholder="Enter your username"
                aria-label="Username"
                :aria-invalid="Boolean(accountError)"
                :aria-describedby="accountError ? 'account-error' : undefined"
              >
              <p v-if="accountError" id="account-error" class="login-field__error" role="alert">{{ accountError }}</p>
            </div>
            <div class="login-field">
              <input
                id="password"
                v-model="password"
                class="login-input"
                type="password"
                autocomplete="current-password"
                placeholder="Enter your password"
                aria-label="Password"
                :aria-invalid="Boolean(passwordError)"
                :aria-describedby="passwordError ? 'password-error' : undefined"
              >
              <p v-if="passwordError" id="password-error" class="login-field__error" role="alert">{{ passwordError }}</p>
            </div>
            <p v-if="errorMessage" class="login-form__error" role="alert" aria-live="assertive">{{ errorMessage }}</p>
            <AppButton class="login-submit" type="submit" size="md" block :loading="isLoading">Continue</AppButton>
          </form>
          <form v-else class="login-form school-context-choice" @submit.prevent="chooseContext">
            <label for="school-context">Choose your workspace</label>
            <select id="school-context" v-model="selectedContext" class="login-input" aria-label="School workspace">
              <option disabled value="">Select a school and role</option>
              <option v-for="(context, index) in pendingContext.availableContexts" :key="`${context.schoolRef}:${context.role}`" :value="String(index)">
                {{ context.schoolRef }}，{{ roleLabels[context.role] }}
              </option>
            </select>
            <p v-if="errorMessage" class="login-form__error" role="alert">{{ errorMessage }}</p>
            <AppButton class="login-submit" type="submit" size="md" block :loading="isLoading" :disabled="!selectedContext || !frontendApi.switchActiveContext">Continue</AppButton>
          </form>
        </div>
      </section>
    </div>

    <button class="login-help-trigger" type="button" aria-label="Help" @click="helpOpen = true">
      <CircleHelp :size="18" aria-hidden="true" />
    </button>

    <DialogRoot :open="helpOpen" @update:open="helpOpen = $event">
      <DialogPortal>
        <DialogOverlay class="login-help-overlay" />
        <DialogContent class="login-help-dialog">
          <DialogClose as-child>
            <button class="login-help-close" type="button" aria-label="Close">
              <X :size="18" aria-hidden="true" />
            </button>
          </DialogClose>
          <div class="login-help-content">
            <DialogTitle class="login-help-title">Help</DialogTitle>
            <DialogDescription id="login-help-copy" class="login-help-copy">
              Use the username and password provided by your school. Contact your school administrator if you cannot sign in or access your workspace
            </DialogDescription>
            <DialogClose as-child>
              <button class="login-help-confirm" type="button">Got it</button>
            </DialogClose>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </main>
</template>

<style scoped>
.login-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  min-height: 100svh;
  place-items: center;
  padding: 60px 40px;
  background: linear-gradient(276deg, #f7f7f7 2.53%, #f1f1f3 97.25%);
  color: #1e1d29;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Segoe UI", "Noto Sans", ui-sans-serif, system-ui, sans-serif;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.6;
}

.login-page__brand {
  position: absolute;
  top: 20px;
  left: 20px;
  display: block;
  width: 160px;
  height: 80px;
  object-fit: contain;
}

.login-content {
  --login-art-width: clamp(310px, 21.3vw, 409px);
  --login-card-width: clamp(500px, 26.9vw, 520px);

  display: grid;
  grid-template-columns: var(--login-art-width) var(--login-card-width);
  align-items: center;
  gap: 100px;
  width: min(100%, calc(var(--login-art-width) + 100px + var(--login-card-width)));
}

.login-visual {
  display: flex;
  justify-content: center;
}

.login-visual__tile {
  position: relative;
  display: grid;
  width: 100%;
  height: auto;
  aspect-ratio: 31 / 27;
  place-items: center;
  overflow: hidden;
  color: #fff;
  background-color: #118edb;
}

.login-visual__flow-track {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}

.login-visual__tile span {
  position: relative;
  z-index: 1;
  color: rgb(255 255 255 / 94%);
  font-size: clamp(25px, 1.35vw, 26px);
  font-weight: 600;
  letter-spacing: -.035em;
  line-height: 1.2;
  text-align: center;
  text-shadow: 0 1px 10px rgb(8 31 91 / 24%);
}

.login-side {
  display: grid;
  place-items: center;
}

.login-card {
  display: flex;
  width: var(--login-card-width);
  flex: 0 0 auto;
  flex-direction: column;
  align-items: center;
  gap: clamp(20px, 1.15vw, 22px);
  padding: clamp(40px, 2.2vw, 44px) clamp(30px, 1.67vw, 32px) clamp(50px, 2.8vw, 54px);
  border: 0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 20px 12px rgb(0 0 0 / 2%), 0 9px 9px rgb(0 0 0 / 2%), 0 2px 5px rgb(0 0 0 / 2%);
}

.login-card__brand {
  display: grid;
  width: 50px;
  height: 50px;
  flex: 0 0 50px;
  place-items: center;
  overflow: hidden;
  border-radius: 12px;
}

.login-card__brand img {
  display: block;
  width: 50px;
  height: 50px;
  object-fit: contain;
}

.login-card__head {
  width: 100%;
  margin: 0;
  text-align: center;
}

.login-card__head h1 {
  margin: 0;
  color: #1e1d29;
  font-size: clamp(21px, 1.1vw, 22px);
  font-weight: 600;
  line-height: 1.3;
}

.login-form {
  display: grid;
  width: 100%;
  gap: 10px;
}

.login-field {
  display: grid;
  gap: 6px;
}

.login-input {
  display: inline-block;
  position: relative;
  width: 100%;
  padding: clamp(13px, 0.7vw, 14px) 20px;
  border: 1px solid transparent;
  border-radius: 6px;
  outline: none;
  color: #1e1d29;
  background: rgb(24 26 31 / 7%);
  font: inherit;
  font-size: clamp(16px, 0.9vw, 17px);
  font-weight: 500;
  line-height: 1.3;
  transition: all 0.2s ease-in-out;
}

.login-input::placeholder {
  color: #a0a3ab;
  opacity: 1;
}

.login-input:focus,
.login-input:focus-visible {
  border-color: #3f424a;
  outline: none;
  color: #1e1d29;
}

.login-input[aria-invalid='true'] {
  border-color: #d53633;
}

.login-field__error {
  margin: 0 2px;
  color: #d53633;
  font-size: 12px;
  line-height: 1.4;
}

.login-form__error {
  margin: 0;
  padding: 9px 11px;
  border: 1px solid rgb(213 54 51 / 18%);
  border-radius: 6px;
  color: #a3261b;
  background: #fff3f1;
  font-size: 12px;
  line-height: 1.5;
}

.login-card :deep(.login-submit) {
  width: 100%;
  min-height: 0;
  padding: 10px 20px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #fff;
  background: #00b1e2;
  box-shadow: none;
  font-family: inherit;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
  transition: all 0.2s ease-in-out;
}

.login-card :deep(.login-submit:hover:not(:disabled)) {
  transform: none;
  color: #fff;
  background: #33c1e8;
  box-shadow: none;
}

.login-card :deep(.login-submit:active:not(:disabled)) {
  transform: none;
  color: #fff;
  background: #008eb5;
  box-shadow: none;
}

.login-card :deep(.login-submit:focus-visible) {
  outline: 2px solid #3f424a;
  outline-offset: 1px;
}

.login-help-trigger {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 10;
  display: inline-flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  padding: 5px;
  border: 0;
  border-radius: 4px;
  color: #656b76;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s ease-in-out;
}

.login-help-trigger:hover {
  background: #f1f1f3;
}

.login-help-trigger:active {
  background: #e6e6e8;
}

.login-help-trigger:focus-visible,
.login-help-close:focus-visible,
.login-help-confirm:focus-visible {
  outline: 2px solid #3f424a;
  outline-offset: 1px;
}

.login-help-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgb(0 0 0 / 80%);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.login-help-dialog {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 101;
  width: min(580px, calc(100vw - 32px));
  min-height: 300px;
  padding: 60px 30px 30px;
  border: 0;
  border-radius: 12px;
  outline: none;
  background: #fff;
  box-shadow: none;
  transform: translate(-50%, -50%);
}

.login-help-close {
  position: absolute;
  top: 15px;
  right: 15px;
  display: flex;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  padding: 11px;
  border: 0;
  border-radius: 50%;
  color: #1e1d29;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s ease-in-out;
}

.login-help-content {
  display: grid;
  width: 100%;
  min-height: 210px;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 30px;
}

.login-help-title {
  display: block;
  margin: 0;
  color: #1e1d29;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
  text-align: center;
}

.login-help-copy {
  display: flex;
  align-items: center;
  margin: 0;
  color: #3f424a;
  font-size: 16px;
  font-weight: 500;
  line-height: 1.6;
}

.login-help-confirm {
  display: flex;
  width: 100%;
  min-height: 0;
  align-items: center;
  justify-content: center;
  padding: 10px 15px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #fff;
  background: #00b1e2;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  transition: all 0.2s ease-in-out;
}

.login-help-confirm:hover {
  background: #33c1e8;
}

.login-help-confirm:active {
  background: #008eb5;
}

@media (max-width: 1024px) {
  .login-content {
    grid-template-columns: minmax(220px, 1fr) minmax(400px, 500px);
    gap: clamp(28px, 6vw, 61px);
  }

  .login-visual__tile {
    width: min(100%, 310px);
    height: auto;
    aspect-ratio: 31 / 27;
  }
}

@media (max-width: 860px) {
  .login-page {
    align-content: start;
    padding: 100px 22px 36px;
  }

  .login-page__brand {
    top: 20px;
    left: 20px;
  }

  .login-content {
    grid-template-columns: minmax(0, 500px);
    justify-content: center;
    gap: 22px;
    width: min(100%, 500px);
  }

  .login-visual__tile {
    width: min(68vw, 310px);
    height: auto;
    aspect-ratio: 31 / 27;
  }

  .login-visual__tile span {
    font-size: clamp(19px, 5.8vw, 24px);
  }

  .login-card {
    width: 100%;
    padding: 30px 20px 34px;
  }

  .login-help-dialog {
    min-height: 0;
    padding: 60px 20px 24px;
  }

  .login-help-content {
    min-height: 190px;
    gap: 24px;
  }
}

@media (max-width: 400px) {
  .login-page {
    padding-right: 16px;
    padding-left: 16px;
  }

  .login-card {
    padding-right: 20px;
    padding-left: 20px;
  }
}

</style>
