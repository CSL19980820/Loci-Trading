<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, ref } from 'vue'
import { Eye, EyeOff, Lock, Mail } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'

const props = defineProps<{
  email: string
  password: string
  confirmPassword: string
  username?: string
  displayName?: string
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:email': [val: string]
  'update:password': [val: string]
  'update:confirmPassword': [val: string]
  'update:username': [val: string]
  'update:displayName': [val: string]
  submit: []
  switchSignin: []
}>()

const passwordStrength = computed(() => {
  const p = props.password
  if (!p) return { text: '', color: '' }
  if (p.length < 8) return { text: '太短（至少 8 位）', color: 'var(--warn-ink)' }
  if (p.length < 12) return { text: '适中（建议更长更安全）', color: 'var(--info-ink)' }
  return { text: '很好（长密码更安全）', color: 'var(--seal-ink)' }
})

/** 默认密文，点开关才明文 */
const revealedPassword = ref<boolean>(false)
const revealedConfirm = ref<boolean>(false)
</script>

<template>
  <div class="signup-panel">
    <form class="auth-fields" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <div class="field">
        <Label for="signup-email" class="field-label">邮箱</Label>
        <div class="relative">
          <Mail class="field-icon size-4" aria-hidden="true" />
          <Input
            id="signup-email"
            :model-value="email"
            class="auth-input pl-10"
            placeholder="name@example.com"
            type="email"
            autocomplete="email"
            @update:model-value="emit('update:email', String($event))"
          />
        </div>
      </div>

      <div class="field">
        <Label for="signup-password" class="field-label">密码</Label>
        <div class="relative">
          <Lock class="field-icon size-4" aria-hidden="true" />
          <Input
            id="signup-password"
            :model-value="password"
            :type="revealedPassword ? 'text' : 'password'"
            class="auth-input pl-10 pr-11"
            placeholder="至少 8 位密码"
            autocomplete="new-password"
            @update:model-value="emit('update:password', String($event))"
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
        <div v-if="password" class="strength-tip" :style="{ color: passwordStrength.color }">
          密码强度：{{ passwordStrength.text }}
        </div>
      </div>

      <div class="field">
        <Label for="signup-confirm" class="field-label">确认密码</Label>
        <div class="relative">
          <Lock class="field-icon size-4" aria-hidden="true" />
          <Input
            id="signup-confirm"
            :model-value="confirmPassword"
            :type="revealedConfirm ? 'text' : 'password'"
            class="auth-input pl-10 pr-11"
            placeholder="再次输入密码"
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

      <div class="signup-optional">
        <div class="field">
          <Label for="signup-username" class="field-label">用户名（选填）</Label>
          <Input
            id="signup-username"
            :model-value="username"
            class="auth-input"
            placeholder="唯一登录账号名"
            @update:model-value="emit('update:username', String($event))"
          />
        </div>

        <div class="field">
          <Label for="signup-display-name" class="field-label">昵称（选填）</Label>
          <Input
            id="signup-display-name"
            :model-value="displayName"
            class="auth-input"
            placeholder="对外展示的名字"
            @update:model-value="emit('update:displayName', String($event))"
          />
        </div>
      </div>

      <Button type="submit" :disabled="submitting" class="login-submit">
        <Spinner v-if="submitting" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {{ submitting ? '提交中' : '注册并验证' }}
      </Button>
    </form>

    <p class="form-bottom-link">
      已有账号？
      <Button type="button" variant="link" size="sm" class="link-btn" @click="emit('switchSignin')">登录</Button>
    </p>
  </div>
</template>

<style scoped src="./AuthForm.css" />

<style scoped>
/* 两个选填项并排，少占一行 */
.signup-optional {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-3);
}

@media (max-width: 400px) {
  .signup-optional {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
