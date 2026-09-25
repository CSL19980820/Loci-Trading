<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, RefreshCw, X } from '@lucide/vue'
import { toast } from 'vue-sonner'

import {
  claimQrSession,
  confirmMockQr,
  markQrScanned,
  pollQrState,
  startQrLogin,
} from '@/shared/api/auth'
import { Button } from '@/shared/components/ui/button'
import { Separator } from '@/shared/components/ui/separator'
import { generateQrMatrix, qrMatrixToSvg } from '@/shared/lib/qrcode'
import type { LoginMode, ProviderOption, QrPollResult, QrStatus, UserProfile } from '@/shared/types/auth'

const props = defineProps<{
  provider: ProviderOption
  redirectTo?: string
}>()

const emit = defineEmits<{
  success: [user: UserProfile]
  cancel: []
}>()

const state = ref<string>('')
const mode = ref<LoginMode>(props.provider.mode)
const qrStatus = ref<QrStatus>('pending')
const qrContent = ref<string>('')
const qrImageUrl = ref<string>('')
const redirectUrl = ref<string>('')
const expiresIn = ref<number>(300)
const errorMessage = ref<string>('')
const starting = ref<boolean>(false)
const claiming = ref<boolean>(false)
const confirmingMock = ref<boolean>(false)

let pollTimer: ReturnType<typeof setInterval> | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null
let isPaused = false

const isMock = computed(() => props.provider.name === 'mock' || props.provider.family === 'mock')

const qrSvg = computed(() => {
  if (!qrContent.value) return ''
  try {
    const matrix = generateQrMatrix(qrContent.value)
    return qrMatrixToSvg(matrix, 6, 2)
  } catch (e) {
    console.error('Failed to generate QR svg', e)
    return ''
  }
})

function clearTimers(): void {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
}

async function initFlow(): Promise<void> {
  clearTimers()
  starting.value = true
  errorMessage.value = ''
  qrStatus.value = 'pending'

  try {
    const res = await startQrLogin({
      provider: props.provider.name,
      redirect_to: props.redirectTo || '/',
    })
    state.value = res.state
    mode.value = res.mode
    expiresIn.value = res.expires_in || 300
    qrContent.value = res.qr_content || ''
    qrImageUrl.value = res.qr_image_url || ''
    redirectUrl.value = res.redirect_url || ''

    if (res.mode === 'redirect' && res.redirect_url) {
      window.location.href = res.redirect_url
      return
    }

    startPolling()
    startCountdown()
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '发起登录失败'
    qrStatus.value = 'failed'
  } finally {
    starting.value = false
  }
}

function startCountdown(): void {
  countdownTimer = setInterval(() => {
    if (expiresIn.value > 0) {
      expiresIn.value--
    } else {
      qrStatus.value = 'expired'
      clearTimers()
    }
  }, 1000)
}

function startPolling(): void {
  if (!state.value) return
  pollTimer = setInterval(async () => {
    if (isPaused || qrStatus.value === 'expired' || qrStatus.value === 'failed') return
    try {
      const res: QrPollResult = await pollQrState(state.value)
      qrStatus.value = res.status

      if (res.status === 'confirmed') {
        clearTimers()
        await claim()
      } else if (res.status === 'expired' || res.status === 'failed') {
        clearTimers()
        if (res.error) errorMessage.value = res.error
      }
    } catch {
      // 网络偶发抖动忽略，继续轮询
    }
  }, 2000)
}

async function claim(): Promise<void> {
  if (claiming.value) return
  claiming.value = true
  try {
    const res = await claimQrSession(state.value)
    qrStatus.value = 'consumed'
    emit('success', res.user)
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : '兑换会话失败'
    qrStatus.value = 'failed'
  } finally {
    claiming.value = false
  }
}

async function onMockScan(): Promise<void> {
  try {
    await markQrScanned(state.value)
    qrStatus.value = 'scanned'
    toast.success('已模拟手机扫码')
  } catch (err: unknown) {
    toast.error(err instanceof Error ? err.message : '模拟扫码失败')
  }
}

async function onMockConfirm(): Promise<void> {
  confirmingMock.value = true
  try {
    await confirmMockQr({ state: state.value, handle: 'demo_user' })
    qrStatus.value = 'confirmed'
    toast.success('已模拟手机确认')
    await claim()
  } catch (err: unknown) {
    toast.error(err instanceof Error ? err.message : '模拟确认失败')
  } finally {
    confirmingMock.value = false
  }
}

function onVisibilityChange(): void {
  isPaused = document.hidden
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  initFlow()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  clearTimers()
})

watch(() => props.provider.name, () => {
  initFlow()
})
</script>

<template>
  <div class="qr-panel" :aria-busy="starting || claiming">
    <div class="qr-box-wrap">
      <div v-if="starting" class="qr-loading" role="status">
        <Spinner class="size-7 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <span class="qr-tip">生成二维码…</span>
      </div>

      <div v-else class="qr-box">
        <div v-if="qrSvg" class="qr-svg-wrap" role="img" aria-label="登录二维码" v-html="qrSvg" />
        <img v-else-if="qrImageUrl" :src="qrImageUrl" alt="二维码" class="qr-img" />
        <div v-else class="qr-fallback">
          <p class="qr-fallback-link">{{ qrContent || state }}</p>
        </div>

        <!-- 状态覆盖遮罩 -->
        <div v-if="qrStatus === 'scanned'" class="qr-mask">
          <span class="qr-mask__icon is-ok"><Check aria-hidden="true" /></span>
          <p class="qr-mask__text" role="status">扫描成功</p>
          <p class="qr-mask__sub">请在手机上点击确认登录</p>
        </div>

        <div v-else-if="qrStatus === 'expired'" class="qr-mask">
          <span class="qr-mask__icon is-warn"><RefreshCw aria-hidden="true" /></span>
          <p class="qr-mask__text" role="status">二维码已过期</p>
          <Button size="sm" @click="initFlow">刷新二维码</Button>
        </div>

        <div v-else-if="qrStatus === 'failed'" class="qr-mask">
          <span class="qr-mask__icon is-warn"><X aria-hidden="true" /></span>
          <p class="qr-mask__text" role="status">{{ errorMessage || '登录失败' }}</p>
          <Button size="sm" @click="initFlow">重试</Button>
        </div>

        <div v-else-if="qrStatus === 'confirmed' || qrStatus === 'consumed'" class="qr-mask">
          <span class="qr-mask__icon is-ok"><Check aria-hidden="true" /></span>
          <p class="qr-mask__text" role="status">登录成功</p>
          <p class="qr-mask__sub">正在跳转…</p>
        </div>
      </div>
    </div>

    <p class="qr-caption">
      <span class="qr-title">{{ provider.label }} 登录</span>
      <span v-if="qrStatus === 'pending' && expiresIn > 0" class="qr-expire-text">
        有效 {{ Math.floor(expiresIn / 60) }}:{{ (expiresIn % 60).toString().padStart(2, '0') }}
      </span>
    </p>

    <div v-if="isMock && qrStatus !== 'consumed'" class="mock-actions">
      <div class="auth-divider">
        <Separator class="min-w-0 flex-1" />
        <span class="auth-divider__text">开发演示通道</span>
        <Separator class="min-w-0 flex-1" />
      </div>
      <div class="mock-btn-group">
        <Button size="sm" variant="outline" :disabled="qrStatus !== 'pending'" @click="onMockScan">1. 模拟扫码</Button>
        <Button
          size="sm"
          variant="outline"
          :disabled="confirmingMock || (qrStatus !== 'scanned' && qrStatus !== 'pending')"
          @click="onMockConfirm"
        >
          <Spinner v-if="confirmingMock" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          2. 模拟手机确认
        </Button>
      </div>
    </div>

    <Button variant="ghost" class="qr-back-btn" @click="emit('cancel')">返回账号密码登录</Button>
  </div>
</template>

<style scoped src="./QrLoginPanel.css" />
