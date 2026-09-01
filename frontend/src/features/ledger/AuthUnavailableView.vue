<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { BRAND_MARK } from '@/shared/lib/brand'

const brandMark = BRAND_MARK

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
  <!-- 非壳内页例外（§3.7.1）：自管 100dvh，但内容靠 place-items 居中，不靠大 padding -->
  <main class="auth-unavailable" aria-labelledby="auth-unavailable-title">
    <section class="auth-unavailable__content">
      <p class="auth-unavailable__eyebrow">{{ brandMark }} / 连接状态</p>
      <h1 id="auth-unavailable-title">认证服务暂不可用</h1>
      <p class="auth-unavailable__message">登录校验失败，服务恢复后可继续原页面</p>
      <el-button type="primary" @click="retry">重试</el-button>
    </section>
  </main>
</template>

<style scoped>
.auth-unavailable {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: var(--gap-4);
  background: var(--paper);
}
.auth-unavailable__content {
  width: min(100%, 26rem);
  padding: var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  /* 原为 border-left: 2px solid var(--seal)：左竖条改为 hairline 外框 + 极淡印章底色 */
  background: color-mix(in srgb, var(--seal) 6%, var(--sheet));
}
.auth-unavailable__eyebrow {
  margin: 0 0 var(--gap-1);
  color: var(--mist);
  font: 600 var(--fs-kicker) / 1.3 var(--mono);
  letter-spacing: 0.08em;
}
h1 {
  margin: 0;
  color: var(--ink);
  font-size: var(--fs-hero);
  font-weight: 700;
  letter-spacing: 0.03em;
  line-height: 1.3;
}
.auth-unavailable__message {
  margin: var(--gap-2) 0 var(--gap-3);
  color: var(--muted);
  font-size: var(--fs-body);
  line-height: 1.6;
}
</style>
