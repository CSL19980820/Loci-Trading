<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, Close, Loading, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  claimQrSession,
  confirmMockQr,
  markQrScanned,
  pollQrState,
  startQrLogin,
} from '@/shared/api/auth'
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
    ElMessage.success('已模拟手机扫码')
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '模拟扫码失败')
  }
}

async function onMockConfirm(): Promise<void> {
  confirmingMock.value = true
  try {
    await confirmMockQr({ state: state.value, handle: 'demo_user' })
    qrStatus.value = 'confirmed'
    ElMessage.success('已模拟手机确认')
    await claim()
  } catch (err: unknown) {
    ElMessage.error(err instanceof Error ? err.message : '模拟确认失败')
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
  <div class="qr-panel">
    <h3 class="qr-title">{{ provider.label }} 登录</h3>

    <div class="qr-box-wrap">
      <div v-if="starting" class="qr-loading">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <span class="qr-tip">生成中...</span>
      </div>

      <div v-else class="qr-box">
        <div v-if="qrSvg" class="qr-svg-wrap" v-html="qrSvg" />
        <img v-else-if="qrImageUrl" :src="qrImageUrl" alt="二维码" class="qr-img" />
        <div v-else class="qr-fallback">
          <p class="qr-fallback-link">{{ qrContent || state }}</p>
        </div>

        <!-- 状态覆盖遮罩 -->
        <div v-if="qrStatus === 'scanned'" class="qr-mask mask-scanned">
          <div class="mask-icon-circle">
            <el-icon :size="24"><Check /></el-icon>
          </div>
          <p class="mask-text">扫描成功</p>
          <p class="mask-sub">请在手机上点击确认登录</p>
        </div>

        <div v-else-if="qrStatus === 'expired'" class="qr-mask mask-expired" @click="initFlow">
          <el-icon :size="28"><RefreshRight /></el-icon>
          <p class="mask-text">二维码已过期</p>
          <p class="mask-sub">点击刷新</p>
        </div>

        <div v-else-if="qrStatus === 'failed'" class="qr-mask mask-failed" @click="initFlow">
          <el-icon :size="28"><Close /></el-icon>
          <p class="mask-text">{{ errorMessage || '登录失败' }}</p>
          <p class="mask-sub">点击重试</p>
        </div>

        <div v-else-if="qrStatus === 'confirmed' || qrStatus === 'consumed'" class="qr-mask mask-success">
          <div class="mask-icon-circle success">
            <el-icon :size="28"><Check /></el-icon>
          </div>
          <p class="mask-text">登录成功</p>
          <p class="mask-sub">正在跳转...</p>
        </div>
      </div>
    </div>

    <div v-if="isMock && qrStatus !== 'consumed'" class="mock-actions">
      <el-divider content-position="center">开发演示通道</el-divider>
      <div class="mock-btn-group">
        <el-button
          size="small"
          :disabled="qrStatus !== 'pending'"
          @click="onMockScan"
        >
          1. 模拟扫码
        </el-button>
        <el-button
          type="primary"
          size="small"
          :loading="confirmingMock"
          :disabled="qrStatus !== 'scanned' && qrStatus !== 'pending'"
          @click="onMockConfirm"
        >
          2. 模拟手机确认
        </el-button>
      </div>
    </div>

    <div class="qr-footer">
      <span v-if="qrStatus === 'pending' && expiresIn > 0" class="qr-expire-text">
        二维码有效时间：{{ Math.floor(expiresIn / 60) }}:{{ (expiresIn % 60).toString().padStart(2, '0') }}
      </span>
      <el-button text class="qr-back-btn" @click="emit('cancel')">
        返回其他登录方式
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.qr-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1.5rem 1rem;
  width: 100%;
}

.qr-title {
  margin: 0 0 1rem;
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--ink);
}

.qr-box-wrap {
  width: 210px;
  height: 210px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius);
  border: 1px solid var(--rule);
  background: var(--sheet);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.qr-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  color: var(--mist);
}

.qr-tip {
  font-size: 0.82rem;
}

.qr-box {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  color: var(--ink);
}

.qr-svg-wrap {
  width: 180px;
  height: 180px;
}

.qr-img {
  width: 180px;
  height: 180px;
  object-fit: contain;
}

.qr-fallback {
  padding: 1rem;
  word-break: break-all;
  text-align: center;
  font-size: 0.8rem;
  color: var(--mist);
}

.qr-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 1rem;
  text-align: center;
  backdrop-filter: blur(4px);
  background: rgba(var(--panel-rgb, 255, 255, 255), 0.92);
  transition: opacity 0.2s ease;
}

.mask-scanned {
  color: var(--ink);
}

.mask-icon-circle {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--seal-soft);
  color: var(--seal-ink);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 0.25rem;
}

.mask-icon-circle.success {
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.mask-expired,
.mask-failed {
  cursor: pointer;
  color: var(--ink);
}

.mask-expired:hover,
.mask-failed:hover {
  background: rgba(var(--panel-rgb, 255, 255, 255), 0.96);
}

.mask-text {
  margin: 0;
  font-weight: 600;
  font-size: 0.95rem;
}

.mask-sub {
  margin: 0;
  font-size: 0.78rem;
  color: var(--mist);
}

.mock-actions {
  width: 100%;
  margin-top: 1rem;
}

.mock-btn-group {
  display: flex;
  gap: 0.5rem;
  justify-content: center;
}

.qr-footer {
  margin-top: 1.25rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}

.qr-expire-text {
  font-size: 0.78rem;
  color: var(--mist);
  font-variant-numeric: tabular-nums;
}

.qr-back-btn {
  font-size: 0.85rem;
  color: var(--mist);
}
</style>
