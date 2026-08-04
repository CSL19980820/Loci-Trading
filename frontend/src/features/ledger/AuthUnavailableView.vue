<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const retryTarget = computed(() => {
  const raw = String(route.query.redirect ?? '').trim()
  return raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
})

function retry(): void {
  void router.replace(retryTarget.value)
}
</script>

<template>
  <main class="auth-unavailable" aria-labelledby="auth-unavailable-title">
    <section class="auth-unavailable__content">
      <p class="auth-unavailable__eyebrow">LOCI / 连接状态</p>
      <h1 id="auth-unavailable-title">认证服务暂不可用</h1>
      <p class="auth-unavailable__message">
        当前无法完成登录状态校验，工作台没有加载。服务恢复后可以继续刚才的页面。
      </p>
      <el-button type="primary" @click="retry">重试</el-button>
    </section>
  </main>
</template>

<style scoped>
.auth-unavailable {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: var(--paper);
}

.auth-unavailable__content {
  width: min(100%, 32rem);
  padding: 1.5rem;
  border: 1px solid var(--rule);
  border-left: 4px solid var(--seal);
  border-radius: var(--radius);
  background: var(--sheet);
}

.auth-unavailable__eyebrow {
  margin: 0 0 0.65rem;
  color: var(--mist);
  font: 600 0.72rem/1.3 var(--mono);
  letter-spacing: 0.08em;
}

h1 {
  margin: 0;
  color: var(--ink);
  font-size: 1.35rem;
  line-height: 1.25;
}

.auth-unavailable__message {
  margin: 0.75rem 0 1.25rem;
  color: var(--muted);
  line-height: 1.65;
}
</style>
