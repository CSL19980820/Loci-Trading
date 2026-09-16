<script setup lang="ts">
import { computed } from 'vue'
import { Lock } from '@element-plus/icons-vue'

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
</script>

<template>
  <div class="reset-panel">
    <div class="panel-head">
      <h2 class="panel-title">重置密码</h2>
    </div>

    <el-form label-position="top" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <el-form-item v-if="!token" label="6 位验证码">
        <el-input
          :model-value="code"
          maxlength="8"
          placeholder="输入验证码"
          autocomplete="one-time-code"
          inputmode="numeric"
          autofocus
          @update:model-value="emit('update:code', String($event))"
        />
      </el-form-item>

      <el-form-item label="新密码">
        <el-input
          :model-value="newPassword"
          type="password"
          :prefix-icon="Lock"
          show-password
          placeholder="至少 8 位新密码"
          autocomplete="new-password"
          @update:model-value="emit('update:newPassword', String($event))"
        />
        <div v-if="newPassword" class="strength-tip" :style="{ color: passwordStrength.color }">
          密码强度：{{ passwordStrength.text }}
        </div>
      </el-form-item>

      <el-form-item label="确认新密码">
        <el-input
          :model-value="confirmPassword"
          type="password"
          :prefix-icon="Lock"
          show-password
          placeholder="再次输入新密码"
          autocomplete="new-password"
          @update:model-value="emit('update:confirmPassword', String($event))"
        />
      </el-form-item>

      <el-button
        type="primary"
        native-type="submit"
        :loading="submitting"
        class="login-submit"
      >
        {{ submitting ? '重置中' : '确认重置密码' }}
      </el-button>

      <div class="form-bottom-link">
        <el-button text class="sub-link" @click="emit('backSignin')">
          返回登录
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<style scoped src="./AuthForm.css" />
