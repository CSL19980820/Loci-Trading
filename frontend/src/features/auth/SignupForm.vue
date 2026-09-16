<script setup lang="ts">
import { computed } from 'vue'
import { Lock, Message } from '@element-plus/icons-vue'

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
</script>

<template>
  <div class="signup-panel">
    <div class="panel-head">
      <h2 class="panel-title">注册账号</h2>
      <span class="panel-switch">
        已有账号？<el-button text type="primary" class="link-btn" @click="emit('switchSignin')">登录</el-button>
      </span>
    </div>

    <el-form label-position="top" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <el-form-item label="邮箱">
        <el-input
          :model-value="email"
          :prefix-icon="Message"
          placeholder="name@example.com"
          type="email"
          autocomplete="email"
          @update:model-value="emit('update:email', String($event))"
        />
      </el-form-item>

      <el-form-item label="密码">
        <el-input
          :model-value="password"
          type="password"
          :prefix-icon="Lock"
          show-password
          placeholder="至少 8 位密码"
          autocomplete="new-password"
          @update:model-value="emit('update:password', String($event))"
        />
        <div v-if="password" class="strength-tip" :style="{ color: passwordStrength.color }">
          密码强度：{{ passwordStrength.text }}
        </div>
      </el-form-item>

      <el-form-item label="确认密码">
        <el-input
          :model-value="confirmPassword"
          type="password"
          :prefix-icon="Lock"
          show-password
          placeholder="再次输入密码"
          autocomplete="new-password"
          @update:model-value="emit('update:confirmPassword', String($event))"
        />
      </el-form-item>

      <el-form-item label="用户名（选填）">
        <el-input
          :model-value="username"
          placeholder="唯一登录账号名"
          @update:model-value="emit('update:username', String($event))"
        />
      </el-form-item>

      <el-form-item label="昵称（选填）">
        <el-input
          :model-value="displayName"
          placeholder="对外展示的名字"
          @update:model-value="emit('update:displayName', String($event))"
        />
      </el-form-item>

      <el-button
        type="primary"
        native-type="submit"
        :loading="submitting"
        class="login-submit"
      >
        {{ submitting ? '提交中' : '注册并验证' }}
      </el-button>
    </el-form>
  </div>
</template>

<style scoped src="./AuthForm.css" />
