<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
  <main class="auth-shell">
    <LoginBrandSide />

    <section class="auth-panel">
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

<style scoped>
.auth-shell {
  display: grid;
  grid-template-columns: minmax(0, 800px) minmax(400px, 1fr);
  height: 100dvh;
  overflow: hidden;
  background: var(--surface);
}

/*
 * 门面页尺度：控件 52px / 圆角 10px，比工作台内部的 30px / 6px 大一档。
 * 密度令牌是给一屏几百行报价准备的，登录页一共两个输入框，照搬只会局促。
 * 变量挂在容器上，五个子表单（含存量的四个）不改内部就跟着变。
 */
.auth-panel {
  /*
   * 覆盖的是 --ctl-h / --radius 本身，不是 EP 桥接变量：style.components.css
   * 里 `.el-button--small { height: var(--ctl-h) }` 直接读密度令牌，
   * 只设 --el-component-size-small 的话按钮会停在 30px 而输入框已经 52px。
   */
  --ctl-h: 52px;
  --radius: 10px;
  --auth-ctl-h: var(--ctl-h);
  --auth-title-fs: 32px;
  --auth-head-gap: 28px;
  --auth-panel-bg: var(--surface);

  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 0;
  padding: var(--gap-4) clamp(var(--gap-4), 5vw, 72px);
  background: var(--surface);
  /*
   * 半透明白而不是 --rule：ink 档表单侧 #1c1c1c 与品牌侧 #0b0d12 几乎同色，
   * 需要这条线分开；day / paper 档表单侧接近白，7% 白叠上去自然隐形。
   */
  border-left: 1px solid rgba(255, 255, 255, 0.07);
}

/*
 * 三段式：顶部外观切换 / 中间表单 / 底部口径。四个角都落内容，不留纯空。
 * 三段共用同一条 432px 的居中列——只给表单设 max-width 的话，宽屏上表单
 * 会贴着左边距，右侧空出一大片。
 */
.auth-panel__top,
.auth-panel__mid,
.auth-panel__bot {
  width: 100%;
  max-width: 432px;
}
.auth-panel__top {
  display: flex;
  justify-content: flex-end;
}
.auth-panel__mid {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 0;
  overflow-y: auto;
  /*
   * 视觉重心比几何中心上移约 4%（Google / Stripe / Microsoft 实测都在 3–5%）。
   * 精确垂直居中会把表单读成一座孤岛，略微偏上才像「页面还在往下继续」。
   */
  padding-bottom: 64px;
}
.auth-panel__bot {
  font-size: var(--fs-aux);
  color: var(--text-tertiary);
  letter-spacing: 0.03em;
}

.auth-form {
  width: 100%;
}
.auth-form__alert {
  margin-bottom: var(--gap-3);
}

/*
 * 下面这组 :deep 统一五个子表单的尺度。写成 `.auth-form :deep(x)` 而不是
 * `:deep(x)` 是为了拿到 (0,3,0) 特异性——子表单自己的 `.x[data-v-child]`
 * 是 (0,2,0)，平手时谁赢取决于打包顺序，不能赌。
 */
.auth-form :deep(.panel-title) {
  font-size: var(--auth-title-fs);
  font-weight: 700;
  letter-spacing: 0.03em;
}
.auth-form :deep(.panel-head) {
  margin-bottom: var(--auth-head-gap);
}
.auth-form :deep(.el-form-item) {
  margin-bottom: 22px;
}
/* label-position=top 时 EP 的 label 宽度是 auto，不撑满就没法把「忘记密码」推到行右端 */
.auth-form :deep(.el-form-item__label) {
  width: 100%;
  padding-bottom: 8px;
  font-size: 13px;
  line-height: 1;
  color: var(--text-secondary);
}
.auth-form :deep(.login-submit) {
  width: 100%;
  height: var(--auth-ctl-h);
  margin-top: var(--gap-2);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.16em;
}
.auth-form :deep(.el-input__wrapper) {
  padding: 0 16px;
}

@media (max-width: 1080px) {
  .auth-shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }
  .auth-panel {
    padding: var(--gap-3) var(--gap-4) var(--gap-4);
  }
  .auth-panel__mid {
    padding-bottom: var(--gap-4);
  }
  .auth-panel__bot {
    text-align: center;
  }
}

@media (max-width: 640px) {
  .auth-panel {
    --ctl-h: 46px;
    --auth-title-fs: 26px;
  }
}
</style>
