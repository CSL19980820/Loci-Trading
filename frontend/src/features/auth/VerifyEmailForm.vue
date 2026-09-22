<script setup lang="ts">
import { LoaderCircle } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'

/** 邮箱验证码：目标邮箱由 LoginView 卡头的说明文字交代，这里只剩大号验证码框与重发 */
defineProps<{
  email: string
  code: string
  submitting?: boolean
  resending?: boolean
  resendCountdown: number
}>()

const emit = defineEmits<{
  'update:code': [val: string]
  submit: []
  resend: []
  backSignin: []
}>()
</script>

<template>
  <div class="verify-panel">
    <form class="auth-fields" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <div class="field">
        <Label for="verify-code" class="field-label">6 位验证码</Label>
        <Input
          id="verify-code"
          :model-value="code"
          maxlength="8"
          placeholder="123456"
          class="code-input"
          autocomplete="one-time-code"
          inputmode="numeric"
          autofocus
          @update:model-value="emit('update:code', String($event))"
        />
      </div>

      <div class="resend-row">
        <span class="resend-label">没有收到验证码？</span>
        <Button
          type="button"
          variant="link"
          size="sm"
          class="link-btn"
          :disabled="resendCountdown > 0 || resending"
          @click="emit('resend')"
        >
          <LoaderCircle v-if="resending" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {{ resendCountdown > 0 ? `${resendCountdown}s 后重发` : '重新发送' }}
        </Button>
      </div>

      <Button type="submit" :disabled="submitting" class="login-submit">
        <LoaderCircle v-if="submitting" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {{ submitting ? '验证中' : '完成验证并进入' }}
      </Button>
    </form>

    <p class="form-bottom-link">
      <Button type="button" variant="link" size="sm" class="link-btn" @click="emit('backSignin')">返回登录</Button>
    </p>
  </div>
</template>

<style scoped src="./AuthForm.css" />
