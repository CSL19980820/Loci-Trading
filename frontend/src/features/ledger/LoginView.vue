<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { login } from '@/shared/api/palace'
import { BRAND_NAME, BRAND_TAGLINE } from '@/shared/lib/brand'

const router = useRouter()
const brandName = BRAND_NAME
const brandTagline = BRAND_TAGLINE
const username = ref('')
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

<template>
  <main class="login-shell">
    <div class="login-layout">
      <section class="login-hero" aria-hidden="false">
        <p class="login-eyebrow">私人交易账本</p>
        <h1 class="login-display">{{ brandName }}</h1>
        <p class="login-tag">{{ brandTagline }}</p>
        <p class="login-copy">把选股、成交、复盘记在同一本账上。</p>
      </section>

      <section class="login-panel">
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="账号">
            <el-input v-model="username" autocomplete="username" autofocus />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="password"
              type="password"
              show-password
              autocomplete="current-password"
            />
          </el-form-item>
          <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="login-error" />
          <el-button type="primary" native-type="submit" :loading="submitting" class="login-submit">
            {{ submitting ? '进入中' : '进入' }}
          </el-button>
        </el-form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.login-shell {
  height: 100%;
  height: 100dvh;
  overflow: auto;
  overscroll-behavior: contain;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background:
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 11px,
      rgba(20, 32, 51, 0.015) 11px,
      rgba(20, 32, 51, 0.015) 12px
    ),
    linear-gradient(165deg, #e8eef4 0%, #eef2f6 45%, #e4ebf2 100%);
}

.login-layout {
  width: min(100%, 52rem);
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 2rem;
  align-items: center;
}

.login-hero {
  padding: 0.5rem 0.75rem;
}

.login-eyebrow {
  margin: 0 0 0.5rem;
  color: var(--mist);
  font-size: 0.75rem;
  letter-spacing: 0.14em;
}

.login-display {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(2.4rem, 5vw, 3.4rem);
  font-weight: 700;
  letter-spacing: 0.02em;
  line-height: 1.1;
  color: var(--ink);
}

.login-tag {
  margin: 0.65rem 0 0;
  color: var(--seal-ink);
  font-size: 0.95rem;
  font-weight: 600;
}

.login-copy {
  margin: 0.85rem 0 0;
  color: var(--mist);
  font-size: 0.92rem;
  max-width: 18rem;
  line-height: 1.55;
}

.login-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  padding: 1.25rem 1.35rem;
}

.login-error {
  margin-bottom: 0.75rem;
}

.login-submit {
  width: 100%;
  margin-top: 0.25rem;
}

@media (max-width: 720px) {
  .login-layout {
    grid-template-columns: 1fr;
    gap: 1.25rem;
  }
}
</style>
