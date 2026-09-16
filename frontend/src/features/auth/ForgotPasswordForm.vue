<script setup lang="ts">
import { Message } from '@element-plus/icons-vue'

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
    <div class="panel-head">
      <h2 class="panel-title">找回密码</h2>
    </div>

    <el-form label-position="top" :aria-busy="submitting" @submit.prevent="emit('submit')">
      <el-form-item label="注册邮箱">
        <el-input
          :model-value="email"
          :prefix-icon="Message"
          type="email"
          autocomplete="email"
          placeholder="name@example.com"
          autofocus
          @update:model-value="emit('update:email', String($event))"
        />
      </el-form-item>

      <el-button
        type="primary"
        native-type="submit"
        :loading="submitting"
        class="login-submit"
      >
        {{ submitting ? '发送中' : '发送重置验证码' }}
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
