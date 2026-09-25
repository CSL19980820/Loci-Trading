<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { Mail } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'

defineProps<{
  email: string
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:email': [val: string]
  submit: []
  backSignin: []
}>()
</script>

<template>
  <div class="forgot-panel">
    <form class="auth-fields" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <div class="field">
        <Label for="forgot-email" class="field-label">注册邮箱</Label>
        <div class="relative">
          <Mail class="field-icon size-4" aria-hidden="true" />
          <Input
            id="forgot-email"
            :model-value="email"
            class="auth-input pl-10"
            type="email"
            autocomplete="email"
            placeholder="name@example.com"
            autofocus
            @update:model-value="emit('update:email', String($event))"
          />
        </div>
      </div>

      <Button type="submit" :disabled="submitting" class="login-submit">
        <Spinner v-if="submitting" class="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {{ submitting ? '发送中' : '发送重置验证码' }}
      </Button>
    </form>

    <p class="form-bottom-link">
      <Button type="button" variant="link" size="sm" class="link-btn" @click="emit('backSignin')">返回登录</Button>
    </p>
  </div>
</template>

<style scoped src="./AuthForm.css" />
