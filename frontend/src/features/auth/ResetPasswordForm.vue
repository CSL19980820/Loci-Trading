<script setup lang="ts">
import { computed, ref } from 'vue'
import { Eye, EyeOff, LoaderCircle, Lock } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'

const props = defineProps<{
  email?: string
  token?: string
  code: string
  newPassword: string
  confirmPassword: string
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:code': [val: string]
  'update:newPassword': [val: string]
  'update:confirmPassword': [val: string]
  submit: []
  backSignin: []
}>()

const passwordStrength = computed(() => {
  const p = props.newPassword
  if (!p) return { text: '', color: '' }
  if (p.length < 8) return { text: '太短（至少 8 位）', color: 'var(--warn-ink)' }
  if (p.length < 12) return { text: '适中', color: 'var(--info-ink)' }
  return { text: '很好', color: 'var(--seal-ink)' }
})

/** 默认密文，点开关才明文 */
const revealedPassword = ref<boolean>(false)
const revealedConfirm = ref<boolean>(false)
</script>

<template>
  <div class="reset-panel">
    <form class="auth-fields" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <div v-if="!token" class="field">
        <Label for="reset-code" class="field-label">6 位验证码</Label>
        <Input
          id="reset-code"
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

      <div class="field">
        <Label for="reset-new-password" class="field-label">新密码</Label>
        <div class="relative">
          <Lock class="field-icon size-4" aria-hidden="true" />
          <Input
            id="reset-new-password"
            :model-value="newPassword"
            :type="revealedPassword ? 'text' : 'password'"
            class="auth-input pl-10 pr-11"
            placeholder="至少 8 位新密码"
            autocomplete="new-password"
            @update:model-value="emit('update:newPassword', String($event))"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            class="field-reveal"
            :aria-label="revealedPassword ? '隐藏密码' : '显示密码'"
            :aria-pressed="revealedPassword"
            @click="revealedPassword = !revealedPassword"
          >
            <EyeOff v-if="revealedPassword" class="size-4" aria-hidden="true" />
            <Eye v-else class="size-4" aria-hidden="true" />
          </Button>
        </div>
        <div v-if="newPassword" class="strength-tip" :style="{ color: passwordStrength.color }">
          密码强度：{{ passwordStrength.text }}
        </div>
      </div>

      <div class="field">
        <Label for="reset-confirm" class="field-label">确认新密码</Label>
        <div class="relative">
          <Lock class="field-icon size-4" aria-hidden="true" />
          <Input
            id="reset-confirm"
            :model-value="confirmPassword"
            :type="revealedConfirm ? 'text' : 'password'"
            class="auth-input pl-10 pr-11"
            placeholder="再次输入新密码"
            autocomplete="new-password"
            @update:model-value="emit('update:confirmPassword', String($event))"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            class="field-reveal"
            :aria-label="revealedConfirm ? '隐藏密码' : '显示密码'"
            :aria-pressed="revealedConfirm"
            @click="revealedConfirm = !revealedConfirm"
          >
            <EyeOff v-if="revealedConfirm" class="size-4" aria-hidden="true" />
            <Eye v-else class="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <Button type="submit" :disabled="submitting" class="login-submit">
        <LoaderCircle v-if="submitting" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {{ submitting ? '重置中' : '确认重置密码' }}
      </Button>
    </form>

    <p class="form-bottom-link">
      <Button type="button" variant="link" size="sm" class="link-btn" @click="emit('backSignin')">返回登录</Button>
    </p>
  </div>
</template>

<style scoped src="./AuthForm.css" />
