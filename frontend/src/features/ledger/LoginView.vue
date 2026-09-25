<script setup lang="ts">
import { toast } from 'vue-sonner'
import { default as SegmentedControl } from '@/shared/components/ui/app/SegmentedControl.vue'
import { Notice } from '@/shared/components/ui/app/presentation'

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  claimQrSession,
  getAuthOptions,
  loginWithPassword,
  registerWithEmail,
  requestForgotPassword,
  resendVerificationCode,
  resetPassword,
  verifyEmail,
} from '@/shared/api/auth'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import { Button } from '@/shared/components/ui/button'
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'
import { APP_VERSION } from '@/shared/lib/release'
import { useThemeStore } from '@/shared/stores/theme'
import { useUserStore } from '@/shared/stores/user'
import type { ProviderOption, UserProfile } from '@/shared/types/auth'
import ForgotPasswordForm from '@/features/auth/ForgotPasswordForm.vue'
import QrLoginPanel from '@/features/auth/QrLoginPanel.vue'
import ResetPasswordForm from '@/features/auth/ResetPasswordForm.vue'
import SigninForm from '@/features/auth/SigninForm.vue'
import SignupForm from '@/features/auth/SignupForm.vue'
import VerifyEmailForm from '@/features/auth/VerifyEmailForm.vue'

/**
 * 登录页（非壳内页，自管 100dvh）。
 *
 * 版面（Linear / Vercel 登录页一路）：点阵 + 径向渐变的画布，中央一张 420px 卡：
 *   品牌标 · 标题 · 一句说明
 *   药片分段：账号密码 | 扫码登录（有第三方通道才出现）
 *   表单 / 二维码
 * 顶栏左品牌、右外观切换；手机端卡片铺满、去掉边框。
 */
type AuthMode = 'signin' | 'signup' | 'verify' | 'forgot' | 'reset'
type LoginTab = 'password' | 'qr'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

/** 登录页就能选外观：右上角那一格不放假链接，放真功能 */
const appearanceOptions = computed(() =>
  themeStore.appearances.map((a) => ({ label: a.label, value: a.id })),
)

const mode = ref<AuthMode>('signin')
const loginTab = ref<LoginTab>('password')
const activeQrProvider = ref<ProviderOption | null>(null)
const emailSignupEnabled = ref<boolean>(true)
const providers = ref<ProviderOption[]>([])

const signinHandle = ref<string>('')
const signinPassword = ref<string>('')

const signupEmail = ref<string>('')
const signupPassword = ref<string>('')
const signupConfirmPassword = ref<string>('')
const signupUsername = ref<string>('')
const signupDisplayName = ref<string>('')

const verifyEmailAddr = ref<string>('')
const verifyCode = ref<string>('')
const verifyToken = ref<string>('')

const forgotEmail = ref<string>('')

const resetEmailAddr = ref<string>('')
const resetCode = ref<string>('')
const resetToken = ref<string>('')
const resetNewPassword = ref<string>('')
const resetConfirmPassword = ref<string>('')

const submitting = ref<boolean>(false)
const resending = ref<boolean>(false)
const resendCountdown = ref<number>(0)
const errorMessage = ref<string>('')

let resendTimer: ReturnType<typeof setInterval> | null = null

/** 有第三方通道才给「扫码登录」这一页 */
const hasProviders = computed(() => providers.value.length > 0)
const providerTabLabel = computed(() =>
  providers.value.every((p) => p.mode === 'qrcode') ? '扫码登录' : '第三方登录',
)
const loginTabs = computed<PageTabItem[]>(() => [
  { name: 'password', label: '账号密码' },
  { name: 'qr', label: providerTabLabel.value },
])
const loginTabModel = computed({
  get: () => loginTab.value,
  set: (next: string) => {
    if (next === 'qr') {
      activeQrProvider.value ??= providers.value[0] ?? null
      loginTab.value = 'qr'
    } else {
      loginTab.value = 'password'
    }
  },
})

const showQr = computed(() => mode.value === 'signin' && loginTab.value === 'qr' && activeQrProvider.value)

const heading = computed(() => {
  if (mode.value === 'signup') return '注册账号'
  if (mode.value === 'verify') return '输入邮箱验证码'
  if (mode.value === 'forgot') return '找回密码'
  if (mode.value === 'reset') return '重置密码'
  return `登录 ${BRAND_NAME}`
})

const subheading = computed(() => {
  if (mode.value === 'signup') return '邮箱注册，验证后即可进入工作台'
  if (mode.value === 'verify') return verifyEmailAddr.value ? `验证码已发送到 ${verifyEmailAddr.value}` : '输入邮件里的 6 位验证码'
  if (mode.value === 'forgot') return '输入注册邮箱，我们会发送重置验证码'
  if (mode.value === 'reset') return resetEmailAddr.value ? `为 ${resetEmailAddr.value} 设置新密码` : '输入验证码并设置新密码'
  if (showQr.value) return '用手机扫码，在手机上确认后自动进入'
  return '量化工作台 · 行情、账本、策略与复盘'
})

async function fetchOptions(): Promise<void> {
  try {
    const res = await getAuthOptions()
    emailSignupEnabled.value = res.email_signup
    providers.value = res.providers || []
  } catch {
    emailSignupEnabled.value = true
    providers.value = []
  }
}

function startResendCountdown(): void {
  if (resendTimer) clearInterval(resendTimer)
  resendCountdown.value = 60
  resendTimer = setInterval(() => {
    if (resendCountdown.value > 0) {
      resendCountdown.value--
    } else {
      if (resendTimer) clearInterval(resendTimer)
      resendTimer = null
    }
  }, 1000)
}

// 倒计时唯一的自然清理路径是「归零」，但登录成功会立刻 router.replace 卸载本页，
// 定时器会继续对已卸载组件的 ref 写最多 60 次，并吊住整个 setup 作用域。
onBeforeUnmount(() => {
  if (resendTimer) clearInterval(resendTimer)
  resendTimer = null
})

function targetRedirect(): string {
  const raw = route.query.redirect
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//')) {
    return raw
  }
  return '/'
}

async function onAuthSuccess(user: UserProfile): Promise<void> {
  userStore.setUser(user)
  toast.success(`欢迎回来，${user.display_name || user.username}`)
  await router.replace(targetRedirect())
}

async function handleSignin(): Promise<void> {
  if (!signinHandle.value || !signinPassword.value) {
    errorMessage.value = '请输入账号和密码'
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const res = await loginWithPassword(signinHandle.value, signinPassword.value)
    await onAuthSuccess(res.user)
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '登录失败'
  } finally {
    submitting.value = false
  }
}

async function handleSignup(): Promise<void> {
  if (!signupEmail.value || !signupPassword.value) {
    errorMessage.value = '请填写邮箱和密码'
    return
  }
  if (signupPassword.value.length < 8) {
    errorMessage.value = '密码长度至少为 8 位'
    return
  }
  if (signupPassword.value !== signupConfirmPassword.value) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }

  submitting.value = true
  errorMessage.value = ''
  try {
    await registerWithEmail({
      email: signupEmail.value,
      password: signupPassword.value,
      username: signupUsername.value || undefined,
      display_name: signupDisplayName.value || undefined,
    })
    verifyEmailAddr.value = signupEmail.value
    mode.value = 'verify'
    startResendCountdown()
    toast.success('验证码已发送至您的邮箱')
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '注册失败'
  } finally {
    submitting.value = false
  }
}

async function handleVerify(): Promise<void> {
  if (!verifyCode.value && !verifyToken.value) {
    errorMessage.value = '请输入 6 位验证码'
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const res = await verifyEmail({
      email: verifyEmailAddr.value || undefined,
      code: verifyCode.value || undefined,
      token: verifyToken.value || undefined,
    })
    await onAuthSuccess(res.user)
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '验证失败'
  } finally {
    submitting.value = false
  }
}

async function handleResendCode(): Promise<void> {
  if (!verifyEmailAddr.value || resendCountdown.value > 0) return
  resending.value = true
  try {
    await resendVerificationCode(verifyEmailAddr.value)
    startResendCountdown()
    toast.success('验证码已重新发送')
  } catch (err: unknown) {
    toast.error(err instanceof Error ? err.message : '重发失败')
  } finally {
    resending.value = false
  }
}

async function handleForgot(): Promise<void> {
  if (!forgotEmail.value) {
    errorMessage.value = '请输入注册邮箱'
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    await requestForgotPassword(forgotEmail.value)
    resetEmailAddr.value = forgotEmail.value
    mode.value = 'reset'
    startResendCountdown()
    toast.success('重置邮件/验证码已发出')
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '发起找回密码失败'
  } finally {
    submitting.value = false
  }
}

async function handleReset(): Promise<void> {
  if (!resetCode.value && !resetToken.value) {
    errorMessage.value = '请输入重置验证码'
    return
  }
  if (!resetNewPassword.value || resetNewPassword.value.length < 8) {
    errorMessage.value = '新密码长度至少为 8 位'
    return
  }
  if (resetNewPassword.value !== resetConfirmPassword.value) {
    errorMessage.value = '两次输入的新密码不一致'
    return
  }

  submitting.value = true
  errorMessage.value = ''
  try {
    await resetPassword({
      email: resetEmailAddr.value || undefined,
      code: resetCode.value || undefined,
      token: resetToken.value || undefined,
      new_password: resetNewPassword.value,
    })
    toast.success('密码已成功重置，请使用新密码登录')
    mode.value = 'signin'
    signinHandle.value = resetEmailAddr.value
    signinPassword.value = ''
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '重置密码失败'
  } finally {
    submitting.value = false
  }
}

function pickProvider(provider: ProviderOption): void {
  activeQrProvider.value = provider
  loginTab.value = 'qr'
}

function cancelQr(): void {
  activeQrProvider.value = null
  loginTab.value = 'password'
}

function switchMode(next: AuthMode): void {
  errorMessage.value = ''
  mode.value = next
}

async function handleUrlQueries(): Promise<void> {
  const q = route.query
  if (typeof q.claim_state === 'string' && q.claim_state) {
    submitting.value = true
    try {
      const res = await claimQrSession(q.claim_state)
      await onAuthSuccess(res.user)
      return
    } catch (err: unknown) {
      errorMessage.value = err instanceof Error ? err.message : '兑换会话失败'
    } finally {
      submitting.value = false
    }
  }

  if (typeof q.verify_token === 'string' && q.verify_token) {
    verifyToken.value = q.verify_token
    mode.value = 'verify'
    await handleVerify()
    return
  }

  if (typeof q.reset_token === 'string' && q.reset_token) {
    resetToken.value = q.reset_token
    mode.value = 'reset'
    return
  }

  if (typeof q.auth_error === 'string' && q.auth_error) {
    errorMessage.value = `第三方登录失败：${q.auth_error}`
  }

  if (typeof q.mock_state === 'string' && q.mock_state) {
    const mockOpt = providers.value.find((p) => p.name === 'mock') || {
      name: 'mock',
      family: 'mock',
      label: '演示扫码',
      mode: 'qrcode',
    }
    pickProvider(mockOpt)
  }
}

/* 切换表单时清掉上一张表单的报错，别让「密码不一致」挂在找回密码页上 */
watch(mode, () => {
  errorMessage.value = ''
})

onMounted(async () => {
  await fetchOptions()
  await handleUrlQueries()
})
</script>

<template>
  <!-- 非壳内页例外（AGENTS §3.7.1）：这里自管 100dvh。 -->
  <main id="auth-main" class="auth-shell">
    <div class="auth-canvas" aria-hidden="true" />

    <header class="auth-top">
      <div class="auth-brand">
        <span class="auth-brand__mark">{{ BRAND_MARK }}</span>
        <span class="auth-brand__name">{{ BRAND_NAME }}</span>
        <span class="auth-brand__tag">量化工作台</span>
      </div>
      <nav class="auth-top__appearance" aria-label="外观">
        <SegmentedControl
          :model-value="themeStore.appearanceId"
          :options="appearanceOptions"
          @change="themeStore.setAppearance(String($event))"
        />
      </nav>
    </header>

    <section class="auth-panel" aria-label="账号登录" :aria-busy="submitting">
      <div class="auth-card">
        <div class="auth-card__head">
          <span class="auth-card__mark" aria-hidden="true">{{ BRAND_MARK }}</span>
          <h1 class="auth-card__title">{{ heading }}</h1>
          <p class="auth-card__desc">{{ subheading }}</p>
        </div>

        <PageTabs
          v-if="mode === 'signin' && hasProviders"
          v-model="loginTabModel"
          panel-id="login-method-panel"
          :items="loginTabs"
          variant="pill"
          :sticky="false"
          aria-label="登录方式"
          class="auth-tabs"
        />

        <!-- 只报当前真实异常，一行 title，无 description -->
        <Notice
          v-if="errorMessage"
          :title="errorMessage"
          tone="error"
          show-icon
          :closable="false"
          class="auth-form__alert"
        />

        <div id="login-method-panel" :role="mode === 'signin' && hasProviders ? 'tabpanel' : undefined" :tabindex="mode === 'signin' && hasProviders ? 0 : undefined" :aria-labelledby="mode === 'signin' && hasProviders ? `login-method-panel-tab-${loginTabModel}` : undefined">
        <template v-if="showQr && activeQrProvider">
          <div v-if="providers.length > 1" class="auth-providers" role="group" aria-label="选择登录通道">
            <Button
              v-for="p in providers"
              :key="p.name"
              type="button"
              size="sm"
              :variant="p.name === activeQrProvider.name ? 'secondary' : 'ghost'"
              :aria-pressed="p.name === activeQrProvider.name"
              @click="activeQrProvider = p"
            >
              {{ p.label }}
            </Button>
          </div>
          <QrLoginPanel
            :provider="activeQrProvider"
            :redirect-to="targetRedirect()"
            @success="onAuthSuccess"
            @cancel="cancelQr"
          />
        </template>

        <div v-else class="auth-form">
          <SigninForm
            v-if="mode === 'signin'"
            v-model:handle="signinHandle"
            v-model:password="signinPassword"
            :submitting="submitting"
            :email-signup-enabled="emailSignupEnabled"
            :providers="providers"
            @submit="handleSignin"
            @switch-signup="switchMode('signup')"
            @switch-forgot="switchMode('forgot')"
            @pick-provider="pickProvider"
          />

          <SignupForm
            v-else-if="mode === 'signup'"
            v-model:email="signupEmail"
            v-model:password="signupPassword"
            v-model:confirmPassword="signupConfirmPassword"
            v-model:username="signupUsername"
            v-model:displayName="signupDisplayName"
            :submitting="submitting"
            @submit="handleSignup"
            @switchSignin="switchMode('signin')"
          />

          <VerifyEmailForm
            v-else-if="mode === 'verify'"
            v-model:code="verifyCode"
            :email="verifyEmailAddr"
            :submitting="submitting"
            :resending="resending"
            :resend-countdown="resendCountdown"
            @submit="handleVerify"
            @resend="handleResendCode"
            @backSignin="switchMode('signin')"
          />

          <ForgotPasswordForm
            v-else-if="mode === 'forgot'"
            v-model:email="forgotEmail"
            :submitting="submitting"
            @submit="handleForgot"
            @backSignin="switchMode('signin')"
          />

          <ResetPasswordForm
            v-else-if="mode === 'reset'"
            v-model:code="resetCode"
            v-model:newPassword="resetNewPassword"
            v-model:confirmPassword="resetConfirmPassword"
            :token="resetToken"
            :email="resetEmailAddr"
            :submitting="submitting"
            @submit="handleReset"
            @backSignin="switchMode('signin')"
          />
        </div>
        </div>
      </div>

      <footer class="auth-foot">
        <span>仅供研究与复盘，不构成投资建议</span>
        <span class="auth-foot__ver">v{{ APP_VERSION }}</span>
      </footer>
    </section>
  </main>
</template>

<style scoped src="../auth/LoginLayout.css" />
