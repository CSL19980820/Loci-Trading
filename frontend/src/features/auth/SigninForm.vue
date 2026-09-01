<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'

import type { ProviderOption } from '@/shared/types/auth'

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
</script>

<template>
  <div class="signin-panel">
    <div class="panel-head">
      <h2 class="panel-title">登录</h2>
      <p v-if="emailSignupEnabled" class="panel-switch">
        还没有账号？<el-button link type="primary" @click="emit('switchSignup')">注册</el-button>
      </p>
    </div>

    <el-form label-position="top" @submit.prevent="emit('submit')">
      <el-form-item label="账号或邮箱">
        <el-input
          :model-value="handle"
          :prefix-icon="User"
          class="signin-handle"
          placeholder="用户名 / 邮箱"
          autocomplete="username"
          autofocus
          @update:model-value="emit('update:handle', String($event))"
          @keyup.enter="emit('submit')"
        />
      </el-form-item>

      <el-form-item>
        <!-- 忘记密码贴在 label 行右端：省一整行，且是 GitHub / Google 的通行位置 -->
        <template #label>
          <span class="label-row">
            密码
            <el-button link @click="emit('switchForgot')">忘记密码</el-button>
          </span>
        </template>
        <el-input
          :model-value="password"
          type="password"
          :prefix-icon="Lock"
          show-password
          placeholder="输入密码"
          autocomplete="current-password"
          @update:model-value="emit('update:password', String($event))"
          @keyup.enter="emit('submit')"
        />
      </el-form-item>

      <el-button type="primary" native-type="submit" :loading="submitting" class="login-submit">
        {{ submitting ? '登录中' : '登录' }}
      </el-button>
    </el-form>

    <div v-if="providers.length > 0" class="signin-providers">
      <el-divider content-position="center">或</el-divider>
      <div class="signin-providers__row">
        <el-button
          v-for="p in providers"
          :key="p.name"
          plain
          class="signin-providers__btn"
          @click="emit('pickProvider', p)"
        >
          {{ p.label }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-head {
  margin-bottom: var(--auth-head-gap, 1.25rem);
}

.panel-title {
  margin: 0;
  font-size: var(--auth-title-fs, 1.35rem);
  font-weight: 700;
  letter-spacing: 0.03em;
  color: var(--ink);
}

.panel-switch {
  margin: 0.5rem 0 0;
  font-size: 0.85rem;
  color: var(--mist);
}

.label-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-2);
  width: 100%;
}

/* 账号是代码化字段（用户名 / 邮箱），等宽体不会把 l/1/I 弄混 */
.signin-handle :deep(.el-input__inner) {
  font-family: var(--mono);
}

.login-submit {
  width: 100%;
}

.signin-providers :deep(.el-divider--horizontal) {
  margin: 26px 0 18px;
}

.signin-providers :deep(.el-divider__text) {
  font-size: var(--fs-aux);
  color: var(--mist);
  background: var(--auth-panel-bg, var(--sheet));
}

.signin-providers__row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: var(--gap-3);
}

.signin-providers__btn {
  width: 100%;
  margin-left: 0;
}
</style>
