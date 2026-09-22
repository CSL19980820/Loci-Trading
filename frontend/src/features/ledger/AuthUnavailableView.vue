<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CloudOff } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { BRAND_MARK, BRAND_NAME } from '@/shared/lib/brand'

/** 认证服务探测失败页：与登录页同一张画布，中央一张状态卡。 */
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
  <!-- 非壳内页例外（§3.7.1）：自管 100dvh -->
  <main class="auth-unavailable" aria-labelledby="auth-unavailable-title">
    <div class="auth-unavailable__canvas" aria-hidden="true" />
    <header class="auth-unavailable__top">
      <span class="auth-unavailable__mark">{{ BRAND_MARK }}</span>
      <span class="auth-unavailable__brand">{{ BRAND_NAME }}</span>
    </header>
    <section class="auth-unavailable__card">
      <span class="auth-unavailable__icon" aria-hidden="true"><CloudOff /></span>
      <p class="auth-unavailable__eyebrow">连接状态</p>
      <h1 id="auth-unavailable-title">认证服务暂不可用</h1>
      <p class="auth-unavailable__message">登录校验没有打通；服务恢复后点重试，会回到你原来的页面。</p>
      <Button access="read" size="lg" class="auth-unavailable__retry" @click="retry">重试</Button>
    </section>
  </main>
</template>

<style scoped>
.auth-unavailable {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  overflow-y: auto;
  background: var(--surface-canvas);
  color: var(--text-primary);
  isolation: isolate;
}

.auth-unavailable__canvas {
  position: absolute;
  inset: 0;
  z-index: -1;
  background-image:
    radial-gradient(ellipse 70% 50% at 50% -10%, color-mix(in oklab, var(--warn) 14%, transparent), transparent 70%),
    radial-gradient(circle, var(--border-default) 1px, transparent 1.2px);
  background-size:
    100% 100%,
    22px 22px;
  mask-image: linear-gradient(to bottom, rgb(0 0 0 / 1), rgb(0 0 0 / 0.3));
  -webkit-mask-image: linear-gradient(to bottom, rgb(0 0 0 / 1), rgb(0 0 0 / 0.3));
}

.auth-unavailable__top {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-4) var(--gap-6);
}

.auth-unavailable__mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius);
  background: var(--seal);
  color: var(--on-primary, #fff);
  font: 700 var(--fs-kicker) / 1 var(--mono);
  letter-spacing: 0.04em;
}

.auth-unavailable__brand {
  font-size: var(--fs-body);
  font-weight: 600;
}

.auth-unavailable__card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--gap-2);
  width: min(100% - var(--gap-6), 26rem);
  margin: auto;
  padding: var(--gap-6);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  background: var(--surface-raised, var(--surface));
  box-shadow: var(--shadow-lg);
  text-align: center;
}

.auth-unavailable__icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  margin-bottom: var(--gap-2);
  border-radius: var(--radius-lg);
  background: var(--warn-soft);
  color: var(--warn-ink);
}

.auth-unavailable__icon :deep(svg) {
  width: 22px;
  height: 22px;
}

.auth-unavailable__eyebrow {
  margin: 0;
  color: var(--text-tertiary);
  font: 500 var(--fs-kicker) / 1.3 var(--mono);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-hero);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.25;
}

.auth-unavailable__message {
  margin: 0 0 var(--gap-3);
  color: var(--text-secondary);
  font-size: var(--fs-ui);
  line-height: 1.6;
}

.auth-unavailable__retry {
  min-width: 10rem;
}

@media (max-width: 640px) {
  .auth-unavailable__top {
    padding: var(--gap-3) var(--gap-4);
  }

  .auth-unavailable__card {
    width: 100%;
    margin: auto 0 0;
    border: 0;
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
    box-shadow: none;
    padding-bottom: calc(var(--gap-6) + env(safe-area-inset-bottom));
  }

  .auth-unavailable__retry {
    width: 100%;
  }
}
</style>
