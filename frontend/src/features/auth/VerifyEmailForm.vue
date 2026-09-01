<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
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
    <div class="panel-head">
      <h2 class="panel-title">输入邮箱验证码</h2>
      <span class="panel-target">{{ email }}</span>
    </div>

    <el-form label-position="top" @submit.prevent="emit('submit')">
      <el-form-item label="6 位验证码">
        <el-input
          :model-value="code"
          maxlength="8"
          placeholder="123456"
          class="code-input"
          autofocus
          @update:model-value="emit('update:code', String($event))"
        />
      </el-form-item>

      <div class="resend-row">
        <span class="resend-label">没有收到验证码？</span>
        <el-button
          text
          type="primary"
          size="small"
          :disabled="resendCountdown > 0"
          :loading="resending"
          @click="emit('resend')"
        >
          {{ resendCountdown > 0 ? `${resendCountdown}s 后重发` : '重新发送' }}
        </el-button>
      </div>

      <el-button
        type="primary"
        native-type="submit"
        :loading="submitting"
        class="login-submit"
      >
        {{ submitting ? '验证中' : '完成验证并进入' }}
      </el-button>

      <div class="form-bottom-link">
        <el-button text class="sub-link" @click="emit('backSignin')">
          返回登录
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<style scoped>
.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 1.25rem;
}

.panel-title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 600;
  color: var(--ink);
}

.panel-target {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.85rem;
  color: var(--mist);
}

.code-input :deep(input) {
  letter-spacing: 0.3em;
  font-size: 1.2rem;
  text-align: center;
  font-weight: 600;
}

.resend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}

.resend-label {
  font-size: 0.82rem;
  color: var(--mist);
}

.login-submit {
  width: 100%;
  height: 2.5rem;
  font-size: 0.95rem;
  font-weight: 500;
}

.form-bottom-link {
  text-align: center;
  margin-top: 1rem;
}

.sub-link {
  font-size: 0.82rem;
  color: var(--mist);
}
</style>
