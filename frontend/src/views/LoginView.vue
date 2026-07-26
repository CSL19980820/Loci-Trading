<template>
  <main class="login-shell">
    <form class="login-card" @submit.prevent="submit">
      <h1>潜龙</h1>
      <label>
        账号
        <input v-model.trim="username" autocomplete="username" required autofocus />
      </label>
      <label>
        密码
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button class="primary-button" type="submit" :disabled="submitting">
        {{ submitting ? '…' : '进入' }}
      </button>
    </form>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { login } from '@/api/palace'

const router = useRouter()
const username = ref('admin')
const password = ref('')
const submitting = ref(false)
const error = ref('')

async function submit(): Promise<void> {
  submitting.value = true
  error.value = ''
  try {
    await login(username.value, password.value)
    await router.replace('/')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '登录失败'
  } finally {
    submitting.value = false
  }
}
</script>