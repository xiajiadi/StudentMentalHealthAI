<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, CircleHelp, X } from '@lucide/vue'
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
import { roleHomes } from '@/components/shell/navigation'
import { useSessionStore } from '@/stores/session'
import { useAssessmentStore } from '@/stores/assessment'
import type { LoginResult } from '@/api/client'
import { frontendApi } from '@/services/mock-api'
import { createPublicDemoAccount, isPublicDemoUsername, loadPublicDemoOptions, loadTurnstile, type PublicDemoOptions } from '@/services/public-demo-registration'
import { useRoute, useRouter } from 'vue-router'

const AppSelect = defineAsyncComponent(() => import('@/components/app/AppSelect.vue'))
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
const authMode = ref<'login' | 'first' | 'recovery' | 'reset' | 'invite' | 'demo'>('login')
const guidedFirstLogin = ref(false)
const authTitles = { login: '登录工作区', demo: '注册体验账号', first: '首次登录', recovery: '申请账号恢复', reset: '重置密码', invite: '接受教职工邀请' }
const authSchoolRef = ref('')
const authUsername = ref('')
const authClassRef = ref('')
const authReasonCode = ref('')
const authCredential = ref('')
const authInvitationRef = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const authNotice = ref('')
const authModeHeading = ref<HTMLElement | null>(null)
const publicDemoOptions = ref<PublicDemoOptions | null>(null)
const demoUsername = ref('')
const demoAgreement = ref(false)
const demoChallenge = ref<HTMLElement | null>(null)
const demoToken = ref('')
const demoChallengeError = ref('')
const optionsRequest = new window.AbortController()
let turnstile: Awaited<ReturnType<typeof loadTurnstile>> | undefined
let widgetId: string | undefined

const removeChallenge = () => {
  if (widgetId !== undefined) turnstile?.remove(widgetId)
  widgetId = undefined
  demoToken.value = ''
}

const mountChallenge = async () => {
  demoChallengeError.value = ''
  try {
    const root = demoChallenge.value
    const options = publicDemoOptions.value
    if (!root || !options) return
    const client = await loadTurnstile()
    if (demoChallenge.value !== root || widgetId !== undefined) return
    turnstile = client
    widgetId = client.render(root, {
      sitekey: options.site_key,
      action: options.action,
      language: 'zh-cn',
      size: root.clientWidth < 300 ? 'compact' : 'flexible',
      callback: (token) => { demoToken.value = token; demoChallengeError.value = '' },
      'expired-callback': () => { demoToken.value = '' },
      'error-callback': () => {
        demoToken.value = ''
        demoChallengeError.value = '人机验证暂时不可用，请重试。'
      },
    })
  } catch {
    if (authMode.value === 'demo') demoChallengeError.value = '人机验证暂时无法加载，请重试。'
  }
}

watch(authMode, async (mode) => {
  if (mode !== 'demo') removeChallenge()
  if (mode !== 'login') { await nextTick(); authModeHeading.value?.focus() }
  if (mode === 'demo' && authMode.value === 'demo') void mountChallenge()
})
const returnToLogin = () => {
  authMode.value = 'login'; authCredential.value = ''; newPassword.value = ''; confirmPassword.value = ''
  guidedFirstLogin.value = false
  demoAgreement.value = false; demoUsername.value = ''
  errorMessage.value = ''; authNotice.value = ''
}

const roleHome = roleHomes

const roleLabels: Record<string, string> = {
  student: '学生', teacher: '教师', psychological_specialist: '心理老师', school_admin: '学校管理员',
}
const contextOptions = computed(() => (pendingContext.value?.availableContexts ?? []).map((context, index) => ({
  value: String(index),
  label: `${context.schoolRef.startsWith('PUBLICDEMO_') ? '合成演示学校' : context.schoolRef}，${roleLabels[context.role]}`,
})))

onMounted(() => {
  if (session.user?.availableContexts?.length && !session.user.activeContext) pendingContext.value = session.user
  const setup = route.query.setup
  if (!pendingContext.value && (setup === 'first' || setup === 'invite' || setup === 'reset')) authMode.value = setup
  if (!pendingContext.value && import.meta.env.MODE !== 'test' && import.meta.env.VITE_API_MODE !== 'mock') {
    void loadPublicDemoOptions(optionsRequest.signal).then((options) => { publicDemoOptions.value = options }).catch(() => {})
  }
})
onUnmounted(() => {
  optionsRequest.abort()
  removeChallenge()
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
    errorMessage.value = error instanceof Error ? error.message : '学校与角色选择未完成，请重试'
  } finally { isLoading.value = false }
}

const submit = async () => {
  if (isLoading.value) return
  errorMessage.value = ''
  authNotice.value = ''
  if (authMode.value === 'demo') {
    if (!isPublicDemoUsername(demoUsername.value)) {
      errorMessage.value = '请输入邮箱，或使用至少 4 位的字母、数字、点、下划线或连字符作为账号。'
      return
    }
    if (newPassword.value.length < 8 || newPassword.value.length > 128 || !newPassword.value.trim()) {
      errorMessage.value = '请输入 8–128 位密码。'
      return
    }
    if (newPassword.value !== confirmPassword.value) {
      errorMessage.value = '两次输入的密码不一致，请重新确认。'
      return
    }
    if (!demoToken.value || !demoAgreement.value) {
      errorMessage.value = '请完成验证，并确认只使用合成数据。'
      return
    }
    isLoading.value = true
    try {
      account.value = await createPublicDemoAccount({
        username: demoUsername.value,
        password: newPassword.value,
        turnstile_token: demoToken.value,
        synthetic_only: demoAgreement.value,
      })
      password.value = ''
      returnToLogin()
      authNotice.value = '账号创建成功。请使用刚设置的密码登录。'
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '注册暂不可用，请稍后再试。'
      demoToken.value = ''
      if (widgetId !== undefined) turnstile?.reset(widgetId)
    } finally { isLoading.value = false }
    return
  }
  if (authMode.value !== 'login') {
    if (authMode.value !== 'invite' && (!authSchoolRef.value.trim() || !authUsername.value.trim())) {
      errorMessage.value = '请填写学校编号和账号'
      return
    }
    if (authMode.value === 'recovery') {
      if (!authClassRef.value.trim() || !authReasonCode.value.trim()) { errorMessage.value = '请填写班级编号和申请原因代码'; return }
    } else if (authMode.value === 'invite' && !authInvitationRef.value.trim()) {
      errorMessage.value = '请填写邀请编号'; return
    } else if (authMode.value !== 'recovery' && (!authCredential.value || !newPassword.value || newPassword.value !== confirmPassword.value)) {
      errorMessage.value = '请填写一次性凭据，并确认两次新密码一致'; return
    }
    isLoading.value = true
    try {
      if (authMode.value === 'first') {
        if (!frontendApi.completeFirstLogin) throw new Error('首次登录服务暂不可用')
        await frontendApi.completeFirstLogin({ school_ref: authSchoolRef.value.trim(), username: authUsername.value.trim(), credential: authCredential.value, new_password: newPassword.value, confirm_password: confirmPassword.value })
        account.value = authUsername.value.trim()
        returnToLogin()
        authNotice.value = '密码已更新，请使用新密码登录'
      } else if (authMode.value === 'recovery') {
        if (!frontendApi.createRecoveryRequest) throw new Error('账号恢复服务暂不可用')
        await frontendApi.createRecoveryRequest({ school_ref: authSchoolRef.value.trim(), username: authUsername.value.trim(), class_ref: authClassRef.value.trim(), reason_code: authReasonCode.value.trim() })
        authNotice.value = '申请已提交，请联系教师核验身份'
      } else if (authMode.value === 'reset') {
        if (!frontendApi.completePasswordReset) throw new Error('密码重置服务暂不可用')
        await frontendApi.completePasswordReset({ school_ref: authSchoolRef.value.trim(), username: authUsername.value.trim(), credential: authCredential.value, new_password: newPassword.value, confirm_password: confirmPassword.value })
        authNotice.value = '密码已重置，请返回登录'
      } else {
        if (!frontendApi.acceptStaffInvitation) throw new Error('邀请接受服务暂不可用')
        await frontendApi.acceptStaffInvitation({ invitation_ref: authInvitationRef.value.trim(), credential: authCredential.value, new_password: newPassword.value, confirm_password: confirmPassword.value })
        returnToLogin()
        authNotice.value = '账号已启用，请使用新密码登录'
      }
      authCredential.value = ''; newPassword.value = ''; confirmPassword.value = ''
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '请求未完成，请稍后重试'
    } finally { isLoading.value = false }
    return
  }
  accountError.value = account.value.trim() ? '' : '请输入账号'
  passwordError.value = password.value ? '' : '请输入密码'
  if (accountError.value || passwordError.value) return

  isLoading.value = true
  try {
    const username = account.value.trim()
    const enteredPassword = password.value
    if (frontendApi.getInitialLoginSchool && /^(?:PN-)?[A-Za-z0-9_-]{43}$/.test(enteredPassword)) {
      const schoolRef = await frontendApi.getInitialLoginSchool({ username, credential: enteredPassword })
      if (schoolRef) {
        authSchoolRef.value = schoolRef
        authUsername.value = username
        authCredential.value = enteredPassword
        guidedFirstLogin.value = true
        password.value = ''
        authMode.value = 'first'
        return
      }
    }
    const response = await frontendApi.login({ account: username, password: enteredPassword })
    password.value = ''
    if (response.data.availableContexts?.length && !response.data.activeContext) {
      pendingContext.value = response.data
      return
    }
    await enterWorkspace(response.data)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录未完成，请稍后重试'
  } finally { isLoading.value = false }
}
</script>

<template>
  <main class="login-page" :class="{ 'login-page--lifecycle': !pendingContext && authMode !== 'login' }">
    <img class="login-page__brand" src="/assets/psynova/wordmark.png" alt="PsyNova">

    <div class="login-content">
      <section class="login-visual" aria-label="PsyNova Workspace">
        <div class="login-visual__tile" aria-hidden="true">
          <img class="login-visual__flow-track" src="/assets/psynova/gentle-rightward-flow-optimized.svg" alt="" aria-hidden="true" decoding="async">
          <span>PsyNova Workspace</span>
        </div>
      </section>

      <section class="login-side" aria-labelledby="login-title">
        <div class="login-card">
          <div class="login-card__brand">
            <img src="/assets/psynova/mark.png" alt="" aria-hidden="true">
          </div>
          <div class="login-card__head">
            <h1 id="login-title" ref="authModeHeading" tabindex="-1">{{ guidedFirstLogin ? '设置个人密码' : authTitles[pendingContext ? 'login' : authMode] }}</h1>
          </div>
          <form v-if="!pendingContext && authMode === 'login'" class="login-form" novalidate @submit.prevent="submit">
            <div class="login-field">
              <input
                id="account"
                v-model="account"
                class="login-input"
                type="text"
                autocomplete="username"
                placeholder="请输入账号"
                aria-label="账号"
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
                placeholder="请输入密码"
                aria-label="密码"
                :aria-invalid="Boolean(passwordError)"
                :aria-describedby="passwordError ? 'password-error' : undefined"
              >
              <p v-if="passwordError" id="password-error" class="login-field__error" role="alert">{{ passwordError }}</p>
            </div>
            <p v-if="errorMessage" class="login-form__error" role="alert" aria-live="assertive">{{ errorMessage }}</p>
            <p v-if="authNotice" class="login-form__success" role="status">{{ authNotice }}</p>
            <AppButton class="login-submit" type="submit" size="md" block :loading="isLoading">登录</AppButton>
          </form>
          <form v-else-if="!pendingContext && authMode === 'demo'" class="login-form" novalidate @input="errorMessage = ''" @submit.prevent="submit">
            <input v-model.trim="demoUsername" class="login-input" required maxlength="128" autocomplete="username" autocapitalize="off" spellcheck="false" aria-label="账号" placeholder="请输入账号或邮箱" :disabled="isLoading">
            <input v-model="newPassword" class="login-input" required type="password" maxlength="128" autocomplete="new-password" aria-label="密码" placeholder="请输入密码（至少 8 位）" :disabled="isLoading">
            <input v-model="confirmPassword" class="login-input" required type="password" maxlength="128" autocomplete="new-password" aria-label="确认密码" placeholder="请再次输入密码" :disabled="isLoading">
            <label class="login-demo-consent"><input v-model="demoAgreement" type="checkbox" :disabled="isLoading"><span>我只使用合成数据，不填写真实学生信息。</span></label>
            <div ref="demoChallenge"></div>
            <p v-if="demoChallengeError" class="login-form__error" role="alert">{{ demoChallengeError }}</p>
            <AppButton v-if="demoChallengeError" variant="quiet" size="sm" @click="removeChallenge(); mountChallenge()">重新加载验证</AppButton>
            <p v-if="errorMessage" class="login-form__error" role="alert">{{ errorMessage }}</p>
            <AppButton class="login-submit" type="submit" size="md" block :loading="isLoading">{{ isLoading ? '正在创建体验账号…' : '创建体验账号' }}</AppButton>
            <AppButton class="login-mode-back" variant="quiet" size="sm" :disabled="isLoading" @click="returnToLogin"><ArrowLeft :size="15" aria-hidden="true" />返回登录</AppButton>
          </form>
          <form v-else-if="!pendingContext" class="login-form" novalidate @input="errorMessage = ''" @submit.prevent="submit">
            <input v-if="authMode !== 'invite' && !guidedFirstLogin" v-model.trim="authSchoolRef" class="login-input" required aria-label="学校编号" placeholder="请输入学校编号">
            <input v-if="authMode !== 'invite' && !guidedFirstLogin" v-model.trim="authUsername" class="login-input" required autocomplete="username" aria-label="账号" placeholder="请输入账号">
            <input v-if="authMode === 'recovery'" v-model.trim="authClassRef" class="login-input" required aria-label="班级编号" placeholder="请输入班级编号">
            <input v-if="authMode === 'recovery'" v-model.trim="authReasonCode" class="login-input" required aria-label="申请原因代码" placeholder="请输入申请原因代码">
            <input v-if="authMode === 'invite'" v-model.trim="authInvitationRef" class="login-input" required aria-label="邀请编号" placeholder="请输入邀请编号">
            <template v-if="authMode !== 'recovery'">
              <input v-if="!guidedFirstLogin" v-model="authCredential" class="login-input" required type="password" autocomplete="one-time-code" :aria-label="authMode === 'first' ? '初始密码' : '一次性凭据'" :placeholder="authMode === 'first' ? '请输入初始密码' : '请输入一次性凭据'">
              <input v-model="newPassword" class="login-input" required type="password" autocomplete="new-password" aria-label="新密码" placeholder="请输入新密码">
              <input v-model="confirmPassword" class="login-input" required type="password" autocomplete="new-password" aria-label="确认新密码" placeholder="请再次输入新密码">
            </template>
            <p v-if="errorMessage" class="login-form__error" role="alert" aria-live="assertive">{{ errorMessage }}</p>
            <p v-if="authNotice" class="login-form__success" role="status" aria-live="polite">{{ authNotice }}</p>
            <AppButton class="login-submit" type="submit" size="md" block :loading="isLoading">提交</AppButton>
            <AppButton class="login-mode-back" variant="quiet" size="sm" :disabled="isLoading" @click="returnToLogin"><ArrowLeft :size="15" aria-hidden="true" />返回登录</AppButton>
          </form>
          <form v-else class="login-form school-context-choice" @submit.prevent="chooseContext">
            <label for="school-context">选择学校与角色</label>
            <AppSelect id="school-context" v-model="selectedContext" :options="contextOptions" placeholder="请选择" variant="login" :disabled="isLoading" />
            <p v-if="errorMessage" class="login-form__error" role="alert">{{ errorMessage }}</p>
            <AppButton class="login-submit" type="submit" size="md" block :loading="isLoading" :disabled="!selectedContext || !frontendApi.switchActiveContext">继续</AppButton>
          </form>
          <nav v-if="!pendingContext && authMode === 'login'" class="login-lifecycle-links" aria-label="账号帮助">
            <AppButton v-if="publicDemoOptions" variant="quiet" size="sm" @click="authMode = 'demo'; errorMessage = ''; authNotice = ''">注册体验账号</AppButton>
            <AppButton variant="quiet" size="sm" @click="authMode = 'first'; errorMessage = ''; authNotice = ''">首次登录</AppButton>
            <AppButton variant="quiet" size="sm" @click="authMode = 'recovery'; errorMessage = ''; authNotice = ''">忘记密码</AppButton>
            <AppButton variant="quiet" size="sm" @click="authMode = 'invite'; errorMessage = ''; authNotice = ''">接受教职工邀请</AppButton>
          </nav>
          <AppButton v-if="!pendingContext && authMode === 'recovery'" variant="quiet" size="sm" :disabled="isLoading" @click="authMode = 'reset'; errorMessage = ''; authNotice = ''">已有管理员批准的恢复凭据？重置密码</AppButton>
        </div>
      </section>
    </div>

    <button v-if="authMode !== 'demo'" class="login-help-trigger" type="button" aria-label="帮助" @click="helpOpen = true">
      <CircleHelp :size="18" aria-hidden="true" />
    </button>

    <DialogRoot :open="helpOpen" @update:open="helpOpen = $event">
      <DialogPortal>
        <DialogOverlay class="login-help-overlay" />
        <DialogContent class="login-help-dialog">
          <DialogClose as-child>
            <button class="login-help-close" type="button" aria-label="关闭">
              <X :size="18" aria-hidden="true" />
            </button>
          </DialogClose>
          <div class="login-help-content">
            <DialogTitle class="login-help-title">登录帮助</DialogTitle>
            <DialogDescription id="login-help-copy" class="login-help-copy">
              账号或密码无法使用时，请联系学校管理员
            </DialogDescription>
            <DialogClose as-child>
              <button class="login-help-confirm" type="button">知道了</button>
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
  font-size: 16px;
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
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-rest);
}

.login-card__brand {
  display: grid;
  width: 50px;
  height: 50px;
  flex: 0 0 50px;
  place-items: center;
  overflow: hidden;
  border-radius: var(--radius-card);
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
  color: var(--color-text-primary);
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
}

.login-form {
  display: grid;
  width: 100%;
  gap: 10px;
}

.login-lifecycle-links { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px; margin-top: 8px; }
.login-mode-back { justify-self: center; }
.login-page--lifecycle { padding-top: 24px; padding-bottom: 24px; }
.login-page--lifecycle .login-card { gap: 14px; padding-top: 24px; padding-bottom: 24px; }
.login-demo-consent { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 13px; line-height: 1.45; cursor: pointer; }
.login-demo-consent input { flex: 0 0 auto; width: 16px; height: 16px; margin: 0; accent-color: var(--color-primary); }
.login-lifecycle-links :deep(button:focus-visible), .login-mode-back:focus-visible { outline: 2px solid var(--color-focus-ring); outline-offset: 2px; }
.login-form__success { margin: 0; padding: 9px 11px; border: .5px solid var(--color-support); color: var(--color-support); background: var(--color-support-wash); font-size: 12px; }

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
  transition: all var(--motion-normal) ease-out;
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
  border: .5px solid transparent;
  border-radius: var(--radius-button);
  color: var(--color-text-inverse);
  background: var(--color-primary);
  box-shadow: none;
  font-family: inherit;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
  transition: all var(--motion-normal) ease-out;
}

.login-card :deep(.login-submit:hover:not(:disabled)) {
  transform: none;
  color: var(--color-text-inverse);
  background: var(--color-primary-hover);
  box-shadow: none;
}

.login-card :deep(.login-submit:active:not(:disabled)) {
  transform: none;
  color: var(--color-text-inverse);
  background: var(--color-primary-active);
  box-shadow: none;
}

.login-card :deep(.login-submit:focus-visible) {
  outline: 2px solid var(--color-focus-ring);
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
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all var(--motion-normal) ease-out;
}

.login-help-trigger:hover {
  background: var(--color-surface-muted);
}

.login-help-trigger:active {
  background: var(--color-border);
}

.login-help-trigger:focus-visible,
.login-help-close:focus-visible,
.login-help-confirm:focus-visible {
  outline: 2px solid var(--color-focus-ring);
  outline-offset: 1px;
}

.login-help-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: color-mix(in srgb, var(--color-text-primary) 82%, transparent);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
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
  border-radius: var(--radius-dialog);
  outline: none;
  background: var(--color-surface);
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
  border-radius: var(--radius-control);
  color: var(--color-text-primary);
  background: transparent;
  cursor: pointer;
  transition: all var(--motion-normal) ease-out;
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
  color: var(--color-text-primary);
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
  text-align: center;
}

.login-help-copy {
  display: flex;
  align-items: center;
  margin: 0;
  color: var(--color-text-secondary);
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
  border: .5px solid transparent;
  border-radius: var(--radius-button);
  color: var(--color-text-inverse);
  background: var(--color-primary);
  cursor: pointer;
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.3;
  transition: all var(--motion-normal) ease-out;
}

.login-help-confirm:hover {
  background: var(--color-primary-hover);
}

.login-help-confirm:active {
  background: var(--color-primary-active);
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

  .login-page--lifecycle { padding: 100px 22px 24px; }

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
    font-size: 16px;
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
