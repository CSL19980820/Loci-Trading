<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

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
import { useThemeStore } from '@/shared/stores/theme'
import { useUserStore } from '@/shared/stores/user'
import type { ProviderOption, UserProfile } from '@/shared/types/auth'
import ForgotPasswordForm from '@/features/auth/ForgotPasswordForm.vue'
import LoginBrandSide from '@/features/auth/LoginBrandSide.vue'
import QrLoginPanel from '@/features/auth/QrLoginPanel.vue'
import ResetPasswordForm from '@/features/auth/ResetPasswordForm.vue'
import SigninForm from '@/features/auth/SigninForm.vue'
import SignupForm from '@/features/auth/SignupForm.vue'
import VerifyEmailForm from '@/features/auth/VerifyEmailForm.vue'

type AuthMode = 'signin' | 'signup' | 'verify' | 'forgot' | 'reset'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

/** 登录页就能选外观：右上角那一格不放假链接，放真功能 */
const appearanceOptions = computed(() =>
  themeStore.appearances.map((a) => ({ label: a.label, value: a.id })),
)

const mode = ref<AuthMode>('signin')
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
  ElMessage.success(`欢迎回来，${user.display_name || user.username}`)
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
    ElMessage.success('验证码已发送至您的邮箱')
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
    ElMessage.success('验证码已重新发送')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '重发失败')
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
    ElMessage.success('重置邮件/验证码已发出')
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
    ElMessage.success('密码已成功重置，请使用新密码登录')
    mode.value = 'signin'
    signinHandle.value = resetEmailAddr.value
    signinPassword.value = ''
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '重置密码失败'
  } finally {
    submitting.value = false
  }
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
    activeQrProvider.value = mockOpt
  }
}

onMounted(async () => {
  await fetchOptions()
  await handleUrlQueries()
})
</script>

<template>
  <!--
    非壳内页例外（AGENTS §3.7.1）：这里自管 100dvh。
    骨架是「深色品牌侧 + 满高表单侧」的双栏对撞，不是浮在留白里的卡片——
    旧版 700px 卡片只占视口 18%，且底色与卡片只差 2% 亮度，看着像没加载完。
  -->
  <main id="auth-main" class="auth-shell">
    <LoginBrandSide />

    <section class="auth-panel" aria-label="账号登录" :aria-busy="submitting">
      <nav class="auth-panel__top" aria-label="外观">
        <el-segmented
          :model-value="themeStore.appearanceId"
          :options="appearanceOptions"
          @change="themeStore.setAppearance(String($event))"
        />
      </nav>

      <div class="auth-panel__mid">
        <QrLoginPanel
          v-if="activeQrProvider"
          :provider="activeQrProvider"
          :redirect-to="targetRedirect()"
          @success="onAuthSuccess"
          @cancel="activeQrProvider = null"
        />

        <div v-else class="auth-form">
          <!-- 只报当前真实异常，一行 title，无 description -->
          <el-alert
            v-if="errorMessage"
            :title="errorMessage"
            type="error"
            show-icon
            :closable="false"
            class="auth-form__alert"
          />

          <SigninForm
            v-if="mode === 'signin'"
            v-model:handle="signinHandle"
            v-model:password="signinPassword"
            :submitting="submitting"
            :email-signup-enabled="emailSignupEnabled"
            :providers="providers"
            @submit="handleSignin"
            @switch-signup="mode = 'signup'"
            @switch-forgot="mode = 'forgot'"
            @pick-provider="activeQrProvider = $event"
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
            @switchSignin="mode = 'signin'"
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
            @backSignin="mode = 'signin'"
          />

          <ForgotPasswordForm
            v-else-if="mode === 'forgot'"
            v-model:email="forgotEmail"
            :submitting="submitting"
            @submit="handleForgot"
            @backSignin="mode = 'signin'"
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
            @backSignin="mode = 'signin'"
          />
        </div>
      </div>

      <footer class="auth-panel__bot">仅供研究与复盘，不构成投资建议</footer>
    </section>
  </main>
</template>

<style scoped src="../auth/LoginLayout.css" />
