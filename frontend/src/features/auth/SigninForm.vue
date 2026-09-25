<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { ref } from 'vue'
import { Eye, EyeOff, Lock, User } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import { Separator } from '@/shared/components/ui/separator'
import type { ProviderOption } from '@/shared/types/auth'

/** 账号密码登录：标题由 LoginView 的卡头统一给，这里只剩字段、主按钮与去注册的链接 */
defineProps<{
  handle: string
  password: string
  submitting?: boolean
  emailSignupEnabled?: boolean
  providers: ProviderOption[]
}>()

const emit = defineEmits<{
  'update:handle': [val: string]
  'update:password': [val: string]
  submit: []
  switchSignup: []
  switchForgot: []
  pickProvider: [provider: ProviderOption]
}>()

/** 默认密文，点开关才明文 */
const revealed = ref<boolean>(false)
</script>

<template>
  <div class="signin-panel">
    <form class="auth-fields" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <div class="field">
        <Label for="signin-handle" class="field-label">账号或邮箱</Label>
        <div class="relative">
          <User class="field-icon size-4" aria-hidden="true" />
          <Input
            id="signin-handle"
            :model-value="handle"
            class="auth-input signin-handle pl-10"
            placeholder="用户名 / 邮箱"
            autocomplete="username"
            autofocus
            @update:model-value="emit('update:handle', String($event))"
            @keyup.enter="emit('submit')"
          />
        </div>
      </div>

      <div class="field">
        <!-- 忘记密码贴在 label 行右端：省一整行，且是 GitHub / Google 的通行位置 -->
        <div class="label-row">
          <Label for="signin-password" class="field-label">密码</Label>
          <Button type="button" variant="link" size="sm" class="sub-link" @click="emit('switchForgot')">
            忘记密码
          </Button>
        </div>
        <div class="relative">
          <Lock class="field-icon size-4" aria-hidden="true" />
          <Input
            id="signin-password"
            :model-value="password"
            :type="revealed ? 'text' : 'password'"
            class="auth-input pl-10 pr-11"
            placeholder="输入密码"
            autocomplete="current-password"
            @update:model-value="emit('update:password', String($event))"
            @keyup.enter="emit('submit')"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            class="field-reveal"
            :aria-label="revealed ? '隐藏密码' : '显示密码'"
            :aria-pressed="revealed"
            @click="revealed = !revealed"
          >
            <EyeOff v-if="revealed" class="size-4" aria-hidden="true" />
            <Eye v-else class="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>

      <Button type="submit" :disabled="submitting" class="login-submit">
        <Spinner v-if="submitting" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {{ submitting ? '登录中' : '登录' }}
      </Button>
    </form>

    <div v-if="providers.length > 0" class="signin-providers">
      <div class="auth-divider">
        <Separator class="min-w-0 flex-1" />
        <span class="auth-divider__text">或使用</span>
        <Separator class="min-w-0 flex-1" />
      </div>
      <div class="signin-providers__row">
        <Button
          v-for="p in providers"
          :key="p.name"
          type="button"
          variant="outline"
          class="signin-providers__btn"
          @click="emit('pickProvider', p)"
        >
          {{ p.label }}
        </Button>
      </div>
    </div>

    <p v-if="emailSignupEnabled" class="form-bottom-link">
      还没有账号？
      <Button type="button" variant="link" size="sm" class="link-btn" @click="emit('switchSignup')">注册</Button>
    </p>
  </div>
</template>

<style scoped src="./AuthForm.css" />
